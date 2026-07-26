"""反馈回流校准（对齐 docs/OPTIMIZATION_ROADMAP.md 第 4 节）。

读取 feedback_records.field_corrections 与 backfilled_cases，按品牌聚合出
「校准后的默认档」。护栏类（出价倍率、止损倍率）只产出人工复核建议，不自动放宽。

最小样本量不足时返回 status=insufficient，调用方应继续用全局默认档。
"""
from __future__ import annotations

from typing import Any

# 达到该样本量后才视为「可注入」的品牌校准档
MIN_CALIBRATION_SAMPLES = 3

# 允许从反馈里校准的软默认字段（护栏不在此列）
_SOFT_FIELDS = frozenset({
    "organic_ratio",
    "ctr_threshold",
    "engagement_threshold",
    "test_budget_ratio",
})

# 护栏字段：只建议、不自动写进 defaults
_GUARDRAIL_FIELDS = frozenset({
    "cold_start_bid_low_mult",
    "cold_start_bid_high_mult",
    "scaling_bid_low_mult",
    "scaling_bid_high_mult",
    "stop_loss_cpc_mult",
    "stop_loss_cpa_mult",
})


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _collect_numeric_corrections(
    feedback_rows: list[dict[str, Any]],
) -> dict[str, list[float]]:
    buckets: dict[str, list[float]] = {}
    for row in feedback_rows:
        for item in _as_list(row.get("field_corrections")):
            payload = _as_dict(item)
            field = str(payload.get("field") or "").strip()
            if not field:
                continue
            raw = payload.get("actual_value")
            if raw is None:
                raw = payload.get("suggested_value")
            try:
                number = float(raw)
            except (TypeError, ValueError):
                continue
            buckets.setdefault(field, []).append(number)
    return buckets


def load_brand_calibration(
    store: Any,
    brand_name: str,
    *,
    min_samples: int = MIN_CALIBRATION_SAMPLES,
) -> dict[str, Any]:
    """按品牌生成校准结果。

    返回：
      - status: ready | insufficient
      - defaults: 可注入 prompt 的软默认档
      - guardrail_suggestions: 仅人工复核的护栏调整建议
      - sample_count / feedback_count / case_count
    """
    brand = (brand_name or "").strip()
    if not brand:
        return {
            "status": "insufficient",
            "brand_name": brand_name,
            "defaults": {},
            "guardrail_suggestions": [],
            "sample_count": 0,
            "feedback_count": 0,
            "case_count": 0,
            "reason": "缺少品牌名",
        }

    feedback_rows = store.list_feedback_for_brand(brand, limit=100)
    case_rows = store.list_backfilled_cases_for_brand(brand, limit=100)
    # 样本：有 field_corrections 的反馈 + 非 mock 回填案例
    usable_feedback = [
        row for row in feedback_rows if _as_list(row.get("field_corrections"))
    ]
    usable_cases = [row for row in case_rows if not row.get("is_mock")]
    sample_count = len(usable_feedback) + len(usable_cases)

    buckets = _collect_numeric_corrections(usable_feedback)
    defaults: dict[str, float] = {}
    for field in _SOFT_FIELDS:
        median = _median(buckets.get(field) or [])
        if median is not None:
            defaults[field] = round(median, 4)

    guardrail_suggestions: list[str] = []
    for field in _GUARDRAIL_FIELDS:
        values = buckets.get(field) or []
        median = _median(values)
        if median is None:
            continue
        guardrail_suggestions.append(
            f"{field} 历史中位数约 {median:g}，请人工决定是否调整护栏（系统不会自动放宽）"
        )

    if sample_count < max(1, min_samples):
        return {
            "status": "insufficient",
            "brand_name": brand,
            "defaults": defaults,
            "guardrail_suggestions": guardrail_suggestions,
            "sample_count": sample_count,
            "feedback_count": len(usable_feedback),
            "case_count": len(usable_cases),
            "reason": f"样本不足（需要 ≥{min_samples}，当前 {sample_count}）",
        }

    return {
        "status": "ready",
        "brand_name": brand,
        "defaults": defaults,
        "guardrail_suggestions": guardrail_suggestions,
        "sample_count": sample_count,
        "feedback_count": len(usable_feedback),
        "case_count": len(usable_cases),
    }
