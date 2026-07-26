"""模块4（聚光投流前置决策）Agent 实例。

角色：把账户结构、定向包、出价、搜索/信息流分配、投放 SOP、风险预案的决策权
交给 LLM，但出价一律先走 calc_bid_range、效果预估一律先走 estimate_paid_performance，
输出以 Pydantic 契约强校验、以工具结果做数字溯源。

本文件只 import models 与 base，禁止 import engine。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from models import CampaignRequest
from module_agents.base import ModuleAgentSpec, run_module_agent
from module_agents._evidence_aggregation import aggregate_time_slots


# ---------------------------------------------------------------------------
# 输出契约
# ---------------------------------------------------------------------------
# 聚光付费计划的合法推广目标与版位（campaigns 是账户计划层级划分，非投放阶段）
_SPOTLIGHT_OBJECTIVES = ("产品种草", "商品成交", "客资收集", "直播引流")
_SPOTLIGHT_PLACEMENTS = ("搜索推广", "信息流推广", "搜索+信息流")


class CampaignPlan(BaseModel):
    name: str
    # 聚光计划推广目标，非投放阶段（禁止品牌曝光/品牌沉淀等非聚光目标）
    objective: Literal["产品种草", "商品成交", "客资收集", "直播引流"]
    budget_share: float = Field(ge=0, le=1)
    # 聚光计划版位，非自然内容形态（禁止「自然内容」等非付费值）
    placement: Literal["搜索推广", "信息流推广", "搜索+信息流"]


class AccountStructure(BaseModel):
    campaign_naming_rule: str
    unit_naming_rule: str
    campaigns: list[CampaignPlan] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def check_shares(self) -> "AccountStructure":
        total = sum(item.budget_share for item in self.campaigns)
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"campaigns 的 budget_share 合计必须为 1.0，当前 {total:.3f}")
        return self

    @model_validator(mode="after")
    def check_all_spotlight_paid(self) -> "AccountStructure":
        """全部计划必须为聚光付费计划：目标与版位都落在聚光允许集合内。"""
        for item in self.campaigns:
            if item.objective not in _SPOTLIGHT_OBJECTIVES:
                raise ValueError(
                    f"计划「{item.name}」objective={item.objective!r} 不是聚光推广目标；"
                    f"campaigns 只能是聚光付费计划，允许：{'、'.join(_SPOTLIGHT_OBJECTIVES)}"
                )
            if item.placement not in _SPOTLIGHT_PLACEMENTS:
                raise ValueError(
                    f"计划「{item.name}」placement={item.placement!r} 不是聚光版位；"
                    f"campaigns 只能是聚光付费计划，允许：{'、'.join(_SPOTLIGHT_PLACEMENTS)}"
                )
        return self


class TargetingPackage(BaseModel):
    package: Literal["精准定向", "宽定向", "达人相似定向"]
    audience_desc: str
    budget_share: float = Field(ge=0, le=1)
    applicable_stage: str
    smart_expansion: bool


class ColdStartBid(BaseModel):
    method: str
    bid_low_cny: float | None = None
    bid_high_cny: float | None = None
    basis: str


class BiddingPlan(BaseModel):
    cold_start: ColdStartBid
    scaling_rules: list[str] = Field(
        min_length=2,
        max_length=4,
        description=(
            "放量/调价规则；调价动作必须用百分比表述（如：提价5%、降价10%），"
            "禁止使用「X倍」这类歧义表述。"
        ),
    )


class SearchFeedSplit(BaseModel):
    search: float = Field(ge=0, le=1)
    feed: float = Field(ge=0, le=1)
    synergy_note: str

    @model_validator(mode="after")
    def check_sum(self) -> "SearchFeedSplit":
        total = self.search + self.feed
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"search_feed_split 合计必须为 1.0，当前 {total:.3f}")
        return self


class ScheduleSlot(BaseModel):
    time_range: str
    action: str


class ForecastBlock(BaseModel):
    test_budget_cny: int
    stop_loss_cpc_cny: float | None = None
    stop_loss_cpa_cny: float | None = None
    roi_point: float | None = None
    roi_band: list[float] | None = None
    status: str


class RiskItem(BaseModel):
    problem: str
    symptom: str
    response: str


class Module4Output(BaseModel):
    account_structure: AccountStructure
    targeting_packages: list[TargetingPackage] = Field(min_length=3, max_length=3)
    bidding: BiddingPlan
    search_feed_split: SearchFeedSplit
    daily_schedule: list[ScheduleSlot] = Field(min_length=2, max_length=4)
    forecast: ForecastBlock
    risk_playbook: list[RiskItem] = Field(min_length=5, max_length=5)
    human_review_items: list[str] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def check_targeting_shares(self) -> "Module4Output":
        total = sum(item.budget_share for item in self.targeting_packages)
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"targeting_packages 的 budget_share 合计必须为 1.0，当前 {total:.3f}"
            )
        return self


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """你是小红书投放策略中「模块4：聚光投流前置决策」的决策 Agent。
你的职责：基于用户提供的证据，决策聚光账户结构、定向包组合、出价、搜索/信息流预算
分配、每日投放 SOP、效果预估与五类风险预案。

铁律：
1. 出价数字必须先调用 calc_bid_range（stage=cold_start），禁止心算或编造。
   - 字段：baseline_cpc_cny + baseline_source（注意：不是 baseline_cpc_source）
   - 倍率护栏 cold_start 仅允许 0.8–1.3；默认用 low_multiplier=0.9、high_multiplier=1.1
     （禁止传 0.5–1.5，会被拒）
   - 缺基准 CPC 时 baseline_cpc_cny 传 null；最终 bidding.cold_start.bid_low_cny /
     bid_high_cny 也填 null
   - 工具返回的 low_cny_per_click / high_cny_per_click / basis 必须原样写入
     bidding.cold_start.bid_low_cny / bid_high_cny / basis（字段名要换，数字不能改）
2. 效果预估必须先调用 estimate_paid_performance：
   - CPC 来源字段是 baseline_cpc_source；CTR/CVR 对应 baseline_ctr_source /
     baseline_cvr_source（不要和 calc_bid_range 的 baseline_source 混用）
   - aov_cny 传已换算为 CNY 的客单价；缺哪档基准就传 null
   - 字段映射（工具→最终 JSON，数字原样拷贝）：
       test_budget_cny → forecast.test_budget_cny
       stop_loss.cpc_stop_cny → forecast.stop_loss_cpc_cny
       stop_loss.cpa_stop_cny → forecast.stop_loss_cpa_cny
       roi_point / roi_band → forecast.roi_point / forecast.roi_band
       forecast_status → forecast.status
     工具不给 ROI 时 roi_point 与 roi_band 填 null
3. 账户结构、定向包、搜索/信息流联动、每日 SOP、风险预案是策略文本，由你基于证据撰写。
3a. account_structure.campaigns 是聚光账户的「计划层级划分」（按推广目标×版位拆分），
   不是投放阶段。objective 只能取聚光推广目标（产品种草/商品成交/客资收集/直播引流），
   禁止品牌曝光/品牌沉淀等非聚光目标；placement 只能取搜索推广/信息流推广/搜索+信息流，
   禁止「自然内容」等非付费值。budget_share 是计划之间的预算分配，
   禁止照抄预热/爆发/长尾（如 0.2/0.6/0.2）这类投放阶段节奏比例。
3b. daily_schedule 是「投放时段建议」（匹配目标用户活跃时间），必须引用证据中的高互动
   时段；无证据时明确写明按目标人群作息假设，禁止输出「总结当日数据/准备次日策略」式
   运营值班表。
3c. bidding.scaling_rules 的调价动作必须用百分比表述（如：提价5%、降价10%），
   禁止使用「X倍」这类歧义表述。
4. 风险预案必须恰好 5 条，覆盖：冷启动失败、成本过高、流量跑不动、拒审、衰退；
   症状与处置要引用本品牌证据数字（止损线/测试带宽），禁止空泛套话。
5. 工具返回参数校验错误时，按 details 修正后重新调用，不要绕过工具。
6. 必填块 bidding 与 forecast 不能省略或填 null；工具失败时也应给出合法结构
   （出价可为 null，forecast.test_budget_cny 必须是整数）。

完成全部工具调用后，只输出一个 ```json 代码块（不要输出多余文字），结构如下：
{
  "account_structure": {
     "campaign_naming_rule": str, "unit_naming_rule": str,
     "campaigns": [ {"name": str,
                     "objective": "产品种草|商品成交|客资收集|直播引流",
                     "budget_share": float,
                     "placement": "搜索推广|信息流推广|搜索+信息流"},
                    2-4 项，聚光付费计划，budget_share 合计=1（计划间分配，非阶段节奏） ] },
  "targeting_packages": [ {"package": "精准定向|宽定向|达人相似定向",
     "audience_desc": str, "budget_share": float, "applicable_stage": str,
     "smart_expansion": bool}, 恰好 3 项，budget_share 合计=1 ],
  "bidding": {"cold_start": {"method": str, "bid_low_cny": float 或 null,
     "bid_high_cny": float 或 null, "basis": str},
     "scaling_rules": [str（调价用百分比如提价5%/降价10%，禁止「X倍」）, ... 2-4 条] },
  "search_feed_split": {"search": float, "feed": float, "synergy_note": str},
  "daily_schedule": [ {"time_range": str（投放时段，引用高互动时段）,
     "action": str（投放动作，非运营值班）}, 2-4 项 ],
  "forecast": {"test_budget_cny": int, "stop_loss_cpc_cny": float 或 null,
     "stop_loss_cpa_cny": float 或 null, "roi_point": float 或 null,
     "roi_band": [float, float] 或 null, "status": str},
  "risk_playbook": [ {"problem": str, "symptom": str, "response": str}, 恰好 5 项 ],
  "human_review_items": [ str, ... 1-6 条 ]
}
所有出价与预估数字必须与工具返回一致，不要另行改动。"""


# ---------------------------------------------------------------------------
# User prompt 渲染
# ---------------------------------------------------------------------------
_METRIC_HINTS = ("cpc", "ctr", "cvr", "conversion")
_FX_HINT = {"HKD": 0.92}


def _match_metric(name: str, key: str) -> bool:
    return key in (name or "").lower()


def build_user_prompt(req: CampaignRequest) -> str:
    selling_points = "、".join(req.selling_points)
    aov_native = (req.price_min + req.price_max) / 2
    if req.price_max > req.price_min:
        pricing = f"{req.price_min:g}–{req.price_max:g} {req.currency}（中值 {aov_native:g}）"
    else:
        pricing = f"{req.price_min:g} {req.currency}"

    lines = [
        f"品牌：{req.brand_name}（{req.category}）",
        f"商品：{req.product_name}",
        f"核心卖点：{selling_points}",
        f"定价：{pricing}",
        f"总预算：{req.total_budget_cny:g} 元，周期 {req.campaign_days} 天，"
        f"核心目标：{req.goal}",
        f"初始人群：{req.initial_audience}",
    ]
    if req.constraints:
        lines.append("约束：" + "；".join(req.constraints))

    # 聚光预算来源
    if req.spotlight_budget_cny:
        lines.append(
            f"聚光投流预算：{req.spotlight_budget_cny:g} 元（直接作为 estimate_paid_performance "
            "的 paid_budget_cny）"
        )
    else:
        lines.append(
            "未提供聚光投流预算：请先调 compute_budget_split 取 paid_budget_cny 部分，"
            "再作为 estimate_paid_performance 的 paid_budget_cny。"
        )

    # 客单价换汇提示
    currency = (req.currency or "CNY").strip().upper()
    if currency in {"CNY", "RMB"}:
        aov_hint = f"客单价（CNY）= 价带中值 {aov_native:g} 元，直接作为 aov_cny。"
    elif currency in _FX_HINT:
        rate = _FX_HINT[currency]
        aov_hint = (
            f"客单价价带中值 {aov_native:g} {currency}；estimate_paid_performance 的 "
            f"aov_cny 须换算为 CNY，参考汇率 ×{rate}（约 {round(aov_native * rate, 2):g} 元，演示值非牌价）。"
        )
    else:
        aov_hint = (
            f"客单价价带中值 {aov_native:g} {currency}，币种换汇需人工确认后再传 aov_cny。"
        )

    # 证据区：CPC/CTR/CVR 逐条
    evidence: list[str] = []
    metric_lines: list[str] = []
    found_keys: set[str] = set()
    for item in req.benchmark_evidence:
        name = (item.metric_name or "")
        for key in _METRIC_HINTS:
            if _match_metric(name, key):
                metric_lines.append(
                    f"  - {item.metric_name} = {item.value:g} {item.unit}"
                    f"（来源：{item.source_name}）"
                )
                found_keys.add("cvr" if key == "conversion" else key)
                break
    if metric_lines:
        evidence.append("效果类基准指标（作为 estimate_paid_performance / calc_bid_range 依据）：")
        evidence.extend(metric_lines)
        missing = [k.upper() for k in ("cpc", "ctr", "cvr") if k not in found_keys]
        if missing:
            evidence.append(
                f"缺失基准：{'、'.join(missing)} —— 预估工具对应 baseline 必须传 null。"
            )
    else:
        evidence.append(
            "无 CPC/CTR/CVR/转化类基准证据：estimate_paid_performance 与 calc_bid_range "
            "的对应 baseline 全部传 null，工具会缩减为只给测试带宽/止损。"
        )

    # 投放时段证据：复用模块1 的时段聚合口径，供 daily_schedule 引用高互动时段
    time_slots = aggregate_time_slots(req.category_note_evidence)
    if time_slots:
        top = time_slots[0]
        slot_lines = "，".join(
            f"{row['slot']} {row['count']}条/互动{row['interaction_sum']}" for row in time_slots
        )
        evidence.append(
            "品类笔记发布时段聚合（daily_schedule 的投放时段应匹配这些高互动时段，"
            f"当前最高互动时段：{top['slot']}）：{slot_lines}"
        )
    else:
        evidence.append(
            "无品类笔记发布时段证据：daily_schedule 需明确写明按目标人群"
            f"（{req.initial_audience}）作息假设的投放时段，禁止输出运营值班表。"
        )

    if req.paid_risk_demo_scenarios:
        evidence.append(
            f"投流问题演示情景：{len(req.paid_risk_demo_scenarios)} 条（可挂载到风险预案示例信号）。"
        )

    task = (
        "请完成（建议调用顺序，尽量少步收敛）：\n"
        "1) 若无聚光预算，先调 compute_budget_split 取 paid 部分；\n"
        "2) 有基准 CPC 时调 calc_bid_range：stage=cold_start，"
        "low_multiplier=0.9，high_multiplier=1.1，来源字段用 baseline_source；\n"
        "3) 调 estimate_paid_performance：CPC 来源用 baseline_cpc_source，"
        "CTR/CVR 用 baseline_ctr_source / baseline_cvr_source，缺基准传 null，"
        "客单价换算为 CNY；\n"
        "4) 撰写账户结构（聚光计划=推广目标×版位）、3 个定向包、搜索/信息流分配与联动、"
        "daily_schedule 投放时段（引用上方高互动时段）、恰好 5 条风险预案"
        "（症状引用工具返回的止损/测试带宽数字，调价用百分比）；\n"
        "5) 最终只输出一个 ```json 代码块；必须包含非空的 bidding 与 forecast 对象"
        "（不要写 bid_plan，契约字段名是 bidding）。"
    )

    return (
        "\n".join(lines)
        + "\n\n客单价：\n"
        + aov_hint
        + "\n\n证据区：\n"
        + "\n".join(evidence)
        + "\n\n"
        + task
    )


# ---------------------------------------------------------------------------
# Spec 与便捷函数
# ---------------------------------------------------------------------------
MODULE4_SPEC = ModuleAgentSpec(
    name="module4_spotlight_decision",
    title="模块4：聚光投流前置决策",
    system_prompt=SYSTEM_PROMPT,
    output_model=Module4Output,
    build_user_prompt=build_user_prompt,
    grounded_fields=[
        "bidding.cold_start.bid_low_cny",
        "bidding.cold_start.bid_high_cny",
        "forecast.test_budget_cny",
        "forecast.stop_loss_cpc_cny",
        "forecast.stop_loss_cpa_cny",
        "forecast.roi_point",
        "forecast.roi_band",
    ],
)


def run_module4(
    req: CampaignRequest, *, transport=None, upstream_context: str = ""
) -> dict:
    """跑模块4 Agent，返回 {module, output, grounding_check, steps_used, ...}。

    max_steps 提到 16：模块4 至少两次工具调用，Qwen 偶发倍率/字段名拒识会多烧几步。
    upstream_context：编排层注入的上游模块结论摘要（默认空，行为与之前一致）。
    """
    return run_module_agent(
        MODULE4_SPEC, req, transport=transport, max_steps=16,
        upstream_context=upstream_context,
    )
