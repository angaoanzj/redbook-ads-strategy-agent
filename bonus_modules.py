"""加分项模块组装：内容审核 / A/B / 竞品监控（看板在 report_view 投影）。"""
from __future__ import annotations

from typing import Any

from models import CampaignRequest
from tools.ab_test import AbTestArgs, TopicVariant, build_ab_matrix
from tools.competitor_monitor import CompetitorMonitorArgs, monitor_competitors
from tools.content_audit import (
    ContentAuditArgs,
    apply_content_audit_gates,
    run_content_audit,
)


def _rule_dicts(req: CampaignRequest) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rule in req.official_rule_evidence or []:
        if hasattr(rule, "model_dump"):
            rows.append(rule.model_dump(mode="json"))
        elif isinstance(rule, dict):
            rows.append(rule)
    return rows


def _violation_dicts(req: CampaignRequest) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in req.account_violation_evidence or []:
        if hasattr(row, "model_dump"):
            rows.append(row.model_dump(mode="json"))
        elif isinstance(row, dict):
            rows.append(row)
    return rows


def build_bonus_modules(
    req: CampaignRequest,
    modules: dict[str, Any],
    *,
    previous_competitor_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    module1 = modules.get("module_1_market_competitor") or {}
    module2 = modules.get("module_2_audience_content") or {}
    module4 = modules.get("module_4_spotlight_decision") or {}
    competitor = module1.get("competitor_full_funnel") or {}
    directions = [
        row.get("name")
        for row in (module2.get("content_directions") or [])
        if isinstance(row, dict) and row.get("name")
    ] or ["场景痛点", "产品证据", "对比决策"]
    probe = (
        ((module4.get("forecast") or {}).get("test_bandwidth") or {}).get(
            "cold_start_budget_cny"
        )
    )
    gate = (module2.get("paid_material_gate") or {}).get("prototype_thresholds") or {}
    ctr = float(gate.get("ctr_percent") or 10) / 100.0
    eng = float(gate.get("engagement_rate_percent") or 7) / 100.0

    draft_title = (req.draft_title or "").strip() or req.product_name
    draft_body = (req.draft_body or "").strip() or "\n".join(req.selling_points or [])
    audit = run_content_audit(
        ContentAuditArgs(
            title=draft_title,
            body=draft_body,
            selling_points=list(req.selling_points or []),
            tags=list(req.draft_tags or []),
            image_urls=list(req.draft_image_urls or []),
            video_urls=list(req.draft_video_urls or []),
            competitor_names=list(req.competitor_candidates or [])[:8],
            category=req.category,
            placement="organic_note",
            official_rules=_rule_dicts(req),
            violation_ledger=_violation_dicts(req),
        )
    )
    gate_trace = apply_content_audit_gates(modules, audit)
    audit["gate_application"] = gate_trace

    topic_variants: list[TopicVariant] = []
    for topic in module2.get("topics") or []:
        if not isinstance(topic, dict):
            continue
        title = str(topic.get("title_template") or "").strip()
        cover = str(
            topic.get("cover_suggestion") or topic.get("cover") or ""
        ).strip()
        body = str(
            topic.get("body_outline")
            or topic.get("hook")
            or topic.get("content_angle")
            or topic.get("outline")
            or ""
        ).strip()
        direction = str(topic.get("direction") or "").strip()
        if not title and not cover and not body:
            continue
        topic_variants.append(
            TopicVariant(
                direction=direction or (directions[0] if directions else "内容方向"),
                title=title,
                cover=cover,
                body=body,
            )
        )
    ab_test = build_ab_matrix(
        AbTestArgs(
            directions=directions[:3],
            title_variants_per_direction=2,
            cover_variants_per_direction=2,
            probe_budget_cny=float(probe) if isinstance(probe, (int, float)) else None,
            ctr_win_threshold=ctr,
            engagement_win_threshold=eng,
            topic_variants=topic_variants[:24],
        )
    )
    monitor = monitor_competitors(
        CompetitorMonitorArgs(
            brand_name=req.brand_name,
            current_accounts=list(competitor.get("accounts") or []),
            current_ad_labeled_count=int(
                (competitor.get("paid_notes") or {}).get("confirmed_count") or 0
            ),
            current_sample_note_count=int(
                (competitor.get("organic_hits_commonalities") or {}).get(
                    "sample_note_count"
                )
                or 0
            ),
            previous_snapshot=previous_competitor_snapshot,
        )
    )
    return {
        "bonus_content_audit": audit,
        "bonus_ab_test": ab_test,
        "bonus_competitor_monitor": monitor,
    }
