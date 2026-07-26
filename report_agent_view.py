"""报告渲染：模块 Agent 决策视图 + 基准指标单一事实源（SSOT）。

设计约束：
- 纯标准库、3.10 兼容；禁止 import engine / report_view（避免循环依赖，且让核心
  逻辑可在只有 3.10 的沙盒中直接测试）。
- 所有函数字段缺失均不抛异常，尽量降级渲染。
- 通用递归渲染，不对六个模块做特判。数字保留原值，不做四舍五入。
- 证据等级仲裁与模块状态判定的规则本身放在 evidence_policy.py（同样纯标准库），
  本文件只做取字段与渲染。
"""

from __future__ import annotations

import re
from typing import Any

from evidence_policy import (
    candidate_evidence_level,
    module_status_badge,
    resolve_ssot_selection,
)


# 六个 engine_key → 中文模块名（用于 Agent 决策卡片标题）
AGENT_MODULE_LABELS: dict[str, str] = {
    "module_1_market_competitor": "赛道与竞品分析 Agent",
    "module_2_audience_content": "用户画像与内容策略 Agent",
    "module_3_keyword_creator": "关键词策略与达人匹配 Agent",
    "module_4_spotlight_decision": "聚光投流前置决策 Agent",
    "module_5_budget_pacing": "全域预算与节奏 Agent",
    "module_6_keyword_strategy": "关键词策略 Agent",
}


# 六个契约的顶层字段 + 常见嵌套字段（表格列）→ 中文标签。
# 未命中的键在 field_label() 中原样返回。
FIELD_LABELS: dict[str, str] = {
    # ---- module1 顶层 ----
    "organic_landscape": "自然流量格局",
    "paid_landscape": "付费流量格局",
    "competitor_breakdown": "竞品拆解",
    "risk_alerts": "风险预警",
    "human_review_items": "需人工复核项",
    # ---- module2 顶层 ----
    "persona": "用户画像",
    "content_directions": "内容方向",
    "topics": "爆款选题",
    "material_screening": "素材筛选标准",
    # ---- module3 顶层 ----
    "keyword_tracks": "关键词赛道",
    "creator_plan": "达人分层预算",
    "matched_creators": "达人推荐",
    "open_slots": "名额缺口",
    # ---- module4 顶层 ----
    "account_structure": "账户结构",
    "targeting_packages": "定向包",
    "bidding": "出价方案",
    "search_feed_split": "搜索/信息流分配",
    "daily_schedule": "每日投放节奏",
    "forecast": "效果预估",
    "risk_playbook": "投流问题SOP",
    # ---- module5 顶层 ----
    "budget_split": "预算拆分",
    "phases": "阶段节奏",
    "creator_tier_plan": "达人分层",
    "bid_plan": "出价方案",
    "synergy_rules": "自然付费联动",
    "contingency_plans": "应急预案",
    # ---- module6 顶层 ----
    "keyword_levels": "三级词库",
    "layout_rules": "布局规则",
    "level_budget_split": "三级预算比例",
    "trending_monitor": "热点监控",
    # ---- 常见嵌套 / 表格列 ----
    "keyword": "关键词",
    "intent": "意向",
    "lane": "版位",
    "bid_note": "出价说明",
    "core": "核心词",
    "long_tail": "长尾词",
    "blue_ocean": "蓝海词",
    "search_ads": "搜索广告词",
    "feed_ads": "信息流广告词",
    "organic": "自然分层",
    "tier": "层级",
    "count": "数量",
    "tiers": "分层",
    "collaboration_budget_cny": "合作预算(元)",
    "spotlight_amplification_budget_cny": "聚光放大预算(元)",
    "amplification_pool_cny": "放大预算池(元)",
    "phase": "阶段",
    "paid_budget_cny": "付费预算(元)",
    "key_actions": "关键动作",
    "metric": "指标",
    "threshold": "阈值",
    "action": "动作",
    "scenario": "场景",
    "trigger": "触发条件",
    "adjustment": "调整动作",
    "organic_budget_cny": "自然预算(元)",
    "organic_ratio": "自然占比",
    "needs_review": "需复核",
    "cold_start": "冷启动",
    "scaling": "放量",
    "basis": "依据",
    "low_cny": "下限(元)",
    "high_cny": "上限(元)",
    "match_score": "匹配度",
    "suggested_note_budget_cny": "建议笔记预算(元)",
    "slots_needed": "所需名额",
    "name": "名称",
    "source": "来源",
    "risk": "风险",
    "position": "位置",
    "rule": "规则",
    "mechanism": "机制",
    "follow_criteria": "追踪标准",
    "data_source_status": "数据源状态",
    "rising_keywords": "实时上升热搜词",
    "heat_score": "热度",
    "trend": "趋势",
    "recommendation": "跟进建议",
    "reason": "理由",
    "direction": "方向",
    "title_template": "标题模板",
    "cover_suggestion": "封面建议",
    "outline": "大纲",
    "suitable_for_paid": "适合投流",
    "paid_objective": "投放目标",
    "objective": "投放目标",
    "organic_score": "自然评分",
    "paid_score": "付费评分",
    "rationale": "理由",
    "format": "内容形式",
    "avg_interactions": "平均互动",
    "sample_size": "样本量",
    "peak_hour_hypothesis": "高峰时段假设",
    "content_form_advice": "内容形式建议",
    "boundary_note": "边界说明",
    "cpc_cny": "CPC(元)",
    "cpc_source": "CPC来源",
    "cpm_cny": "CPM(元)",
    "cpm_source": "CPM来源",
    "conversion_cost_cny": "转化成本(元)",
    "conversion_cost_source": "转化成本来源",
    "missing_notice": "缺口说明",
    "common_patterns": "爆款共性",
    "content_gaps": "内容缺口",
    "ad_labeled_count": "广告标识数",
    "targeting_hypotheses": "定向假设",
    "budget_inference_policy": "预算推断口径",
    "budget_share": "预算占比",
    "test_budget_cny": "测试预算(元)",
    "stop_loss_cpc_cny": "止损CPC(元)",
    "stop_loss_cpa_cny": "止损CPA(元)",
    "roi_point": "ROI基准",
    "roi_band": "ROI区间",
    "interest_tags": "兴趣标签",
    "behavior_tags": "行为标签",
    "crowd_packages": "人群包",
    "tag_status": "标签状态",
    "ctr_threshold": "CTR阈值",
    "engagement_threshold": "互动率阈值",
    "demographic": "人口维度",
    "behavioral": "行为维度",
    "psychological": "心理维度",
    "level_budget_split": "三级预算比例",
    "value": "数值",
    "unit": "单位",
    "source_name": "来源",
    "collected_at": "采集时间",
    # ---- 指标单一事实源（04 文档字段）----
    "period": "统计期",
    "formula": "计算口径",
    "value_kind": "数值类型",
    "evidence_level": "证据等级",
    "escalation": "升级事项",
    "unresolved_gaps": "未解决缺口",
    "module_status": "模块状态",
}


def field_label(key: str) -> str:
    """字段键 → 中文标签；未命中原样返回。"""
    if not isinstance(key, str):
        return str(key)
    return FIELD_LABELS.get(key, key)


def _ordered_columns(rows: list[dict[str, Any]]) -> list[str]:
    """按首次出现顺序取所有行的键并集，容错元素键不完全一致的情况。"""
    cols: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                cols.append(key)
    return cols


def build_agent_decision_view(engine_key: str, block: dict) -> dict | None:
    """把某模块块上的 agent_decision 转成可渲染视图；无 agent_decision 返回 None。

    通用递归规则（不做六模块特判）：
    - output 顶层每个键生成一个 section；
    - 值为非空 list[dict] → kind=table（columns 用 FIELD_LABELS 映射）；
    - 值为 dict → kind=kv；
    - 值为 list（非 dict 元素）→ kind=list；
    - 标量并入末尾「其他」kv 组。
    数字保留原值，不做四舍五入。
    """
    if not isinstance(block, dict):
        return None
    decision = block.get("agent_decision")
    if not isinstance(decision, dict):
        return None

    output = decision.get("output")
    if not isinstance(output, dict):
        output = {}

    grounding_raw = decision.get("grounding_check")
    if not isinstance(grounding_raw, dict):
        grounding_raw = {}
    # 缺 grounding_check 时按未通过处理，避免静默当成溯源成功
    if "passed" not in grounding_raw:
        passed = False
    else:
        passed = bool(grounding_raw.get("passed"))
    mismatches = grounding_raw.get("mismatches")
    if not isinstance(mismatches, list):
        mismatches = []
    grounding = {
        "passed": passed,
        "badge": "数字溯源通过" if passed else "存在未溯源数字，需人工复核",
        "mismatches": mismatches,
    }

    sections: list[dict[str, Any]] = []
    scalar_pairs: list[dict[str, Any]] = []
    for key, value in output.items():
        title = field_label(key)
        if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
            column_keys = _ordered_columns(value)
            columns = [{"key": c, "label": field_label(c)} for c in column_keys]
            rows = [{c: item.get(c) for c in column_keys} for item in value]
            sections.append(
                {"title": title, "kind": "table", "columns": columns, "rows": rows}
            )
        elif isinstance(value, dict):
            items = [
                {"label": field_label(sub_key), "value": sub_value}
                for sub_key, sub_value in value.items()
            ]
            sections.append({"title": title, "kind": "kv", "items": items})
        elif isinstance(value, list):
            sections.append({"title": title, "kind": "list", "items": list(value)})
        else:
            scalar_pairs.append({"label": title, "value": value})
    if scalar_pairs:
        sections.append({"title": "其他", "kind": "kv", "items": scalar_pairs})

    source = block.get("decision_source")
    if not isinstance(source, str) or not source.strip():
        source = "llm_agent" if passed else "llm_agent_ungrounded"
    elif not passed and source == "llm_agent":
        source = "llm_agent_ungrounded"

    return {
        "module_label": AGENT_MODULE_LABELS.get(engine_key, engine_key),
        "decision_source": source,
        "steps_used": decision.get("steps_used"),
        "grounding": grounding,
        "module_status": _module_status_view(decision, block, passed),
        "sections": sections,
    }


def _module_status_view(
    decision: dict[str, Any], block: dict[str, Any], grounding_passed: bool
) -> dict[str, Any]:
    """顶部徽标区的模块状态（02 文档 module_state.status）。

    状态优先取 agent_decision.module_status（由 module_agents.base 纯代码判定，
    engine 接线时透传），其次取模块块上的 module_status；都没有时按溯源结果降级，
    保证旧存档（无该字段）也能渲染出合理徽标。
    """
    status = decision.get("module_status")
    if not isinstance(status, str) or not status.strip():
        status = block.get("module_status")
    if not isinstance(status, str) or not status.strip():
        status = "completed" if grounding_passed else "completed_with_gaps"

    gaps = decision.get("unresolved_gaps")
    if not isinstance(gaps, list):
        gaps = block.get("unresolved_gaps")
    if not isinstance(gaps, list):
        gaps = []
    gaps = [str(item) for item in gaps]

    badge = module_status_badge(status, len(gaps))
    badge["unresolved_gaps"] = gaps
    badge["gap_count"] = len(gaps)
    return badge


def apply_agent_grounding_policy(modules: dict[str, Any]) -> list[dict[str, Any]]:
    """根据 grounding_check 降级 decision_source，并返回未溯源告警列表。

    - passed=True → decision_source=llm_agent
    - 否则 → llm_agent_ungrounded（仍保留 agent_decision 供报告展示与人工复核）
    """
    alerts: list[dict[str, Any]] = []
    for engine_key, label in AGENT_MODULE_LABELS.items():
        block = modules.get(engine_key)
        if not isinstance(block, dict):
            continue
        decision = block.get("agent_decision")
        if not isinstance(decision, dict):
            continue
        grounding = decision.get("grounding_check")
        if not isinstance(grounding, dict):
            grounding = {}
        passed = grounding.get("passed") is True
        mismatches = grounding.get("mismatches")
        if not isinstance(mismatches, list):
            mismatches = []
        if passed:
            block["decision_source"] = "llm_agent"
            continue
        block["decision_source"] = "llm_agent_ungrounded"
        alerts.append(
            {
                "engine_key": engine_key,
                "module_label": label,
                "decision_source": "llm_agent_ungrounded",
                "mismatch_count": len(mismatches),
                "mismatches": mismatches[:8],
            }
        )
    return alerts


# ---------------------------------------------------------------------------
# 基准指标单一事实源（SSOT）
# ---------------------------------------------------------------------------
BENCHMARK_POLICY = (
    "同类指标多来源时，按证据等级梯子仲裁"
    "（A_官方或授权 > C_用户导入 > B_公开观察 > D_行业基准 > E_策略假设 > Mock）："
    "账户实测值优先于行业参考值，同等级口径一致时取最近采集；"
    "同等级数值分歧超过 1% 则不选值、升级人工裁决；Mock 永不当选。"
    "下游模块引用时必须注明来源"
)

# 判类顺序有意义：先判 cpc/cpm/ctr/cvr，再判更宽泛的 conversion。
# 注意：不得用裸子串把 organic_content_ctr 并进投流 CTR，或把无关指标塞进「其他指标」大桶。
_METRIC_CATEGORIES: list[tuple[str, str]] = [
    ("cpc", "CPC 单次点击成本"),
    ("cpm", "CPM 千次曝光成本"),
    ("ctr", "CTR 点击率"),
    ("cvr", "CVR 转化率"),
    ("conversion", "转化成本 / 转化"),
]

_METRIC_LABELS = {
    "organic_content_ctr": "自然内容 CTR",
    "organic_interaction_rate": "自然内容互动率",
    "cost_per_interaction": "单次互动成本",
    "engagement_rate": "互动率",
}


def _categorize(metric_name: Any) -> tuple[str, str]:
    raw = str(metric_name or "").strip()
    name = raw.casefold()
    if not name:
        return "unknown", "未知指标"

    # 1) 自然/内容侧指标：与聚光投流 CTR/CVR 分桶，避免假冲突
    if "organic" in name or name.startswith("content_"):
        if "ctr" in name:
            return "organic_content_ctr", _METRIC_LABELS["organic_content_ctr"]
        if "interaction" in name or "engagement" in name:
            return "organic_interaction_rate", _METRIC_LABELS["organic_interaction_rate"]
        return name, raw

    # 2) 精确别名
    if name in _METRIC_LABELS:
        return name, _METRIC_LABELS[name]
    if name in {"cost_per_interaction", "cpi_interaction", "cost_per_engage"}:
        return "cost_per_interaction", _METRIC_LABELS["cost_per_interaction"]

    # 3) 核心投流指标：要求是独立词/后缀，避免 organic_xxx_ctr 误入
    for key, label in _METRIC_CATEGORIES:
        if name == key or name.endswith(f"_{key}") or name.startswith(f"{key}_"):
            return key, label
        # 兼容「行业 CPC」「CTR 点击率」这类展示名
        tokens = [tok for tok in re.split(r"[\s_/｜|·\-]+", name) if tok]
        if key in tokens:
            return key, label

    # 4) 未知指标按 metric_name 独立成组，禁止全部并进「其他指标」
    return name, raw


def _collected_key(candidate: dict[str, Any]) -> str:
    return str(candidate.get("collected_at") or "")


def select_ssot_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """选用规则（薄封装，逻辑在 evidence_policy.resolve_ssot_selection）：

    a) 按证据等级梯子取最高等级组；b) 组内口径一致（±1%）取最近采集；
    c) 组内数值分歧 >1% 不选值（返回 None，升级信息见 resolve_ssot_selection）。
    Mock 永不当选：只有 Mock 候选时同样返回 None。

    保持旧签名与旧返回类型（候选 dict 或 None），便于既有调用方与前端接线不改。
    """
    return resolve_ssot_selection(candidates)["selected"]


def build_benchmark_ssot(benchmark_evidence: list[dict]) -> dict:
    """输入 MetricEvidence 的 dict 列表；按指标类别分组，多来源标 conflict，
    并按证据等级梯子给出 selected / evidence_level / escalation。字段缺失全部容错。"""
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for evidence in benchmark_evidence or []:
        if not isinstance(evidence, dict):
            continue
        cat_key, cat_label = _categorize(evidence.get("metric_name"))
        if cat_key not in grouped:
            grouped[cat_key] = {"category": cat_label, "candidates": []}
            order.append(cat_key)
        candidate = {
            "value": evidence.get("value"),
            "unit": evidence.get("unit"),
            "source_name": evidence.get("source_name"),
            "collected_at": evidence.get("collected_at"),
            "metric_name": evidence.get("metric_name"),
            # 04 文档要求候选保留期间与公式；证据等级用于冲突仲裁
            "period": evidence.get("period"),
            "formula": evidence.get("formula"),
            "value_kind": evidence.get("value_kind"),
            "evidence_level": candidate_evidence_level(evidence),
            "is_mock": evidence.get("is_mock") is True,
        }
        grouped[cat_key]["candidates"].append(candidate)

    groups: list[dict[str, Any]] = []
    for cat_key in order:
        raw = grouped[cat_key]
        candidates = sorted(raw["candidates"], key=_collected_key, reverse=True)
        decision = resolve_ssot_selection(candidates)
        groups.append(
            {
                "category_key": cat_key,
                "category": raw["category"],
                "conflict": len(candidates) > 1,
                "candidates": candidates,
                "selected": decision["selected"],
                "evidence_level": decision["evidence_level"],
                "escalation": decision["escalation"],
                "conflict_candidates": decision["conflict_candidates"],
                "note": decision["note"],
            }
        )

    return {"groups": groups, "policy": BENCHMARK_POLICY}
