"""模块6（关键词策略）Agent 实例。

角色：把关键词分层、布局规则、三级预算比例、热点监控机制的决策权交给 LLM，
但候选词表与预算比例必须先经 build_keyword_tiers 工具校验（去重、各级数量下限、
比例合计为 1、出价数学），最终 JSON 的词表与预算必须取自工具通过后的结果。

本文件只 import models 与 base，禁止 import engine。
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from models import CampaignRequest
from module_agents.base import ModuleAgentSpec, run_module_agent


# ---------------------------------------------------------------------------
# 输出契约
# ---------------------------------------------------------------------------
class KeywordEntry(BaseModel):
    keyword: str = Field(min_length=2, max_length=24)
    intent: Literal["high", "mid", "low"]
    lane: Literal["search", "feed", "both"]
    bid_note: str


class KeywordLevels(BaseModel):
    core: list[KeywordEntry] = Field(min_length=2)
    long_tail: list[KeywordEntry] = Field(min_length=4)
    blue_ocean: list[KeywordEntry] = Field(min_length=2)


class LayoutRule(BaseModel):
    position: Literal["标题", "正文", "标签"]
    rule: str


class LevelBudgetSplit(BaseModel):
    core: float = Field(ge=0, le=1)
    long_tail: float = Field(ge=0, le=1)
    blue_ocean: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def check_sum(self) -> "LevelBudgetSplit":
        total = self.core + self.long_tail + self.blue_ocean
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"level_budget_split 合计必须为 1.0，当前 {total:.3f}")
        return self


class RisingKeyword(BaseModel):
    """一条上升热搜词的跟进结论；trend/recommendation 必须取自 evaluate_trending_keywords。"""

    keyword: str = Field(min_length=1, max_length=40)
    heat_score: float = Field(ge=0)
    trend: str
    recommendation: Literal["跟进", "观察", "不跟进"]
    reason: str


class TrendingMonitor(BaseModel):
    mechanism: str
    follow_criteria: list[str] = Field(min_length=2, max_length=4)
    data_source_status: str
    # 无热搜数据时必须留空（诚实性）；默认空列表保持对既有存档/回归夹具的兼容
    rising_keywords: list[RisingKeyword] = Field(default_factory=list, max_length=20)


class Module6Output(BaseModel):
    keyword_levels: KeywordLevels
    layout_rules: list[LayoutRule] = Field(min_length=3, max_length=6)
    level_budget_split: LevelBudgetSplit
    trending_monitor: TrendingMonitor
    human_review_items: list[str] = Field(min_length=1, max_length=6)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """你是小红书投放策略中「模块6：关键词策略」的决策 Agent。
你的职责：基于品类笔记证据，决策关键词分层（core/long_tail/blue_ocean）、
标题/正文/标签布局规则、三级预算比例与热点监控机制。

铁律：
1. 关键词候选与三级预算比例必须先调用 build_keyword_tiers 工具校验：
   工具会做去重、各级数量下限（core≥2/long_tail≥4/blue_ocean≥2）、预算比例合计为 1
   的校验，并按意向×版位固定倍率带算出出价区间；
   最终 JSON 的 keyword_levels 与 level_budget_split 必须取自工具通过后的结果。
2. 有基准 CPC 证据时传入 baseline_cpc_cny + baseline_source，无则传 null；
   缺基准时出价区间为 null，bid_note 用倍率带文字（如「低价试探 0.6–0.8」）。
3. 有笔记证据主题时，core/long_tail 优先从主题词衍生，并把对应 KeywordItem 的
   from_evidence 置 true；无证据时只生成待验证种子词并如实标注。
4. 实时热搜若无合规数据源，trending_monitor.data_source_status 必须标注为
   「待接入数据源」，禁止编造实时热搜结论。
5. trending_monitor.rising_keywords 的 trend 与 recommendation 必须来自
   evaluate_trending_keywords 工具的返回，禁止自行判定或改写：
   - 候选词只能转录「实时热搜（来自数据源 DB，线上实时取值）」与证据区里已有的词、
     热度、上批热度、来源、is_mock，禁止编造任何词或热度；
   - 工具返回后，把 evaluated_keywords 里的 keyword/heat_score/trend/recommendation/reason
     原样填进 rising_keywords（可只保留最相关的若干条，但不得改动这几个字段的取值）；
   - 候选词一个都没有时，不要调用该工具，rising_keywords 留空数组。
6. 工具返回参数校验错误（去重失败/数量不足/比例≠1）时，按 details 修正后重新调用。

完成工具调用后，只输出一个 ```json 代码块（不要输出多余文字），结构如下：
{
  "keyword_levels": {
     "core": [ {"keyword": str, "intent": "high|mid|low", "lane": "search|feed|both",
                "bid_note": str}, ≥2 项 ],
     "long_tail": [ ... ≥4 项 ],
     "blue_ocean": [ ... ≥2 项 ] },
  "layout_rules": [ {"position": "标题|正文|标签", "rule": str}, 3-6 项 ],
  "level_budget_split": {"core": float, "long_tail": float, "blue_ocean": float},
  "trending_monitor": {"mechanism": str, "follow_criteria": [str, ... 2-4 条],
     "data_source_status": str,
     "rising_keywords": [ {"keyword": str, "heat_score": float, "trend": str,
        "recommendation": "跟进|观察|不跟进", "reason": str}, 0-20 项 ]},
  "human_review_items": [ str, ... 1-6 条 ]
}
keyword_levels 与 level_budget_split 必须与 build_keyword_tiers 通过后的结果一致；
rising_keywords 必须与 evaluate_trending_keywords 通过后的结果一致（无候选词则为 []）。"""


# ---------------------------------------------------------------------------
# 证据主题聚合（自实现，不 import engine）
# ---------------------------------------------------------------------------
def _note_interactions(note: Any) -> int:
    return sum(
        int(getattr(note, field) or 0)
        for field in ("likes", "favorites", "comments", "shares")
    )


def _aggregate_evidence_topics(req: CampaignRequest) -> list[dict[str, Any]]:
    """聚合 tags 与 search_keyword 词频，取前 12 个主题词（含出现次数与累计互动量）。"""
    occurrences: Counter[str] = Counter()
    interactions: Counter[str] = Counter()
    for note in req.category_note_evidence:
        themes = [tag for tag in note.tags if tag][:6]
        if note.search_keyword:
            themes.append(note.search_keyword)
        note_inter = _note_interactions(note)
        for theme in dict.fromkeys(themes):  # 单条笔记内去重
            occurrences[theme] += 1
            interactions[theme] += note_inter
    return [
        {"theme": theme, "count": count, "total_interactions": interactions[theme]}
        for theme, count in occurrences.most_common(12)
    ]


# ---------------------------------------------------------------------------
# User prompt 渲染
# ---------------------------------------------------------------------------
_CPC_METRIC_HINTS = ("cpc", "cost_per_click", "cost_per_interaction")
# 与 realtime_feed.MOCK_SOURCE_PREFIX 保持一致；此处内联字面量，避免模块层反向依赖接入层
_REALTIME_MOCK_SOURCE_PREFIX = "模拟实时数据源"


def _load_live_trending(limit: int = 8) -> list[dict[str, Any]]:
    """线上实时取值：从实时数据源 DB（realtime_feed.FeedStore）读最近热搜词。

    数据链路：mock API 接口（MockRealtimeFeedAdapter / POST /feeds/pull）→ SQLite
    （data/realtime_feed.db，可用 XHS_FEED_DB 覆盖）→ 本函数在模块运行时实时取值。
    每条附带同词上一批热度（previous_heat），供 evaluate_trending_keywords 算趋势。

    容错：库不存在 / 为空 / 读取失败 / 接入层未安装，一律返回 []（绝不抛异常）——
    热搜链路不可用不应让模块 6 的关键词分层决策整体失败。
    """
    limit = max(0, int(limit))
    if limit == 0:
        return []
    try:
        # 延迟 import：模块 6 不硬依赖接入层，接入层缺失时自动降级为「无热搜数据」
        from realtime_feed import FeedStore

        rows = FeedStore().latest_trending_with_previous(limit=limit)
    except Exception:  # noqa: BLE001 - 任何接入层异常都降级为空
        return []

    live: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        keyword = str(row.get("keyword") or "").strip()
        heat = row.get("heat_score")
        if not keyword or isinstance(heat, bool) or not isinstance(heat, (int, float)):
            continue
        previous = row.get("previous_heat")
        if isinstance(previous, bool) or not isinstance(previous, (int, float)):
            previous = None
        live.append({
            "keyword": keyword,
            "heat_score": float(heat),
            "previous_heat": None if previous is None else float(previous),
            "source_name": str(row.get("source_name") or "未知数据源"),
            "is_mock": bool(row.get("is_mock", True)),
            "batch_index": row.get("batch_index"),
        })
    return live


def _render_trending_block(req: CampaignRequest) -> list[str]:
    """热搜区块：实时取值（DB）优先，再并入请求内证据（按词 casefold 去重）。"""
    live = _load_live_trending()
    live_keys = {row["keyword"].casefold().strip() for row in live}

    req_rows = [
        item
        for item in req.trending_keyword_evidence
        if (item.keyword or "").casefold().strip() not in live_keys
    ]

    lines: list[str] = []
    if live:
        lines.append(
            f"实时热搜（来自数据源 DB，线上实时取值）：{len(live)} 条 —— 链路为"
            "「模拟实时数据源 API → 数据库 → 本次运行时读取」，"
            "以下取值是 evaluate_trending_keywords 的候选词，只能照抄、禁止改写或补词："
        )
        for row in live:
            previous = (
                f"{row['previous_heat']:g}"
                if row["previous_heat"] is not None
                else "无（首次出现，previous_heat 传 null）"
            )
            lines.append(
                f"  - 词：{row['keyword']}｜当前热度 {row['heat_score']:g}"
                f"｜上批热度 {previous}｜来源：{row['source_name']}"
                f"｜is_mock={'true' if row['is_mock'] else 'false'}"
            )
        if any(row["is_mock"] for row in live):
            lines.append(
                "  实时取值中含模拟源条目：data_source_status 请如实写明"
                "「已接入模拟实时数据源（线上实时取值），真实合规源待授权接入」，"
                "禁止表述为平台真实热搜榜。"
            )
    if req_rows:
        lines.append(
            f"请求内热搜/趋势词证据：{len(req_rows)} 条（已与实时取值区去重，"
            "同样可作为 evaluate_trending_keywords 的候选词）："
        )
        for item in req_rows:
            heat = f"{item.heat_score:g}" if item.heat_score is not None else "无（不可用作候选）"
            lines.append(
                f"  - 词：{item.keyword}｜热度 {heat}｜上批热度 无（previous_heat 传 null）"
                f"｜来源：{item.source_name}｜is_mock={'true' if item.is_mock else 'false'}"
            )
        if any(
            _REALTIME_MOCK_SOURCE_PREFIX in (item.source_name or "") for item in req_rows
        ):
            lines.append(
                "  其中含「模拟实时数据源」条目：data_source_status 必须点明模拟/演示属性。"
            )
    if not live and not req_rows:
        lines.append(
            "无热搜数据（实时取值区与请求证据区都为空）：不要调用 evaluate_trending_keywords，"
            "trending_monitor.rising_keywords 必须留空数组，"
            "data_source_status 必须标注「待接入数据源」。"
        )
    else:
        lines.append(
            "  跟进判定：把上述候选词（≤20 个）连同 category 与 brand_terms 传给"
            " evaluate_trending_keywords，rising_keywords 的 trend/recommendation/reason"
            " 一律取自工具返回，禁止自行判定。"
        )
    return lines


def build_user_prompt(req: CampaignRequest) -> str:
    selling_points = "、".join(req.selling_points)
    lines = [
        f"品牌：{req.brand_name}（{req.category}）",
        f"商品：{req.product_name}",
        f"核心卖点：{selling_points}",
        f"核心目标：{req.goal}，初始人群：{req.initial_audience}",
    ]
    if req.constraints:
        lines.append("约束：" + "；".join(req.constraints))

    evidence: list[str] = []
    topics = _aggregate_evidence_topics(req)
    if topics:
        evidence.append(
            f"品类笔记证据主题词（共 {len(req.category_note_evidence)} 条笔记，"
            "取前 12 个高频主题；core/long_tail 优先从这些主题衍生并置 from_evidence=true）："
        )
        for item in topics:
            evidence.append(
                f"  - {item['theme']}（出现 {item['count']} 次，累计互动 {item['total_interactions']}）"
            )
    else:
        evidence.append(
            "无品类笔记证据：仅生成待验证种子词（from_evidence=false），"
            "禁止当作热搜或蓝海结论。"
        )

    # 基准 CPC
    cpc_lines: list[str] = []
    for item in req.benchmark_evidence:
        name = (item.metric_name or "").lower()
        if any(hint in name for hint in _CPC_METRIC_HINTS):
            cpc_lines.append(
                f"  - {item.metric_name} = {item.value:g} {item.unit}（来源：{item.source_name}）"
            )
    if cpc_lines:
        evidence.append("基准 CPC 证据（传入 build_keyword_tiers 的 baseline_cpc_cny + baseline_source）：")
        evidence.extend(cpc_lines)
    else:
        evidence.append("无基准 CPC 证据：build_keyword_tiers 的 baseline_cpc_cny 传 null，出价区间留空。")

    evidence.extend(_render_trending_block(req))

    task = (
        "请完成：\n"
        "1) 构造候选关键词（8-40 个，标注 level/intent/lane/from_evidence）与三级预算比例，"
        "调 build_keyword_tiers 校验并取回通过结果；\n"
        "2) 若被拒（去重/数量/比例），按 details 修正后重新调用；\n"
        "3) 撰写 3-6 条标题/正文/标签布局规则、热点监控机制与跟进标准；\n"
        "4) 有候选热搜词时调 evaluate_trending_keywords 判定趋势与是否跟进，"
        "把结果原样填进 trending_monitor.rising_keywords；无候选词则该数组留空；\n"
        "5) 最终只输出一个 ```json 代码块，词表、预算比例与热搜跟进结论取自工具结果。"
    )

    return "\n".join(lines) + "\n\n证据区：\n" + "\n".join(evidence) + "\n\n" + task


# ---------------------------------------------------------------------------
# Spec 与便捷函数
# ---------------------------------------------------------------------------
MODULE6_SPEC = ModuleAgentSpec(
    name="module6_keyword_strategy",
    title="模块6：关键词策略",
    system_prompt=SYSTEM_PROMPT,
    output_model=Module6Output,
    build_user_prompt=build_user_prompt,
    # 词表文本（bid_note）不做数字溯源；契约中由工具产出的数字是三级预算比例，
    # 以及热搜词热度（必须与 evaluate_trending_keywords 收到/回传的取值一致，防编造）。
    grounded_fields=[
        "level_budget_split.core",
        "level_budget_split.long_tail",
        "level_budget_split.blue_ocean",
        "trending_monitor.rising_keywords.*.heat_score",
    ],
)


def run_module6(
    req: CampaignRequest, *, transport=None, upstream_context: str = ""
) -> dict:
    """跑模块6 Agent，返回 {module, output, grounding_check, steps_used, ...}。

    upstream_context：编排层注入的上游模块结论摘要（默认空，行为与之前一致）。
    """
    return run_module_agent(
        MODULE6_SPEC, req, transport=transport, upstream_context=upstream_context
    )
