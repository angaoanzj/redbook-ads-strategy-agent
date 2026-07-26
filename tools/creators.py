"""达人分层预算工具：原 engine._creator_plan 中「分层预算数学」的工具化版本。

旧版把 素人12/达人6/KOL2、50/35/15 写死；现在分层结构是 LLM 的决策，
工具校验比例合计为 1、层级不重复，并完成全部金额计算。
候选名单排序/证据标记仍留在 engine（后续步骤再迁移）。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from tools.registry import ToolSpec


class TierAllocation(BaseModel):
    tier: Literal["素人", "达人", "KOL"]
    count: int = Field(ge=1, le=100, description="该层级合作达人数量")
    budget_ratio: float = Field(gt=0, lt=1, description="占达人合作预算的比例")


class CreatorTierPlanArgs(BaseModel):
    """LLM 提交的达人分层决策参数。"""

    organic_budget_cny: float = Field(gt=0, description="达人合作预算池（元）")
    paid_budget_cny: float = Field(ge=0, description="聚光投流总预算（元）")
    amplification_ratio: float = Field(
        default=0.30,
        ge=0.10,
        le=0.50,
        description="从聚光预算中拨给达人笔记二次放大的比例，默认 0.30",
    )
    allocations: list[TierAllocation] = Field(
        min_length=1, max_length=3, description="各层级的数量与预算比例"
    )
    rationale: str = Field(min_length=10, description="分层结构的决策理由")

    @model_validator(mode="after")
    def check(self) -> "CreatorTierPlanArgs":
        tiers = [item.tier for item in self.allocations]
        if len(tiers) != len(set(tiers)):
            raise ValueError("层级不能重复")
        total = sum(item.budget_ratio for item in self.allocations)
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"budget_ratio 合计必须为 1.0，当前为 {total:.3f}")
        return self


def plan_creator_tiers(args: CreatorTierPlanArgs) -> dict[str, Any]:
    pool = args.paid_budget_cny * args.amplification_ratio
    tiers: list[dict[str, Any]] = []
    for item in args.allocations:
        collab = round(args.organic_budget_cny * item.budget_ratio)
        spotlight = round(pool * item.budget_ratio)
        tiers.append({
            "tier": item.tier,
            "count": item.count,
            "budget_ratio": item.budget_ratio,
            "collaboration_budget_cny": collab,
            "suggested_quote_per_creator_cny": round(collab / item.count),
            "spotlight_amplification_budget_cny": spotlight,
            "suggested_spotlight_per_note_cny": round(spotlight / item.count),
        })
    return {
        "collaboration_budget_pool_cny": round(args.organic_budget_cny),
        "spotlight_amplification_pool_cny": round(pool),
        "amplification_ratio": args.amplification_ratio,
        "tiers": tiers,
        "decision_rationale": args.rationale,
        "policy": "本工具只做预算数学；达人候选名单必须来自真实证据，不得编造",
    }


CREATOR_TOOLS = [
    ToolSpec(
        name="plan_creator_tiers",
        description=(
            "按 LLM 提出的素人/达人/KOL 分层结构计算合作预算、单人报价参考、"
            "聚光二次放大预算。比例必须合计为 1，金额由本工具保证准确。"
        ),
        args_model=CreatorTierPlanArgs,
        fn=plan_creator_tiers,
    )
]
