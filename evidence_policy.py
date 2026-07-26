"""证据治理策略：等级梯子仲裁、指标口径纪律、模块状态判定。

移植自零代码治理规范（docs/no-code-agent/）：
- `01_全局证据与数据纪律.md`：证据等级与允许结论、Mock 隔离、未来值必须区间化；
- `02_模块状态输出契约.md`：`status` 只能是完成 / 带缺口完成 / 阻塞，且不得删 `unresolved_gaps`；
- `03_跨模块依赖与冲突处理.md` 第 2 节：冲突优先级 A > C > B > D > E > Mock，
  同级但数值/口径不同时停止下游正式计算并升级人工裁决；
- `04_指标单一事实源规范.md`：`benchmark_registry` 的 `period` / `formula` /
  `value_kind`（历史事实精确、未来建议区间）。

设计约束（与 report_agent_view.py 一致）：
- 纯标准库、Python 3.10 兼容；**绝不 import engine / main / report_view**，
  这样核心治理逻辑可以在只有 3.10 的沙盒里直接单测；
- 全部函数对脏数据容错，不抛异常（治理层不应把报告打挂）。
"""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# 1. 证据等级梯子（对齐 03 文档第 2 节的冲突优先级，越靠前越优先）
# ---------------------------------------------------------------------------
EVIDENCE_PRIORITY: list[str] = [
    "A_官方或授权",
    "C_用户导入",
    "B_公开观察",
    "D_行业基准",
    "E_策略假设",
    "M",
]

MOCK_LEVEL = "M"

# 名次留空档（每级 ×10），让「未声明等级」能插在 E_策略假设 与 Mock 之间自成一组：
# 未声明等级不可越过已声明的 A/C/B/D/E，但仍优于永不可当选的 Mock。
_RANK_STEP = 10
_UNKNOWN_RANK = EVIDENCE_PRIORITY.index("E_策略假设") * _RANK_STEP + _RANK_STEP // 2
_MOCK_RANK = EVIDENCE_PRIORITY.index(MOCK_LEVEL) * _RANK_STEP

# 代码版 evidence_grade 的实际取值域 → 梯子标签
# （models.py 默认值 + 存档 JSON 里出现过的写法，全部归一）
_GRADE_ALIASES: dict[str, str] = {
    "a": "A_官方或授权",
    "a_official_public_rule": "A_官方或授权",
    "a_official": "A_官方或授权",
    "a_authorized": "A_官方或授权",
    "b": "B_公开观察",
    "b_public_observation": "B_公开观察",
    "c": "C_用户导入",
    "c_user_provided": "C_用户导入",
    "c_user_provided_workbook": "C_用户导入",
    "c_manual_paste": "C_用户导入",
    "d": "D_行业基准",
    "d_industry_benchmark": "D_行业基准",
    "e": "E_策略假设",
    "e_strategy_assumption": "E_策略假设",
    "m": MOCK_LEVEL,
    "mock": MOCK_LEVEL,
}

# 关键词兜底（中英混写、自由文本写法）
_LEVEL_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("mock", "模拟", "演示补全"), MOCK_LEVEL),
    (("官方", "授权", "official", "authorized"), "A_官方或授权"),
    (("用户导入", "导入", "工作簿", "workbook", "user_provided", "manual_paste"), "C_用户导入"),
    (("公开观察", "公开", "observation", "public"), "B_公开观察"),
    (("行业基准", "行业", "benchmark", "industry"), "D_行业基准"),
    (("策略假设", "假设", "assumption", "hypothesis"), "E_策略假设"),
]

# 来源名兜底：没有任何 evidence_grade 时，从来源措辞反推等级
# （账户实测 / 品牌工作簿属于 C_用户导入；行业报告属于 D_行业基准）
_SOURCE_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("官方", "授权"), "A_官方或授权"),
    (("账户", "实测", "数据需求", "工作簿", "后台", "导入"), "C_用户导入"),
    (("行业", "报告", "基准", "参考"), "D_行业基准"),
    (("公开", "笔记", "观察"), "B_公开观察"),
]


def normalize_evidence_level(raw: Any) -> str | None:
    """把任意写法的证据等级归一到 EVIDENCE_PRIORITY 里的标签；无法识别返回 None。

    兼容：简写 "A"/"C"/"M"、代码版 "C_user_provided"/"A_official_public_rule"/
    "C_manual_paste"、零代码版 "A_官方或授权"、以及自由文本（含「行业基准」等）。
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text in EVIDENCE_PRIORITY:
        return text
    lowered = text.casefold()
    if lowered in _GRADE_ALIASES:
        return _GRADE_ALIASES[lowered]
    # "A_官方或授权" / "a_xxx" 这类带前缀字母的写法
    head = lowered.split("_", 1)[0]
    if len(head) == 1 and head in _GRADE_ALIASES:
        return _GRADE_ALIASES[head]
    for needles, level in _LEVEL_KEYWORDS:
        if any(needle in lowered for needle in needles):
            return level
    return None


def evidence_level_rank(level: Any) -> int:
    """梯子名次：数字越小越优先；未识别的等级排在 E 之后、Mock 之前，独立成组。"""
    normalized = normalize_evidence_level(level)
    if normalized is None:
        return _UNKNOWN_RANK
    try:
        return EVIDENCE_PRIORITY.index(normalized) * _RANK_STEP
    except ValueError:  # 理论上不可达
        return _UNKNOWN_RANK


def is_mock_level(level: Any) -> bool:
    return normalize_evidence_level(level) == MOCK_LEVEL


def candidate_evidence_level(candidate: dict[str, Any]) -> str | None:
    """取候选的证据等级：显式 evidence_level / evidence_grade 优先，其次 is_mock，
    最后按来源措辞反推（账户实测→C，行业报告→D）；都识别不出返回 None。"""
    if not isinstance(candidate, dict):
        return None
    for key in ("evidence_level", "evidence_grade"):
        level = normalize_evidence_level(candidate.get(key))
        if level is not None:
            return level
    if candidate.get("is_mock") is True:
        return MOCK_LEVEL
    source = str(candidate.get("source_name") or "")
    for needles, level in _SOURCE_HINTS:
        if any(needle in source for needle in needles):
            return level
    return None


# ---------------------------------------------------------------------------
# 2. SSOT 选值：等级梯子 → 同级口径一致取最新 → 同级分歧升级人工裁决
# ---------------------------------------------------------------------------
VALUE_TOLERANCE = 0.01  # ±1%：同级候选口径是否一致的判定阈值

CONFLICT_ESCALATION = "同等级证据数值冲突，停止下游正式计算，需人工裁决"
MOCK_ONLY_NOTE = "仅有 Mock 候选，不得用于正式决策"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _collected_key(candidate: dict[str, Any]) -> str:
    if not isinstance(candidate, dict):
        return ""
    return str(candidate.get("collected_at") or "")


def values_within_tolerance(values: list[Any], tolerance: float = VALUE_TOLERANCE) -> bool:
    """同组候选数值口径是否一致（相对差 ≤ tolerance）。

    非数值候选只接受完全相等；数值与非数值混排一律判为不一致。
    """
    if len(values) <= 1:
        return True
    numbers = [value for value in values if _is_number(value)]
    if len(numbers) != len(values):
        return len({str(value) for value in values}) == 1
    low, high = min(numbers), max(numbers)
    if low == high:
        return True
    scale = max(abs(low), abs(high))
    if scale == 0:
        return False
    return (high - low) / scale <= tolerance


def resolve_ssot_selection(
    candidates: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """按证据等级梯子仲裁单一事实源，返回选值决策。

    三段逻辑（对齐 03 文档第 2 节 + 04 文档第 2 节）：
      a. 按 EVIDENCE_PRIORITY 取最高等级组；
      b. 组内多候选且数值口径一致（±1%）→ 取最新采集（collected_at 最大）；
      c. 组内数值分歧 > 1% → 不选值，返回 escalation + conflict_candidates。

    Mock（M 级）永远不可当选：只有当组内**只有** Mock 时它才会成为最高等级组，
    此时 selected=None 并给出 note。

    返回：{"selected", "evidence_level", "escalation", "conflict_candidates", "note"}。
    """
    decision: dict[str, Any] = {
        "selected": None,
        "evidence_level": None,
        "escalation": None,
        "conflict_candidates": [],
        "note": None,
    }
    pool = [item for item in (candidates or []) if isinstance(item, dict)]
    if not pool:
        return decision

    ranked = sorted(pool, key=lambda item: evidence_level_rank(candidate_evidence_level(item)))
    best_rank = evidence_level_rank(candidate_evidence_level(ranked[0]))
    group = [
        item
        for item in ranked
        if evidence_level_rank(candidate_evidence_level(item)) == best_rank
    ]
    decision["evidence_level"] = candidate_evidence_level(group[0])

    # Mock 组：只可能出现在「全部候选都是 Mock」时，绝不当选
    if best_rank == _MOCK_RANK:
        decision["note"] = MOCK_ONLY_NOTE
        decision["conflict_candidates"] = list(group)
        return decision

    if len(group) == 1:
        decision["selected"] = group[0]
        return decision

    if values_within_tolerance([item.get("value") for item in group]):
        decision["selected"] = max(group, key=_collected_key)
        return decision

    decision["escalation"] = CONFLICT_ESCALATION
    decision["conflict_candidates"] = list(group)
    return decision


# ---------------------------------------------------------------------------
# 3. value_kind 纪律（04 文档第 2 节第 4/5 条）
# ---------------------------------------------------------------------------
HISTORICAL_FACT = "historical_fact"
FORWARD_ESTIMATE = "forward_estimate"

_RANGE_KEYS = ("band", "range", "low", "high", "min", "max", "pairs")


def _metric_label(metric: dict[str, Any], index: int) -> str:
    for key in ("metric_name", "id", "name"):
        text = str(metric.get(key) or "").strip()
        if text:
            return text
    return f"第 {index + 1} 项指标"


def _has_range_representation(metric: dict[str, Any]) -> bool:
    """指标是否以区间/带宽表达（value 本身是二元区间，或带 low/high/band 字段）。"""
    value = metric.get("value")
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return True
    if isinstance(value, dict) and any(
        any(hint in str(key).casefold() for hint in ("low", "high", "min", "max"))
        for key in value
    ):
        return True
    for key, sub in metric.items():
        if key == "value":
            continue
        lowered = str(key).casefold()
        if any(hint in lowered for hint in _RANGE_KEYS) and sub not in (None, "", [], {}):
            return True
    return False


def check_value_kind_discipline(metrics: list[dict[str, Any]] | None) -> list[str]:
    """校验历史事实/未来建议的表达纪律，返回违规描述列表（空列表表示通过）。

    - `historical_fact` 必须是标量精确值（不得改写成区间，也不得缺值）；
    - `forward_estimate` 若以单一标量出现（而非区间/带宽）→ 记违规
      「未来建议必须表达为范围」。
    未标 `value_kind` 的指标不在本函数的判定范围内（04 文档只约束已声明口径的指标）。
    """
    violations: list[str] = []
    for index, metric in enumerate(metrics or []):
        if not isinstance(metric, dict):
            continue
        kind = str(metric.get("value_kind") or "").strip()
        if not kind:
            continue
        label = _metric_label(metric, index)
        value = metric.get("value")
        if kind == HISTORICAL_FACT:
            if not _is_number(value):
                violations.append(
                    f"{label}：value_kind=historical_fact 必须是标量精确值，当前 {value!r}"
                )
            elif _has_range_representation(metric):
                violations.append(
                    f"{label}：历史事实不得改写成区间/带宽（保留导入或授权来源的精确值）"
                )
        elif kind == FORWARD_ESTIMATE:
            if _is_number(value) and not _has_range_representation(metric):
                violations.append(
                    f"{label}：未来建议必须表达为范围，不得给单点值 {value!r}"
                )
            elif value is None and not _has_range_representation(metric):
                violations.append(
                    f"{label}：未来建议必须表达为范围，当前既无区间也无取值"
                )
    return violations


# ---------------------------------------------------------------------------
# 4. module_state：completed / completed_with_gaps（blocked 由编排层判定）
# ---------------------------------------------------------------------------
STATUS_COMPLETED = "completed"
STATUS_COMPLETED_WITH_GAPS = "completed_with_gaps"
STATUS_BLOCKED = "blocked"
STATUS_FAILED = "failed"

MODULE_STATUSES = (
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_GAPS,
    STATUS_BLOCKED,
    STATUS_FAILED,
)

# 输出文本里出现即视为「带缺口完成」的待办标记（对齐六模块契约里的诚实措辞）
GAP_MARKERS: tuple[str, ...] = (
    "待接入",
    "待补",
    "待人工",
    "待投手",
    "待确认",
    "演示补全",
)

MODULE_STATUS_LABELS: dict[str, str] = {
    STATUS_COMPLETED: "已完成",
    STATUS_COMPLETED_WITH_GAPS: "带缺口完成",
    STATUS_BLOCKED: "已阻塞",
    STATUS_FAILED: "执行失败",
}

MODULE_STATUS_TONES: dict[str, str] = {
    STATUS_COMPLETED: "green",
    STATUS_COMPLETED_WITH_GAPS: "orange",
    STATUS_BLOCKED: "red",
    STATUS_FAILED: "red",
}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            ordered.append(text)
    return ordered


def _serialize(output: Any) -> str:
    try:
        return json.dumps(output, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(output)


def find_gap_markers(output: Any) -> list[str]:
    """输出 JSON 文本里命中的待办标记（按 GAP_MARKERS 顺序去重）。"""
    text = _serialize(output)
    return [marker for marker in GAP_MARKERS if marker in text]


def derive_module_status(
    output: Any, grounding_check: dict[str, Any] | None = None
) -> dict[str, Any]:
    """纯代码判定模块状态（不靠 LLM 自述），返回 {module_status, unresolved_gaps}。

    判定（对齐 02 文档：不得以「已完成」掩盖 unresolved_gaps）：
      - grounding_check.passed 为 False → completed_with_gaps，缺口写入各 mismatch；
      - 输出文本命中 GAP_MARKERS 任一 → completed_with_gaps，缺口取 human_review_items；
      - 否则 completed。
    `blocked` 由编排层（module_agents.orchestrator）按硬前序判定，本函数不产生。
    """
    gaps: list[str] = []
    status = STATUS_COMPLETED

    grounding = grounding_check if isinstance(grounding_check, dict) else {}
    if grounding and grounding.get("passed") is not True:
        status = STATUS_COMPLETED_WITH_GAPS
        mismatches = grounding.get("mismatches")
        if not isinstance(mismatches, list) or not mismatches:
            gaps.append("数字溯源未通过，需人工复核")
        for mismatch in mismatches if isinstance(mismatches, list) else []:
            if isinstance(mismatch, dict):
                gaps.append(
                    f"数字未溯源：{mismatch.get('path')} = {mismatch.get('value')}"
                )
            else:
                gaps.append(f"数字未溯源：{mismatch}")

    markers = find_gap_markers(output)
    if markers:
        status = STATUS_COMPLETED_WITH_GAPS
        review_items = output.get("human_review_items") if isinstance(output, dict) else None
        if isinstance(review_items, list) and review_items:
            gaps.extend(str(item) for item in review_items)
        else:
            gaps.append("输出含待办标记：" + "、".join(markers))

    return {"module_status": status, "unresolved_gaps": _dedupe(gaps)}


def module_status_badge(status: Any, gap_count: int = 0) -> dict[str, Any]:
    """状态徽标：completed=绿 / completed_with_gaps=橙 / blocked=红。"""
    text = str(status or "").strip()
    if text not in MODULE_STATUSES:
        text = STATUS_COMPLETED
    label = MODULE_STATUS_LABELS[text]
    if text == STATUS_COMPLETED_WITH_GAPS and gap_count:
        label = f"{label}（缺口 {gap_count} 项）"
    return {
        "status": text,
        "label": label,
        "tone": MODULE_STATUS_TONES[text],
    }
