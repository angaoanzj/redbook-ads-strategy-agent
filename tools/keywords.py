"""关键词分层工具：原 engine._keyword_library 的工具化版本。

分工：LLM 决策候选词、级别/意向/版位标注与预算比例；工具校验去重、
各级数量下限、预算比例合计为 1，并用固定出价倍率带算出出价区间。
缺基准 CPC 时各词 bid_range 返回 null 并标注待补，绝不编造出价。

本文件只依赖 pydantic 与 tools.registry，绝不 import engine。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from tools.registry import ToolSpec

# 固定出价倍率带（LLM 不可调）：优先级 blue_ocean > feed 版位 > 搜索意向
BLUE_OCEAN_BAND = (0.6, 0.8)
FEED_BAND = (0.7, 1.0)
SEARCH_HIGH_BAND = (1.0, 1.3)
SEARCH_MID_BAND = (0.9, 1.1)
SEARCH_LOW_BAND = (0.8, 1.0)

# 各级最少数量
MIN_CORE = 2
MIN_LONG_TAIL = 4
MIN_BLUE_OCEAN = 2


class KeywordItem(BaseModel):
    keyword: str = Field(min_length=2, max_length=24, description="关键词")
    level: Literal["core", "long_tail", "blue_ocean"] = Field(description="分层级别")
    intent: Literal["high", "mid", "low"] = Field(description="购买意向强度")
    lane: Literal["search", "feed", "both"] = Field(description="投放版位")
    from_evidence: bool = Field(description="是否由笔记证据主题衍生")


class LevelBudgetSplit(BaseModel):
    core: float = Field(ge=0, le=1)
    long_tail: float = Field(ge=0, le=1)
    blue_ocean: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def check_sum(self) -> "LevelBudgetSplit":
        total = self.core + self.long_tail + self.blue_ocean
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"level_budget_split 合计必须为 1.0，当前为 {total:.3f}")
        return self


class KeywordTiersArgs(BaseModel):
    """LLM 提交的关键词分层决策参数。"""

    keywords: list[KeywordItem] = Field(
        min_length=8, max_length=40, description="候选关键词（8-40 个）"
    )
    level_budget_split: LevelBudgetSplit = Field(description="三级预算比例，合计为 1")
    baseline_cpc_cny: float | None = Field(
        default=None, gt=0, description="基准 CPC（元/点击），来自证据；无则传 null"
    )
    baseline_source: str | None = Field(
        default=None, description="基准 CPC 的证据来源（提供 CPC 时必填）"
    )
    rationale: str = Field(min_length=10, description="分层与预算比例的决策理由")

    @model_validator(mode="after")
    def check(self) -> "KeywordTiersArgs":
        if self.baseline_cpc_cny is not None and not self.baseline_source:
            raise ValueError("提供 baseline_cpc_cny 时必须注明 baseline_source")
        # 去重：casefold 后重复即整体拒绝并列出重复词
        seen: dict[str, str] = {}
        dups: list[str] = []
        for item in self.keywords:
            key = item.keyword.casefold().strip()
            if key in seen:
                dups.append(item.keyword)
            else:
                seen[key] = item.keyword
        if dups:
            raise ValueError(f"关键词去重失败，重复词：{', '.join(dups)}")
        # 各级数量下限
        counts = {"core": 0, "long_tail": 0, "blue_ocean": 0}
        for item in self.keywords:
            counts[item.level] += 1
        shortfalls = []
        if counts["core"] < MIN_CORE:
            shortfalls.append(f"core≥{MIN_CORE}（当前 {counts['core']}）")
        if counts["long_tail"] < MIN_LONG_TAIL:
            shortfalls.append(f"long_tail≥{MIN_LONG_TAIL}（当前 {counts['long_tail']}）")
        if counts["blue_ocean"] < MIN_BLUE_OCEAN:
            shortfalls.append(f"blue_ocean≥{MIN_BLUE_OCEAN}（当前 {counts['blue_ocean']}）")
        if shortfalls:
            raise ValueError("各级数量不足：" + "；".join(shortfalls))
        return self


def _multiplier_band(level: str, intent: str, lane: str) -> tuple[tuple[float, float], str]:
    """按 级别 → 版位 → 意向 优先级返回固定倍率带与说明。"""
    if level == "blue_ocean":
        return BLUE_OCEAN_BAND, "低价试探 0.6–0.8"
    if lane == "feed":
        return FEED_BAND, "信息流稳成本 0.7–1.0"
    # search 或 both
    if intent == "high":
        return SEARCH_HIGH_BAND, "搜索高意向抢位 1.0–1.3"
    if intent == "mid":
        return SEARCH_MID_BAND, "搜索中意向稳投 0.9–1.1"
    return SEARCH_LOW_BAND, "搜索低意向控成本 0.8–1.0"


def build_keyword_tiers(args: KeywordTiersArgs) -> dict[str, Any]:
    cpc = args.baseline_cpc_cny
    grouped: dict[str, list[dict[str, Any]]] = {
        "core": [],
        "long_tail": [],
        "blue_ocean": [],
    }
    from_evidence_count = 0
    for item in args.keywords:
        (low_m, high_m), note = _multiplier_band(item.level, item.intent, item.lane)
        if cpc is not None:
            bid_range = [round(cpc * low_m, 2), round(cpc * high_m, 2)]
            evidence_status = "有基准CPC：出价区间已算出，仍需账户实时建议价校准"
        else:
            bid_range = None
            evidence_status = "待补数据：缺基准CPC，出价区间留空"
        if item.from_evidence:
            from_evidence_count += 1
        grouped[item.level].append({
            "keyword": item.keyword,
            "intent": item.intent,
            "lane": item.lane,
            "from_evidence": item.from_evidence,
            "multiplier_band": [low_m, high_m],
            "bid_note": note,
            "bid_range_cny": bid_range,
            "evidence_status": evidence_status,
        })

    total = len(args.keywords)
    coverage = round(from_evidence_count / total, 3) if total else 0.0
    return {
        "keyword_tiers": grouped,
        "counts": {level: len(rows) for level, rows in grouped.items()},
        "level_budget_split": {
            "core": args.level_budget_split.core,
            "long_tail": args.level_budget_split.long_tail,
            "blue_ocean": args.level_budget_split.blue_ocean,
        },
        "evidence_coverage": coverage,
        "baseline_cpc_cny": cpc,
        "baseline_source": args.baseline_source,
        "bid_status": "有基准CPC" if cpc is not None else "待补基准CPC",
        "decision_rationale": args.rationale,
        "policy": "本工具只做去重/数量/预算比例校验与出价数学；词表语义由真实证据支撑",
    }


KEYWORD_TOOLS = [
    ToolSpec(
        name="build_keyword_tiers",
        description=(
            "校验候选关键词的去重与各级数量下限（core≥2/long_tail≥4/blue_ocean≥2）、"
            "预算比例合计为 1，并按意向×版位固定倍率带算出各词出价区间。"
            "缺基准 CPC 时出价区间返回 null。"
        ),
        args_model=KeywordTiersArgs,
        fn=build_keyword_tiers,
    )
]
