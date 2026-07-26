"""聚光投流效果预估工具：原 engine._forecast_block 的工具化版本。

分工：LLM 提交决策参数（预算、来自证据的基准指标、最小转化样本），
工具用固定数学产出测试带宽、止损线与 ROI 粗算，倍率写死不由 LLM 调节；
缺基准时诚实返回证据缺口而非编造效果承诺。

本文件只依赖 pydantic 与 tools.registry，绝不 import engine。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from tools.registry import ToolSpec


def _normalize_forecast_aliases(data: Any) -> Any:
    """兼容 LLM 把 calc_bid_range 的 baseline_source 误传到本工具。

    只在 baseline_cpc_source 缺失时回填，不覆盖已正确填写的字段。
    """
    if not isinstance(data, dict):
        return data
    payload = dict(data)
    if not payload.get("baseline_cpc_source") and payload.get("baseline_source"):
        payload["baseline_cpc_source"] = payload["baseline_source"]
    return payload

# 固定数学常量（LLM 不可调）
NO_CVR_CPA_MULTIPLIER = 25  # 无 CVR 时的保守 CPA 占位（约 4% 点击转化）
TEST_BUDGET_RATIO = 0.15  # 测试带宽占聚光预算比例
TEST_BUDGET_RATIO_NO_CPA = 0.10  # 无 CPA 参照时的测试带宽比例
TEST_BUDGET_FLOOR_RATIO = 0.05  # 最低测试带宽下限（占聚光预算比例）
SAMPLE_SAFETY = 1.5  # 样本安全系数
STOP_CPC_MULTIPLIER = 1.5  # CPC 止损倍率
STOP_CPA_MULTIPLIER = 1.2  # CPA 止损倍率
ROI_BAND_LOW = 0.7  # ROI 区间下界系数
ROI_BAND_HIGH = 1.2  # ROI 区间上界系数
MIN_IMPRESSIONS = 3000  # 最低曝光门槛
MIN_CLICKS = 100  # 最低点击门槛


class PaidForecastArgs(BaseModel):
    """LLM 提交的投流效果预估参数。

    基准 CPC/CTR/CVR 必须来自输入证据；没有证据的档位传 null，
    工具会缩减为「只给测试带宽/止损」并如实标注缺口。
    aov_cny 由调用方先换算为 CNY（HKD 建议 ×0.92 参考汇率）。
    """

    paid_budget_cny: float = Field(gt=0, description="聚光投流总预算（元）")
    baseline_cpc_cny: float | None = Field(
        default=None, gt=0, description="基准 CPC（元/点击），来自证据；无则传 null"
    )
    baseline_cpc_source: str | None = Field(
        default=None, description="基准 CPC 的证据来源（提供 CPC 时必填）"
    )
    baseline_ctr: float | None = Field(
        default=None, gt=0, lt=1, description="基准点击率（0-1），来自证据；无则传 null"
    )
    baseline_ctr_source: str | None = Field(
        default=None, description="基准 CTR 的证据来源（提供 CTR 时必填）"
    )
    baseline_cvr: float | None = Field(
        default=None, gt=0, lt=1, description="基准转化率（0-1），来自证据；无则传 null"
    )
    baseline_cvr_source: str | None = Field(
        default=None, description="基准 CVR 的证据来源（提供 CVR 时必填）"
    )
    aov_cny: float = Field(
        gt=0, description="客单价（元，已换算为 CNY；HKD 参考 ×0.92）"
    )
    target_min_conversions: int = Field(
        default=20, ge=10, le=100, description="决策所需最小转化样本"
    )
    rationale: str = Field(min_length=10, description="预估口径与证据依据说明")

    @model_validator(mode="before")
    @classmethod
    def accept_source_aliases(cls, data: Any) -> Any:
        return _normalize_forecast_aliases(data)

    @model_validator(mode="after")
    def check_sources(self) -> "PaidForecastArgs":
        pairs = [
            ("baseline_cpc_cny", self.baseline_cpc_cny, self.baseline_cpc_source),
            ("baseline_ctr", self.baseline_ctr, self.baseline_ctr_source),
            ("baseline_cvr", self.baseline_cvr, self.baseline_cvr_source),
        ]
        for name, value, source in pairs:
            if value is not None and not source:
                raise ValueError(f"提供 {name} 时必须注明对应 *_source 来源")
        return self


def estimate_paid_performance(args: PaidForecastArgs) -> dict[str, Any]:
    cpc = args.baseline_cpc_cny
    ctr = args.baseline_ctr
    cvr = args.baseline_cvr

    # 目标 CPA：有 CVR 走 cpc/cvr；无 CVR 用保守占位 cpc×25；无 CPC 则 None
    target_cpa: float | None = None
    cpa_basis = "无基准 CPC：无法估算目标 CPA"
    if cpc is not None and cvr is not None:
        target_cpa = cpc / cvr
        cpa_basis = f"目标CPA = CPC ¥{cpc:.2f} ÷ CVR {cvr:.4f}"
    elif cpc is not None:
        target_cpa = cpc * NO_CVR_CPA_MULTIPLIER
        cpa_basis = (
            f"无CVR证据：目标CPA 用保守占位 CPC ¥{cpc:.2f} × {NO_CVR_CPA_MULTIPLIER}"
            "（约4%点击转化假设，仅用于测试带宽估算）"
        )

    # 测试带宽 = min(聚光×15%, 目标CPA×最小转化×1.5)；无 CPA 时用聚光×10%
    if target_cpa is not None:
        by_ratio = args.paid_budget_cny * TEST_BUDGET_RATIO
        by_sample = target_cpa * args.target_min_conversions * SAMPLE_SAFETY
        test_budget = round(min(by_ratio, by_sample))
        test_budget_basis = (
            f"min(聚光×{TEST_BUDGET_RATIO}, 目标CPA×{args.target_min_conversions}×{SAMPLE_SAFETY})"
        )
    else:
        test_budget = round(args.paid_budget_cny * TEST_BUDGET_RATIO_NO_CPA)
        test_budget_basis = f"无目标CPA：聚光×{TEST_BUDGET_RATIO_NO_CPA}"

    # 最低测试带宽下限（聚光×5%）：防止无CVR占位公式在低CPC下算出不可执行的极小带宽
    test_budget_floor = round(args.paid_budget_cny * TEST_BUDGET_FLOOR_RATIO)
    if test_budget < test_budget_floor:
        test_budget = test_budget_floor
        test_budget_basis += (
            f"；已触发最低测试带宽下限（聚光×{TEST_BUDGET_FLOOR_RATIO}）"
        )

    stop_cpc = round(cpc * STOP_CPC_MULTIPLIER, 2) if cpc is not None else None
    stop_cpa = round(target_cpa * STOP_CPA_MULTIPLIER, 2) if target_cpa is not None else None

    roi_point: float | None = None
    roi_band: list[float] | None = None
    roi_warning: str | None = None
    if cpc is not None and ctr is not None and cvr is not None:
        # ROI ≈ (1/CPC)×CVR×客单价_CNY − 1
        point = (1 / cpc) * cvr * args.aov_cny - 1
        roi_point = round(point, 2)
        roi_band = [round(point * ROI_BAND_LOW, 2), round(point * ROI_BAND_HIGH, 2)]
        roi_warning = "未计入退货、归因窗口与版位差异；上线前由投手用账户真实CVR复核"
        forecast_status = "证据齐全（CPC/CTR/CVR）：给出 ROI 粗算 + 测试带宽 + 止损"
    else:
        missing = [
            name
            for name, value in (("CPC", cpc), ("CTR", ctr), ("CVR", cvr))
            if value is None
        ]
        forecast_status = (
            f"证据不足（缺 {'/'.join(missing)}）：不输出 ROI，仅给测试带宽与止损公式"
        )

    present = [
        name
        for name, value in (("cpc", cpc), ("ctr", ctr), ("cvr", cvr))
        if value is not None
    ]
    return {
        "forecast_status": forecast_status,
        "evidence_status": {
            "baselines_present": present,
            "cpc_present": cpc is not None,
            "ctr_present": ctr is not None,
            "cvr_present": cvr is not None,
        },
        "target_cpa_cny": round(target_cpa, 2) if target_cpa is not None else None,
        "target_cpa_basis": cpa_basis,
        "test_budget_cny": test_budget,
        "test_budget_basis": test_budget_basis,
        "stop_loss": {
            "cpc_stop_cny": stop_cpc,
            "cpa_stop_cny": stop_cpa,
            "min_impressions": MIN_IMPRESSIONS,
            "min_clicks": MIN_CLICKS,
            "formula": (
                "若 (CPC>基准×1.5 或 CPA>目标×1.2) 且 (曝光≥最小样本 或 点击≥最小点击) → 暂停"
            ),
        },
        "roi_point": roi_point,
        "roi_band": roi_band,
        "roi_warning": roi_warning,
        "min_impressions": MIN_IMPRESSIONS,
        "min_clicks": MIN_CLICKS,
        "target_min_conversions": args.target_min_conversions,
        "aov_cny": args.aov_cny,
        "decision_rationale": args.rationale,
    }


FORECAST_TOOLS = [
    ToolSpec(
        name="estimate_paid_performance",
        description=(
            "按证据中的基准 CPC/CTR/CVR 与聚光预算估算首轮测试带宽、止损线与 ROI 粗算。"
            "倍率写死不可调；缺基准的档位传 null，工具会缩减输出并标注证据缺口，"
            "绝不编造效果承诺。客单价须先换算为 CNY。"
            "CPC 来源字段名为 baseline_cpc_source（也接受误传的 baseline_source 别名）。"
        ),
        args_model=PaidForecastArgs,
        fn=estimate_paid_performance,
    )
]
