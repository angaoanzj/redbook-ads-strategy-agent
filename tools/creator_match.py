"""达人匹配工具：把「达人分层 + 受众匹配打分 + 单篇放大预算 + 名额缺口」工具化。

分工：LLM 只转录证据中的达人（prompt 层约束），并从画像/卖点提炼受众关键词；
本工具做确定性分层（<1万素人 / <50万达人 / 否则 KOL / 无粉丝数待判定）、
按受众标签与关键词的交集打匹配分、算互动率、排序输出 top 20，并按层给出单篇
放大预算与名额缺口。不足名额绝不编造达人，只如实返回 open_slots。

本文件只依赖 pydantic 与 tools.registry，绝不 import engine。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from tools.registry import ToolSpec

# 分层阈值（粉丝数）
TIER_AMATEUR_MAX = 10_000  # <1万 素人
TIER_KOC_MAX = 500_000  # <50万 达人；否则 KOL
BASE_MATCH_SCORE = 55
PER_TAG_BONUS = 10
MAX_MATCH_SCORE = 95
TOP_N = 20
CANONICAL_TIERS = ("素人", "达人", "KOL")


class CreatorItem(BaseModel):
    name: str = Field(min_length=1, description="达人名，须来自证据")
    followers: int | None = Field(default=None, ge=0, description="粉丝数，缺失传 null 则待判定分层")
    average_interactions: int | None = Field(default=None, ge=0, description="篇均互动，缺失传 null")
    quote_cny: float | None = Field(default=None, ge=0, description="报价（元），缺失传 null")
    audience_tags: list[str] = Field(default_factory=list, description="受众标签")
    source_name: str = Field(min_length=1, description="证据来源")


class TierBudgets(BaseModel):
    """来自 plan_creator_tiers 的各层单人预算（元）。"""

    素人: float = Field(ge=0)
    达人: float = Field(ge=0)
    KOL: float = Field(ge=0)


class MatchCreatorsArgs(BaseModel):
    """LLM 提交的达人清单、受众关键词与各层单人预算。"""

    creators: list[CreatorItem] = Field(
        default_factory=list, max_length=50, description="达人候选（0-50 项），只转录证据中的达人"
    )
    audience_keywords: list[str] = Field(
        min_length=2, max_length=12, description="从画像/卖点提炼的受众关键词（2-12 项）"
    )
    tier_budgets: TierBudgets = Field(description="各层单人预算，来自 plan_creator_tiers")
    per_note_cap_ratio: float = Field(
        default=0.5, ge=0.2, le=1.0, description="单篇放大预算占该层单人预算比例上限"
    )
    rationale: str = Field(min_length=10, description="匹配与名额缺口判断的决策理由")


def _classify_tier(followers: int | None) -> str:
    if followers is None:
        return "待判定"
    if followers < TIER_AMATEUR_MAX:
        return "素人"
    if followers < TIER_KOC_MAX:
        return "达人"
    return "KOL"


def match_creators(args: MatchCreatorsArgs) -> dict[str, Any]:
    keyword_set = {kw.casefold().strip() for kw in args.audience_keywords if kw.strip()}
    budgets = {"素人": args.tier_budgets.素人, "达人": args.tier_budgets.达人, "KOL": args.tier_budgets.KOL}

    scored: list[dict[str, Any]] = []
    for creator in args.creators:
        tag_set = {t.casefold().strip() for t in creator.audience_tags if t.strip()}
        overlap = keyword_set & tag_set
        match_score = min(BASE_MATCH_SCORE + PER_TAG_BONUS * len(overlap), MAX_MATCH_SCORE)
        tier = _classify_tier(creator.followers)
        if creator.average_interactions is not None and creator.followers:
            engagement_rate = round(creator.average_interactions / creator.followers, 4)
        else:
            engagement_rate = None
        if tier in budgets:
            suggested_note_budget = round(budgets[tier] * args.per_note_cap_ratio)
        else:
            suggested_note_budget = None
        scored.append({
            "name": creator.name,
            "tier": tier,
            "match_score": match_score,
            "matched_keywords": sorted(overlap),
            "engagement_rate": engagement_rate,
            "followers": creator.followers,
            "average_interactions": creator.average_interactions,
            "quote_cny": creator.quote_cny,
            "suggested_note_budget_cny": suggested_note_budget,
            "source": creator.source_name,
        })

    scored.sort(
        key=lambda row: (
            row["match_score"],
            row["engagement_rate"] if row["engagement_rate"] is not None else -1.0,
        ),
        reverse=True,
    )
    matched = scored[:TOP_N]

    # 名额缺口：达人总数不足 20 时，按层给缺口数（缺口对齐每层在 20 名额中的均分目标）
    open_slots: list[dict[str, Any]] = []
    if len(args.creators) < TOP_N:
        active_tiers = [t for t in CANONICAL_TIERS if budgets[t] > 0]
        if active_tiers:
            base = TOP_N // len(active_tiers)
            remainder = TOP_N % len(active_tiers)
            counts: dict[str, int] = {t: 0 for t in active_tiers}
            for row in matched:
                if row["tier"] in counts:
                    counts[row["tier"]] += 1
            for index, tier in enumerate(active_tiers):
                target = base + (1 if index < remainder else 0)
                gap = target - counts[tier]
                if gap > 0:
                    open_slots.append({"tier": tier, "slots_needed": gap})

    return {
        "matched_creators": matched,
        "matched_count": len(matched),
        "candidate_count": len(args.creators),
        "audience_keywords": list(args.audience_keywords),
        "tier_budgets": budgets,
        "per_note_cap_ratio": args.per_note_cap_ratio,
        "open_slots": open_slots,
        "policy": "不足名额不编造，导入 CSV/蒲公英后补齐",
        "decision_rationale": args.rationale,
    }


CREATOR_MATCH_TOOLS = [
    ToolSpec(
        name="match_creators",
        description=(
            "对证据中的达人做确定性分层（<1万素人/<50万达人/否则KOL/无粉丝数待判定），"
            "按受众标签与受众关键词交集打匹配分（55+10×交集数，封顶95），算互动率并排序"
            "输出 top 20，按层附单篇放大预算；达人不足 20 时按层返回 open_slots，绝不编造达人。"
        ),
        args_model=MatchCreatorsArgs,
        fn=match_creators,
    )
]
