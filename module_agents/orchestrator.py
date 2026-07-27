"""模块间依赖传递编排（对齐 docs/OPTIMIZATION_ROADMAP.md 第 3 节）。

现状短板是六个模块按数字顺序独立执行、彼此不传结论；这里把编排职责收在一层：
- 按业务依赖顺序执行：M1 → M2 → M6 → M3 → M4 → M5
  （先赛道判读 → 人群与选题 → 关键词词库 → 达人匹配 → 聚光决策 → 预算统筹）；
- 每个模块跑完后，把它的结论压缩成一段 ≤600 字的中文摘要（build_upstream_digest），
  注入后续模块的 user prompt（base.run_module_agent 的 upstream_context 参数）；
- 模块6 成功后额外注入完整共享词表（build_shared_keyword_handoff），供模块3 复用，
  避免两套 build_keyword_tiers 结果冲突；
- 硬前序检查：前序模块
  failed / blocked 时，本模块不执行并记 blocked，而不是继续推断；前序
  completed_with_gaps 时照常执行，但在 upstream_context 里附一行缺口提示。

设计约束：摘要在编排层生成；模块3 的 system prompt 识别共享词表标记后跳过重复建词。

本文件只依赖 models / evidence_policy / 模块便捷函数，绝不 import engine。
"""
from __future__ import annotations

import json
from typing import Any, Callable

from evidence_policy import (
    MODULE_STATUSES,
    STATUS_BLOCKED,
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_GAPS,
    STATUS_FAILED,
)

# 依赖顺序：先赛道 → 人群选题 → 关键词 → 达人 → 聚光决策 → 预算统筹
PIPELINE_ORDER: list[str] = [
    "module1",
    "module2",
    "module6",
    "module3",
    "module4",
    "module5",
]

# 硬前序（对齐 03 文档的前序要求表，按代码现实定义）：
#   M2/M6 依赖 M1 的赛道与观察边界；M3 依赖 M2 人群 + M6 关键词；
#   M4 依赖 M3 候选；M5 依赖 M4 测试方案。
# 缺硬前序时不得继续推断（03 文档第 1 节末句），只能标 blocked 并列入人工复核。
PREREQUISITES: dict[str, list[str]] = {
    "module2": ["module1"],
    "module6": ["module1"],
    "module3": ["module2", "module6"],
    "module4": ["module3"],
    "module5": ["module4"],
}

# 前序处于这些状态时，下游必须阻塞（completed_with_gaps 不阻塞，只降级提示）
BLOCKING_STATUSES: frozenset[str] = frozenset({STATUS_FAILED, STATUS_BLOCKED})

BLOCKED_REASON = "硬前序缺失，按治理规范不得继续推断"

MODULE_LABELS: dict[str, str] = {
    "module1": "模块1（赛道与竞品）",
    "module2": "模块2（人群与内容）",
    "module6": "模块6（关键词策略）",
    "module3": "模块3（关键词与达人）",
    "module4": "模块4（聚光投流决策）",
    "module5": "模块5（预算与节奏）",
}

_RUNNER_REGISTRY: dict[str, tuple[str, str]] = {
    "module1": ("module_agents.module1", "run_module1"),
    "module2": ("module_agents.module2", "run_module2"),
    "module3": ("module_agents.module3", "run_module3"),
    "module4": ("module_agents.module4", "run_module4"),
    "module5": ("module_agents.module5", "run_module5"),
    "module6": ("module_agents.module6", "run_module6"),
}

DIGEST_MAX_CHARS = 600
SHARED_KEYWORD_HANDOFF_HEADER = "【模块6共享词表】"
SHARED_KEYWORD_HANDOFF_MAX_CHARS = 4000


# ---------------------------------------------------------------------------
# 容错取值：上游输出可能因降级/契约演进缺字段，摘要函数一律不抛异常
# ---------------------------------------------------------------------------
def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _num(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _text(value)
    return f"{value:g}"


def _join(parts: list[str], sep: str = "、") -> str:
    return sep.join(part for part in parts if part)


# ---------------------------------------------------------------------------
# 各模块摘要：只提取下游最需要的结论
# ---------------------------------------------------------------------------
def _digest_module1(output: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    organic = _as_dict(output.get("organic_landscape"))
    formats = [
        f"{_text(item.get('format'))}(均互动{_num(item.get('avg_interactions'))})"
        for item in (_as_dict(row) for row in _as_list(organic.get("hot_formats")))
        if _text(item.get("format"))
    ]
    if formats:
        lines.append("热门形式：" + _join(formats))
    else:
        lines.append("热门形式：无笔记证据，未判读")
    peak = _text(organic.get("peak_hour_hypothesis"))
    if peak:
        lines.append(f"峰时假设：{peak}")

    competitor = _as_dict(output.get("competitor_breakdown"))
    gaps = [_text(gap) for gap in _as_list(competitor.get("content_gaps"))]
    if _join(gaps):
        lines.append("内容空白：" + _join(gaps))
    hypotheses = [_text(item) for item in _as_list(competitor.get("targeting_hypotheses"))][:2]
    if _join(hypotheses):
        lines.append("竞品定向假设：" + _join(hypotheses, "；"))

    risks = [
        f"{_text(item.get('risk'))}→{_text(item.get('action'))}"
        for item in (_as_dict(row) for row in _as_list(output.get("risk_alerts")))
        if _text(item.get("risk"))
    ][:3]
    if risks:
        lines.append("风险要点：" + _join(risks, "；"))
    return lines


def _digest_module2(output: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    directions = [
        f"{_text(item.get('direction'))}(自然{_num(item.get('organic_score'))}/付费{_num(item.get('paid_score'))})"
        for item in (_as_dict(row) for row in _as_list(output.get("content_directions")))
        if _text(item.get("direction"))
    ]
    if directions:
        lines.append("三方向双评分：" + _join(directions))

    topics = [
        _text(item.get("title_template"))
        for item in (_as_dict(row) for row in _as_list(output.get("topics")))
        if _text(item.get("title_template"))
    ][:5]
    if topics:
        lines.append("Top5 选题：" + _join(topics))

    screening = _as_dict(output.get("material_screening"))
    if screening.get("ctr_threshold") is not None or screening.get("engagement_threshold") is not None:
        lines.append(
            "素材筛选阈值：CTR≥"
            f"{_num(screening.get('ctr_threshold'))}、互动率≥{_num(screening.get('engagement_threshold'))}"
        )

    tags = _as_dict(_as_dict(output.get("persona")).get("targeting_tags"))
    interest = [_text(tag) for tag in _as_list(tags.get("interest_tags"))][:5]
    packages = [_text(tag) for tag in _as_list(tags.get("crowd_packages"))][:3]
    if _join(interest):
        lines.append("核心兴趣标签：" + _join(interest))
    if _join(packages):
        lines.append("人群包：" + _join(packages))
    return lines


def _digest_module6(output: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    levels = _as_dict(output.get("keyword_levels"))
    for key, label in (("core", "核心词"), ("long_tail", "长尾词"), ("blue_ocean", "蓝海词")):
        words = [
            _text(item.get("keyword"))
            for item in (_as_dict(row) for row in _as_list(levels.get(key)))
            if _text(item.get("keyword"))
        ][:5]
        if words:
            lines.append(f"{label}（前5）：" + _join(words))
    split = _as_dict(output.get("level_budget_split"))
    if split:
        lines.append(
            "三级预算比例：核心"
            f"{_num(split.get('core'))}/长尾{_num(split.get('long_tail'))}"
            f"/蓝海{_num(split.get('blue_ocean'))}"
        )
    return lines


def _digest_module3(output: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    plan = _as_dict(output.get("creator_plan"))
    tiers = [
        f"{_text(item.get('tier'))}{_num(item.get('count'))}人/合作{_num(item.get('collaboration_budget_cny'))}元"
        f"+放大{_num(item.get('spotlight_amplification_budget_cny'))}元"
        for item in (_as_dict(row) for row in _as_list(plan.get("tiers")))
        if _text(item.get("tier"))
    ]
    if tiers:
        lines.append("达人分层预算：" + _join(tiers))
    if plan.get("amplification_pool_cny") is not None:
        lines.append(f"二次放大池：{_num(plan.get('amplification_pool_cny'))}元")

    matched = _as_list(output.get("matched_creators"))
    slots = [
        f"{_text(item.get('tier'))}缺{_num(item.get('slots_needed'))}位"
        for item in (_as_dict(row) for row in _as_list(output.get("open_slots")))
        if _text(item.get("tier"))
    ]
    lines.append(
        f"已匹配达人 {len(matched)} 位" + ("；名额缺口：" + _join(slots) if slots else "；无名额缺口")
    )

    tracks = _as_dict(output.get("keyword_tracks"))
    lines.append(
        f"广告词量：搜索 {len(_as_list(tracks.get('search_ads')))} 个、"
        f"信息流 {len(_as_list(tracks.get('feed_ads')))} 个"
    )
    return lines


def _digest_module4(output: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    structure = _as_dict(output.get("account_structure"))
    campaigns = [
        f"{_text(item.get('name'))}({_text(item.get('objective'))}/{_text(item.get('placement'))}"
        f"/{_num(item.get('budget_share'))})"
        for item in (_as_dict(row) for row in _as_list(structure.get("campaigns")))
        if _text(item.get("name"))
    ]
    if campaigns:
        lines.append("计划结构：" + _join(campaigns))

    packages = [
        f"{_text(item.get('package'))}{_num(item.get('budget_share'))}"
        for item in (_as_dict(row) for row in _as_list(output.get("targeting_packages")))
        if _text(item.get("package"))
    ]
    if packages:
        lines.append("定向包比例：" + _join(packages))

    cold_start = _as_dict(_as_dict(output.get("bidding")).get("cold_start"))
    low, high = cold_start.get("bid_low_cny"), cold_start.get("bid_high_cny")
    if low is not None or high is not None:
        lines.append(f"冷启动出价区间：{_num(low)}-{_num(high)} 元/点击")
    else:
        lines.append("冷启动出价区间：无基准 CPC 证据，待人工定价")

    forecast = _as_dict(output.get("forecast"))
    stop_parts = []
    if forecast.get("stop_loss_cpc_cny") is not None:
        stop_parts.append(f"CPC>{_num(forecast.get('stop_loss_cpc_cny'))}")
    if forecast.get("stop_loss_cpa_cny") is not None:
        stop_parts.append(f"CPA>{_num(forecast.get('stop_loss_cpa_cny'))}")
    if stop_parts:
        lines.append("止损线：" + _join(stop_parts))
    if forecast.get("test_budget_cny") is not None:
        lines.append(f"测试带宽：{_num(forecast.get('test_budget_cny'))}元")
    return lines


def _digest_module5(output: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    split = _as_dict(output.get("budget_split"))
    if split:
        lines.append(
            "预算拆分：自然"
            f"{_num(split.get('organic_budget_cny'))}元 / 付费{_num(split.get('paid_budget_cny'))}元"
            f"（自然占比 {_num(split.get('organic_ratio'))}）"
        )
    phases = [
        f"{_text(item.get('phase'))}{_num(item.get('paid_budget_cny'))}元"
        for item in (_as_dict(row) for row in _as_list(output.get("phases")))
        if _text(item.get("phase"))
    ]
    if phases:
        lines.append("三阶段付费：" + _join(phases))
    rules = [
        f"{_text(item.get('metric'))}{_text(item.get('threshold'))}→{_text(item.get('action'))}"
        for item in (_as_dict(row) for row in _as_list(output.get("synergy_rules")))
        if _text(item.get("metric"))
    ][:3]
    if rules:
        lines.append("联动规则：" + _join(rules, "；"))
    return lines


_DIGEST_BUILDERS: dict[str, Callable[[dict[str, Any]], list[str]]] = {
    "module1": _digest_module1,
    "module2": _digest_module2,
    "module3": _digest_module3,
    "module4": _digest_module4,
    "module5": _digest_module5,
    "module6": _digest_module6,
}


def build_upstream_digest(module_name: str, output: dict[str, Any]) -> str:
    """把某模块输出压缩成 ≤600 字的中文纯文本摘要，供下游模块 prompt 引用。

    字段缺失一律容错（返回可能更短甚至只有标题行），绝不抛异常。
    """
    builder = _DIGEST_BUILDERS.get(module_name)
    if builder is None:
        return ""
    lines = builder(_as_dict(output))
    if not lines:
        return ""
    label = MODULE_LABELS.get(module_name, module_name)
    text = f"{label}：\n" + "\n".join(f"- {line}" for line in lines if line)
    if len(text) > DIGEST_MAX_CHARS:
        text = text[: DIGEST_MAX_CHARS - 1] + "…"
    return text


def build_shared_keyword_handoff(output: dict[str, Any]) -> str:
    """把模块6 的 keyword_levels + level_budget_split 整包交给模块3，避免两套词表。

    下游识别 SHARED_KEYWORD_HANDOFF_HEADER 后应直接复用，禁止再调 build_keyword_tiers。
    """
    payload = _as_dict(output)
    levels = _as_dict(payload.get("keyword_levels"))
    split = _as_dict(payload.get("level_budget_split"))
    if not levels and not split:
        return ""
    body = {
        "keyword_levels": levels,
        "level_budget_split": split,
    }
    try:
        encoded = json.dumps(body, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return ""
    text = (
        f"{SHARED_KEYWORD_HANDOFF_HEADER}\n"
        "模块3 必须直接采用下列词表与三级预算比例，禁止再调用 build_keyword_tiers 另起一套；"
        "仅从词库挑选 search_ads / feed_ads 并配 bid_note。\n"
        f"{encoded}"
    )
    if len(text) > SHARED_KEYWORD_HANDOFF_MAX_CHARS:
        text = text[: SHARED_KEYWORD_HANDOFF_MAX_CHARS - 1] + "…"
    return text


def format_calibration_digest(calibration: dict[str, Any]) -> str:
    """把品牌校准结果压成可注入上游上下文的短摘要。"""
    payload = _as_dict(calibration)
    if payload.get("status") != "ready":
        return ""
    defaults = _as_dict(payload.get("defaults"))
    suggestions = [
        str(item).strip()
        for item in _as_list(payload.get("guardrail_suggestions"))
        if str(item).strip()
    ][:3]
    parts = ["【品牌校准默认档（优先级低于账户实测，高于全局默认）】"]
    if defaults.get("organic_ratio") is not None:
        parts.append(f"- 建议自然预算占比：{_num(defaults.get('organic_ratio'))}")
    if defaults.get("ctr_threshold") is not None:
        parts.append(f"- 建议素材 CTR 门槛：{_num(defaults.get('ctr_threshold'))}")
    if defaults.get("engagement_threshold") is not None:
        parts.append(
            f"- 建议互动率门槛：{_num(defaults.get('engagement_threshold'))}"
        )
    if defaults.get("test_budget_ratio") is not None:
        parts.append(f"- 建议测试带宽比例：{_num(defaults.get('test_budget_ratio'))}")
    for tip in suggestions:
        parts.append(f"- 护栏建议（仅人工复核，不自动放宽）：{tip}")
    sample = payload.get("sample_count")
    if sample is not None:
        parts.append(f"- 样本数：{_num(sample)}")
    if len(parts) <= 1:
        return ""
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 硬前序检查（engine 侧编排 lazy import 复用同一套判定，逻辑不复制）
# ---------------------------------------------------------------------------
def should_block(module_name: str, completed_status_map: dict[str, Any]) -> list[str]:
    """按 PREREQUISITES 判定本模块是否因硬前序缺失而阻塞。

    参数 completed_status_map：已执行模块 → 状态（completed / completed_with_gaps /
    blocked / failed）。返回导致阻塞的前序模块名列表（空列表表示可执行）。

    口径：只有**已尝试执行且落到 failed / blocked** 的前序才阻塞下游；本次运行里
    根本没跑的前序（子集执行、engine 只挂了部分模块）不阻塞，行为与既有分批执行一致。
    """
    statuses = completed_status_map if isinstance(completed_status_map, dict) else {}
    blocked_by: list[str] = []
    for prerequisite in PREREQUISITES.get(module_name, []):
        status = statuses.get(prerequisite)
        if isinstance(status, str) and status in BLOCKING_STATUSES:
            blocked_by.append(prerequisite)
    return blocked_by


def build_gap_notice(module_name: str, status_map: dict[str, Any], gaps_map: dict[str, Any]) -> str:
    """前序为 completed_with_gaps 时，给下游 prompt 附的缺口提示行（可能为空串）。"""
    statuses = status_map if isinstance(status_map, dict) else {}
    gaps = gaps_map if isinstance(gaps_map, dict) else {}
    lines: list[str] = []
    for prerequisite in PREREQUISITES.get(module_name, []):
        if statuses.get(prerequisite) != STATUS_COMPLETED_WITH_GAPS:
            continue
        count = len(gaps.get(prerequisite) or [])
        label = MODULE_LABELS.get(prerequisite, prerequisite)
        lines.append(f"注意：上游 {label} 带缺口完成，缺口数 {count}")
    return "\n".join(lines)


def module_status_of(result: Any) -> str:
    """取模块结果里的 module_status（base 层判定）；旧结果按溯源结论兜底。"""
    payload = _as_dict(result)
    status = payload.get("module_status")
    if isinstance(status, str) and status in MODULE_STATUSES:
        return status
    grounding = _as_dict(payload.get("grounding_check"))
    return STATUS_COMPLETED if grounding.get("passed") is True else STATUS_COMPLETED_WITH_GAPS


def unresolved_gaps_of(result: Any) -> list[str]:
    gaps = _as_dict(result).get("unresolved_gaps")
    return [str(item) for item in gaps] if isinstance(gaps, list) else []


# ---------------------------------------------------------------------------
# 流水线执行
# ---------------------------------------------------------------------------
def _default_runner(module_name: str, req: Any, upstream_context: str) -> dict[str, Any]:
    """默认 runner：lazy import 对应模块的 run_moduleN 便捷函数。"""
    import importlib

    module_path, fn_name = _RUNNER_REGISTRY[module_name]
    run_fn = getattr(importlib.import_module(module_path), fn_name)
    return run_fn(req, upstream_context=upstream_context)


def run_pipeline(
    req: Any,
    module_names: list[str] | None = None,
    *,
    runner: Callable[[str, Any, str], dict[str, Any]] | None = None,
    upstream_limit: int = 3,
) -> dict[str, Any]:
    """按依赖顺序执行模块，并把最近 upstream_limit 段上游摘要注入下游 prompt。

    参数：
      module_names  只跑其中的模块（仍按 PIPELINE_ORDER 排序）；None 表示全部；
      runner        (module_name, req, upstream_context) -> 模块结果 dict，测试可注入；
      upstream_limit 注入下游的上游摘要条数上限（0 表示不注入）。

    返回：{"modules": {module_name: result}, "pipeline_trace": [...]}；
    单模块异常记 failed；其硬前序下游记 blocked（不执行），其余模块继续。
    """
    execute = runner or _default_runner
    requested = list(PIPELINE_ORDER) if module_names is None else list(module_names)
    ordered = [name for name in PIPELINE_ORDER if name in requested]

    results: dict[str, Any] = {}
    pipeline_trace: list[dict[str, Any]] = []
    digests: list[str] = []
    status_map: dict[str, str] = {}
    gaps_map: dict[str, list[str]] = {}

    for name in requested:
        if name not in PIPELINE_ORDER:
            pipeline_trace.append(
                {"module": name, "status": "skipped", "reason": "unknown_module"}
            )

    for name in ordered:
        # 硬前序缺失（前序 failed / blocked）→ 本模块不执行
        blocked_by = should_block(name, status_map)
        if blocked_by:
            status_map[name] = STATUS_BLOCKED
            pipeline_trace.append({
                "module": name,
                "status": STATUS_BLOCKED,
                "blocked_by": blocked_by,
                "reason": BLOCKED_REASON,
            })
            continue

        # 共享词表 handoff 可能很长，注入时优先保留含 SHARED_KEYWORD 的段落
        if upstream_limit > 0 and digests:
            window = digests[-upstream_limit:]
            handoffs = [d for d in digests if d.startswith(SHARED_KEYWORD_HANDOFF_HEADER)]
            if handoffs and handoffs[-1] not in window:
                window = window[1:] + [handoffs[-1]] if len(window) >= upstream_limit else window + [handoffs[-1]]
            upstream_context = "\n\n".join(window)
        else:
            upstream_context = ""
        # 前序带缺口完成：照常执行，但把缺口提示压进上下文（02 文档：不得掩盖缺口）
        gap_notice = build_gap_notice(name, status_map, gaps_map)
        if gap_notice:
            upstream_context = (
                upstream_context + "\n\n" + gap_notice if upstream_context else gap_notice
            )
        try:
            result = execute(name, req, upstream_context)
        except Exception as exc:  # 单模块失败不中断流水线（但其硬前序下游会被阻塞）
            status_map[name] = STATUS_FAILED
            pipeline_trace.append({
                "module": name,
                "status": STATUS_FAILED,
                "reason": exc.__class__.__name__,
                "detail": str(exc)[:300],
                "upstream_digest_chars": len(upstream_context),
            })
            continue

        results[name] = result
        status_map[name] = module_status_of(result)
        gaps_map[name] = unresolved_gaps_of(result)
        output = _as_dict(_as_dict(result).get("output"))
        digest = build_upstream_digest(name, output)
        if digest:
            digests.append(digest)
        if name == "module6":
            handoff = build_shared_keyword_handoff(output)
            if handoff:
                digests.append(handoff)
                pipeline_trace.append({
                    "module": name,
                    "status": "shared_keyword_handoff",
                    "chars": len(handoff),
                })
        grounding = _as_dict(_as_dict(result).get("grounding_check"))
        pipeline_trace.append({
            "module": name,
            "status": "success",
            "module_status": status_map[name],
            "unresolved_gap_count": len(gaps_map[name]),
            "steps_used": _as_dict(result).get("steps_used"),
            "repair_rounds_used": _as_dict(result).get("repair_rounds_used"),
            "grounding_passed": grounding.get("passed") is True,
            "upstream_digest_chars": len(upstream_context),
            "digest_chars": len(digest),
        })

    return {"modules": results, "pipeline_trace": pipeline_trace}
