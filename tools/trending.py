"""实时热搜词跟进判定工具（模块6「热点监控」的决策护栏）。

分工：LLM 只负责「转录」实时取值区/证据区里的候选词及其热度（禁止编造），
工具用一套**固定规则**（LLM 不可调）判定趋势方向与是否跟进，
模块最终 JSON 的 trending_monitor.rising_keywords 必须原样取自本工具结果。

规则依据（与 module_agents/module6.py 的铁律、docs 的证据分级口径一致）：

* **相关性优先**：与品类/品牌/卖点词无 casefold 包含匹配的词一律「不跟进」——
  蹭无关热点既拉低搜索相关性权重，也有品牌安全风险。
* **趋势阈值 ±5%**：热度较上一批 >+5% 记 rising、< -5% 记 cooling，中间记 flat。
  ±5% 是噪声带（mock 源每批 +3 点的演化幅度也落在该带之外），避免把抖动当趋势。
* **cooling 一律不跟进**：热搜回落期入场等于追尾，内容产出周期跑不赢热度衰减。
* **缺趋势数据（首次出现）只「观察」**：没有上一批热度就无法判断方向，
  仅把高于本批中位数的词纳入监控池，下一批有对比值后再决策。
* **兜底「观察」**：flat 或低于中位数的 unknown 词维持监控，不额外占用预算。

本文件只依赖标准库 / pydantic / tools.registry，绝不 import engine / main / realtime_feed。
"""
from __future__ import annotations

from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, Field

from tools.registry import ToolSpec

# 固定阈值（LLM 不可调）
RISING_RATIO = 1.05   # 热度 > 上批 ×1.05 记 rising
COOLING_RATIO = 0.95  # 热度 < 上批 ×0.95 记 cooling

RECOMMENDATION_FOLLOW = "跟进"
RECOMMENDATION_WATCH = "观察"
RECOMMENDATION_SKIP = "不跟进"
RECOMMENDATIONS = (RECOMMENDATION_FOLLOW, RECOMMENDATION_WATCH, RECOMMENDATION_SKIP)

# 固定动作文案（跟进/观察/不跟进 各一套，避免 LLM 自由发挥成不可执行的空话）
ACTION_FOLLOW = "24h 内产出蹭点笔记 + 小预算搜索词测试（先跑 3 天再看留投）"
ACTION_WATCH_UNKNOWN = "只入监控池，不产出内容；等下一批数据有对比热度后再决策"
ACTION_WATCH_DEFAULT = "维持监控，热度出现明确上升（>+5%）再触发跟进"
ACTION_SKIP_IRRELEVANT = "不跟进、不产出内容，仅在监控台账留痕"
ACTION_SKIP_COOLING = "不新增投放；若已有相关词在投，降预算或转长尾承接"

POLICY = (
    "热度与趋势来自数据源快照，跟进前需人工确认平台实时热搜榜；mock 数据仅作演示"
)


class TrendingCandidate(BaseModel):
    """一个候选热搜词。**只能转录实时取值区/证据区里已有的词**，禁止编造。"""

    keyword: str = Field(min_length=1, max_length=40, description="热搜词原文（照抄证据）")
    heat_score: float = Field(ge=0, description="本批热度（照抄证据，无单位可比值）")
    previous_heat: float | None = Field(
        default=None, ge=0, description="上一批热度；证据里没有上批值时传 null"
    )
    source_name: str = Field(min_length=1, description="数据来源名（照抄证据）")
    is_mock: bool = Field(description="该条是否来自模拟数据源（照抄证据的 is_mock）")


class TrendingArgs(BaseModel):
    candidates: list[TrendingCandidate] = Field(
        min_length=1,
        max_length=20,
        description="候选热搜词 1-20 个，只能来自实时取值区/证据区，禁止编造",
    )
    brand_terms: list[str] = Field(
        min_length=1, max_length=10, description="品牌/产品/卖点词，用于相关性判定"
    )
    category: str = Field(min_length=1, description="品类名，用于相关性判定")
    rationale: str = Field(min_length=10, description="本次热搜判定的决策理由")


def _relevance_terms(category: str, brand_terms: list[str]) -> list[str]:
    """相关性词表 = 品类词 + 品牌/产品/卖点词（casefold 去重、去空）。"""
    terms: list[str] = []
    for raw in [category, *brand_terms]:
        term = (raw or "").casefold().strip()
        if term and term not in terms:
            terms.append(term)
    return terms


def _relevance_hits(keyword: str, terms: list[str]) -> list[str]:
    """casefold 双向包含匹配：词包含品类词、或品类词包含该词，都记一次命中。"""
    word = (keyword or "").casefold().strip()
    if not word:
        return []
    return [term for term in terms if term in word or word in term]


def _classify_trend(heat: float, previous: float | None) -> str:
    """趋势方向：±5% 噪声带外才算 rising / cooling；无上批值记 unknown。"""
    if previous is None:
        return "unknown"
    if heat > previous * RISING_RATIO:
        return "rising"
    if heat < previous * COOLING_RATIO:
        return "cooling"
    return "flat"


def _decide(
    trend: str, hits: int, heat: float, heat_median: float
) -> tuple[str, str, str]:
    """固定决策规则表，返回 (recommendation, reason, action)。顺序即优先级。"""
    # 规则 1：与品类/品牌无关 → 不跟进（蹭无关热点损伤相关性权重与品牌安全）
    if hits == 0:
        return (
            RECOMMENDATION_SKIP,
            "与品类/品牌卖点无关键词匹配，属无关热点，蹭点会拉低搜索相关性",
            ACTION_SKIP_IRRELEVANT,
        )
    # 规则 2：相关 + 上升 → 跟进
    if trend == "rising":
        return (
            RECOMMENDATION_FOLLOW,
            f"与品类/品牌有 {hits} 处词面匹配，且热度较上一批上升超过 5%，处于爬坡期",
            ACTION_FOLLOW,
        )
    # 规则 3：相关 + 缺趋势数据 + 热度不低于本批中位数 → 观察
    if trend == "unknown" and heat >= heat_median:
        return (
            RECOMMENDATION_WATCH,
            f"缺上一批热度无法判断趋势，但热度 {heat:g} 不低于本批中位数 "
            f"{heat_median:g}，先入监控池",
            ACTION_WATCH_UNKNOWN,
        )
    # 规则 4：热度回落 → 不跟进
    if trend == "cooling":
        return (
            RECOMMENDATION_SKIP,
            "热度较上一批回落超过 5%，内容产出周期跑不赢衰减，避免追尾",
            ACTION_SKIP_COOLING,
        )
    # 规则 5：兜底（flat，或 unknown 且低于中位数）→ 观察
    return (
        RECOMMENDATION_WATCH,
        f"趋势为 {trend}（未越过 ±5% 阈值或热度低于本批中位数），暂不占用预算",
        ACTION_WATCH_DEFAULT,
    )


def evaluate_trending_keywords(args: TrendingArgs) -> dict[str, Any]:
    terms = _relevance_terms(args.category, args.brand_terms)
    heat_median = float(median([item.heat_score for item in args.candidates]))

    evaluated: list[dict[str, Any]] = []
    summary = {
        RECOMMENDATION_FOLLOW: 0,
        RECOMMENDATION_WATCH: 0,
        RECOMMENDATION_SKIP: 0,
    }
    for item in args.candidates:
        hits = _relevance_hits(item.keyword, terms)
        trend = _classify_trend(item.heat_score, item.previous_heat)
        recommendation, reason, action = _decide(
            trend, len(hits), item.heat_score, heat_median
        )
        summary[recommendation] += 1
        evaluated.append({
            "keyword": item.keyword,
            "heat_score": item.heat_score,
            "previous_heat": item.previous_heat,
            "trend": trend,
            "relevance_hits": len(hits),
            "matched_terms": hits,
            "recommendation": recommendation,
            "reason": reason,
            "action": action,
            "is_mock": item.is_mock,
            "source_name": item.source_name,
        })

    mock_count = sum(1 for item in args.candidates if item.is_mock)
    return {
        "evaluated_keywords": evaluated,
        "summary": summary,
        "candidate_count": len(evaluated),
        "heat_median": heat_median,
        "mock_candidate_count": mock_count,
        "rules": {
            "rising_threshold": f"heat > previous × {RISING_RATIO}",
            "cooling_threshold": f"heat < previous × {COOLING_RATIO}",
            "irrelevant": "relevance_hits = 0 → 不跟进",
            "unknown": "无上批热度 + 相关 + 热度 ≥ 本批中位数 → 观察",
            "fallback": "其余 → 观察",
        },
        "decision_rationale": args.rationale,
        "policy": POLICY,
    }


TRENDING_TOOLS = [
    ToolSpec(
        name="evaluate_trending_keywords",
        description=(
            "按固定规则判定候选热搜词的趋势方向（rising/flat/cooling/unknown）与是否跟进"
            "（跟进/观察/不跟进），并给出理由与建议动作。"
            "候选词只能转录实时取值区/证据区里已有的词与热度，禁止编造；"
            "规则不可由调用方调整。"
        ),
        args_model=TrendingArgs,
        fn=evaluate_trending_keywords,
    )
]
