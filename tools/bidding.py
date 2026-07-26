"""出价区间工具：原 engine._bid_range 的工具化版本。

LLM 决策：投放阶段与倍率区间（护栏内）。
工具保证：倍率合法（low < high）、缺基准 CPC 时诚实返回证据缺口而非编造数字。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from tools.registry import ToolSpec


def _normalize_bid_aliases(data: Any) -> Any:
    """兼容 LLM 把 forecast 的 baseline_cpc_source 误传到本工具。"""
    if not isinstance(data, dict):
        return data
    payload = dict(data)
    if not payload.get("baseline_source") and payload.get("baseline_cpc_source"):
        payload["baseline_source"] = payload["baseline_cpc_source"]
    return payload

# 各阶段允许的倍率护栏；LLM 只能在护栏内选值
STAGE_GUARDRAILS: dict[str, tuple[float, float]] = {
    "cold_start": (0.80, 1.30),
    "scaling": (0.90, 1.60),
}


class BidRangeArgs(BaseModel):
    """LLM 提交的出价决策参数。"""

    stage: Literal["cold_start", "scaling"] = Field(description="投放阶段")
    baseline_cpc_cny: float | None = Field(
        default=None,
        gt=0,
        description="基准 CPC（元/点击）。必须来自输入证据；没有证据就传 null，禁止编造。",
    )
    baseline_source: str | None = Field(
        default=None,
        description=(
            "基准 CPC 的证据来源（有 baseline 时必填）。"
            "也接受误传的 baseline_cpc_source 别名。"
        ),
    )
    low_multiplier: float = Field(
        ge=0.5,
        le=2.0,
        description="出价下限倍率；cold_start 必须落在 0.8–1.3，建议默认 0.9",
    )
    high_multiplier: float = Field(
        ge=0.5,
        le=2.0,
        description="出价上限倍率；cold_start 必须落在 0.8–1.3，建议默认 1.1",
    )
    rationale: str = Field(min_length=10, description="选择该倍率区间的理由")

    @model_validator(mode="before")
    @classmethod
    def accept_source_aliases(cls, data: Any) -> Any:
        return _normalize_bid_aliases(data)

    @model_validator(mode="after")
    def check(self) -> "BidRangeArgs":
        if self.low_multiplier >= self.high_multiplier:
            raise ValueError("low_multiplier 必须小于 high_multiplier")
        low_cap, high_cap = STAGE_GUARDRAILS[self.stage]
        if not (low_cap <= self.low_multiplier and self.high_multiplier <= high_cap):
            raise ValueError(
                f"{self.stage} 阶段倍率护栏为 {low_cap}–{high_cap}，"
                f"当前 {self.low_multiplier}–{self.high_multiplier} 越界；"
                f"cold_start 请改用 0.9–1.1（切勿传 0.5–1.5）"
            )
        if self.baseline_cpc_cny is not None and not self.baseline_source:
            raise ValueError("提供 baseline_cpc_cny 时必须注明 baseline_source")
        return self


def calc_bid_range(args: BidRangeArgs) -> dict[str, Any]:
    if args.baseline_cpc_cny is None:
        return {
            "stage": args.stage,
            "low_cny_per_click": None,
            "high_cny_per_click": None,
            "evidence_status": "待补数据",
            "fallback": "缺少历史CPC：使用聚光账户实时建议价做首轮小预算测试",
            "decision_rationale": args.rationale,
        }
    return {
        "stage": args.stage,
        "low_cny_per_click": round(args.baseline_cpc_cny * args.low_multiplier, 2),
        "high_cny_per_click": round(args.baseline_cpc_cny * args.high_multiplier, 2),
        "basis": (
            f"基准CPC ¥{args.baseline_cpc_cny:.2f} × "
            f"{args.low_multiplier:.2f}–{args.high_multiplier:.2f}"
        ),
        "baseline_source": args.baseline_source,
        "evidence_status": "有来源证据，仍需以账户实时建议价校准",
        "decision_rationale": args.rationale,
    }


BIDDING_TOOLS = [
    ToolSpec(
        name="calc_bid_range",
        description=(
            "根据证据中的基准 CPC 与所选阶段倍率计算聚光出价区间。"
            "没有基准 CPC 证据时传 null，工具会返回证据缺口而非编造数字。"
        ),
        args_model=BidRangeArgs,
        fn=calc_bid_range,
    )
]
