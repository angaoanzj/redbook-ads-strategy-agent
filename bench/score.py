"""四维加权评分（0–100）与运行级汇总；另附 Critic 文本分与收敛惩罚。

维度与权重（对齐 docs/OPTIMIZATION_ROADMAP.md 第 5 节的「溯源分 / 诚实分 / 结构分」）：

| 维度 | 满分 | 判据 |
| --- | --- | --- |
| grounding | 40 | `result["grounding_check"]["passed"] is True` → 40，否则 0 |
| honesty | 25 | 诚实标记命中率 × 25（每条标记 any_of 任一措辞命中即通过） |
| invariants | 25 | 违规数为 0 得 25，每条违规扣 5，扣到 0 为止 |
| structure | 10 | 关键路径命中率 × 10 |

附加：
- text：有 `critic_review.status=ok` 时按 high/medium issues 从 total 扣分；
  无 Critic 时不计惩罚（离线回放基线仍可 100）。
- convergence：按 repair 轮次记入 detail（每轮 2 分惩罚信息），**不改 total**，
  避免「合法满分」回归夹具因一次修复轮掉分。

`result` 的形状就是 `module_agents.base.run_module_agent` 的返回：
`{"module", "output", "grounding_check", "steps_used", "repair_rounds_used", "trace"}`，
可选顶层 `critic_review`。

本文件只依赖标准库与 bench.golden，绝不 import engine / main。
"""
from __future__ import annotations

import json
from typing import Any

from bench.golden import (
    GOLDEN_EXPECTATIONS,
    MODULE_KEYS,
    check_invariants,
    golden_for,
    normalize_module_name,
    path_exists,
)

# 各维度满分
WEIGHT_GROUNDING = 40.0
WEIGHT_HONESTY = 25.0
WEIGHT_INVARIANTS = 25.0
WEIGHT_STRUCTURE = 10.0
WEIGHT_TEXT = 15.0
MAX_TOTAL = WEIGHT_GROUNDING + WEIGHT_HONESTY + WEIGHT_INVARIANTS + WEIGHT_STRUCTURE

# 每条不变量违规的扣分
INVARIANT_PENALTY = 5.0
TEXT_HIGH_PENALTY = 5.0
TEXT_MED_PENALTY = 1.5
CONVERGENCE_PENALTY_PER_ROUND = 2.0
MAX_CONVERGENCE_PENALTY = 6.0


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def serialize_output(output: Any) -> str:
    """诚实标记在「输出 JSON 序列化文本」里查找，因此这里固定 ensure_ascii=False。"""
    try:
        return json.dumps(output, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(output)


def check_honesty_markers(module_name: str, output: Any) -> dict[str, Any]:
    golden = golden_for(module_name)
    markers = list(golden["honesty_markers"]) if golden else []
    text = serialize_output(output)
    hits: list[str] = []
    missing: list[dict[str, Any]] = []
    for marker in markers:
        alternatives = [str(item) for item in marker.get("any_of", [])]
        if any(alternative and alternative in text for alternative in alternatives):
            hits.append(str(marker.get("id")))
        else:
            missing.append({
                "id": marker.get("id"),
                "any_of": alternatives,
                "why": marker.get("why"),
            })
    return {"total": len(markers), "hits": hits, "missing": missing}


def check_structure(module_name: str, output: Any) -> dict[str, Any]:
    golden = golden_for(module_name)
    paths = list(golden["required_structure"]) if golden else []
    hits: list[str] = []
    missing: list[str] = []
    for path in paths:
        (hits if path_exists(output, path) else missing).append(path)
    return {"total": len(paths), "hits": hits, "missing": missing}


def score_text_from_critic(result: dict[str, Any]) -> dict[str, Any]:
    """从 critic_review 折算文本分；无 Critic 时 skipped（不对 total 扣分）。"""
    review = _as_dict(result.get("critic_review"))
    if not review:
        return {
            "status": "skipped",
            "score": WEIGHT_TEXT,
            "penalty": 0.0,
            "high_count": 0,
            "medium_count": 0,
        }
    if review.get("status") != "ok":
        return {
            "status": "degraded",
            "score": WEIGHT_TEXT,
            "penalty": 0.0,
            "high_count": 0,
            "medium_count": 0,
            "reason": review.get("reason"),
        }
    issues = _as_list(_as_dict(review.get("report")).get("issues"))
    high = sum(1 for item in issues if _as_dict(item).get("severity") == "high")
    medium = sum(1 for item in issues if _as_dict(item).get("severity") == "medium")
    penalty = min(
        WEIGHT_TEXT,
        high * TEXT_HIGH_PENALTY + medium * TEXT_MED_PENALTY,
    )
    return {
        "status": "scored",
        "score": round(max(0.0, WEIGHT_TEXT - penalty), 2),
        "penalty": round(penalty, 2),
        "high_count": high,
        "medium_count": medium,
    }


def score_convergence(result: dict[str, Any]) -> dict[str, Any]:
    rounds = int(result.get("repair_rounds_used") or 0)
    penalty = min(MAX_CONVERGENCE_PENALTY, CONVERGENCE_PENALTY_PER_ROUND * max(0, rounds))
    return {
        "repair_rounds_used": rounds,
        "penalty": round(penalty, 2),
    }


def score_module(module_name: str, result: dict, req: dict | None = None) -> dict[str, Any]:
    """给单个模块结果打分，返回 {total, dimensions, violations, missing_markers, missing_paths}。"""
    key = normalize_module_name(module_name)
    result = _as_dict(result)
    req = _as_dict(req)
    output = _as_dict(result.get("output"))

    if key is None:
        return {
            "module": module_name,
            "label": module_name,
            "known_module": False,
            "total": 0.0,
            "dimensions": {
                "grounding": 0.0,
                "honesty": 0.0,
                "invariants": 0.0,
                "structure": 0.0,
                "text": 0.0,
            },
            "violations": [f"未知模块 {module_name!r}：不在黄金断言集内"],
            "missing_markers": [],
            "missing_paths": [],
            "notes": ["未知模块不计入 overall 平均"],
        }

    golden = GOLDEN_EXPECTATIONS[key]

    # -- grounding --
    grounding_check = _as_dict(result.get("grounding_check"))
    grounding_passed = grounding_check.get("passed") is True
    grounding_score = WEIGHT_GROUNDING if grounding_passed else 0.0
    mismatches = grounding_check.get("mismatches") or []

    # -- honesty --
    honesty = check_honesty_markers(key, output)
    honesty_rate = (len(honesty["hits"]) / honesty["total"]) if honesty["total"] else 1.0
    honesty_score = WEIGHT_HONESTY * honesty_rate

    # -- invariants --
    violations = check_invariants(key, output, req)
    invariants_score = max(0.0, WEIGHT_INVARIANTS - INVARIANT_PENALTY * len(violations))

    # -- structure --
    structure = check_structure(key, output)
    structure_rate = (len(structure["hits"]) / structure["total"]) if structure["total"] else 1.0
    structure_score = WEIGHT_STRUCTURE * structure_rate

    text_info = score_text_from_critic(result)
    convergence = score_convergence(result)
    text_penalty = (
        float(text_info["penalty"]) if text_info.get("status") == "scored" else 0.0
    )

    total = (
        grounding_score
        + honesty_score
        + invariants_score
        + structure_score
        - text_penalty
    )
    total = max(0.0, total)
    return {
        "module": key,
        "label": golden["label"],
        "known_module": True,
        "total": round(total, 2),
        "dimensions": {
            "grounding": round(grounding_score, 2),
            "honesty": round(honesty_score, 2),
            "invariants": round(invariants_score, 2),
            "structure": round(structure_score, 2),
            "text": round(float(text_info["score"]), 2),
        },
        "detail": {
            "grounding_passed": grounding_passed,
            "grounding_mismatch_count": len(mismatches) if isinstance(mismatches, list) else 0,
            "honesty_hit": len(honesty["hits"]),
            "honesty_total": honesty["total"],
            "invariant_violation_count": len(violations),
            "structure_hit": len(structure["hits"]),
            "structure_total": structure["total"],
            "steps_used": result.get("steps_used"),
            "repair_rounds_used": result.get("repair_rounds_used"),
            "text": text_info,
            "convergence": convergence,
            "text_penalty": text_penalty,
            "convergence_penalty": float(convergence["penalty"]),
        },
        "violations": violations,
        "missing_markers": honesty["missing"],
        "missing_paths": structure["missing"],
    }


def score_run(results: dict[str, dict], req: dict | None = None) -> dict[str, Any]:
    """逐模块评分 + overall 平均 + markdown 摘要。

    `results` 形如 `{module_name: run_module_agent 返回的 result}`；
    缺席的模块记进 `missing_modules`（不拉低平均，但会在 markdown 里点名）。
    """
    req = _as_dict(req)
    scored: dict[str, Any] = {}
    seen_keys: set[str] = set()
    unknown: list[str] = []
    for module_name, result in (results or {}).items():
        entry = score_module(module_name, result, req)
        if entry["known_module"]:
            seen_keys.add(entry["module"])
            scored[entry["module"]] = entry
        else:
            unknown.append(module_name)
            scored[module_name] = entry

    known_scores = [
        entry["total"] for entry in scored.values() if entry.get("known_module")
    ]
    overall = round(sum(known_scores) / len(known_scores), 2) if known_scores else 0.0
    dimension_totals = {
        "grounding": 0.0,
        "honesty": 0.0,
        "invariants": 0.0,
        "structure": 0.0,
        "text": 0.0,
    }
    for entry in scored.values():
        if not entry.get("known_module"):
            continue
        for key in dimension_totals:
            dimension_totals[key] += float(entry["dimensions"].get(key) or 0.0)
    count = len(known_scores) or 1
    dimension_avg = {key: round(value / count, 2) for key, value in dimension_totals.items()}

    summary = {
        "overall": overall,
        "module_count": len(known_scores),
        "dimension_avg": dimension_avg,
        "missing_modules": [key for key in MODULE_KEYS if key not in seen_keys],
        "unknown_modules": unknown,
        "modules": scored,
    }
    summary["markdown"] = render_markdown(summary)
    return summary


# ---------------------------------------------------------------------------
# Markdown 报告
# ---------------------------------------------------------------------------
def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".") or "0"
    return str(value)


def _fmt_delta(delta: float | None) -> str:
    if delta is None:
        return "—"
    if abs(delta) < 0.005:
        return "0"
    return f"{'+' if delta > 0 else ''}{delta:.2f}"


def render_markdown(summary: dict[str, Any], previous: dict[str, Any] | None = None) -> str:
    """评分表 + 违规明细（+ 与上次报告的分差对比，若提供 previous）。"""
    previous_modules = _as_dict(_as_dict(previous).get("modules"))
    lines: list[str] = []
    lines.append("# 六模块回归评分报告")
    lines.append("")
    overall_delta = (
        summary["overall"] - previous["overall"] if previous and "overall" in previous else None
    )
    lines.append(
        f"- 总分（模块平均）：**{_fmt(summary['overall'])} / {_fmt(MAX_TOTAL)}**"
        + (f"（较上次 {_fmt_delta(overall_delta)}）" if overall_delta is not None else "")
    )
    lines.append(f"- 参评模块数：{summary['module_count']} / {len(MODULE_KEYS)}")
    avg = summary["dimension_avg"]
    lines.append(
        "- 各维度均分：溯源 {g}/{G}、诚实 {h}/{H}、不变量 {i}/{I}、结构 {s}/{S}"
        "、文本 {t}/{T}".format(
            g=_fmt(avg["grounding"]), G=_fmt(WEIGHT_GROUNDING),
            h=_fmt(avg["honesty"]), H=_fmt(WEIGHT_HONESTY),
            i=_fmt(avg["invariants"]), I=_fmt(WEIGHT_INVARIANTS),
            s=_fmt(avg["structure"]), S=_fmt(WEIGHT_STRUCTURE),
            t=_fmt(avg.get("text", 0)), T=_fmt(WEIGHT_TEXT),
        )
    )
    if summary.get("missing_modules"):
        lines.append("- 缺席模块：" + "、".join(summary["missing_modules"]))
    if summary.get("unknown_modules"):
        lines.append("- 未知模块（不计平均）：" + "、".join(summary["unknown_modules"]))
    lines.append("")

    lines.append("## 评分表")
    lines.append("")
    lines.append(
        "| 模块 | 总分 | 较上次 | 溯源 40 | 诚实 25 | 不变量 25 | 结构 10 | 文本 15 | 违规数 |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for key, entry in sorted(summary["modules"].items()):
        prev_entry = previous_modules.get(key)
        delta = (
            entry["total"] - prev_entry["total"]
            if isinstance(prev_entry, dict) and "total" in prev_entry
            else None
        )
        dims = entry["dimensions"]
        lines.append(
            "| {label} | {total} | {delta} | {g} | {h} | {i} | {s} | {t} | {v} |".format(
                label=entry.get("label") or key,
                total=_fmt(entry["total"]),
                delta=_fmt_delta(delta),
                g=_fmt(dims["grounding"]),
                h=_fmt(dims["honesty"]),
                i=_fmt(dims["invariants"]),
                s=_fmt(dims["structure"]),
                t=_fmt(dims.get("text", 0)),
                v=len(entry.get("violations") or []),
            )
        )
    lines.append("")

    lines.append("## 违规与缺口明细")
    lines.append("")
    clean = True
    for key, entry in sorted(summary["modules"].items()):
        details: list[str] = []
        for violation in entry.get("violations") or []:
            details.append(f"  - 不变量违规：{violation}")
        for marker in entry.get("missing_markers") or []:
            details.append(
                f"  - 缺诚实标记 `{marker.get('id')}`（任一即可：{'、'.join(marker.get('any_of') or [])}）"
                f" — {marker.get('why')}"
            )
        for path in entry.get("missing_paths") or []:
            details.append(f"  - 缺关键路径：`{path}`")
        detail = entry.get("detail") or {}
        if detail.get("grounding_passed") is False:
            details.append(
                f"  - 数字溯源未通过：mismatch {detail.get('grounding_mismatch_count')} 处"
            )
        if details:
            clean = False
            lines.append(f"- **{entry.get('label') or key}**")
            lines.extend(details)
    if clean:
        lines.append("- 全部模块无违规、无缺失标记与路径。")
    lines.append("")
    return "\n".join(lines)
