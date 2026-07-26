"""竞品格局工具：把竞品证据的「聚合统计」与「内容缺口对照」工具化。

分工：LLM 从证据区转录竞品条目（禁止新增证据里没有的竞品，prompt 层约束），
本工具只做确定性聚合——按笔记形态聚合计数与互动均值、排出爆款共性、算内容缺口、
统计广告标识数量。绝不给竞品预算数字：无广告标识证据时明令禁止推测预算，
即便有广告标识也只返回「需人工核验」的粗估口径文本，不吐任何数字。

本文件只依赖 pydantic 与 tools.registry，绝不 import engine。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from tools.registry import ToolSpec

# 无广告标识证据时的预算政策（禁止任何预算推测）
_NO_AD_BUDGET_POLICY = "无广告标识证据：禁止推测竞品预算"
# 完全无竞品证据时的预算政策
_NO_COMPETITOR_BUDGET_POLICY = "无竞品证据：禁止推测竞品预算"
# 有广告标识时也只给口径文本，绝不给数字
_HAS_AD_BUDGET_POLICY = "可按投放时长×档位区间粗估，需人工核验"
_TARGETING_POLICY = "评论画像仅可生成定向测试假设，不得表述为竞品真实定向"
_SAMPLE_UNCOVERED_POLICY = "自身卖点未命中当前竞品主题，只能视为样本内未覆盖候选；需用户需求与效果测试后升级。"
_EVIDENCE_INSUFFICIENT_GAP_POLICY = "无竞品证据：样本覆盖本身未知，content_gaps 仅为待核验候选；需先补采竞品样本。"


class CompetitorItem(BaseModel):
    name: str = Field(min_length=1, description="竞品账号/品牌名，须来自证据区")
    note_format: str = Field(min_length=1, description="笔记形态，如图文/短视频/合集")
    interactions: int | None = Field(default=None, ge=0, description="互动量，缺失传 null")
    is_ad_labeled: bool | None = Field(default=None, description="是否带广告标识，未知传 null")
    evidence_status: str = Field(min_length=1, description="该条证据的成色/来源说明")


class CompetitorLandscapeArgs(BaseModel):
    """LLM 从证据区转录的竞品清单与自身卖点。"""

    competitors: list[CompetitorItem] = Field(
        min_length=0, max_length=20,
        description="竞品条目（0-20 项），只转录证据中的竞品；无竞品证据时传空列表，禁止编造",
    )
    own_selling_points: list[str] = Field(
        min_length=1, max_length=8, description="自身核心卖点（1-8 项），用于算内容缺口"
    )
    covered_themes: list[str] = Field(
        default_factory=list, description="证据中竞品已覆盖的主题"
    )
    rationale: str = Field(min_length=10, description="竞品格局判读理由")


def _covered(selling_point: str, covered_themes: list[str]) -> bool:
    sp = selling_point.casefold().strip()
    if not sp:
        return True
    for theme in covered_themes:
        th = (theme or "").casefold().strip()
        if not th:
            continue
        if sp in th or th in sp:
            return True
    return False


def summarize_competitor_landscape(args: CompetitorLandscapeArgs) -> dict[str, Any]:
    # 零竞品证据：返回诚实结论而非逼模型编造竞品条目
    if not args.competitors:
        return {
            "competitor_count": 0,
            "hot_format_ranking": [],
            "common_patterns": [],
            "content_gaps": list(args.own_selling_points),
            "content_gap_stage": "evidence_insufficient",
            "content_gap_policy": _EVIDENCE_INSUFFICIENT_GAP_POLICY,
            "covered_themes": list(args.covered_themes),
            "ad_labeled_count": 0,
            "budget_inference_policy": _NO_COMPETITOR_BUDGET_POLICY,
            "targeting_hypothesis_policy": _TARGETING_POLICY,
            "evidence_status": "无竞品证据，需补采",
            "decision_rationale": args.rationale,
            "policy": "无竞品证据：不做竞品聚合，content_gaps 仅作待核验候选，禁止编造竞品与预算数字",
        }

    # 按笔记形态聚合计数与互动均值
    buckets: dict[str, dict[str, Any]] = {}
    for item in args.competitors:
        fmt = item.note_format.strip()
        bucket = buckets.setdefault(fmt, {"count": 0, "interaction_sum": 0, "interaction_n": 0})
        bucket["count"] += 1
        if item.interactions is not None:
            bucket["interaction_sum"] += item.interactions
            bucket["interaction_n"] += 1

    format_stats: list[dict[str, Any]] = []
    for fmt, bucket in buckets.items():
        avg = (
            round(bucket["interaction_sum"] / bucket["interaction_n"], 2)
            if bucket["interaction_n"]
            else None
        )
        format_stats.append({
            "note_format": fmt,
            "count": bucket["count"],
            "avg_interactions": avg,
            "sample_with_interactions": bucket["interaction_n"],
        })
    # 爆款共性排序：优先按互动均值降序（无均值排后），再按出现次数降序
    format_stats.sort(
        key=lambda row: (
            row["avg_interactions"] if row["avg_interactions"] is not None else -1.0,
            row["count"],
        ),
        reverse=True,
    )

    # 内容缺口：自身卖点中未被 covered_themes 命中的项
    content_gaps = [
        sp for sp in args.own_selling_points if not _covered(sp, args.covered_themes)
    ]

    ad_labeled_count = sum(1 for item in args.competitors if item.is_ad_labeled is True)
    budget_policy = _HAS_AD_BUDGET_POLICY if ad_labeled_count > 0 else _NO_AD_BUDGET_POLICY

    return {
        "competitor_count": len(args.competitors),
        "hot_format_ranking": format_stats,
        "content_gaps": content_gaps,
        "content_gap_stage": "sample_uncovered",
        "content_gap_policy": _SAMPLE_UNCOVERED_POLICY,
        "covered_themes": list(args.covered_themes),
        "ad_labeled_count": ad_labeled_count,
        "budget_inference_policy": budget_policy,
        "targeting_hypothesis_policy": _TARGETING_POLICY,
        "decision_rationale": args.rationale,
        "policy": "本工具只做竞品聚合与缺口对照；竞品清单须来自真实证据，禁止编造竞品与预算数字",
    }


COMPETITOR_TOOLS = [
    ToolSpec(
        name="summarize_competitor_landscape",
        description=(
            "聚合竞品证据：按笔记形态统计计数与互动均值并排出爆款共性，"
            "对照自身卖点与已覆盖主题算内容缺口，统计广告标识数量。"
            "无广告标识证据时禁止推测竞品预算，有标识也只给需人工核验的口径文本、不给数字。"
        ),
        args_model=CompetitorLandscapeArgs,
        fn=summarize_competitor_landscape,
    )
]
