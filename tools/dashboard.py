"""数据看板载荷构建：把各模块分析结果与投放规划投影为可可视化看板。

不新增平台事实，只做投影；供 /board、Web「附加工具」看板区与导出复用。
刷新时重新从已保存 report_view/modules 组装，并可叠加实时数据源状态。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _section_map(report_view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sections = report_view.get("report_sections") or []
    return {
        str(row.get("key")): row
        for row in sections
        if isinstance(row, dict) and row.get("key")
    }


def _visuals(section: dict[str, Any] | None) -> dict[str, Any]:
    return (section or {}).get("visuals") or {}


def _money(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _module_panels(by_key: dict[str, dict[str, Any]], modules: dict[str, Any]) -> list[dict[str, Any]]:
    """六大分析模块 + 执行摘要，供看板一屏总览。"""
    panels: list[dict[str, Any]] = []
    order = [
        ("market_competitor", "赛道与竞品"),
        ("audience", "用户画像"),
        ("keyword_strategy", "关键词策略"),
        ("creator_keyword", "关键词与达人"),
        ("spotlight_decision", "聚光前置决策"),
        ("budget", "预算与节奏"),
    ]
    for key, fallback_title in order:
        section = by_key.get(key) or {}
        if not section:
            continue
        visuals = _visuals(section)
        highlight = ""
        metrics: list[dict[str, Any]] = []
        if key == "market_competitor":
            spot = visuals.get("spotlight") or {}
            share = spot.get("budget_share") or {}
            highlight = section.get("decision") or ""
            if share.get("search_ratio") is not None:
                metrics.append(
                    {
                        "label": "搜推占比",
                        "value": f"{float(share['search_ratio']):.0%}/{float(share.get('feed_ratio') or 0):.0%}",
                    }
                )
        elif key == "audience":
            dirs = visuals.get("directions") or []
            topics = visuals.get("topics") or []
            highlight = f"{len(dirs)} 个内容方向 · {len(topics)} 个选题"
            gate = visuals.get("material_screening") or {}
            if gate.get("rule_text"):
                metrics.append({"label": "投流门槛", "value": gate["rule_text"]})
        elif key == "keyword_strategy":
            core = visuals.get("core_keywords") or []
            long_tail = visuals.get("long_tail_keywords") or []
            blue = visuals.get("blue_ocean_keywords") or []
            highlight = f"核心{len(core)} / 长尾{len(long_tail)} / 蓝海{len(blue)}"
            split = visuals.get("level_budget_split") or {}
            if split:
                metrics.append(
                    {
                        "label": "词层投放",
                        "value": (
                            f"核心{float(split.get('core') or 0):.0%} · "
                            f"长尾{float(split.get('long_tail') or 0):.0%} · "
                            f"蓝海{float(split.get('blue_ocean') or 0):.0%}"
                        ),
                    }
                )
        elif key == "creator_keyword":
            tiers = (visuals.get("creator_tier_plan") or {}).get("tiers") or []
            creators = visuals.get("top_creators") or []
            highlight = f"分层{len(tiers)} · 名单{len(creators)}人"
        elif key == "spotlight_decision":
            plans = visuals.get("account_plans") or []
            packages = visuals.get("targeting_packages") or []
            highlight = f"{len(plans)} 计划 · {len(packages)} 定向包"
            fc = visuals.get("forecast") or {}
            if fc.get("roi_point") is not None or fc.get("roi_band"):
                metrics.append(
                    {
                        "label": "ROI参考",
                        "value": fc.get("roi_point") or (
                            " ~ ".join(str(x) for x in (fc.get("roi_band") or []))
                        ),
                    }
                )
        elif key == "budget":
            split = visuals.get("budget_split") or {}
            highlight = (
                f"自然:聚光 = {split.get('ratio_label') or '—'}"
                if split
                else (section.get("decision") or "")
            )
            phases = visuals.get("phases") or []
            if phases:
                metrics.append(
                    {
                        "label": "三阶段",
                        "value": " / ".join(
                            f"{p.get('name') or p.get('phase')}"
                            f"{float(p.get('paid_ratio') or p.get('budget_ratio') or 0):.0%}"
                            for p in phases[:3]
                        ),
                    }
                )
        panels.append(
            {
                "key": key,
                "title": section.get("title") or fallback_title,
                "decision": (section.get("decision") or "")[:220],
                "highlight": highlight,
                "badge": section.get("execution_badge"),
                "status": section.get("execution_status"),
                "metrics": metrics,
                "is_mock": bool(section.get("is_mock")),
            }
        )

    # 加分项摘要
    audit = modules.get("bonus_content_audit") or {}
    if audit:
        panels.append(
            {
                "key": "bonus_audit",
                "title": "内容预审",
                "decision": f"风险等级 {audit.get('risk_level') or '—'}，发现 {audit.get('finding_count') or 0} 项",
                "highlight": "发布前处理绝对化/功效表述",
                "badge": audit.get("risk_level"),
                "status": "bonus",
                "metrics": [],
                "is_mock": False,
            }
        )
    return panels


def build_dashboard_payload(
    report_view: dict[str, Any],
    modules: dict[str, Any] | None = None,
    *,
    report_id: str | None = None,
    generated_at: str | None = None,
    feed_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = report_view.get("executive_summary") or {}
    budget_focus = summary.get("budget_focus") or {}
    by_key = _section_map(report_view)
    modules = modules or {}

    budget_section = by_key.get("budget") or {}
    budget_visuals = _visuals(budget_section)
    budget_split = budget_visuals.get("budget_split") or {}
    phases = budget_visuals.get("phases") or []
    if not phases:
        phases = (modules.get("module_5_budget_pacing") or {}).get("phases") or []

    kw = _visuals(by_key.get("keyword_strategy"))
    spotlight = _visuals(by_key.get("spotlight_decision"))
    audience = _visuals(by_key.get("audience"))
    creator = _visuals(by_key.get("creator_keyword"))

    market = by_key.get("market_competitor") or {}
    market_visuals = market.get("visuals") or {}
    organic_visuals = market_visuals.get("organic") or {}
    spotlight_market = market_visuals.get("spotlight") or {}
    # 兼容旧七章结构
    if not market_visuals:
        organic_visuals = _visuals(by_key.get("organic"))
        spotlight_market = _visuals(by_key.get("spotlight"))

    series = organic_visuals.get("trend_series") or []
    search_feed_share = spotlight_market.get("budget_share") or spotlight.get("budget_share") or {}

    organic_ratio = budget_split.get("organic_ratio")
    spotlight_ratio = budget_split.get("spotlight_ratio")
    if organic_ratio is None:
        module5_budget = (modules.get("module_5_budget_pacing") or {}).get("budget") or {}
        organic_ratio = module5_budget.get("organic_ratio")
        spotlight_ratio = module5_budget.get("spotlight_ratio")
        if not budget_split:
            budget_split = {
                "ratio_label": module5_budget.get("ratio_label"),
                "organic_ratio": organic_ratio,
                "spotlight_ratio": spotlight_ratio,
                "organic_cny": module5_budget.get("organic_content_cny") or budget_focus.get("organic_cny"),
                "spotlight_cny": module5_budget.get("spotlight_cny") or budget_focus.get("spotlight_cny"),
                "goal_label": module5_budget.get("goal_label"),
                "rationale": module5_budget.get("split_rationale"),
            }

    forecast = spotlight.get("forecast") or (
        (modules.get("module_4_spotlight_decision") or {}).get("forecast") or {}
    )
    probe = forecast.get("probe_budget_cny")
    if probe is None:
        probe = (forecast.get("test_bandwidth") or {}).get("cold_start_budget_cny")

    synergy = budget_visuals.get("organic_paid_synergy") or (
        (modules.get("module_5_budget_pacing") or {}).get("organic_paid_synergy") or {}
    )
    start_when = synergy.get("start_paid_when") or {}

    organic_cny = _money(budget_split.get("organic_cny")) or _money(budget_focus.get("organic_cny"))
    spotlight_cny = _money(budget_split.get("spotlight_cny")) or _money(
        budget_focus.get("spotlight_cny")
    )
    total_cny = _money(budget_focus.get("total_cny"))
    if total_cny is None and (organic_cny is not None or spotlight_cny is not None):
        total_cny = (organic_cny or 0) + (spotlight_cny or 0)

    kpis: list[dict[str, Any]] = [
        {
            "label": "数据可信度",
            "value": str(summary.get("data_confidence") or "").upper() or "—",
            "unit": "",
            "hint": "证据完整度",
        },
        {
            "label": "总预算",
            "value": total_cny,
            "unit": "CNY",
        },
        {
            "label": "自然预算",
            "value": organic_cny,
            "unit": "CNY",
            "hint": budget_split.get("ratio_label"),
        },
        {
            "label": "聚光预算",
            "value": spotlight_cny,
            "unit": "CNY",
        },
        {
            "label": "建议配比",
            "value": budget_split.get("ratio_label") or "—",
            "unit": budget_split.get("goal_label") or "",
        },
        {
            "label": "探测预算",
            "value": probe,
            "unit": "CNY",
            "hint": "非全案",
        },
        {
            "label": "证据缺口",
            "value": summary.get("gap_count") or 0,
            "unit": "项",
        },
    ]
    this_week = summary.get("this_week_action")
    if this_week:
        kpis.append(
            {
                "label": "本周唯一动作",
                "value": this_week.get("title"),
                "unit": this_week.get("priority") or "",
            }
        )

    bonus = modules.get("bonus_competitor_monitor") or {}
    alerts = list(bonus.get("alerts") or [])[:8]
    audit = modules.get("bonus_content_audit") or {}
    if audit.get("finding_count"):
        alerts.insert(
            0,
            {
                "severity": audit.get("risk_level") or "medium",
                "type": "content_audit",
                "message": f"内容预审发现 {audit.get('finding_count')} 项风险",
                "response": "发布前处理绝对化/功效表述",
            },
        )
    if start_when.get("rule_text"):
        alerts.append(
            {
                "severity": "info",
                "type": "paid_gate",
                "message": f"启动投流门槛：{start_when['rule_text']}",
                "response": "未达门槛前仅保留探测预算，不放大",
            }
        )

    phase_rows = []
    for row in phases:
        share = row.get("paid_ratio") or row.get("budget_ratio") or row.get("ratio")
        phase_rows.append(
            {
                "key": row.get("key"),
                "name": row.get("name") or row.get("phase"),
                "day_range": row.get("day_range"),
                "days": row.get("days"),
                "paid_ratio": share,
                "paid_budget_cny": row.get("paid_budget_cny"),
                "summary": row.get("summary") or row.get("action"),
                "organic_focus": row.get("organic_focus"),
                "paid_focus": row.get("paid_focus"),
            }
        )

    keyword_tiers = {
        "core": list(kw.get("core_keywords") or [])[:8],
        "long_tail": list(kw.get("long_tail_keywords") or [])[:8],
        "blue_ocean": list(kw.get("blue_ocean_keywords") or [])[:6],
        "level_budget_split": kw.get("level_budget_split") or {},
        "rising_follow": list(
            ((by_key.get("creator_keyword") or {}).get("visuals") or {})
            .get("rising_follow")
            or []
        )[:5],
    }

    creator_tiers = ((creator.get("creator_tier_plan") or {}).get("tiers") or [])[:5]
    account_plans = list(spotlight.get("account_plans") or [])[:6]
    targeting_packages = list(spotlight.get("targeting_packages") or [])[:6]

    delivery = {
        "organic_paid_split": {
            "organic_ratio": organic_ratio,
            "spotlight_ratio": spotlight_ratio,
            "ratio_label": budget_split.get("ratio_label"),
            "organic_cny": budget_split.get("organic_cny") or budget_focus.get("organic_cny"),
            "spotlight_cny": budget_split.get("spotlight_cny") or budget_focus.get("spotlight_cny"),
            "rationale": budget_split.get("rationale"),
        },
        "search_feed_share": {
            "search_ratio": search_feed_share.get("search_ratio"),
            "feed_ratio": search_feed_share.get("feed_ratio"),
        },
        "phases": phase_rows,
        "probe_budget_cny": probe,
        "forecast": {
            "status": forecast.get("status"),
            "ctr": forecast.get("ctr"),
            "cpc": forecast.get("cpc"),
            "cpa": forecast.get("cpa") or forecast.get("conversion_cost"),
            "roi_point": forecast.get("roi_point"),
            "roi_band": forecast.get("roi_band"),
            "stop_loss_cpc": forecast.get("stop_loss_cpc"),
            "stop_loss_cpa": forecast.get("stop_loss_cpa"),
        },
        "paid_start_gate": start_when,
        "account_plans": account_plans,
        "targeting_packages": targeting_packages,
        "creator_tiers": [
            {
                "tier": row.get("tier"),
                "count": row.get("count"),
                "budget_ratio": row.get("budget_ratio"),
                "collaboration_budget_cny": row.get("collaboration_budget_cny"),
                "suggested_spotlight_per_note_cny": row.get("suggested_spotlight_per_note_cny"),
            }
            for row in creator_tiers
        ],
        "content_directions": [
            {
                "name": row.get("name") or row.get("direction"),
                "organic_score": row.get("organic_score"),
                "paid_score": row.get("paid_score"),
            }
            for row in (audience.get("directions") or [])[:5]
        ],
    }

    tables = {
        "action_plan": [
            {
                "priority": row.get("priority"),
                "title": row.get("title"),
                "budget_cny": row.get("budget_cny"),
                "budget_kind": row.get("budget_kind"),
                "timeline": row.get("timeline"),
                "owner": row.get("owner"),
            }
            for row in (report_view.get("action_plan") or [])[:6]
        ],
        "ab_cells": ((modules.get("bonus_ab_test") or {}).get("matrix") or [])[:12],
        "ab_plan": {
            "title": (modules.get("bonus_ab_test") or {}).get("title"),
            "what_it_is": (modules.get("bonus_ab_test") or {}).get("what_it_is"),
            "how_to_read": (modules.get("bonus_ab_test") or {}).get("how_to_read") or [],
            "status_label": (modules.get("bonus_ab_test") or {}).get("status_label"),
            "decision_rule": (modules.get("bonus_ab_test") or {}).get("decision_rule"),
            "success_metrics": (modules.get("bonus_ab_test") or {}).get("success_metrics") or [],
            "budget_per_cell_cny": (modules.get("bonus_ab_test") or {}).get("budget_per_cell_cny"),
            "probe_budget_cny": (modules.get("bonus_ab_test") or {}).get("probe_budget_cny"),
            "cell_count": (modules.get("bonus_ab_test") or {}).get("cell_count"),
        },
        "execution_badges": [
            {
                "chapter": row.get("title"),
                "badge": row.get("execution_badge"),
                "status": row.get("execution_status"),
            }
            for row in (report_view.get("report_sections") or [])
        ],
        "phases": phase_rows,
        "keyword_tiers": keyword_tiers,
    }

    refreshed_at = _now_iso()
    live = {
        "mode": "projection_plus_feed_status",
        "note": (
            "看板聚合本次分析结果与投放规划；"
            "「刷新」会从已保存报告重投影，并叠加实时数据源库状态。"
            "不伪造平台账户消耗/曝光等未接入指标。"
        ),
        "feed_status": feed_status or {},
        "auto_refresh_supported": True,
        "recommended_poll_seconds": 30,
    }

    return {
        "title": "全域投放数据看板",
        "report_id": report_id or summary.get("report_id") or "",
        "generated_at": generated_at or summary.get("generated_at") or "",
        "refreshed_at": refreshed_at,
        "kpis": kpis,
        "series": series,
        "budget_share": search_feed_share,
        "organic_paid_share": {
            "organic_ratio": organic_ratio,
            "spotlight_ratio": spotlight_ratio,
            "ratio_label": budget_split.get("ratio_label"),
        },
        "module_panels": _module_panels(by_key, modules),
        "delivery": delivery,
        "keyword_tiers": keyword_tiers,
        "alerts": alerts,
        "tables": tables,
        "live": live,
        "updated_from": "report_view+modules",
        "note": (
            "集成赛道/画像/关键词/达人/聚光/预算与加分项；"
            "支持刷新重投影与 JSON/Markdown/CSV 导出。"
        ),
        "export": {
            "formats": ["json", "markdown", "csv"],
            "endpoints": {
                "json": "/board/{report_id}/export?format=json",
                "markdown": "/board/{report_id}/export?format=markdown",
                "csv": "/board/{report_id}/export?format=csv",
            },
        },
    }


def export_dashboard_markdown(dashboard: dict[str, Any]) -> str:
    """把看板投影导出为 Markdown。"""
    lines = [
        f"# {dashboard.get('title') or '全域投放数据看板'}",
        "",
        f"- 报告 ID：{dashboard.get('report_id') or '—'}",
        f"- 生成时间：{dashboard.get('generated_at') or '—'}",
        f"- 刷新时间：{dashboard.get('refreshed_at') or '—'}",
        f"- 说明：{dashboard.get('note') or ''}",
        "",
        "## KPI",
    ]
    for row in dashboard.get("kpis") or []:
        unit = row.get("unit") or ""
        hint = f"（{row.get('hint')}）" if row.get("hint") else ""
        lines.append(f"- **{row.get('label')}**：{row.get('value')} {unit}{hint}".rstrip())

    delivery = dashboard.get("delivery") or {}
    split = delivery.get("organic_paid_split") or {}
    lines.extend(
        [
            "",
            "## 预算拆分",
            f"- 配比：{split.get('ratio_label') or '—'}",
            f"- 自然：¥{split.get('organic_cny') if split.get('organic_cny') is not None else '—'}",
            f"- 聚光：¥{split.get('spotlight_cny') if split.get('spotlight_cny') is not None else '—'}",
            "",
            "## 三阶段节奏",
        ]
    )
    for phase in delivery.get("phases") or []:
        ratio = phase.get("paid_ratio")
        ratio_text = f"{float(ratio):.0%}" if isinstance(ratio, (int, float)) else "—"
        money = phase.get("paid_budget_cny")
        money_text = f"¥{int(money):,}" if isinstance(money, (int, float)) else "—"
        lines.append(
            f"- **{phase.get('name')}**（投流{ratio_text} · {phase.get('day_range') or ''} · {money_text}）："
            f"{phase.get('summary') or ''}"
        )

    lines.extend(["", "## 模块总览"])
    for panel in dashboard.get("module_panels") or []:
        lines.append(f"### {panel.get('title')}")
        if panel.get("highlight"):
            lines.append(f"- 摘要：{panel['highlight']}")
        if panel.get("decision"):
            lines.append(f"- 决策：{panel['decision']}")

    tiers = dashboard.get("keyword_tiers") or {}
    lines.extend(
        [
            "",
            "## 关键词分层",
            f"- 核心词：{'、'.join(tiers.get('core') or []) or '—'}",
            f"- 长尾词：{'、'.join(tiers.get('long_tail') or []) or '—'}",
            f"- 蓝海词：{'、'.join(tiers.get('blue_ocean') or []) or '—'}",
        ]
    )

    lines.extend(["", "## 预警"])
    alerts = dashboard.get("alerts") or []
    if not alerts:
        lines.append("- 暂无预警")
    for alert in alerts:
        lines.append(
            f"- [{alert.get('severity') or 'info'}] {alert.get('message') or ''}"
            f"（{alert.get('response') or ''}）"
        )

    lines.extend(["", "## 执行动作"])
    for row in (dashboard.get("tables") or {}).get("action_plan") or []:
        lines.append(
            f"- **{row.get('priority')}** {row.get('title')} · {row.get('timeline') or ''}"
        )
    lines.append("")
    return "\n".join(lines)


def export_dashboard_csv(dashboard: dict[str, Any]) -> str:
    """扁平导出 KPI / 阶段 / 动作为 CSV。"""
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["section", "key", "label", "value", "unit", "extra"])
    writer.writerow(
        ["meta", "report_id", "报告ID", dashboard.get("report_id") or "", "", ""]
    )
    writer.writerow(
        ["meta", "refreshed_at", "刷新时间", dashboard.get("refreshed_at") or "", "", ""]
    )
    for row in dashboard.get("kpis") or []:
        writer.writerow(
            [
                "kpi",
                row.get("label"),
                row.get("label"),
                row.get("value"),
                row.get("unit") or "",
                row.get("hint") or "",
            ]
        )
    for phase in (dashboard.get("delivery") or {}).get("phases") or []:
        writer.writerow(
            [
                "phase",
                phase.get("key") or phase.get("name"),
                phase.get("name"),
                phase.get("paid_budget_cny"),
                "CNY",
                f"ratio={phase.get('paid_ratio')}; {phase.get('summary') or ''}",
            ]
        )
    for row in (dashboard.get("tables") or {}).get("action_plan") or []:
        writer.writerow(
            [
                "action",
                row.get("priority"),
                row.get("title"),
                row.get("budget_cny"),
                "CNY",
                row.get("timeline") or "",
            ]
        )
    for panel in dashboard.get("module_panels") or []:
        writer.writerow(
            [
                "module",
                panel.get("key"),
                panel.get("title"),
                panel.get("highlight"),
                "",
                (panel.get("decision") or "")[:180],
            ]
        )
    return buf.getvalue()
