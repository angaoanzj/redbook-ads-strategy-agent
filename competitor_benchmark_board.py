"""Build the competitor-benchmark board for the web UI.

Brief may be user-supplied or auto-synthesized from fetched given-link evidence.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from competitor_insight_analysis import build_competitor_insight_rows
from models import CampaignRequest, CompetitorBenchmarkBrief, CompetitorEvidence
from organic_benchmark_insights import build_organic_benchmark_insights
from risk_signals import build_risk_signal_pack


def _ad_label_text(flag: bool | None) -> str:
    if flag is True:
        return "有广告标识"
    if flag is False:
        return "未见广告标识"
    return "未标注"


def _is_displayable_sample(item: CompetitorEvidence) -> bool:
    """Hide empty stubs / knowledge-candidate placeholders from the sample table."""
    if (item.account_name or "").startswith("对标笔记"):
        return False
    if item.source_name == "本地知识库候选" and item.likes is None and not item.title:
        return False
    return bool(
        item.likes is not None
        or item.interactions is not None
        or item.title
        or item.content_themes
    )


def _sample_rows_from_evidence(items: list[CompetitorEvidence]) -> list[dict[str, Any]]:
    usable = [item for item in items if _is_displayable_sample(item)]
    if not usable:
        usable = [item for item in items if item.profile_or_note_url]
    rows = []
    for item in usable:
        angle = "、".join((item.content_themes or [])[:3])
        if not angle:
            angle = (item.title or "")[:40] or "—"
        rows.append({
            "account": item.account_name,
            "title": item.title or "",
            "angle": angle,
            "format": item.note_format or "图集",
            "likes": item.likes,
            "collects": item.favorites,
            "comments": item.comments,
            "interactions": item.interactions,
            "ad_label": _ad_label_text(item.is_ad_labeled),
            "published": item.collected_at or "",
            "audience": list(item.observed_audience or []),
            "notes": item.notes or "",
            "url": item.profile_or_note_url,
        })
    return rows


def _backfill_sample_rows(
    sample_rows: list[dict[str, Any]],
    evidence: list[CompetitorEvidence],
) -> list[dict[str, Any]]:
    """Fill blank 赞/藏/评/时间 from structured evidence when brief rows are incomplete."""
    by_account = {
        (item.account_name or "").strip(): item
        for item in evidence
        if (item.account_name or "").strip()
    }
    filled: list[dict[str, Any]] = []
    for row in sample_rows:
        data = dict(row)
        item = by_account.get(str(data.get("account") or "").strip())
        if item is not None:
            if data.get("likes") is None and item.likes is not None:
                data["likes"] = item.likes
            if data.get("collects") is None and item.favorites is not None:
                data["collects"] = item.favorites
            if data.get("comments") is None and item.comments is not None:
                data["comments"] = item.comments
            if not data.get("published") and item.collected_at:
                data["published"] = item.collected_at
            if data.get("interactions") is None and item.interactions is not None:
                data["interactions"] = item.interactions
            if not data.get("angle") and item.content_themes:
                data["angle"] = "、".join(item.content_themes[:3])
            if (not data.get("format") or data.get("format") == "待核验") and item.note_format:
                data["format"] = item.note_format
        filled.append(data)
    return filled


def _interaction_stats(items: list[CompetitorEvidence]) -> list[dict[str, Any]]:
    ranked = sorted(
        [item for item in items if isinstance(item.interactions, int)],
        key=lambda item: item.interactions or 0,
        reverse=True,
    )
    stats = []
    labels = ["爆款互动", "中腰部互动", "冷启动对照"]
    for index, item in enumerate(ranked[:3]):
        stats.append({
            "label": f"{labels[index]}（{item.account_name}）" if index < len(labels) else item.account_name,
            "value": item.interactions,
        })
    return stats


def _build_section_risk(
    brief: CompetitorBenchmarkBrief | None,
    req: CampaignRequest,
    risk: dict[str, Any],
    evidence: list[CompetitorEvidence],
) -> dict[str, Any]:
    pack = build_risk_signal_pack(req, risk, evidence)
    content = list(brief.risk_content_signals) if brief and brief.risk_content_signals else pack["content_types"]
    rejection = (
        list(brief.risk_rejection_signals)
        if brief and brief.risk_rejection_signals
        else pack["rejection_reasons"]
    )
    # 过滤历史误写入的长规则原文
    content = [item for item in content if isinstance(item, str) and len(item) <= 60] or pack["content_types"]
    rejection = [item for item in rejection if isinstance(item, str) and len(item) <= 60] or pack["rejection_reasons"]
    return {
        "title_content": "该赛道近期被限流/违规的内容类型",
        "title_rejection": "聚光广告拒审高频原因",
        "content_status": pack["content_status"],
        "rejection_status": pack["rejection_status"],
        "content_signals": content[:8],
        "rejection_signals": rejection[:8],
        "has_ledger": pack["has_ledger"],
        "ledger_rows": pack["ledger_rows"],
        "risk_note": (
            brief.risk_note
            if brief and brief.risk_note
            else pack["risk_note"]
        ),
        "baseline_checks": pack["baseline_checks"],
    }


def _merge_spotlight_metrics(brief_metrics: dict[str, Any] | None, live: dict[str, Any]) -> dict[str, Any]:
    """Brief 文案优先，空字段用引擎投流表回填（CTR / 互动成本等）。"""
    base = dict(brief_metrics or {})
    fill = {
        "cpc": live.get("cpc"),
        "cpm": live.get("cpm"),
        "ctr": live.get("ctr"),
        "interaction_cost": live.get("interaction_cost"),
        "conversion_cost": live.get("cpa"),
    }
    for key, value in fill.items():
        current = base.get(key)
        empty = current is None or current == "" or current == "缺口"
        if empty and value is not None:
            base[key] = value
    if base.get("conversion_cost") in (None, ""):
        base["conversion_cost"] = "缺口"
    return base


def _spotlight_from_module(module1: dict[str, Any]) -> dict[str, Any]:
    spot = module1.get("spotlight_market") or {}
    cpc = (spot.get("average_cpc") or {}).get("value")
    cpm = (spot.get("average_cpm") or {}).get("value")
    ctr = (spot.get("average_ctr") or {}).get("value")
    cpa = (spot.get("conversion_cost") or {}).get("value")
    interaction = (spot.get("interaction_cost") or {}).get("value")
    share = spot.get("search_feed_budget_share") or {}
    goals = spot.get("popular_promotion_goals") or {}
    direction = spot.get("latest_traffic_direction_2026") or {}
    return {
        "cpc": cpc,
        "cpm": cpm,
        "cpa": cpa,
        "ctr": ctr,
        "interaction_cost": interaction,
        "search_ratio": share.get("search_ratio"),
        "feed_ratio": share.get("feed_ratio"),
        "goal_notes": list(goals.get("goal_notes") or []),
        "goal_ranking": list(goals.get("market_ranking") or []),
        "goal_conclusion": goals.get("decision_conclusion"),
        "traffic_points": list(direction.get("direction_points") or []),
        "traffic_conclusion": direction.get("decision_conclusion") or share.get("decision_conclusion"),
        "decision": (spot.get("average_cpc") or {}).get("decision_conclusion")
        or spot.get("decision_conclusion"),
    }


def _agent_output_if_usable(module1: dict[str, Any]) -> dict[str, Any] | None:
    """Return module1 Agent JSON when present and safe to overlay onto board copy."""
    decision = module1.get("agent_decision")
    if not isinstance(decision, dict):
        return None
    grounding = decision.get("grounding_check") or {}
    if grounding.get("passed") is False:
        return None
    output = decision.get("output")
    if not isinstance(output, dict):
        return None
    return output


def apply_module1_agent_overlay(
    board: dict[str, Any],
    modules: dict[str, Any],
    *,
    overlay_competitor_section: bool = True,
    overlay_organic_copy: bool = True,
) -> dict[str, Any]:
    """把模块1 DeepSeek 人话结论叠到看板文案（不改趋势数字/高峰计数/聚光成本）。

    overlay_competitor_section=False 时保留本地引擎的「竞品全域投放拆解」。
    overlay_organic_copy=False 时保留本地「共性/空白/摘要」金样结构，不被 Agent 覆盖。
    """
    if not board or not board.get("available"):
        return board
    module1 = modules.get("module_1_market_competitor") or {}
    output = _agent_output_if_usable(module1)
    if output is None:
        board["agent_insight"] = {"applied": False, "reason": "无可用 Agent 结论或溯源未通过"}
        return board

    organic_out = output.get("organic_landscape") or {}
    breakdown = output.get("competitor_breakdown") or {}
    risks = output.get("risk_alerts") or []
    review_items = [str(item) for item in (output.get("human_review_items") or []) if item]

    patterns = [str(item).strip() for item in (breakdown.get("common_patterns") or []) if str(item).strip()]
    gaps = [str(item).strip() for item in (breakdown.get("content_gaps") or []) if str(item).strip()]
    hypotheses = [
        str(item).strip()
        for item in (breakdown.get("targeting_hypotheses") or [])
        if str(item).strip()
    ]
    form_advice = [
        str(item).strip()
        for item in (organic_out.get("content_form_advice") or [])
        if str(item).strip()
    ]
    peak = str(organic_out.get("peak_hour_hypothesis") or "").strip()
    boundary = str(organic_out.get("boundary_note") or "").strip()

    section_organic = board.setdefault("section_organic", {})
    if overlay_organic_copy:
        if patterns:
            section_organic["commonalities"] = patterns
            section_organic["summary"] = (
                f"Agent 解读：{patterns[0]}"
                + (f"；另见 {len(patterns) - 1} 条共性。" if len(patterns) > 1 else "")
            )
        if gaps:
            section_organic["gaps"] = [
                gap if gap.startswith(("空白", "可抢占", "可强化")) else f"空白：{gap}"
                for gap in gaps[:6]
            ]
        if form_advice:
            section_organic["format_note"] = "；".join(form_advice)
    elif patterns:
        # 本地共性优先：Agent 只追加补充句，不覆盖
        extras = [f"Agent补充：{item}" for item in patterns[:2]]
        section_organic["commonalities"] = list(section_organic.get("commonalities") or []) + extras
    if peak and overlay_organic_copy:
        section_organic["peak_caption"] = peak

    if overlay_competitor_section:
        section_comp = board.setdefault("section_competitor", {})
        commonality_rows: list[dict[str, Any]] = []
        if patterns:
            commonality_rows.append(
                {"dimension": "爆款共性", "observation": "；".join(patterns[:4])}
            )
        if gaps:
            commonality_rows.append(
                {"dimension": "内容空白", "observation": "；".join(gaps[:4])}
            )
        if form_advice:
            commonality_rows.append(
                {"dimension": "形式建议", "observation": "；".join(form_advice[:3])}
            )
        if commonality_rows:
            section_comp["commonality_rows"] = commonality_rows
        if hypotheses:
            # 追加为额外卡片，不整表替换本地定向拆解
            cards = list(section_comp.get("targeting_cards") or [])
            cards.extend(
                {
                    "title": f"Agent 定向测试假设 {index}",
                    "body": hypo,
                }
                for index, hypo in enumerate(hypotheses[:3], start=1)
            )
            section_comp["targeting_cards"] = cards[:6]

    counter_actions: list[dict[str, Any]] = []
    for index, gap in enumerate(gaps[:3], start=1):
        counter_actions.append(
            {
                "priority": f"P{index}",
                "action": f"围绕「{gap}」做差异化探测内容并小流量验证",
                "gap": gap,
            }
        )
    for index, alert in enumerate(risks[:3], start=len(counter_actions) + 1):
        if not isinstance(alert, dict):
            continue
        action = str(alert.get("action") or "").strip()
        risk = str(alert.get("risk") or "").strip()
        if not action:
            continue
        counter_actions.append(
            {
                "priority": f"P{index}",
                "action": action,
                "gap": risk or "风险应对",
            }
        )
    if counter_actions:
        board["counter_actions"] = counter_actions[:6]

    pills = list(board.get("pills") or [])
    if "Agent 人话解读已写入" not in pills:
        pills.append("Agent 人话解读已写入")
    board["pills"] = pills

    board["agent_insight"] = {
        "applied": True,
        "source": "module1_market_competitor",
        "boundary_note": boundary,
        "human_review_items": review_items[:6],
        "risk_alerts": [
            {
                "risk": str(row.get("risk") or ""),
                "source": str(row.get("source") or ""),
                "action": str(row.get("action") or ""),
            }
            for row in risks[:4]
            if isinstance(row, dict)
        ],
        "note": (
            "数字图表与对标共性/空白以本地引擎为准；"
            "Agent 主要补充应对动作"
            + ("；未覆盖第03章表格" if not overlay_competitor_section else "")
            + ("；未覆盖共性/空白金样结构" if not overlay_organic_copy else "")
            + "。"
        ),
        "competitor_section_preserved": not overlay_competitor_section,
        "organic_copy_preserved": not overlay_organic_copy,
    }
    return board


def _blob_from_competitor(
    competitor: dict[str, Any],
    evidence: list[CompetitorEvidence],
) -> str:
    common = competitor.get("organic_hits_commonalities") or {}
    themes = [str(row.get("theme") or "") for row in (common.get("top_themes") or [])]
    audience = list((competitor.get("targeting_inference") or {}).get("audience_signals") or [])
    titles = [item.title or "" for item in evidence]
    notes = [item.notes or "" for item in evidence]
    return " ".join(themes + audience + titles + notes)


def _pick_matches(blob: str, keywords: tuple[str, ...]) -> list[str]:
    hits = [key for key in keywords if key and key in blob]
    # 去重保序
    seen: set[str] = set()
    ordered: list[str] = []
    for hit in hits:
        if hit in seen:
            continue
        seen.add(hit)
        ordered.append(hit)
    return ordered


def _content_type_label(row: dict[str, Any]) -> str:
    fmt = str(row.get("format") or "图集").strip() or "图集"
    themes = " ".join(row.get("content_themes") or [])
    title = str(row.get("title") or "")
    blob = f"{themes} {title}"
    if row.get("ad_labeled") is True:
        return f"疑似投流{fmt}"
    if any(key in blob for key in ("避坑", "地图", "真假", "门店")):
        return f"攻略种草{fmt}"
    if any(key in blob for key in ("开箱", "花费", "开销")):
        return f"自然开箱{fmt}"
    if any(key in blob for key in ("排序", "测评", "必买", "Top")):
        return f"自然种草{fmt}"
    return f"自然种草{fmt}"


def _duration_judgment(row: dict[str, Any]) -> str:
    duration = row.get("campaign_duration") or {}
    status = str(duration.get("status") or "").strip()
    interactions = row.get("interactions")
    if row.get("ad_labeled") is True:
        return status or "有广告标识；投放时长仍需多日快照核验"
    if isinstance(interactions, int) and interactions >= 2000:
        return "无法认定投放；高互动更像自然长尾，需多日斜率核验"
    if isinstance(interactions, int) and interactions < 800:
        return "低互动，不像持续加热；公开页无法认定投放时长"
    return status or "无广告角标；无连续快照，时长未知"


def build_section_competitor_from_engine(
    competitor: dict[str, Any],
    evidence: list[CompetitorEvidence],
    *,
    spotlight_live: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """用本地模块1 competitor_full_funnel 组装「竞品全域投放拆解」（对标 Jenny 结构）。"""
    common = competitor.get("organic_hits_commonalities") or {}
    gaps = competitor.get("content_gaps") or {}
    paid = competitor.get("paid_notes") or {}
    targeting = competitor.get("targeting_inference") or {}
    budget = competitor.get("budget_range") or {}
    themes = list(common.get("top_themes") or [])
    formats = list(common.get("observed_formats") or [])
    audience = [str(item) for item in (targeting.get("audience_signals") or []) if item]
    blob = _blob_from_competitor(competitor, evidence)

    theme_names = [str(row.get("theme") or "").strip() for row in themes if row.get("theme")]
    commonality_rows = build_competitor_insight_rows(
        evidence,
        content_gap_analysis=gaps,
        observed_formats=formats,
    )

    accounts = list(competitor.get("accounts") or [])
    paid_note_rows = [
        {
            "note": f"{row.get('account') or ''} · {row.get('title') or ''}".strip(" ·"),
            "ad_label": (
                "是"
                if row.get("ad_labeled") is True
                else "否"
                if row.get("ad_labeled") is False
                else "未判定"
            ),
            "ad_status": row.get("ad_note_status") or "",
            "content_type": _content_type_label(row),
            "duration_judgment": _duration_judgment(row),
            "evidence_note": row.get("evidence_status") or "",
        }
        for row in accounts
    ]

    confirmed = int(paid.get("confirmed_count") or 0)
    if confirmed <= 0 and accounts:
        paid_conclusion = (
            f"当前 {len(accounts)} 条对标应按「自然流量内容武器」拆解，不要写成竞品聚光在投素材。"
            "若要坐实投流，需 App 内截取「广告」角标 + 多日互动斜率快照。"
        )
    else:
        paid_conclusion = str(
            paid.get("decision_conclusion")
            or f"公开页确认 {confirmed} 条带广告标识笔记；只有确认样本进入投流内容拆解。"
        )

    scene_keys = ("游客", "到港", "内地", "出发", "机场", "香港", "澳门", "台湾")
    scene = [item for item in audience if any(key in item for key in scene_keys)] or audience[:4]
    interest = theme_names[:8] or _pick_matches(
        blob, ("伴手礼", "手信", "探店", "曲奇", "测评", "现金", "换汇", "机场")
    )
    cpc = (spotlight_live or {}).get("cpc")
    budget_body = str(budget.get("decision_conclusion") or "不依据点赞量反推竞品预算。")
    if isinstance(cpc, (int, float)):
        budget_body = (
            f"竞品预算：证据不足，不估。自身可参考品牌表 CPC≈¥{float(cpc):.2f}，"
            "用探测预算验证对标高频搜索意图词。"
        )

    targeting_cards = [
        {
            "title": "地域/场景",
            "body": "、".join(scene) if scene else "待从评论区补抓地域/出行场景信号",
        },
        {
            "title": "兴趣词包",
            "body": "、".join(interest) if interest else "待补主题标注后生成测试词包",
        },
        {
            "title": "定向测试包",
            "body": (
                f"{targeting.get('status') or '定向测试假设'}："
                f"{'、'.join(audience[:5]) if audience else '待补评论画像'}。"
                "首轮在自有聚光账户分组验证，不能照搬为竞品真实定向。"
            ),
        },
        {
            "title": "预算范围",
            "body": budget_body,
        },
    ]

    return {
        "commonality_rows": commonality_rows,
        "paid_note_rows": paid_note_rows,
        "paid_conclusion": paid_conclusion,
        "targeting_cards": targeting_cards,
        "source": "local_engine",
    }


def _normalize_month_label(raw: str, *, fallback_year: int | None = None) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}", text):
        return text
    if text.endswith("月") and text[:-1].isdigit():
        month = int(text[:-1])
        year = fallback_year or datetime.now().year
        if 1 <= month <= 12:
            return f"{year}-{month:02d}"
    match = re.fullmatch(r"(\d{4})年(\d{1,2})月", text)
    if match:
        return f"{int(match.group(1))}-{int(match.group(2)):02d}"
    return text


def _brand_natural_rows(
    req: CampaignRequest,
    module1: dict[str, Any],
    brief: CompetitorBenchmarkBrief | None,
) -> list[dict[str, Any]]:
    """品牌自然内容表：内容供给(篇数)+曝光，月份对齐为 YYYY-MM。"""
    owned = module1.get("owned_content_history") or {}
    periods = list(owned.get("periods") or req.owned_content_history or [])
    rows: list[dict[str, Any]] = []
    year_hint = datetime.now().year
    for row in periods:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        merged = {**row, **metrics}
        month = _normalize_month_label(
            str(merged.get("时间") or merged.get("period") or merged.get("月份") or ""),
            fallback_year=year_hint,
        )
        if not month:
            continue
        try:
            supply = float(
                str(
                    merged.get("篇数")
                    or merged.get("内容供给")
                    or merged.get("供给")
                    or merged.get("note_count")
                    or 0
                ).replace(",", "")
            )
        except ValueError:
            supply = 0.0
        try:
            exposure = float(
                str(merged.get("曝光量") or merged.get("impressions") or 0).replace(",", "")
            )
            exposure_wan = round(exposure / 10000, 1)
        except ValueError:
            exposure_wan = 0.0
        try:
            clicks = float(str(merged.get("点击量") or merged.get("clicks") or 0).replace(",", ""))
        except ValueError:
            clicks = None
        rows.append(
            {
                "month": month,
                "supply": supply,
                "note_count": supply,
                "exposure_wan": exposure_wan,
                "clicks": clicks,
            }
        )
    rows.sort(key=lambda item: item["month"])
    if rows:
        return rows
    # brief 回退：对齐月份标签
    cats = list(brief.organic_trend_categories) if brief else []
    counts = list(brief.organic_trend_note_counts) if brief else []
    exposure = list(brief.organic_trend_exposure_wan) if brief else []
    fallback: list[dict[str, Any]] = []
    for index, cat in enumerate(cats):
        fallback.append(
            {
                "month": _normalize_month_label(str(cat), fallback_year=year_hint),
                "supply": counts[index] if index < len(counts) else 0,
                "note_count": counts[index] if index < len(counts) else 0,
                "exposure_wan": exposure[index] if index < len(exposure) else 0,
                "clicks": None,
            }
        )
    return fallback


def _peak_slots_for_board(
    organic: dict[str, Any],
    brief: CompetitorBenchmarkBrief | None,
) -> tuple[list[dict[str, Any]], str]:
    """优先用本地引擎北京时间分桶；无数据再回退 brief。"""
    peak = organic.get("traffic_peak_hours") or {}
    engine_slots = list(peak.get("slots") or [])
    if engine_slots:
        return (
            [
                {
                    "slot": row.get("slot"),
                    "count": row.get("count"),
                    "average_interactions": row.get("average_interactions"),
                }
                for row in engine_slots
            ],
            str(peak.get("decision_conclusion") or ""),
        )
    if brief and brief.peak_slots:
        return (
            [row.model_dump(mode="json") for row in brief.peak_slots],
            brief.peak_caption or str(peak.get("decision_conclusion") or ""),
        )
    return (
        [
            {
                "slot": row.get("hour"),
                "count": row.get("note_count"),
                "average_interactions": row.get("average_interactions"),
            }
            for row in (peak.get("hours") or [])
        ],
        str(peak.get("decision_conclusion") or ""),
    )


def build_competitor_benchmark_board(
    req: CampaignRequest,
    modules: dict[str, Any],
    *,
    overlay_agent: bool = True,
    prefer_engine_competitor: bool = False,
) -> dict[str, Any] | None:
    """Return a renderable board, or None when there is nothing to show."""
    brief: CompetitorBenchmarkBrief | None = req.competitor_benchmark_brief
    evidence = list(req.competitor_evidence or [])
    if not brief and not evidence:
        return None

    module1 = modules.get("module_1_market_competitor") or {}
    competitor = module1.get("competitor_full_funnel") or {}
    organic = module1.get("organic_market") or {}
    risk = module1.get("risk_warning") or {}
    spotlight_live = _spotlight_from_module(module1)

    # 有实时抓取证据时，样本表以证据为准，避免 brief/知识库空行（待接入）污染
    live_samples = _sample_rows_from_evidence(evidence)
    if live_samples and any(
        row.get("likes") is not None or row.get("interactions") is not None
        for row in live_samples
    ):
        sample_rows = live_samples
    elif brief and brief.sample_notes:
        sample_rows = _backfill_sample_rows(
            [row.model_dump(mode="json") for row in brief.sample_notes],
            evidence,
        )
        sample_rows = [
            row for row in sample_rows
            if row.get("likes") is not None
            or row.get("collects") is not None
            or row.get("title")
            or (row.get("angle") and row.get("angle") not in {"", "待接入", "—"})
        ] or sample_rows
    else:
        sample_rows = live_samples

    stats = []
    if brief and brief.hero_stats:
        stats = [row.model_dump(mode="json") for row in brief.hero_stats]
    else:
        stats = _interaction_stats(evidence)

    paid_confirmed = competitor.get("paid_notes", {}).get("confirmed_count")
    if paid_confirmed is None:
        paid_confirmed = sum(1 for item in evidence if item.is_ad_labeled is True)

    brand_rows = _brand_natural_rows(req, module1, brief)
    peak_slots, peak_caption = _peak_slots_for_board(organic, brief)
    peak_meta = organic.get("traffic_peak_hours") or {}
    local_organic = build_organic_benchmark_insights(
        req,
        competitor=competitor,
        organic=organic,
        evidence=evidence,
    )
    use_local_organic_copy = prefer_engine_competitor or not (
        brief and brief.organic_commonalities and brief.organic_summary
    )

    board = {
        "available": True,
        "module": "module_1_market_competitor",
        "source_policy": "fetch_user_given_links_only",
        "analysis_days": req.analysis_days,
        "headline": "赛道与竞品深度分析",
        "subtitle": (
            brief.subtitle
            if brief and brief.subtitle
            else (
                f"{req.brand_name}｜{req.category}｜"
                f"自然流量大盘 + 聚光投放大盘 + 对标笔记拆解 + 风险预警"
            )
        ),
        "brand_label": req.brand_name,
        "pills": list(brief.pills) if brief and brief.pills else [
            f"对标条目 {len(evidence)}",
            f"广告标识 {paid_confirmed}/{len(evidence) or 0}",
            "给定链接抓取",
            f"近{req.analysis_days}天",
        ],
        "evidence_boundary": (
            brief.evidence_boundary
            if brief and brief.evidence_boundary
            else competitor.get("paid_notes", {}).get("warning")
            or "对标证据来自用户给定链接的公开页抓取；未见广告标识的笔记不得当作正在投流。"
        ),
        "hero_stats": stats,
        "sample_notes": sample_rows,
        "section_organic": {
            "summary": (
                local_organic["summary"]
                if use_local_organic_copy
                else (
                    brief.organic_summary
                    if brief and brief.organic_summary
                    else local_organic["summary"]
                )
            ),
            "commonalities": (
                list(local_organic["commonalities"])
                if use_local_organic_copy
                else list(brief.organic_commonalities)
                if brief and brief.organic_commonalities
                else list(local_organic["commonalities"])
            ),
            "gaps": (
                list(local_organic["gaps"])
                if use_local_organic_copy
                else list(brief.organic_gaps)
                if brief and brief.organic_gaps
                else list(local_organic["gaps"])
            ),
            "organic_insight_source": (
                local_organic.get("source")
                if use_local_organic_copy
                else "user_brief"
            ),
            "trend_caption": (
                brief.organic_trend_caption
                if brief and brief.organic_trend_caption
                else (organic.get("publication_interaction_trend") or {}).get("decision_conclusion")
                or "品类笔记发布量／互动量趋势（知识库检索样本）"
            ),
            "trend_series": (organic.get("publication_interaction_trend") or {}).get("series") or [],
            "trend_granularity": (organic.get("publication_interaction_trend") or {}).get("granularity"),
            "trend_sample_size": organic.get("trend_sample_size") or organic.get("raw_sample_size"),
            "window_sample_size": organic.get("sample_size"),
            "window_average_interactions": organic.get("window_average_interactions_per_note"),
            "brand_history_scoped": True,
            "brand_natural_rows": brand_rows,
            "trend_categories": [row["month"] for row in brand_rows],
            "trend_exposure_wan": [row["exposure_wan"] for row in brand_rows],
            "trend_note_counts": [row["supply"] for row in brand_rows],
            "peak_caption": peak_caption or (
                brief.peak_caption if brief else ""
            ),
            "peak_slots": peak_slots,
            "peak_hours_beijing": list(peak_meta.get("hours") or []),
            "peak_timezone": peak_meta.get("timezone") or "Asia/Shanghai",
            "peak_warning": peak_meta.get("warning") or "",
            "format_note": (
                brief.format_note
                if brief and brief.format_note and not use_local_organic_copy
                else local_organic.get("format_note")
                or organic.get("popular_content_format_conclusion")
                or "热门形式以用户对标样本与品类笔记为准。"
            ),
        },
        "section_spotlight": {
            "notice": (
                brief.spotlight_notice
                if brief and brief.spotlight_notice
                else "聚光成本优先使用用户导入的品牌投流表；不是竞品账户后台，也不是平台行业均值。"
            ),
            "metrics": _merge_spotlight_metrics(
                brief.spotlight_metrics.model_dump(mode="json")
                if brief and brief.spotlight_metrics
                else None,
                spotlight_live,
            ),
            "monthly_rows": (
                [row.model_dump(mode="json") for row in brief.spotlight_monthly]
                if brief and brief.spotlight_monthly
                else [
                    {
                        "month": str(row.get("month") or ""),
                        "spend": str(row.get("spend") or "—"),
                        "cpc": str(row.get("cpc") or "—"),
                        "cpm": str(row.get("cpm") or "—"),
                        "ctr": str(row.get("ctr") or "—"),
                    }
                    for row in (req.paid_monthly_history or [])
                    if isinstance(row, dict) and row.get("month")
                ]
            ),
            "goal_notes": list(brief.spotlight_goal_notes) if brief and brief.spotlight_goal_notes else (
                spotlight_live.get("goal_notes")
                or (
                    [spotlight_live["goal_conclusion"]]
                    if spotlight_live.get("goal_conclusion")
                    else (
                        [f"测试优先级：{' > '.join(spotlight_live['goal_ranking'])}"]
                        if spotlight_live.get("goal_ranking")
                        else []
                    )
                )
            ),
            "traffic_notes": list(brief.spotlight_traffic_notes) if brief and brief.spotlight_traffic_notes else [
                f"搜索/信息流配比参考：搜索 {spotlight_live.get('search_ratio') if spotlight_live.get('search_ratio') is not None else '—'} / "
                f"信息流 {spotlight_live.get('feed_ratio') if spotlight_live.get('feed_ratio') is not None else '—'}",
                *(spotlight_live.get("traffic_points") or []),
                *(
                    [spotlight_live["traffic_conclusion"]]
                    if spotlight_live.get("traffic_conclusion")
                    else []
                ),
            ],
        },
        "section_competitor": (
            build_section_competitor_from_engine(
                competitor,
                evidence,
                spotlight_live=spotlight_live,
            )
            if prefer_engine_competitor
            else {
                "commonality_rows": [row.model_dump(mode="json") for row in brief.commonality_rows] if brief and brief.commonality_rows else [
                    {"dimension": "主题", "observation": "、".join(
                        row.get("theme", "") for row in ((competitor.get("organic_hits_commonalities") or {}).get("top_themes") or [])[:5]
                    ) or "待标注"},
                ],
                "paid_note_rows": [row.model_dump(mode="json") for row in brief.paid_note_rows] if brief and brief.paid_note_rows else [
                    {
                        "note": f"{row.get('account')} · {row.get('title') or ''}".strip(" ·"),
                        "ad_label": "有" if row.get("ad_labeled") is True else "无" if row.get("ad_labeled") is False else "未标注",
                        "content_type": row.get("format") or "待核验",
                        "duration_judgment": (row.get("campaign_duration") or {}).get("status") or "用户未提供投放时长",
                    }
                    for row in (competitor.get("accounts") or [])
                ],
                "paid_conclusion": (
                    brief.paid_conclusion
                    if brief and brief.paid_conclusion
                    else (competitor.get("paid_notes") or {}).get("decision_conclusion")
                ),
                "targeting_cards": [row.model_dump(mode="json") for row in brief.targeting_cards] if brief and brief.targeting_cards else [
                    {
                        "title": "受众信号（用户标注）",
                        "body": "、".join((competitor.get("targeting_inference") or {}).get("audience_signals") or []) or "待补充评论画像",
                    },
                    {
                        "title": "定向使用方式",
                        "body": (competitor.get("targeting_inference") or {}).get("decision_conclusion") or "",
                    },
                    {
                        "title": "预算范围",
                        "body": (competitor.get("budget_range") or {}).get("decision_conclusion") or "",
                    },
                ],
                "source": "user_brief" if brief else "fallback",
            }
        ),
        "section_risk": _build_section_risk(brief, req, risk, evidence),
        "counter_actions": [row.model_dump(mode="json") for row in brief.counter_actions] if brief and brief.counter_actions else [
            {
                "priority": "P1",
                "action": opp.get("opportunity") or "",
                "gap": opp.get("reason") or "",
            }
            for opp in ((competitor.get("content_gaps") or {}).get("opportunities") or [])[:4]
        ],
        "agent_insight": {"applied": False},
    }
    if overlay_agent:
        # 自动合成路径：保留本地共性/空白与第03章；Agent 只补应对动作
        apply_module1_agent_overlay(
            board,
            modules,
            overlay_competitor_section=not prefer_engine_competitor,
            overlay_organic_copy=not prefer_engine_competitor,
        )
    return board
