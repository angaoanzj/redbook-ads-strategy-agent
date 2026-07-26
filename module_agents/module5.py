"""模块5（全域预算与节奏）Agent 实例。

角色：把总预算、三阶段节奏、达人分层、出价与「自然→付费」联动规则的决策权
交给 LLM，但金额/比例/出价一律先走工具算术，输出以 Pydantic 契约强校验、
以工具结果做数字溯源。

本文件只 import models 与 base，禁止 import engine。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from models import CampaignRequest
from module_agents.base import ModuleAgentSpec, run_module_agent


# ---------------------------------------------------------------------------
# 输出契约
# ---------------------------------------------------------------------------
class BudgetSplit(BaseModel):
    organic_budget_cny: int
    paid_budget_cny: int
    organic_ratio: float
    needs_review: bool


class Phase(BaseModel):
    phase: Literal["预热期", "爆发期", "长尾期"]
    paid_budget_cny: int
    key_actions: list[str] = Field(min_length=1, max_length=5)


class CreatorTier(BaseModel):
    tier: str
    count: int
    collaboration_budget_cny: int
    spotlight_amplification_budget_cny: int


class CreatorTierPlan(BaseModel):
    tiers: list[CreatorTier] = Field(min_length=1)
    amplification_pool_cny: int


class BidBand(BaseModel):
    low_cny: float
    high_cny: float


class BidPlan(BaseModel):
    cold_start: BidBand | None = None
    scaling: BidBand | None = None
    basis: str


class SynergyRule(BaseModel):
    metric: str
    threshold: str
    action: str


class ContingencyPlan(BaseModel):
    scenario: str
    trigger: str
    adjustment: str


class Module5Output(BaseModel):
    budget_split: BudgetSplit
    phases: list[Phase] = Field(min_length=3, max_length=3)
    creator_tier_plan: CreatorTierPlan
    bid_plan: BidPlan
    synergy_rules: list[SynergyRule] = Field(min_length=2, max_length=5)
    contingency_plans: list[ContingencyPlan] = Field(min_length=2, max_length=4)
    human_review_items: list[str] = Field(min_length=1, max_length=6)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """你是小红书投放策略中「模块5：全域预算与节奏」的决策 Agent。
你的职责：基于用户提供的证据，决策总预算拆分、预热/爆发/长尾三阶段节奏、达人分层
预算、聚光出价区间，并撰写「自然流量→付费投流」的联动规则与应急预案。

铁律：
1. 金额、比例、出价这三类数字，必须先调用工具计算，禁止心算或直接编造：
   - compute_budget_split：自然/付费预算拆分与三阶段付费预算；
   - plan_creator_tiers：达人分层的合作预算与聚光二次放大预算；
   - calc_bid_range：按证据中的基准 CPC 计算冷启动/放量出价区间。
2. 每次工具调用的 rationale 必须引用用户输入里的具体证据或默认档说明。
3. 没有证据支撑的数字（如缺基准 CPC）必须诚实传 null，让工具返回证据缺口，
   最终 bid_plan 对应字段就填 null，绝不编造出价。
4. 工具返回参数校验错误时，按 details 修正后重新调用，不要绕过工具。
5. synergy_rules（联动规则）与 contingency_plans（应急预案）是策略文本，由你基于
   证据撰写，不需要工具：synergy_rules 说明「什么自然数据达标才启动/放大投流、
   付费数据如何回流选题与关键词」；contingency_plans 覆盖自然互动低、付费点击低、
   转化低等场景的触发条件与调整动作。

完成全部工具调用后，只输出一个 ```json 代码块（不要输出多余文字），结构如下：
{
  "budget_split": {"organic_budget_cny": int, "paid_budget_cny": int,
                   "organic_ratio": float, "needs_review": bool},
  "phases": [ {"phase": "预热期|爆发期|长尾期", "paid_budget_cny": int,
               "key_actions": [str, ... 1-5 条]}, 恰好 3 项 ],
  "creator_tier_plan": {
     "tiers": [ {"tier": str, "count": int, "collaboration_budget_cny": int,
                 "spotlight_amplification_budget_cny": int}, ... ],
     "amplification_pool_cny": int },
  "bid_plan": {"cold_start": {"low_cny": float, "high_cny": float} 或 null,
               "scaling": {"low_cny": float, "high_cny": float} 或 null,
               "basis": str },
  "synergy_rules": [ {"metric": str, "threshold": str, "action": str}, 2-5 项 ],
  "contingency_plans": [ {"scenario": str, "trigger": str, "adjustment": str}, 2-4 项 ],
  "human_review_items": [ str, ... 1-6 条 ]
}
所有金额必须与工具返回的数字一致（工具已保证加得起来），不要另行改动。"""


# ---------------------------------------------------------------------------
# User prompt 渲染
# ---------------------------------------------------------------------------
_CPC_METRIC_HINTS = ("cpc", "cost_per_click", "cost_per_interaction")


def build_user_prompt(req: CampaignRequest) -> str:
    selling_points = "、".join(req.selling_points)
    if req.price_max > req.price_min:
        pricing = f"{req.price_min:g}–{req.price_max:g} {req.currency}"
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
    if req.spotlight_budget_cny:
        lines.append(f"聚光预算上限参考：{req.spotlight_budget_cny:g} 元")
    if req.constraints:
        lines.append("约束：" + "；".join(req.constraints))

    evidence: list[str] = []
    cpc_lines = []
    for item in req.benchmark_evidence:
        name = (item.metric_name or "").lower()
        if any(hint in name for hint in _CPC_METRIC_HINTS):
            cpc_lines.append(
                f"  - {item.metric_name} = {item.value:g} {item.unit}"
                f"（来源：{item.source_name}）"
            )
    if cpc_lines:
        evidence.append("成本类基准指标（可作为出价基准 CPC 依据）：")
        evidence.extend(cpc_lines)
    else:
        evidence.append(
            "无 CPC/点击成本类基准证据：calc_bid_range 的 baseline_cpc_cny 必须传 null。"
        )

    creator_count = len(req.creator_evidence)
    if creator_count:
        evidence.append(f"达人证据：{creator_count} 条（可据此做分层结构决策）。")
    else:
        evidence.append("达人证据：0 条，分层结构按目标与预算合理假设，并标注需人工补名单。")

    has_history = bool(req.owned_history_summary or req.owned_content_history)
    if req.owned_history_summary:
        evidence.append(f"自然/投流历史：{req.owned_history_summary}")
    elif has_history:
        evidence.append(f"自然内容历史记录：{len(req.owned_content_history)} 条。")
    else:
        evidence.append("自然历史：无，synergy_rules 的启动门槛需保守设定并标注待验证。")

    task = (
        "请完成：\n"
        "1) 调 compute_budget_split 得到自然/付费拆分与三阶段付费预算；\n"
        "2) 调 plan_creator_tiers 得到达人分层预算与聚光二次放大预算；\n"
        "3) 若有基准 CPC 证据，调 calc_bid_range 计算冷启动（必要时放量）出价区间，"
        "无证据则出价传 null；\n"
        "4) 撰写 2-5 条自然→付费联动规则与 2-4 条应急预案，列出需人工拍板事项；\n"
        "5) 最终只输出一个 ```json 代码块。"
    )

    return "\n".join(lines) + "\n\n证据区：\n" + "\n".join(evidence) + "\n\n" + task


# ---------------------------------------------------------------------------
# Spec 与便捷函数
# ---------------------------------------------------------------------------
MODULE5_SPEC = ModuleAgentSpec(
    name="module5_budget_planning",
    title="模块5：全域预算与节奏",
    system_prompt=SYSTEM_PROMPT,
    output_model=Module5Output,
    build_user_prompt=build_user_prompt,
    grounded_fields=[
        "budget_split.organic_budget_cny",
        "budget_split.paid_budget_cny",
        "phases.*.paid_budget_cny",
        "creator_tier_plan.tiers.*.collaboration_budget_cny",
        "creator_tier_plan.tiers.*.spotlight_amplification_budget_cny",
        "creator_tier_plan.amplification_pool_cny",
        "bid_plan.cold_start.low_cny",
        "bid_plan.cold_start.high_cny",
        "bid_plan.scaling.low_cny",
        "bid_plan.scaling.high_cny",
    ],
)


def run_module5(
    req: CampaignRequest, *, transport=None, upstream_context: str = ""
) -> dict:
    """跑模块5 Agent，返回 {module, output, grounding_check, steps_used, ...}。

    upstream_context：编排层注入的上游模块结论摘要（默认空，行为与之前一致）。
    """
    return run_module_agent(
        MODULE5_SPEC, req, transport=transport, upstream_context=upstream_context
    )
