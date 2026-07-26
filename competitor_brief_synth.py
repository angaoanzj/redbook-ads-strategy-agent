"""Synthesize competitor_benchmark_brief from fetched evidence + engine modules."""

from __future__ import annotations

from typing import Any

from models import (
    BenchmarkKvRow,
    BenchmarkMonthlyRow,
    BenchmarkPeakSlot,
    BenchmarkSampleNote,
    BenchmarkSpotlightMetrics,
    BenchmarkStat,
    CampaignRequest,
    CompetitorBenchmarkBrief,
)
from risk_signals import build_risk_signal_pack


def _ad_text(flag: bool | None) -> str:
    if flag is True:
        return "有广告标识"
    if flag is False:
        return "未见广告标识"
    return "未标注"


def synthesize_competitor_benchmark_brief(
    req: CampaignRequest,
    modules: dict[str, Any],
) -> CompetitorBenchmarkBrief | None:
    evidence = list(req.competitor_evidence or [])
    if not evidence:
        return None
    if req.competitor_benchmark_brief is not None:
        return req.competitor_benchmark_brief

    module1 = modules.get("module_1_market_competitor") or {}
    competitor = module1.get("competitor_full_funnel") or {}
    organic = module1.get("organic_market") or {}
    spotlight = module1.get("spotlight_market") or {}
    risk = module1.get("risk_warning") or {}

    ranked = sorted(
        [item for item in evidence if isinstance(item.interactions, int)],
        key=lambda item: item.interactions or 0,
        reverse=True,
    )
    labels = ["爆款互动", "中腰部互动", "冷启动对照"]
    hero_stats = [
        BenchmarkStat(
            label=f"{labels[i]}（{item.account_name}）",
            value=item.interactions or 0,
            tone="warning" if i == 2 else None,
        )
        for i, item in enumerate(ranked[:3])
    ]

    sample_notes = [
        BenchmarkSampleNote(
            account=item.account_name,
            title=item.title or "",
            angle="、".join((item.content_themes or [])[:3]),
            format=item.note_format or "待核验",
            likes=item.likes,
            collects=item.favorites,
            comments=item.comments,
            ad_label=_ad_text(item.is_ad_labeled),
            published=item.collected_at or "",
        )
        for item in evidence
    ]

    from organic_benchmark_insights import build_organic_benchmark_insights

    organic_insights = build_organic_benchmark_insights(
        req,
        competitor=competitor,
        organic=organic,
        evidence=evidence,
    )
    commonalities = list(organic_insights.get("commonalities") or [])
    gaps = list(organic_insights.get("gaps") or [])
    format_note = organic_insights.get("format_note") or (
        organic.get("popular_content_format_conclusion") or "热门形式待更多样本确认"
    )
    themes = (competitor.get("organic_hits_commonalities") or {}).get("top_themes") or []
    formats = (competitor.get("organic_hits_commonalities") or {}).get("observed_formats") or []

    cpc = (spotlight.get("average_cpc") or {}).get("value")
    cpm = (spotlight.get("average_cpm") or {}).get("value")
    ctr = (spotlight.get("average_ctr") or {}).get("value")
    cpa = (spotlight.get("conversion_cost") or {}).get("value")
    interaction = (spotlight.get("interaction_cost") or {}).get("value")
    share = spotlight.get("search_feed_budget_share") or {}
    goals = spotlight.get("popular_promotion_goals") or {}
    direction = spotlight.get("latest_traffic_direction_2026") or {}

    owned = module1.get("owned_content_history") or {}
    periods = owned.get("periods") or req.owned_content_history or []
    trend_categories: list[str] = []
    trend_exposure: list[float] = []
    trend_counts: list[float] = []
    for row in periods[:6]:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        merged = {**row, **metrics}
        period_raw = str(merged.get("时间") or merged.get("period") or merged.get("月份") or "")
        if period_raw.endswith("月") and period_raw[:-1].isdigit():
            # 与看板 YYYY-MM 对齐；缺少年份时用当前年占位
            from datetime import datetime as _dt
            trend_categories.append(f"{_dt.now().year}-{int(period_raw[:-1]):02d}")
        else:
            trend_categories.append(period_raw)
        try:
            exposure = float(
                str(merged.get("曝光量") or merged.get("impressions") or 0).replace(",", "")
            )
            trend_exposure.append(round(exposure / 10000, 1))
        except ValueError:
            trend_exposure.append(0)
        try:
            trend_counts.append(
                float(
                    str(
                        merged.get("篇数")
                        or merged.get("内容供给")
                        or merged.get("供给")
                        or merged.get("note_count")
                        or 0
                    )
                )
            )
        except ValueError:
            trend_counts.append(0)

    peak_block = organic.get("traffic_peak_hours") or {}
    peak_source = list(peak_block.get("slots") or peak_block.get("hours") or [])
    peak_slots = [
        BenchmarkPeakSlot(
            slot=str(item.get("slot") or item.get("hour") or item),
            count=int(item.get("count") or item.get("note_count") or 1),
        )
        if isinstance(item, dict)
        else BenchmarkPeakSlot(slot=str(item), count=1)
        for item in peak_source[:6]
    ]

    audience = (competitor.get("targeting_inference") or {}).get("audience_signals") or []
    paid_count = (competitor.get("paid_notes") or {}).get("confirmed_count") or 0
    risk_pack = build_risk_signal_pack(req, risk, evidence)

    return CompetitorBenchmarkBrief(
        headline="赛道与竞品深度分析",
        subtitle=(
            f"{req.brand_name}｜已对用户给定的 {len(evidence)} 条链接做公开页抓取；"
            "含自然流量大盘、聚光投放大盘、竞品拆解与风险预警。未做全站爬取。"
        ),
        pills=[
            f"对标条目 {len(evidence)}",
            f"广告标识确认 {paid_count}",
            "给定链接抓取 · 非全站爬取",
        ],
        evidence_boundary=(
            (competitor.get("paid_notes") or {}).get("warning")
            or "广告标识与投放时长仅来自给定链接公开页可观测信号；不能还原竞品后台预算。"
        ),
        hero_stats=hero_stats,
        sample_notes=sample_notes,
        organic_summary=organic_insights.get("summary")
        or (competitor.get("organic_hits_commonalities") or {}).get("decision_conclusion")
        or (organic.get("publication_interaction_trend") or {}).get("decision_conclusion")
        or "基于给定对标笔记的互动与主题归纳自然流量特征。",
        organic_commonalities=commonalities,
        organic_gaps=gaps,
        organic_trend_caption=(
            (organic.get("publication_interaction_trend") or {}).get("decision_conclusion")
            or "品类笔记发布量／互动量趋势（知识库检索样本）；下方另附品牌自有月度历史（若已导入）。"
        ),
        organic_trend_categories=trend_categories,
        organic_trend_exposure_wan=trend_exposure,
        organic_trend_note_counts=trend_counts,
        peak_caption=(
            (organic.get("traffic_peak_hours") or {}).get("decision_conclusion")
            or "高峰按时区：published_at→北京时间分桶；样本不足时多时段等量测试。"
        ),
        peak_slots=peak_slots,
        format_note=format_note,
        spotlight_notice=(
            "聚光成本来自品牌导入投流表/基准证据，不是竞品账户后台，也不是平台公开行业均值。"
        ),
        spotlight_metrics=BenchmarkSpotlightMetrics(
            cpc=cpc,
            cpm=cpm,
            ctr=ctr,
            interaction_cost=interaction,
            conversion_cost=cpa if cpa is not None else "缺口",
        ),
        spotlight_monthly=[
            BenchmarkMonthlyRow(
                month=str(row.get("month") or ""),
                spend=str(row.get("spend") or "—"),
                cpc=str(row.get("cpc") or "—"),
                cpm=str(row.get("cpm") or "—"),
                ctr=str(row.get("ctr") or "—"),
            )
            for row in (req.paid_monthly_history or [])
            if isinstance(row, dict) and row.get("month")
        ],
        spotlight_goal_notes=[
            *(goals.get("goal_notes") or []),
            goals.get("decision_conclusion") or "热门推广目标需分目标消耗数据验证；当前按任务目标拆建种草/成交测试。",
            "对标评论若大量问价格/门店/寄送，优先种草到店与搜索承接；客资导流需合规。",
        ],
        spotlight_traffic_notes=[
            f"搜索/信息流参考配比：搜索 {share.get('search_ratio') if share.get('search_ratio') is not None else '—'} / "
            f"信息流 {share.get('feed_ratio') if share.get('feed_ratio') is not None else '—'}",
            *(direction.get("direction_points") or []),
            share.get("decision_conclusion") or "无分版位消耗时，首轮用搜索/信息流双轨探测。",
            direction.get("decision_conclusion")
            or direction.get("status")
            or "平台流量倾斜待官方公告/帮助中心证据，不写传闻。",
        ],
        commonality_rows=[
            BenchmarkKvRow(dimension="主题", observation="、".join(row.get("theme", "") for row in themes[:5]) or "见对标主题标注"),
            BenchmarkKvRow(
                dimension="形式",
                observation="、".join(f"{row.get('format')}" for row in formats[:4]) or "图集为主（对标样本）",
            ),
            BenchmarkKvRow(
                dimension="互动引擎",
                observation="、".join(audience[:6]) or "评论画像待更多抓取样本",
            ),
        ],
        paid_note_rows=[
            BenchmarkKvRow(
                note=f"{item.account_name} · {item.title or ''}".strip(" ·"),
                ad_label="有" if item.is_ad_labeled is True else "无" if item.is_ad_labeled is False else "未判定",
                content_type=item.note_format or "待核验",
                duration_judgment=(
                    f"用户/脚本提供 {item.campaign_duration_days} 天"
                    if item.campaign_duration_days
                    else "公开页无法认定投放时长；需多日快照"
                ),
            )
            for item in evidence
        ],
        paid_conclusion=(
            (competitor.get("paid_notes") or {}).get("decision_conclusion")
            or f"广告标识确认 {paid_count}/{len(evidence)}；未确认样本不作为正在投流证据。"
        ),
        targeting_cards=[
            BenchmarkKvRow(title="受众信号", body="、".join(audience) or "待从评论区补抓"),
            BenchmarkKvRow(
                title="定向使用方式",
                body=(competitor.get("targeting_inference") or {}).get("decision_conclusion")
                or "评论画像仅生成定向测试假设，须在自有账户验证。",
            ),
            BenchmarkKvRow(
                title="预算范围",
                body=(competitor.get("budget_range") or {}).get("decision_conclusion")
                or "不由点赞反推竞品预算；按自身 CPC/止损线分配。",
            ),
        ],
        risk_content_signals=risk_pack["content_types"],
        risk_rejection_signals=risk_pack["rejection_reasons"],
        risk_note=risk_pack["risk_note"],
        counter_actions=[
            BenchmarkKvRow(
                priority=f"P{i}",
                action=opp.get("opportunity") or "",
                gap=opp.get("reason") or "",
            )
            for i, opp in enumerate(
                ((competitor.get("content_gaps") or {}).get("opportunities") or [])[:3],
                start=1,
            )
        ] or [
            BenchmarkKvRow(priority="P1", action="围绕对标高频主题做对比/攻略图集", gap="承接对标自然流量意图"),
            BenchmarkKvRow(priority="P2", action="搜索词包截流对标高意向词", gap="门店/避坑/排序类搜索"),
            BenchmarkKvRow(priority="P3", action="评论区准备价格/寄送/支付标准答", gap="对标评论高意向问题"),
        ],
    )
