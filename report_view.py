"""Build a human-readable strategy report from the six deterministic modules."""
from __future__ import annotations

from typing import Any

from models import CampaignRequest, EvidenceGap
from report_agent_view import (
    AGENT_MODULE_LABELS,
    apply_agent_grounding_policy,
    build_agent_decision_view,
    build_benchmark_ssot,
)


# engine_key → 报告章节号（章节由 build_report_view 顺序赋号）。
# 1 赛道与竞品 / 2 画像 / 3 关键词策略 / 4 达人匹配 / 5 聚光前置 / 6 预算节奏
_AGENT_DECISION_CHAPTER = {
    "module_1_market_competitor": 1,
    "module_2_audience_content": 2,
    "module_6_keyword_strategy": 3,
    "module_3_keyword_creator": 4,
    "module_4_spotlight_decision": 5,
    "module_5_budget_pacing": 6,
}


GOAL_LABELS = {
    "awareness": "品牌曝光",
    "engagement": "点赞收藏",
    "search_growth": "搜索增长",
    "conversion": "商品成交",
    "leads": "客资收集",
    "live_traffic": "直播引流",
}


def _value(row: dict[str, Any], default: str = "待接入") -> Any:
    value = row.get("value")
    return default if value is None else value


def _money(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return f"¥{int(round(value)):,}"
    return None


def _bid_money(value: Any) -> str | None:
    """出价/CPC 保留两位小数，避免 0.30 被格式化成 ¥0。"""
    if isinstance(value, (int, float)):
        return f"¥{float(value):.2f}"
    return None


def _mock_context(*rows: dict[str, Any] | None) -> tuple[bool, str | None, str | None]:
    mocks = [row for row in rows if row and row.get("is_mock") is True]
    if not mocks:
        return False, None, None
    seed = next((row.get("mock_seed") for row in mocks if row.get("mock_seed")), None)
    warning = next((row.get("warning") for row in mocks if row.get("warning")), None)
    return True, seed, warning


def _section_mock_flags(*rows: dict[str, Any] | None) -> dict[str, Any]:
    """章节级 is_mock 仅在“决策主指标全部为 Mock”时为真；部分 Mock 单独标注。"""
    present = [row for row in rows if row and row.get("value") is not None]
    if not present:
        has_mock, seed, warning = _mock_context(*rows)
        return {
            "is_mock": has_mock,
            "has_partial_mock": False,
            "mock_seed": seed,
            "warning": warning,
        }
    mock_rows = [row for row in present if row.get("is_mock") is True]
    real_rows = [row for row in present if row.get("is_mock") is not True]
    seed = next((row.get("mock_seed") for row in mock_rows if row.get("mock_seed")), None)
    warning = next((row.get("warning") for row in mock_rows if row.get("warning")), None)
    return {
        "is_mock": bool(mock_rows) and not real_rows,
        "has_partial_mock": bool(mock_rows) and bool(real_rows),
        "mock_seed": seed,
        "warning": warning,
    }


def build_organic_section(req: CampaignRequest, module1: dict[str, Any]) -> dict[str, Any]:
    organic = module1["organic_market"]
    platform = module1.get("simulated_platform_market") or {}
    sample_series = organic.get("publication_interaction_trend", {}).get("series") or []
    visual_series = sample_series or platform.get("series") or []
    peaks = organic.get("traffic_peak_hours", {}).get("hours") or []
    formats = organic.get("popular_content_formats") or []
    tags = organic.get("observed_hot_tags", {}).get("tags") or organic.get("top_tags") or []
    is_mock, seed, warning = _mock_context(organic, platform if not sample_series else None)
    trend_conclusion = organic.get("publication_interaction_trend", {}).get(
        "decision_conclusion", "当前缺少可用发布时间，不能判断趋势。"
    )
    peak_conclusion = organic.get("traffic_peak_hours", {}).get(
        "decision_conclusion", "当前缺少高峰时段证据。"
    )
    format_conclusion = organic.get(
        "popular_content_format_conclusion", "当前缺少内容形式证据。"
    )
    has_verified_peak = bool(peaks)
    window_n = int(organic.get("sample_size") or 0)
    raw_n = organic.get("raw_sample_size")
    trend_n = organic.get("trend_sample_size")
    out_n = organic.get("out_of_window_count")
    scope_label = f"近{req.analysis_days}天"
    if isinstance(raw_n, int) and raw_n > window_n:
        sample_line = (
            f"【{scope_label}】窗口样本{window_n}条；"
            f"检索/导入全量{raw_n}条"
            f"（其中{trend_n if isinstance(trend_n, int) else raw_n}条带发布时间计入趋势与高峰；"
            f"窗外{out_n if isinstance(out_n, int) else raw_n - window_n}条不计入窗口样本）。"
        )
    else:
        sample_line = f"【{scope_label}】窗口样本{window_n}条。"
    window_avg = organic.get("window_average_interactions_per_note")
    if window_avg is None:
        window_avg = organic.get("average_interactions_per_note", 0)
    if not window_n:
        decision = "先补充品类笔记证据，再确定内容形式与发布时间；当前仅执行分时对照测试。"
    elif has_verified_peak:
        decision = (
            f"以样本高互动主题和已验证高峰时段作为首轮内容测试入口；{format_conclusion}"
        )
    else:
        decision = (
            f"以样本高互动主题作为首轮内容测试入口；高峰时段样本不足"
            f"（单时段需≥3条），首轮多时段等量测试，暂不指定唯一高峰。"
            f"{format_conclusion}"
        )
    peak_action = (
        "在排名靠前的发布时间段等量发布；24小时后按互动与搜索承接筛选胜出素材。"
        if has_verified_peak
        else "高峰证据不足：首轮在多个候选时段等量发布，不指定唯一高峰；24小时后按互动筛选。"
    )
    return {
        "key": "organic",
        "chapter_number": 1,
        "title": "自然流量大盘分析",
        "decision": decision,
        "data_explanation": [
            sample_line,
            (
                f"全量命中累计互动{organic.get('total_interactions', 0):,}，"
                f"全量篇均{organic.get('average_interactions_per_note', 0)}；"
                f"【{scope_label}】窗口篇均{window_avg}。"
            ),
        ],
        "analysis": [trend_conclusion, peak_conclusion, format_conclusion],
        "actions": [
            "围绕样本高互动主题制作场景、对比和体验三类内容，并保持唯一变量测试。",
            peak_action,
            "标签只作为候选布局，发布后按真实搜索流量迭代，不能称作平台扶持事实。",
        ],
        "success_metrics": [
            "每个内容方向至少获得可比较的发布样本",
            "24小时互动表现达到品牌历史中位数或样本中位数",
            "胜出素材进入聚光小预算验证",
        ],
        "evidence_boundary": (
            warning
            if is_mock
            else organic.get("sampling_warning") or organic.get("warning")
        ),
        "is_mock": is_mock,
        "mock_seed": seed,
        "warning": warning,
        "visuals": {
            "metric_cards": [
                {
                    "label": "窗口样本",
                    "value": window_n,
                    "unit": "条",
                    "scope": "window",
                    "scope_label": scope_label,
                },
                {
                    "label": "趋势/高峰样本",
                    "value": trend_n if isinstance(trend_n, int) else (
                        raw_n if isinstance(raw_n, int) else window_n
                    ),
                    "unit": "条",
                    "scope": "full",
                    "scope_label": "全量命中",
                },
                {
                    "label": "窗口篇均互动",
                    "value": window_avg,
                    "unit": "次",
                    "scope": "window",
                    "scope_label": scope_label,
                },
            ],
            "trend_series": visual_series,
            "peak_hours": peaks,
            "formats": formats,
            "tags": tags,
            "analysis_days": req.analysis_days,
        },
    }


def build_spotlight_section(
    req: CampaignRequest,
    module1: dict[str, Any],
    module4: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spotlight = module1["spotlight_market"]
    cpc = spotlight["average_cpc"]
    cpm = spotlight["average_cpm"]
    ctr = spotlight.get("average_ctr") or {}
    interaction = spotlight.get("interaction_cost") or {}
    cpa = spotlight["conversion_cost"]
    share = spotlight["search_feed_budget_share"]
    goals = spotlight["popular_promotion_goals"]
    direction = spotlight["latest_traffic_direction_2026"]
    flags = _section_mock_flags(cpc, cpm, cpa, ctr, interaction)
    m4 = module4 or {}
    # 优先用模块4账户级搜推拆分；否则回退大盘 share
    m4_split = m4.get("search_feed_split") or {}
    share_mock = share.get("is_mock") is True and not isinstance(m4_split.get("search"), (int, float))
    search_ratio = m4_split.get("search")
    feed_ratio = m4_split.get("feed")
    if not isinstance(search_ratio, (int, float)):
        search_ratio = share.get("search_ratio")
        feed_ratio = share.get("feed_ratio")
    split_text = (
        f"搜索{search_ratio:.0%}、信息流{feed_ratio:.0%}"
        if isinstance(search_ratio, (int, float)) and isinstance(feed_ratio, (int, float))
        else "搜索与信息流占比待账户数据校准"
    )
    if isinstance(search_ratio, (int, float)) and share_mock:
        split_text = f"{split_text}（搜推配比为 Mock 情景）"

    account = m4.get("account_structure") or {}
    plans = account.get("plans") or []
    plan_text = "、".join(
        f"{row.get('name')}（{float(row.get('budget_ratio') or 0):.0%}）"
        for row in plans
        if row.get("name")
    )
    packages = m4.get("targeting_packages") or []
    package_text = "、".join(
        f"{row.get('name')}{float(row.get('ratio') or 0):.0%}"
        for row in packages
        if row.get("name")
    )
    schedules = m4.get("daily_schedules") or {}
    slots = schedules.get("slots") or []
    slot_text = "、".join(
        f"{row.get('slot')}（{row.get('role') or '高峰窗'}）"
        for row in slots[:4]
        if row.get("slot")
    )
    bidding = m4.get("bidding") or {}
    cold = bidding.get("cold_start")
    if isinstance(cold, dict):
        bid_low = _money(cold.get("bid_low_cny"))
        bid_high = _money(cold.get("bid_high_cny"))
        bid_text = (
            f"冷启动出价 {bid_low}–{bid_high}"
            if bid_low or bid_high
            else (cold.get("method") or cold.get("basis") or "出价待账户建议价校准")
        )
    else:
        bid_text = str(cold) if cold else "出价待账户建议价校准"
    forecast = m4.get("forecast") or {}
    probe = (forecast.get("test_bandwidth") or {}).get("cold_start_budget_cny")
    stop = forecast.get("stop_loss") or {}
    probe_money = _money(probe)
    cpc_stop = _money(stop.get("cpc_stop_cny"))
    cpa_stop = _money(stop.get("cpa_stop_cny"))

    decision = (
        f"本次以“{GOAL_LABELS[req.goal]}”为主目标，"
        + (f"按「{plan_text}」拆建账户；" if plan_text else "搜索与信息流分计划搭建；")
        + f"首轮采用{split_text}双轨测试"
        + (f"，探测预算{probe_money}（非全案投放预算）" if probe_money else "")
        + "；达到最小样本后只放大成本稳定的版位和素材。"
    )
    ctr_text = _value(ctr)
    if isinstance(ctr.get("value"), (int, float)):
        ctr_text = f"{ctr['value'] * 100:.2f}%"
    interaction_text = (
        f"{_value(interaction)} {interaction.get('unit', '')}"
        if interaction.get("value") is not None
        else "缺口（有 CPC/CTR 时仍可先测点击与互动）"
    )
    cpa_text = (
        f"{_value(cpa)} {cpa.get('unit', '')}"
        if cpa.get("value") is not None
        else "缺口（勿把单次互动成本当成 CPA）"
    )
    goal_rank = goals.get("market_ranking") or []
    goal_rank_text = " > ".join(str(x) for x in goal_rank) if goal_rank else GOAL_LABELS[req.goal]
    data_explanation = [
        f"CPC参考值为{_value(cpc)} {cpc.get('unit', '')}，CPM参考值为{_value(cpm)} {cpm.get('unit', '')}，CTR参考值为{ctr_text}。",
        f"单次互动成本参考值为{interaction_text}；转化成本参考值为{cpa_text}；当前推广目标为{GOAL_LABELS[req.goal]}。",
        f"推广目标测试优先级：{goal_rank_text}（非品类消耗热度榜）。",
        f"预算结构：{split_text}"
        + (f"；探测预算{probe_money}（用于冷启动可比较测试，不等于全案聚光预算）。" if probe_money else "。"),
    ]
    for note in (goals.get("goal_notes") or [])[:3]:
        data_explanation.append(str(note))
    for point in (direction.get("direction_points") or [])[:3]:
        data_explanation.append(str(point))
    if plan_text:
        data_explanation.append(f"账户计划：{plan_text}；单元命名：{account.get('unit_naming') or '待定'}。")
    if package_text:
        data_explanation.append(f"定向包：{package_text}。")
    if slot_text:
        data_explanation.append(
            f"优先投放时段：{slot_text}。"
            + (f" {schedules.get('warning')}" if schedules.get("warning") else "")
        )
    data_explanation.append(f"出价策略：{bid_text}。")

    actions = []
    if plan_text:
        actions.append(f"按计划拆建：{plan_text}；搜索与信息流不混在同一单元。")
    else:
        actions.append("搜索和信息流分别建计划，不在同一单元混合定向与素材变量。")
    if package_text:
        actions.append(f"定向包按比例测试：{package_text}。")
    if slot_text:
        actions.append(f"优先投放时段：{slot_text}；其余预算均分测试。")
    if probe_money:
        actions.append(
            f"首轮只用探测预算{probe_money}做可比较测试；未达最小点击/转化样本前不放大全案预算。"
        )
    else:
        actions.append("先按低／中／高三档成本情景设置测试带宽，每3天用真实账户数据替换。")
    if cpc_stop or cpa_stop:
        actions.append(
            f"止损线：CPC>{cpc_stop or '账户校准'} 或 CPA>{cpa_stop or '账户校准'}，"
            "且达最小样本时暂停素材/定向，不依据单日波动放量。"
        )
    else:
        actions.append("达到最小点击或转化样本后，依据CPA与止损线调预算，不依据单日波动放量。")

    return {
        "key": "spotlight",
        "chapter_number": 2,
        "title": "聚光投放大盘分析",
        "decision": decision,
        "data_explanation": data_explanation,
        "analysis": [
            cpc.get("decision_conclusion", "CPC需在账户中验证。"),
            ctr.get("decision_conclusion", "CTR需在账户中验证。"),
            interaction.get("decision_conclusion")
            or cpa.get("decision_conclusion", "转化成本需在账户中验证。"),
            goals.get("decision_conclusion", "推广目标优先级需按账户消耗验证。"),
            share.get("decision_conclusion", "搜索/信息流配比需按账户消耗验证。"),
            direction.get("decision_conclusion", "流量方向需按官方资料或账户实验验证。"),
            *([schedules.get("status")] if schedules.get("status") else []),
            *(
                [((forecast.get("test_bandwidth") or {}).get("decision_conclusion"))]
                if (forecast.get("test_bandwidth") or {}).get("decision_conclusion")
                else []
            ),
        ],
        "actions": actions,
        "success_metrics": [
            "完成搜索与信息流可比较测试",
            "CPC和CPA不高于预设止损线",
            "连续两个观察窗口成本稳定后才提高预算",
        ],
        "evidence_boundary": (
            (
                "含部分 Mock 字段（如转化成本或搜推配比）；CPC/CPM 等真实指标仍可用于首轮参考。"
                if flags["has_partial_mock"]
                else flags["warning"]
            )
            or schedules.get("warning")
            or "聚光指标以品牌授权报表和账户实时数据为准。"
        ),
        "is_mock": flags["is_mock"],
        "has_partial_mock": flags["has_partial_mock"],
        "mock_seed": flags["mock_seed"],
        "warning": flags["warning"],
        "visuals": {
            "metric_cards": [
                {
                    "label": "CPC",
                    "value": cpc.get("value"),
                    "unit": cpc.get("unit"),
                    "is_mock": cpc.get("is_mock"),
                    "scope": "window",
                    "scope_label": f"近{req.analysis_days}天加权",
                },
                {
                    "label": "CPM",
                    "value": cpm.get("value"),
                    "unit": cpm.get("unit"),
                    "is_mock": cpm.get("is_mock"),
                    "scope": "window",
                    "scope_label": f"近{req.analysis_days}天加权",
                },
                {
                    "label": "CTR",
                    "value": (
                        round(ctr["value"] * 100, 2)
                        if isinstance(ctr.get("value"), (int, float))
                        else ctr.get("value")
                    ),
                    "unit": "%" if isinstance(ctr.get("value"), (int, float)) else (ctr.get("unit") or ""),
                    "is_mock": ctr.get("is_mock"),
                    "scope": "window",
                    "scope_label": f"近{req.analysis_days}天加权",
                },
                {
                    "label": "单次互动成本",
                    "value": interaction.get("value"),
                    "unit": interaction.get("unit") or "元/次互动",
                    "is_mock": interaction.get("is_mock"),
                    "hint": "≠CPA",
                    "scope": "window",
                    "scope_label": f"近{req.analysis_days}天加权",
                },
                {
                    "label": "转化成本",
                    "value": cpa.get("value"),
                    "unit": cpa.get("unit") or "元/次转化",
                    "is_mock": cpa.get("is_mock"),
                },
                {
                    "label": "探测预算",
                    "value": probe,
                    "unit": "CNY",
                    "hint": "非全案投放预算",
                },
            ],
            "analysis_days": req.analysis_days,
            "budget_share": {"search_ratio": search_ratio, "feed_ratio": feed_ratio},
            "scenario_rows": [
                {
                    "metric": label,
                    "value": (
                        f"{row.get('value') * 100:.2f}%"
                        if label == "CTR" and isinstance(row.get("value"), (int, float))
                        else row.get("value")
                    ),
                    "unit": "%" if label == "CTR" and isinstance(row.get("value"), (int, float)) else row.get("unit"),
                    "source": row.get("source_name")
                    or row.get("basis")
                    or row.get("status")
                    or "—",
                    "is_mock": row.get("is_mock"),
                }
                for label, row in (
                    ("CPC", cpc),
                    ("CPM", cpm),
                    ("CTR", ctr),
                    ("单次互动成本", interaction),
                    ("转化成本", cpa),
                )
            ],
            "goal_notes": list(goals.get("goal_notes") or []),
            "goal_ranking": list(goal_rank),
            "traffic_points": list(direction.get("direction_points") or []),
            "account_plans": plans,
            "targeting_packages": packages,
            "daily_slots": slots,
            "bidding": bidding,
            "probe_budget_cny": probe,
        },
    }


def build_competitor_section(req: CampaignRequest, module1: dict[str, Any]) -> dict[str, Any]:
    competitor = module1["competitor_full_funnel"]
    accounts = competitor.get("accounts") or []
    common = competitor["organic_hits_commonalities"]
    gaps = competitor["content_gaps"]
    targeting = competitor["targeting_inference"]
    budget = competitor["budget_range"]
    mock_rows = [row for row in accounts if row.get("is_mock")]
    is_mock, seed, warning = _mock_context(
        targeting, budget, mock_rows[0] if mock_rows else None
    )
    decision = (
        f"竞争切入应优先利用样本内容空白，而不是复制竞品形式。{gaps.get('decision_conclusion', '')}"
        if accounts or common.get("sample_note_count")
        else "竞品证据不足，先完成3–5个账号的公开内容采样，再确定差异化投放策略。"
    )
    return {
        "key": "competitor",
        "chapter_number": 3,
        "title": "竞品全域投放分析",
        "decision": decision,
        "data_explanation": [
            (
                f"用户提供对标条目{len(accounts)}个"
                f"（结构化主题标注{common.get('user_competitor_count', len(accounts))}条），"
                f"品类笔记样本{common.get('sample_note_count', 0)}条；"
                "对标结构化字段来自给定链接公开页抓取（非全站爬取）。"
            ),
            f"广告标识确认笔记{competitor.get('paid_notes', {}).get('confirmed_count', 0)}条。",
        ],
        "analysis": [
            common.get("decision_conclusion", "竞品爆款共性证据不足。"),
            gaps.get("decision_conclusion", "内容空白仍需通过样本验证。"),
            targeting.get("decision_conclusion", "评论画像仅形成定向测试假设。"),
            budget.get("decision_conclusion", "公开互动不能可靠反推竞品预算。"),
        ],
        "actions": [
            "只把带广告标识或有连续快照证据的笔记纳入投流素材拆解。",
            "将内容空白制作成对比型与真实体验型素材，用自有账户小预算验证。",
            "评论区画像仅转换成定向测试包，不表述为竞品真实定向。",
        ],
        "success_metrics": [
            "形成3–5个可核验对标账号样本",
            "每个差异化方向至少完成一组素材测试",
            "只有经账户验证的定向假设进入放量阶段",
        ],
        "evidence_boundary": warning or competitor.get("paid_notes", {}).get("warning"),
        "is_mock": is_mock,
        "mock_seed": seed,
        "warning": warning,
        "visuals": {
            "metric_cards": [
                {"label": "对标条目", "value": len(accounts), "unit": "个"},
                {"label": "广告标识", "value": competitor.get("paid_notes", {}).get("confirmed_count", 0), "unit": "条"},
                {"label": "内容空白", "value": len(gaps.get("opportunities") or []), "unit": "项"},
            ],
            "accounts": accounts,
            "opportunities": gaps.get("opportunities") or [],
        },
    }


def build_risk_section(req: CampaignRequest, module1: dict[str, Any]) -> dict[str, Any]:
    from risk_signals import build_risk_signal_pack

    risk = module1["risk_warning"]
    rules = risk["official_rules"]
    ledger = risk["category_high_frequency_violations"]
    rejection = risk["frequent_ad_rejection_reasons"]
    pack = build_risk_signal_pack(req, risk, req.competitor_evidence)
    rows = pack["ledger_rows"]
    mock_rows = [row for row in rows if row.get("is_mock")]
    is_mock, seed, warning = _mock_context(mock_rows[0] if mock_rows else None)
    top_reason = None
    if rows:
        top_reason = rows[0].get("reason")
    elif pack["rejection_reasons"]:
        top_reason = pack["rejection_reasons"][0]
    decision = (
        f"发布与投流前优先排查“{top_reason}”；同步规避赛道高风险内容类型："
        f"{'、'.join(pack['content_types'][:3])}。"
        if top_reason
        else "当前没有赛道频次台账，先按官方规则完成预审并建立拒审记录，不能宣称高频排名。"
    )
    return {
        "key": "risk",
        "chapter_number": 4,
        "title": "风险预警",
        "decision": decision,
        "data_explanation": [
            f"已接入官方规则{pack['official_source_count']}份。",
            pack["content_status"],
            pack["rejection_status"],
            f"违规／拒审台账原因{len(rows)}项。",
        ],
        "analysis": [
            f"限流/违规内容类型：{'；'.join(pack['content_types'][:5])}。",
            f"聚光拒审原因：{'；'.join(pack['rejection_reasons'][:5])}。",
            rules.get("decision_conclusion", "官方规则用于发布前底线检查。"),
            ledger.get("decision_conclusion", "高频结论必须来自频次台账。"),
            rejection.get("decision_conclusion", "拒审原因需按账户审核记录统计。"),
        ],
        "actions": [
            "发布前检查绝对化表述、功效承诺、虚假稀缺、资质和商业合作披露。",
            "拒审后按原因、素材、商品和日期写入台账；同原因连续拒审时升级合规复核。",
            "规则更新与赛道频次分开维护，避免把规则条文误写成近期高发事实。",
        ],
        "success_metrics": [
            "所有发布素材完成预审记录",
            "拒审原因可按频次追溯",
            "同类违规表述进入素材黑名单",
        ],
        "evidence_boundary": warning or pack["risk_note"],
        "is_mock": is_mock,
        "mock_seed": seed,
        "warning": warning,
        "visuals": {
            "metric_cards": [
                {"label": "官方规则", "value": pack["official_source_count"], "unit": "份"},
                {"label": "限流内容类型", "value": len(pack["content_types"]), "unit": "项"},
                {"label": "拒审原因", "value": len(pack["rejection_reasons"]), "unit": "项"},
                {"label": "台账原因", "value": len(rows), "unit": "项"},
            ],
            "content_types": pack["content_types"],
            "content_status": pack["content_status"],
            "rejection_reasons": pack["rejection_reasons"],
            "rejection_status": pack["rejection_status"],
            "has_ledger": pack["has_ledger"],
            "risk_rows": rows,
            "baseline_checks": pack["baseline_checks"],
            "official_sources": rules.get("official_sources") or [],
        },
    }


def build_market_competitor_section(
    req: CampaignRequest,
    module1: dict[str, Any],
    module4: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """模块1：自然流量 + 聚光投放 + 竞品拆解 + 风险预警，统一为赛道与竞品深度分析。"""
    organic = build_organic_section(req, module1)
    spotlight = build_spotlight_section(req, module1, module4)
    competitor = build_competitor_section(req, module1)
    risk = build_risk_section(req, module1)
    subsections = [organic, spotlight, competitor, risk]
    # 任一子章有 mock 时章节级标注
    has_mock = any(section.get("is_mock") for section in subsections)
    has_partial = any(section.get("has_partial_mock") for section in subsections) or (
        has_mock and not all(section.get("is_mock") for section in subsections)
    )
    seed = next(
        (section.get("mock_seed") for section in subsections if section.get("mock_seed")),
        None,
    )
    warning = next(
        (section.get("warning") for section in subsections if section.get("warning")),
        None,
    )
    evidence_n = len(req.competitor_evidence or [])
    link_n = len(req.competitor_links or [])
    return {
        "key": "market_competitor",
        "chapter_number": 1,
        "title": "赛道与竞品深度分析",
        "decision": (
            f"模块1已合并自然流量大盘、聚光投放大盘、竞品全域投放与风险预警；"
            f"对标证据{evidence_n or link_n}条。"
            f"自然侧：{organic.get('decision', '')}"
            f" 聚光侧：{spotlight.get('decision', '')}"
        )[:480],
        "data_explanation": [
            f"品类：{req.category}；分析窗口近{req.analysis_days}天。",
            f"对标链接/证据：{max(evidence_n, link_n)}条（仅抓取用户给定链接，非全站爬取）。",
            "本页同时承载：①自然流量大盘 ②聚光投放大盘 ③竞品全域投放拆解 ④风险预警。",
            *list(organic.get("data_explanation") or [])[:1],
            *list(spotlight.get("data_explanation") or [])[:1],
        ],
        "analysis": [
            organic.get("decision") or "自然流量大盘待补证据。",
            spotlight.get("decision") or "聚光投放大盘待补证据。",
            competitor.get("decision") or "竞品拆解待补对标链接。",
            risk.get("decision") or "风险预警按官方规则预审。",
        ],
        "actions": list(dict.fromkeys([
            *(organic.get("actions") or [])[:2],
            *(spotlight.get("actions") or [])[:2],
            *(competitor.get("actions") or [])[:2],
            *(risk.get("actions") or [])[:2],
        ])),
        "success_metrics": list(dict.fromkeys([
            *(organic.get("success_metrics") or [])[:1],
            *(spotlight.get("success_metrics") or [])[:1],
            *(competitor.get("success_metrics") or [])[:1],
            *(risk.get("success_metrics") or [])[:1],
        ])),
        "evidence_boundary": (
            warning
            or "自然大盘来自品类笔记/历史表；聚光成本来自品牌投流表；竞品仅来自给定链接公开页。"
        ),
        "is_mock": has_mock and not has_partial,
        "has_partial_mock": has_partial,
        "mock_seed": seed,
        "warning": warning,
        "subsections": subsections,
        "visuals": {
            "subsection_keys": ["organic", "spotlight", "competitor", "risk"],
            "organic": organic.get("visuals") or {},
            "spotlight": spotlight.get("visuals") or {},
            "competitor": competitor.get("visuals") or {},
            "risk": risk.get("visuals") or {},
        },
    }


def build_action_plan(req: CampaignRequest, modules: dict[str, Any]) -> list[dict[str, Any]]:
    budget = modules["module_5_budget_pacing"]["budget"]
    forecast = modules["module_4_spotlight_decision"]["forecast"]
    stop_loss = forecast.get("stop_loss") or {}
    topics = modules["module_2_audience_content"].get("topics") or []
    creators = (
        modules["module_3_keyword_creator"].get("creator_recommendations_20")
        or modules["module_3_keyword_creator"].get("creator_candidates")
        or []
    )
    dual = modules["module_3_keyword_creator"].get("dual_track_keyword_library") or {}
    search_kw = [
        item.get("keyword")
        for item in (dual.get("spotlight_paid", {}).get("search_promotion", {}) or {}).get("keywords") or []
        if item.get("keyword")
    ][:5]
    if not search_kw:
        search_kw = (modules["module_6_keyword_strategy"].get("keyword_levels") or {}).get("long_tail") or [
            f"{req.category}推荐",
            f"{req.product_name}怎么选",
        ]
    search_kw = search_kw[:5]
    topic_titles = [t.get("title_template") for t in topics[:3] if t.get("title_template")]
    test_budget = forecast.get("test_bandwidth", {}).get("cold_start_budget_cny")
    cpa_stop = stop_loss.get("cpa_stop_cny")
    mock_creator_count = sum(1 for row in creators if row.get("is_mock") is True)
    verified_creators = [
        row for row in creators
        if row.get("followers") is not None and row.get("is_mock") is not True
    ]
    verified_creator_count = len(verified_creators)
    top_creator_names = [
        row.get("creator_name") or row.get("name") for row in verified_creators[:3]
    ]
    top_creator_names = [name for name in top_creator_names if name]
    creator_amplify = _round_optional(
        modules["module_3_keyword_creator"].get("creator_tier_plan", {})
        .get("spotlight_amplification_pool_cny")
    )
    if mock_creator_count and not verified_creator_count:
        creator_summary = f"{mock_creator_count}位Mock 演示达人候选（非真实推荐）"
    elif mock_creator_count:
        creator_summary = (
            f"{verified_creator_count}位待复核候选和{mock_creator_count}位Mock 演示达人候选"
        )
    else:
        creator_summary = f"{len(creators)}位达人候选"
    gate = modules["module_2_audience_content"].get("paid_material_gate", {}).get("prototype_thresholds") or {}
    return [
        {
            "priority": "P1",
            "title": "验证高意向搜索承接",
            "why": (
                f"先用词包「{'、'.join(search_kw[:3])}」承接主动需求，"
                f"验证{GOAL_LABELS[req.goal]}目标是否跑得通。"
            ),
            "steps": [
                f"新建搜索计划，词包优先：{'、'.join(search_kw)}",
                f"单元命名：{GOAL_LABELS[req.goal]}_搜索_高意向_{{素材方向}}_日期",
                (
                    f"冷启动探测预算约 ¥{test_budget or 0:,}"
                    f"（非全案投放预算；全案聚光约 ¥{int(budget.get('spotlight_cny') or 0):,}）；"
                    "达到最小点击后再按 CPA 筛选"
                ),
            ],
            "keywords": search_kw,
            "budget_cny": test_budget,
            "budget_kind": "probe",
            "budget_label": "探测预算（非全案投放预算）",
            "campaign_budget_cny": budget.get("spotlight_cny"),
            "owner": "优化师",
            "timeline": "第1–3天",
            "success_metrics": [
                "点击≥100 或转化≥20（以先到者为决策门槛）",
                f"CPA不高于止损线{f'¥{cpa_stop}' if cpa_stop else '（待账户校准）'}",
            ],
            "stop_condition": stop_loss.get("formula") or "达到最小样本后仍超过目标成本20%则暂停",
            "evidence_dependency": "聚光账户实时建议价、点击与转化回传",
        },
        {
            "priority": "P2",
            "title": "用自然表现筛选可放大素材",
            "why": (
                f"先发{len(topics)}个选题中的前3个方向降低付费试错："
                f"{'；'.join(topic_titles) if topic_titles else '场景痛点／产品证据／对比决策'}。"
            ),
            "steps": [
                "按场景痛点、产品证据、对比决策各发至少1篇",
                f"观察{gate.get('observation_hours', 24)}小时："
                f"CTR>{gate.get('ctr_percent', 10)}% 且互动率>{gate.get('engagement_rate_percent', 7)}% 才进聚光",
                "只把过门槛素材复制到信息流精准单元",
            ],
            "topics": topic_titles,
            "budget_cny": budget.get("organic_content_cny"),
            "owner": "内容负责人 + 优化师",
            "timeline": "第1–7天",
            "success_metrics": [
                "每类内容获得可比较样本",
                f"胜出素材达到 CTR>{gate.get('ctr_percent', 10)}% 或品牌历史中位数",
            ],
            "stop_condition": "连续两轮低于基准的方向停止追加制作与投流",
            "evidence_dependency": "自然笔记24小时表现与搜索来源数据",
        },
        {
            "priority": "P3",
            "title": "验证达人与竞品差异化机会",
            "why": (
                f"当前有{creator_summary}"
                + (f"；优先复核 {'、'.join(top_creator_names)}" if top_creator_names else "")
                + "；达人下单前必须人工核验粉丝与报价。"
            ),
            "steps": [
                "复核达人报价、粉丝画像与过往投流结果",
                "差异化内容先做对比/真实体验，不直接抄竞品封面",
                f"达人笔记独立放大预算池约 ¥{creator_amplify or 0:,}（可调）",
            ],
            "creators": top_creator_names,
            "budget_cny": creator_amplify,
            "owner": "媒介采购 + 内容负责人",
            "timeline": "第4–14天",
            "success_metrics": ["完成真实达人复核", "每层达人至少有一个可比较样本"],
            "stop_condition": "证据未复核或报价超预算时不下单",
            "evidence_dependency": "蒲公英／授权达人库、竞品公开笔记人工核验",
        },
    ]


def _round_optional(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(round(value))
    return None


def build_executive_summary(
    req: CampaignRequest,
    modules: dict[str, Any],
    gaps: list[EvidenceGap],
    data_confidence: str,
    sections: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    *,
    agent_grounding_alerts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    module1 = modules["module_1_market_competitor"]
    budget = modules["module_5_budget_pacing"]["budget"]
    platform = module1.get("simulated_platform_market") or {}
    seed = platform.get("mock_seed") or next(
        (row.get("mock_seed") for row in sections if row.get("mock_seed")), None
    )
    agent_count = sum(
        1
        for key in AGENT_MODULE_LABELS
        if isinstance(modules.get(key), dict)
        and isinstance((modules.get(key) or {}).get("agent_decision"), dict)
    )
    alerts = list(agent_grounding_alerts or [])
    by_key = {section["key"]: section for section in sections}
    preferred_keys = ("market_competitor", "audience", "keyword_strategy", "budget")
    key_findings: list[dict[str, Any]] = []
    market = by_key.get("market_competitor")
    if market:
        # 模块1拆成自然/聚光两条关键发现，便于摘要扫描
        for sub in (market.get("subsections") or [])[:2]:
            key_findings.append(
                {
                    "title": sub.get("title") or "赛道分析",
                    "conclusion": sub.get("decision") or market.get("decision"),
                    "is_mock": sub.get("is_mock") is True,
                    "has_partial_mock": sub.get("has_partial_mock") is True,
                }
            )
    for key in preferred_keys:
        if key == "market_competitor":
            continue
        section = by_key.get(key)
        if section is None:
            continue
        key_findings.append(
            {
                "title": section["title"],
                "conclusion": section["decision"],
                "is_mock": section["is_mock"],
                "has_partial_mock": section.get("has_partial_mock") is True,
            }
        )
    if len(key_findings) < 3:
        for section in sections:
            if section["key"] in preferred_keys:
                continue
            key_findings.append(
                {
                    "title": section["title"],
                    "conclusion": section["decision"],
                    "is_mock": section["is_mock"],
                    "has_partial_mock": section.get("has_partial_mock") is True,
                }
            )
            if len(key_findings) >= 3:
                break
    key_findings = key_findings[:3]
    this_week = actions[0] if actions else None
    return {
        "report_period": f"近{req.analysis_days}天分析／{req.campaign_days}天投放",
        "strategic_thesis": (
            f"围绕{req.initial_audience}，先用自然内容筛选“场景痛点、产品证据、对比决策”素材，"
            f"再以{GOAL_LABELS[req.goal]}为目标通过搜索承接与信息流放大。"
        ),
        "data_confidence": data_confidence,
        "mock_seed": seed,
        "budget_focus": {
            "total_cny": round(req.total_budget_cny),
            "organic_cny": budget.get("organic_content_cny"),
            "spotlight_cny": budget.get("spotlight_cny"),
        },
        "key_findings": key_findings[:3],
        "this_week_action": (
            {
                "priority": this_week.get("priority"),
                "title": this_week.get("title"),
                "why": this_week.get("why"),
                "timeline": this_week.get("timeline"),
                "budget_cny": this_week.get("budget_cny"),
                "budget_kind": this_week.get("budget_kind"),
                "budget_label": this_week.get("budget_label"),
            }
            if this_week
            else None
        ),
        "priority_actions": [
            {
                "priority": row["priority"],
                "title": row["title"],
                "timeline": row["timeline"],
                "budget_cny": row.get("budget_cny"),
                "budget_kind": row.get("budget_kind"),
                "budget_label": row.get("budget_label"),
                "campaign_budget_cny": row.get("campaign_budget_cny"),
                "keywords": row.get("keywords") or [],
                "success_metrics": row.get("success_metrics") or [],
            }
            for row in actions[:3]
        ],
        "gap_count": len(gaps),
        "evidence_gaps": [
            {
                "field": gap.field,
                "impact": gap.impact,
                "recommended_source": gap.recommended_source,
            }
            for gap in gaps
        ],
        "agent_decision_count": agent_count,
        "agent_ungrounded_count": len(alerts),
        "agent_grounding_alerts": alerts,
    }


def build_audience_section(req: CampaignRequest, modules: dict[str, Any]) -> dict[str, Any]:
    module2 = modules["module_2_audience_content"]
    persona = module2.get("persona") or {}
    directions = module2.get("content_directions") or []
    topics = module2.get("topics") or []
    screening = module2.get("material_screening") or module2.get("paid_material_gate") or {}
    knowledge = module2.get("knowledge_targeting") or {}
    topic_titles = [t.get("title_template") for t in topics if t.get("title_template")]
    nested_tags = persona.get("targeting_tags") if isinstance(persona.get("targeting_tags"), dict) else {}
    interest = list(nested_tags.get("interest_tags") or [])
    behavior_tags = list(nested_tags.get("behavior_tags") or [])
    crowds = list(nested_tags.get("crowd_packages") or [])
    flat_tags = persona.get("targeting_tags_to_validate") or [*interest, *behavior_tags, *crowds]
    demographic = persona.get("demographic")
    if isinstance(demographic, str):
        demographic_text = demographic
        demographic_list = [demographic] if demographic else []
    else:
        demographic_list = list(demographic or [])
        demographic_text = "；".join(demographic_list) or req.initial_audience
    behavioral = list(persona.get("behavioral") or [])
    psychological = list(
        persona.get("psychological") or persona.get("psychographic") or []
    )
    thresholds = screening.get("prototype_thresholds") or {}
    ctr = screening.get("ctr_percent") or thresholds.get("ctr_percent") or 10
    eng = (
        screening.get("engagement_rate_percent")
        or thresholds.get("engagement_rate_percent")
        or 7
    )
    hours = screening.get("observation_hours") or thresholds.get("observation_hours") or 24
    actions: list[str] = []
    if topic_titles:
        actions.append(f"首发选题：「{topic_titles[0]}」")
        if len(topic_titles) > 1:
            actions.append(
                "并行准备：「" + "」「".join(topic_titles[1:3]) + "」"
            )
    else:
        actions.append("补充选题证据后按场景痛点／产品证据／对比决策各发1篇")
    if interest[:3]:
        actions.append(f"兴趣标签先测：{'、'.join(str(t) for t in interest[:3])}")
    elif flat_tags:
        actions.append(f"定向先小流量验证标签：{'、'.join(str(t) for t in flat_tags[:5])}")
    else:
        actions.append("聚光定向先用兴趣/场景标签小流量验证，再扩人群包")
    actions.append(
        f"自然笔记发布{hours}小时内 CTR>{ctr}% 且互动率>{eng}% 再进入付费放大"
    )
    return {
        "key": "audience",
        "chapter_number": 2,
        "title": "目标用户精准画像",
        "decision": (
            f"围绕「{demographic_list[0] if demographic_list else req.initial_audience}」优先测试"
            f"{len(directions)}个内容方向，输出{len(topics)}个选题；"
            f"知识库命中剧本「{knowledge.get('playbook_title') or '通用'}」，"
            f"定向标签待后台核验。"
        ),
        "data_explanation": [
            f"人口属性：{demographic_text}",
            f"行为属性：{'；'.join(behavioral) or '待补充'}",
            f"心理属性：{'；'.join(psychological) or '待补充'}",
            f"定价带：{persona.get('price_band') or f'{req.currency} {req.price_min:g}–{req.price_max:g}'}",
            f"知识库标签：兴趣{len(interest)} / 行为{len(behavior_tags)} / 人群包{len(crowds)}",
        ],
        "analysis": [
            "内容方向双评分："
            + "；".join(
                f"{d.get('name') or d.get('direction')} 自然{d.get('organic_score')}/投流{d.get('paid_score')}"
                for d in directions
            ),
            screening.get("rule_text")
            or f"投流筛选：发布{hours}小时 CTR>{ctr}% 且互动率>{eng}%。",
            persona.get("tag_status")
            or knowledge.get("warning")
            or "定向标签为知识库候选，须在聚光后台核对。",
        ],
        "actions": actions,
        "success_metrics": [
            "每个内容方向至少1组可比较样本",
            "定向包点击成本不超过止损线",
            f"进入投流池的笔记满足 CTR>{ctr}% 且互动率>{eng}%",
        ],
        "evidence_boundary": (
            knowledge.get("warning")
            or "画像与选题在缺少评论聚合时偏框架输出；知识库标签不是账户真实可投清单。"
        ),
        "is_mock": False,
        "has_partial_mock": False,
        "mock_seed": None,
        "warning": knowledge.get("warning"),
        "visuals": {
            "metric_cards": [
                {"label": "内容方向", "value": len(directions), "unit": "个"},
                {"label": "爆款选题", "value": len(topics), "unit": "个"},
                {"label": "兴趣标签", "value": len(interest), "unit": "个"},
                {"label": "人群包", "value": len(crowds), "unit": "个"},
            ],
            "persona": {
                "demographic": demographic_list,
                "behavioral": behavioral,
                "psychological": psychological,
                "price_band": persona.get("price_band"),
            },
            "targeting_tags": {
                "interest_tags": interest,
                "behavior_tags": behavior_tags,
                "crowd_packages": crowds,
            },
            "tag_status": persona.get("tag_status") or knowledge.get("warning"),
            "knowledge_targeting": knowledge,
            "topics": topics,
            "directions": directions,
            "material_screening": {
                "observation_hours": hours,
                "ctr_percent": ctr,
                "engagement_rate_percent": eng,
                "rule_text": screening.get("rule_text")
                or f"发布{hours}小时内 CTR>{ctr}% 且互动率>{eng}%",
                "warning": screening.get("warning"),
            },
        },
    }


def build_keyword_strategy_section(
    req: CampaignRequest, modules: dict[str, Any]
) -> dict[str, Any]:
    """模块6专项：三级词库 / 布局与投放比例 / 热搜跟进。"""
    module6 = modules.get("module_6_keyword_strategy") or {}
    levels = module6.get("keyword_levels") or {}
    core = list(levels.get("core") or [])
    long_tail = list(levels.get("long_tail") or [])
    blue = list(
        levels.get("blue_ocean")
        or levels.get("blue_ocean_candidates")
        or []
    )
    layout = module6.get("layout") or {}
    layout_plan = layout.get("layout_plan") or {}
    layout_rule = layout.get("layout_rule") or {
        "title": layout.get("title"),
        "body": layout.get("body"),
        "tags": layout.get("tags"),
    }
    paid_mix = layout.get("paid_mix") or module6.get("level_budget_split") or {}
    split = module6.get("level_budget_split") or {
        "core": paid_mix.get("core", 0.30),
        "long_tail": paid_mix.get("long_tail", 0.50),
        "blue_ocean": paid_mix.get("blue_ocean_test") or paid_mix.get("blue_ocean") or 0.20,
    }
    trending = module6.get("trending_monitor") or {}
    scored = list(trending.get("scored_keywords") or [])
    rising = list(trending.get("rising_keywords") or [])
    if not rising:
        rising = [
            row for row in scored
            if row.get("recommendation") == "跟进" or row.get("action") == "可跟进测试"
        ]
    inputs = module6.get("inputs") or {}
    follow_n = len(rising)
    actions = [
        f"核心词优先落标题/标签：{'、'.join(str(x) for x in core[:3]) or '待补'}",
        f"长尾词铺正文与搜索计划：{'、'.join(str(x) for x in long_tail[:4]) or '待补'}",
        (
            f"蓝海词仅小预算验证：{'、'.join(str(x) for x in blue[:3])}"
            if blue
            else "蓝海词缺口：需搜索量/竞争度校准后再补"
        ),
        (
            f"布局示例：{layout_plan['example']}"
            if layout_plan.get("example")
            else "按标题1主词 / 正文2–4相关词 / 标签3–6组合落词"
        ),
        (
            f"热搜跟进：{'、'.join(str(r.get('keyword')) for r in rising[:3])}"
            if rising
            else (trending.get("how_to_supply") or "暂无上升热搜，先粘贴合规趋势词再评分")
        ),
    ]
    return {
        "key": "keyword_strategy",
        "chapter_number": 3,
        "title": "关键词策略",
        "decision": (
            f"基于「{inputs.get('product_name') or req.product_name} / "
            f"{'、'.join((inputs.get('selling_points') or req.selling_points or [])[:2])}」"
            f"与赛道主题生成三级词库：核心{len(core)} / 长尾{len(long_tail)} / 蓝海{len(blue)}；"
            f"层级投放建议 "
            f"核心{float(split.get('core') or 0):.0%} / "
            f"长尾{float(split.get('long_tail') or 0):.0%} / "
            f"蓝海{float(split.get('blue_ocean') or 0):.0%}；"
            f"热搜可跟进{follow_n}条。"
        ),
        "data_explanation": [
            f"输入：产品「{inputs.get('product_name') or req.product_name}」，"
            f"卖点「{'、'.join((inputs.get('selling_points') or req.selling_points or [])[:4])}」，"
            f"品类「{inputs.get('category') or req.category}」。",
            module6.get("status") or "词库已按知识库笔记与品牌种子分层",
            module6.get("keyword_pipeline") or "知识库抽词→去重分层",
            (
                f"赛道主题种子：{'、'.join(str(x) for x in (inputs.get('from_module1_themes') or [])[:5])}"
                if inputs.get("from_module1_themes")
                else "模块1主题种子不足时以降级品牌词补齐"
            ),
            trending.get("status") or "热搜监控待接入",
            trending.get("data_source_note")
            or "无官方实时热搜 API 时仅用合规导入/粘贴词评分",
        ],
        "analysis": [
            f"核心词：{'、'.join(str(x) for x in core[:6]) or '待补'}",
            f"长尾词：{'、'.join(str(x) for x in long_tail[:8]) or '待补'}",
            f"蓝海待验证：{'、'.join(str(x) for x in blue[:6]) or '待补'}（需搜索量验证）",
            (
                f"布局：标题「{layout_rule.get('title') or '—'}」；"
                f"正文「{layout_rule.get('body') or '—'}」；"
                f"标签「{layout_rule.get('tags') or '—'}」"
            ),
            (
                f"层级投放比例：核心{float(split.get('core') or 0):.0%} / "
                f"长尾{float(split.get('long_tail') or 0):.0%} / "
                f"蓝海试探{float(split.get('blue_ocean') or 0):.0%}"
            ),
            trending.get("decision_rule") or "热搜按四维评分决定跟进/观察/不跟进",
        ],
        "actions": actions,
        "success_metrics": [
            "三级词库跨层无重复且数量达标",
            "标题/正文/标签按布局落词可抽检",
            "跟进热搜完成小预算内容验证后再放量",
        ],
        "evidence_boundary": (
            (trending.get("warning") + "；" if trending.get("warning") else "")
            + (module6.get("status") or "蓝海与热搜均需证据校准，禁止写成已验证结论。")
        ),
        "is_mock": bool(trending.get("input_mode") == "mock_demo"),
        "has_partial_mock": bool(
            scored and any(row.get("is_mock") for row in scored)
        ),
        "mock_seed": next((row.get("mock_seed") for row in scored if row.get("mock_seed")), None),
        "warning": trending.get("warning"),
        "visuals": {
            "metric_cards": [
                {"label": "核心词", "value": len(core), "unit": "个"},
                {"label": "长尾词", "value": len(long_tail), "unit": "个"},
                {"label": "蓝海待验证", "value": len(blue), "unit": "个"},
                {
                    "label": "层级配比",
                    "value": (
                        f"{int(round(float(split.get('core') or 0)*10))}:"
                        f"{int(round(float(split.get('long_tail') or 0)*10))}:"
                        f"{int(round(float(split.get('blue_ocean') or 0)*10))}"
                    ),
                    "hint": "核心:长尾:蓝海",
                },
                {"label": "热搜可跟进", "value": follow_n, "unit": "条"},
            ],
            "inputs": inputs,
            "core_keywords": core,
            "long_tail_keywords": long_tail,
            "blue_ocean_keywords": blue,
            "layout_rule": layout_rule,
            "layout_plan": layout_plan,
            "frequency_guide": layout.get("frequency_guide") or {},
            "level_budget_split": split,
            "paid_mix": paid_mix,
            "trending_monitor": trending,
            "trending_rows": scored,
            "rising_keywords": rising,
            "pipeline": module6.get("keyword_pipeline"),
            "status": module6.get("status"),
        },
    }


def build_creator_keyword_section(req: CampaignRequest, modules: dict[str, Any]) -> dict[str, Any]:
    module3 = modules["module_3_keyword_creator"]
    module6 = modules.get("module_6_keyword_strategy") or {}
    kw_ref = module3.get("keyword_strategy_ref") or {}
    levels = kw_ref.get("levels") or module6.get("keyword_levels") or {}
    creators = module3.get("creator_recommendations_20") or module3.get("creator_candidates") or []
    real = [c for c in creators if c.get("followers") is not None and c.get("is_mock") is not True]
    mock = [c for c in creators if c.get("is_mock") is True]
    dual = module3.get("dual_track_keyword_library") or {}
    organic = dual.get("organic_traffic") or {}
    # 承接关键词策略：三级词以 M6 为准，覆盖自然词库展示
    if levels.get("core") or levels.get("long_tail"):
        organic = {
            **organic,
            "core_keywords": list(levels.get("core") or organic.get("core_keywords") or []),
            "long_tail_keywords": list(
                levels.get("long_tail") or organic.get("long_tail_keywords") or []
            ),
            "blue_ocean_candidates_to_validate": list(
                levels.get("blue_ocean")
                or levels.get("blue_ocean_candidates")
                or organic.get("blue_ocean_candidates_to_validate")
                or []
            ),
            "usage": (
                "已承接「关键词策略」三级词库；此处用于达人匹配与聚光双轨出价，不再另起互斥词表"
            ),
        }
    spotlight = dual.get("spotlight_paid") or {}
    search_kw_rows = (spotlight.get("search_promotion") or {}).get("keywords") or []
    feed_kw_rows = (spotlight.get("feed_interest") or {}).get("keywords") or []
    layout_plan = (
        kw_ref.get("layout_plan")
        or organic.get("layout_plan")
        or (module6.get("layout") or {}).get("layout_plan")
        or {}
    )
    search_n = len(search_kw_rows)
    feed_n = len(feed_kw_rows)
    top_names = [
        row.get("creator_name") or row.get("name")
        for row in real[:3]
        if row.get("creator_name") or row.get("name")
    ]
    rising_follow = list(kw_ref.get("rising_follow") or [])
    kw_labels: list[str] = []
    for item in search_kw_rows[:4]:
        if not isinstance(item, dict) or not item.get("keyword"):
            continue
        bid = item.get("suggested_bid_range") or {}
        low = _bid_money(bid.get("low_cny_per_click"))
        high = _bid_money(bid.get("high_cny_per_click"))
        if low or high:
            kw_labels.append(f"{item['keyword']}（{low or '?'}–{high or '?'}）")
        else:
            kw_labels.append(str(item["keyword"]))
    if not kw_labels:
        fallback = levels.get("long_tail") or []
        kw_labels = [str(k) for k in fallback[:4]]

    feed_labels = []
    for item in feed_kw_rows[:3]:
        if not isinstance(item, dict):
            continue
        word = item.get("interest_word") or item.get("keyword")
        if not word:
            continue
        bid = item.get("suggested_bid_range") or {}
        low = _bid_money(bid.get("low_cny_per_click"))
        high = _bid_money(bid.get("high_cny_per_click"))
        feed_labels.append(f"{word}（{low or '?'}–{high or '?'}）" if low or high else str(word))

    actions: list[str] = [
        "已承接关键词策略三级词库与布局方案，聚光词包不得另起冲突词表",
    ]
    if rising_follow:
        actions.append(f"热搜跟进词优先给到达人brief：{'、'.join(str(x) for x in rising_follow[:3])}")
    if top_names:
        actions.append(f"优先复核达人：{'、'.join(top_names)}（未复核前不得下单）")
    elif mock and not real:
        actions.append("当前仅有 Mock 达人：导入真实 CSV／蒲公英名单前只保留分层槽位，不得采购")
    else:
        actions.append("导入达人CSV或关闭Mock后只保留分层槽位")
    if layout_plan.get("example"):
        actions.append(f"达人笔记落词：{layout_plan['example']}")
    if kw_labels:
        actions.append(f"聚光搜索推广词先行：{'、'.join(kw_labels)}")
    if feed_labels:
        actions.append(f"信息流兴趣词分计划：{'、'.join(feed_labels)}")
    if not kw_labels and not feed_labels:
        actions.append("搜索高意向词与信息流兴趣词分计划投放")
    actions.append("每篇达人笔记单独设放大预算上限；蓝海词需搜索量验证后才能放量")

    organic_core_n = len(organic.get("core_keywords") or [])
    organic_long_n = len(organic.get("long_tail_keywords") or [])
    split = kw_ref.get("level_budget_split") or module6.get("level_budget_split") or {}

    return {
        "key": "creator_keyword",
        "chapter_number": 4,
        "title": "关键词与达人匹配",
        "decision": (
            f"已承接关键词策略（核心{organic_core_n}/长尾{organic_long_n}）→ "
            f"聚光搜索{search_n}个、信息流兴趣{feed_n}个"
            + (f"；热搜跟进{len(rising_follow)}条" if rising_follow else "")
            + (f"（搜索示例：{'、'.join(kw_labels[:2])}）" if kw_labels else "")
            + f"；达人侧真实候选{len(real)}位"
            + (f"，优先复核{'、'.join(top_names)}" if top_names else "")
            + (f"，Mock演示{len(mock)}位" if mock else "")
            + "，未复核前不得下单。"
        ),
        "data_explanation": [
            kw_ref.get("note") or "聚光双轨与达人匹配承接关键词策略词库",
            module3.get("creator_data_status") or "达人状态未提供",
            dual.get("status") or "双轨词库已按上游词库生成出价",
            spotlight.get("bid_note")
            or "出价区间按历史加权CPC×意向倍率带；上线以账户实时建议价校准。",
            layout_plan.get("example") or organic.get("usage") or "达人笔记按上游布局落词。",
        ],
        "analysis": [
            "关键词策略为规范词库；本模块只做聚光出价词转换与达人匹配",
            (
                f"层级投放承接：核心{float(split.get('core') or 0):.0%} / "
                f"长尾{float(split.get('long_tail') or 0):.0%} / "
                f"蓝海{float(split.get('blue_ocean') or 0):.0%}"
                if split
                else "层级投放比例承接关键词策略"
            ),
            "聚光搜索推广词优先高意向长尾；信息流兴趣词覆盖泛需求",
            "达人分层预算可先定，名单必须来自CSV/蒲公英",
            "蓝海词与热搜跟进词需验证后才能放量",
        ],
        "actions": actions,
        "success_metrics": [
            "与关键词策略词表差集为空（无另起词）",
            "真实达人复核完成率100%",
            "搜索计划跑出可比较CPA",
            "达人笔记标题/标签按上游布局落词",
        ],
        "evidence_boundary": (
            "模拟数据（Mock）：达人仅用于分层演示，不是推荐名单。"
            if mock and not real
            else (
                "含部分 Mock 达人：真实候选可复核，Mock 不得采购。"
                if mock
                else "达人名单来自用户导入或授权库，下单前仍需人工复核。"
            )
        ),
        "is_mock": bool(mock) and not real,
        "has_partial_mock": bool(mock) and bool(real),
        "mock_seed": next((c.get("mock_seed") for c in mock if c.get("mock_seed")), None),
        "warning": "含Mock达人时不得直接采购" if mock else None,
        "visuals": {
            "metric_cards": [
                {"label": "承接核心词", "value": organic_core_n, "unit": "个"},
                {"label": "承接长尾词", "value": organic_long_n, "unit": "个"},
                {"label": "搜索推广词", "value": search_n, "unit": "个"},
                {"label": "信息流兴趣词", "value": feed_n, "unit": "个"},
                {"label": "真实达人", "value": len(real), "unit": "位"},
                {"label": "Mock达人", "value": len(mock), "unit": "位"},
            ],
            "keyword_strategy_ref": kw_ref,
            "dual_track": dual,
            "organic_traffic": organic,
            "layout_plan": layout_plan,
            "layout_rule": organic.get("layout_rule")
            or (module6.get("layout") or {}).get("layout_rule")
            or {},
            "bid_note": spotlight.get("bid_note"),
            "creator_tier_plan": module3.get("creator_tier_plan"),
            "rising_follow": rising_follow,
            "top_creators": [
                {
                    "name": row.get("creator_name") or row.get("name"),
                    "tier": row.get("tier"),
                    "followers": row.get("followers"),
                    "avg_interactions": row.get("avg_interactions") or row.get("average_interactions"),
                    "quote_cny": row.get("quote_cny"),
                    "audience_match_score": row.get("audience_match_score"),
                    "past_paid_effect": row.get("past_paid_effect") or row.get("paid_effect_notes"),
                }
                for row in (real + mock)[:20]
            ],
            "search_keywords": search_kw_rows,
            "feed_keywords": feed_kw_rows,
        },
    }


def build_spotlight_decision_section(
    req: CampaignRequest,
    modules: dict[str, Any],
    *,
    operator_playbook: list[dict[str, Any]] | None = None,
    operational_risk_playbook: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """模块4专项：账户结构 / 定向包 / 出价节奏 / 搜推联动 / 预估风控 / 投手执行方案。"""
    module4 = modules.get("module_4_spotlight_decision") or {}
    module1 = modules.get("module_1_market_competitor") or {}
    inputs = module4.get("inputs") or {}
    account = module4.get("account_structure") or {}
    plans = account.get("plans") or account.get("campaigns") or []
    packages = module4.get("targeting_packages") or []
    bidding = module4.get("bidding") or {}
    split = module4.get("search_feed_split") or {}
    schedules = module4.get("daily_schedules") or {}
    slots = schedules.get("slots") or []
    forecast = module4.get("forecast") or {}
    risk_playbook = module4.get("risk_playbook") or []
    compliance_gate = module4.get("content_audit_gate") or (
        (module4.get("account_structure") or {}).get("compliance_gate") or {}
    )
    spotlight_market = module1.get("spotlight_market") or {}
    ctr_row = spotlight_market.get("average_ctr") or {}
    cpc_row = spotlight_market.get("average_cpc") or {}
    cpa_row = spotlight_market.get("conversion_cost") or {}

    goal_label = inputs.get("promotion_goal") or GOAL_LABELS.get(req.goal, req.goal)
    budget_cny = inputs.get("spotlight_budget_cny")
    if budget_cny is None:
        budget_cny = (modules.get("module_5_budget_pacing") or {}).get("budget", {}).get(
            "spotlight_cny"
        )
    days = inputs.get("campaign_days") or req.campaign_days
    search_ratio = split.get("search")
    feed_ratio = split.get("feed")
    split_text = (
        f"搜索{float(search_ratio):.0%} / 信息流{float(feed_ratio):.0%}"
        if isinstance(search_ratio, (int, float)) and isinstance(feed_ratio, (int, float))
        else "搜索/信息流配比待校准"
    )
    plan_text = "、".join(
        f"{row.get('name')}（{float(row.get('budget_ratio') or row.get('budget_share') or 0):.0%}）"
        for row in plans
        if row.get("name")
    ) or "待生成计划"
    package_text = "、".join(
        f"{row.get('name') or row.get('package')}（"
        f"{float(row.get('ratio') or row.get('budget_share') or 0):.0%}）"
        for row in packages
        if row.get("name") or row.get("package")
    ) or "精准/宽/达人相似三包"
    cold = bidding.get("cold_start")
    if isinstance(cold, dict):
        bid_low = _bid_money(cold.get("bid_low_cny"))
        bid_high = _bid_money(cold.get("bid_high_cny"))
        bid_text = (
            f"{cold.get('method') or '稳定成本出价'}"
            + (f"：{bid_low}–{bid_high}" if bid_low or bid_high else "")
        )
        scaling_rules = list(bidding.get("scaling_rules") or [])
        if bidding.get("scale_rule") and bidding["scale_rule"] not in scaling_rules:
            scaling_rules.insert(0, bidding["scale_rule"])
    else:
        bid_text = str(cold or bidding.get("scale_rule") or "出价待账户建议价校准")
        scaling_rules = [
            rule
            for rule in (bidding.get("scaling_rules") or [bidding.get("scale_rule")])
            if rule
        ]
    probe = (forecast.get("test_bandwidth") or {}).get("cold_start_budget_cny")
    stop = forecast.get("stop_loss") or {}
    roi = forecast.get("roi_range") or {}
    probe_money = _money(probe)

    normalized_packages = []
    for row in packages:
        if not isinstance(row, dict):
            continue
        share = row.get("budget_share")
        if share is None:
            share = row.get("ratio")
        expansion = row.get("smart_expansion")
        if expansion is None:
            expansion = row.get("expansion")
        normalized_packages.append(
            {
                **row,
                "name": row.get("name") or row.get("package") or "定向包",
                "package": row.get("package") or row.get("name") or "定向包",
                "budget_share": share,
                "ratio": share,
                "applicable_stage": row.get("applicable_stage") or row.get("stage") or "—",
                "stage": row.get("stage") or row.get("applicable_stage") or "—",
                "smart_expansion": bool(expansion),
                "expansion": bool(expansion),
                "audience_desc": row.get("audience_desc") or row.get("desc") or "待账户核对",
            }
        )

    normalized_plans = []
    for row in plans:
        if not isinstance(row, dict):
            continue
        share = row.get("budget_ratio")
        if share is None:
            share = row.get("budget_share")
        normalized_plans.append(
            {
                **row,
                "name": row.get("name") or "计划",
                "budget_ratio": share,
                "budget_share": share,
                "objective": row.get("objective") or goal_label,
                "placement": row.get("placement") or "—",
            }
        )

    normalized_slots = []
    for row in slots:
        if not isinstance(row, dict):
            continue
        normalized_slots.append(
            {
                **row,
                "slot": row.get("slot") or row.get("time_range") or "—",
                "time_range": row.get("time_range") or row.get("slot") or "—",
                "role": row.get("role") or "高峰窗",
                "action": row.get("action") or "优先投放",
                "sample_note_count": row.get("sample_note_count") or row.get("note_count"),
            }
        )

    risk_rows = []
    for row in risk_playbook:
        if not isinstance(row, dict):
            continue
        risk_rows.append(
            {
                "problem": row.get("problem") or row.get("issue") or "投流问题",
                "issue": row.get("issue") or row.get("problem") or "投流问题",
                "symptom": row.get("symptom")
                or "；".join(row.get("diagnosis") or [])
                or "—",
                "response": row.get("response")
                or " → ".join(
                    [
                        "；".join(row.get("actions_0_2h") or [])[:80],
                        "；".join(row.get("actions_2_24h") or [])[:80],
                    ]
                ).strip(" →"),
                "diagnosis": row.get("diagnosis") or [],
                "actions_0_2h": row.get("actions_0_2h") or [],
                "actions_2_24h": row.get("actions_2_24h") or [],
                "stop_or_escalate": row.get("stop_or_escalate") or "",
                "owner": row.get("owner") or "",
            }
        )

    ctr_value = ctr_row.get("value")
    ctr_display = (
        round(float(ctr_value) * 100, 2)
        if isinstance(ctr_value, (int, float)) and float(ctr_value) <= 1
        else ctr_value
    )
    playbook = list(operator_playbook or [])
    if not playbook:
        playbook = build_action_plan(req, modules)
    ops_risk = list(operational_risk_playbook or [])
    if not ops_risk:
        for row in risk_rows:
            ops_risk.append(
                {
                    "issue": row.get("issue") or row.get("problem") or "投流问题",
                    "diagnosis": row.get("symptom")
                    or "；".join(row.get("diagnosis") or []),
                    "actions_0_2h": row.get("actions_0_2h") or [],
                    "actions_2_24h": row.get("actions_2_24h") or [],
                    "stop_or_escalate": row.get("stop_or_escalate"),
                    "owner": row.get("owner"),
                    "is_mock": False,
                }
            )

    actions = [
        f"按计划拆建：{plan_text}；单元命名遵循「{account.get('unit_naming') or account.get('unit_naming_rule') or '目标_渠道_定向包_素材方向_日期'}」。",
        f"定向三包按占比测试：{package_text}。",
        f"冷启动出价：{bid_text}；放量按「成本低于目标10%则提价5%」规则迭代。",
        f"搜推联动：{split_text}；{split.get('synergy_note') or '搜索承接后信息流二次触达'}。",
    ]
    if probe_money:
        actions.append(f"首轮探测预算{probe_money}做可比较测试，未达最小样本不放大全案。")
    for row in playbook[:3]:
        actions.append(
            f"{row.get('priority') or ''}｜{row.get('title') or ''}（{row.get('timeline') or ''} · {row.get('owner') or ''}）"
        )
    if risk_rows:
        actions.append(f"风控优先预案：{risk_rows[0]['issue']}（详见投流问题应对 SOP）。")
    if compliance_gate.get("block_new_creatives"):
        actions.insert(
            0,
            f"内容预审拦截：{compliance_gate.get('reason') or '高风险文案未改写前禁止进聚光创意池'}",
        )
    elif compliance_gate.get("require_human_review"):
        actions.insert(
            0,
            f"内容预审待复核：{compliance_gate.get('reason') or '中风险素材需人工确认后再放量'}",
        )
    playbook_summary = " → ".join(
        f"{row.get('priority')} {row.get('title')}" for row in playbook[:3] if row.get("title")
    )

    return {
        "key": "spotlight_decision",
        "chapter_number": 4,
        "title": "聚光投流前置决策",
        "decision": (
            f"聚光预算¥{int(round(budget_cny or 0)):,} / {days}天 / 目标「{goal_label}」："
            f"账户按「{plan_text}」搭建，定向{package_text}，{split_text}双轨，"
            f"冷启动{bid_text}"
            + (f"，探测预算{probe_money}" if probe_money else "")
            + "。"
            + (f" 投手执行：{playbook_summary}。" if playbook_summary else "")
        ),
        "data_explanation": [
            f"输入：聚光预算¥{int(round(budget_cny or 0)):,}，周期{days}天，推广目标{goal_label}。",
            account.get("hierarchy_logic")
            or "计划按推广目标/版位/定向类型划分。",
            account.get("creative_grouping")
            or account.get("creative_test")
            or "创意分组做标题/封面正交测试。",
            split.get("synergy_note") or f"搜推预算：{split_text}。",
            forecast.get("status") or "效果预估随证据完整度输出。",
            "本页含投手执行方案（P1–P3）与投流问题应对 SOP，按优先级落地。",
        ],
        "analysis": [
            f"账户结构：{plan_text}",
            f"定向组合：{package_text}",
            f"出价节奏：{bid_text}；{scaling_rules[0] if scaling_rules else '按观察窗调价'}",
            f"搜推联动：{split_text}",
            f"投手执行方案：{len(playbook)} 条优先级动作",
            f"风控预案：{len(risk_rows)} 条常见投流问题 SOP",
        ],
        "actions": actions,
        "success_metrics": [
            "搜索与信息流计划可比较、单元命名可追溯",
            "三套定向包完成首轮占比测试",
            "CPC/CPA 不高于止损线后再放量",
            *[
                metric
                for row in playbook[:2]
                for metric in (row.get("success_metrics") or [])[:1]
            ],
        ],
        "evidence_boundary": (
            schedules.get("warning")
            or "出价与 ROI 以账户实时建议价/真实 CVR 校准；缺证据时不承诺效果区间。"
            " 投手执行动作达到最小样本后依据真实成本继续、调整或停止。"
        ),
        "is_mock": False,
        "has_partial_mock": any(
            bool((row or {}).get("is_mock"))
            for row in (cpc_row, ctr_row, cpa_row)
            if isinstance(row, dict)
        ),
        "mock_seed": None,
        "warning": None,
        "visuals": {
            "metric_cards": [
                {"label": "聚光预算", "value": budget_cny, "unit": "CNY"},
                {"label": "投放周期", "value": days, "unit": "天"},
                {"label": "推广目标", "value": goal_label},
                {
                    "label": "探测预算",
                    "value": probe,
                    "unit": "CNY",
                    "hint": "非全案",
                },
                {
                    "label": "CTR参考",
                    "value": ctr_display,
                    "unit": "%" if isinstance(ctr_display, (int, float)) else (ctr_row.get("unit") or ""),
                    "is_mock": ctr_row.get("is_mock"),
                },
                {
                    "label": "止损CPC",
                    "value": stop.get("cpc_stop_cny"),
                    "unit": "CNY",
                },
            ],
            "inputs": {
                "spotlight_budget_cny": budget_cny,
                "campaign_days": days,
                "promotion_goal": goal_label,
            },
            "hierarchy_logic": account.get("hierarchy_logic"),
            "unit_naming": account.get("unit_naming") or account.get("unit_naming_rule"),
            "creative_test": account.get("creative_test"),
            "creative_grouping": account.get("creative_grouping"),
            "account_plans": normalized_plans,
            "targeting_packages": normalized_packages,
            "bidding": {
                "cold_start": cold if isinstance(cold, dict) else {"method": bid_text, "basis": ""},
                "scaling_rules": scaling_rules,
                "stop_loss": bidding.get("stop_loss") or stop.get("formula"),
            },
            "daily_slots": normalized_slots,
            "schedule_warning": schedules.get("warning"),
            "budget_share": {"search_ratio": search_ratio, "feed_ratio": feed_ratio},
            "synergy_note": split.get("synergy_note"),
            "forecast": {
                "status": forecast.get("status"),
                "ctr": ctr_display,
                "cpc": cpc_row.get("value"),
                "cpa": cpa_row.get("value"),
                "cvr_note": "CVR/ROI 仅在有完整基准时输出",
                "roi_point": (roi or {}).get("point_estimate"),
                "roi_band": (roi or {}).get("band"),
                "probe_budget_cny": probe,
                "stop_loss_cpc": stop.get("cpc_stop_cny"),
                "stop_loss_cpa": stop.get("cpa_stop_cny"),
                "test_bandwidth": forecast.get("test_bandwidth"),
            },
            "risk_playbook": risk_rows,
            "operator_playbook": playbook,
            "operational_risk_playbook": ops_risk,
            "content_audit_gate": compliance_gate,
        },
    }


def build_budget_section(req: CampaignRequest, modules: dict[str, Any]) -> dict[str, Any]:
    from tools.budget import (
        all_goal_split_matrix,
        build_emergency_adjustments,
        build_organic_paid_synergy,
        goal_split_guide,
    )

    module5 = modules["module_5_budget_pacing"]
    budget = module5.get("budget") or {}
    phases = module5.get("phases") or []
    forecast = modules["module_4_spotlight_decision"].get("forecast") or {}
    probe = (forecast.get("test_bandwidth") or {}).get("cold_start_budget_cny")
    probe_money = _money(probe)
    spotlight_money = _money(budget.get("spotlight_cny"))
    organic_money = _money(budget.get("organic_content_cny"))
    split = goal_split_guide(req.goal)
    ratio_label = budget.get("ratio_label") or split["ratio_label"]
    split_rationale = budget.get("split_rationale") or split["rationale"]
    organic_ratio = float(budget.get("organic_ratio") if budget.get("organic_ratio") is not None else split["organic_ratio"])
    spotlight_ratio = float(
        budget.get("spotlight_ratio") if budget.get("spotlight_ratio") is not None else split["paid_ratio"]
    )
    matrix = budget.get("goal_split_matrix") or all_goal_split_matrix()
    phase_lines = []
    for phase in phases:
        name = phase.get("name") or phase.get("phase") or "阶段"
        share = phase.get("budget_ratio") or phase.get("ratio") or phase.get("paid_ratio")
        summary = phase.get("summary") or phase.get("action") or ""
        day_range = phase.get("day_range") or (f"{phase.get('days')}天" if phase.get("days") else "")
        if isinstance(share, (int, float)):
            phase_lines.append(
                f"{name}（投流{float(share):.0%}{' · ' + day_range if day_range else ''}）：{summary}".rstrip("：")
            )
        else:
            phase_lines.append(f"{name}：{summary}" if summary else str(name))
    pacing_rule = module5.get("pacing_rule") or (
        "聚光预算按预热20% → 爆发60% → 长尾20% 分配；自然与聚光在各阶段协同推进。"
    )
    synergy = module5.get("organic_paid_synergy") or build_organic_paid_synergy(
        material_screening=(modules.get("module_2_audience_content") or {}).get("material_screening"),
        probe_budget_cny=probe,
        goal=req.goal,
    )
    emergency = module5.get("emergency_playbook") or build_emergency_adjustments(
        phases=phases,
        goal=req.goal,
        organic_budget_cny=budget.get("organic_content_cny"),
        paid_budget_cny=budget.get("spotlight_cny"),
    )
    handoff = module5.get("upstream_handoff") or {}
    start_rule = (synergy.get("start_paid_when") or {}).get("rule_text") or ""
    actions = [
        (
            f"按目标「{GOAL_LABELS[req.goal]}」采用自然:聚光 = {ratio_label}"
            f"（自然{organic_ratio:.0%} / 聚光{spotlight_ratio:.0%}）："
            f"{organic_money or '—'} vs {spotlight_money or '—'}。"
        ),
        split_rationale,
        pacing_rule,
        start_rule or (module5.get("coordination") or "自然过门槛后再投流"),
        (
            f"全案聚光预算{spotlight_money or '待定'}；首轮探测预算{probe_money}"
            "（冷启动测试额，未达最小样本不放大）"
            if probe_money
            else "先完成自然过线筛选，再开聚光探测。"
        ),
        *phase_lines[:3],
        *[
            f"应急｜{row.get('scenario')}：{row.get('budget_adjustment')}"
            for row in emergency[:2]
        ],
    ]
    return {
        "key": "budget",
        "chapter_number": 6,
        "title": "全域预算与节奏规划",
        "decision": (
            f"目标「{GOAL_LABELS[req.goal]}」建议自然:聚光 = {ratio_label}："
            f"总预算¥{round(req.total_budget_cny):,} → "
            f"自然{organic_ratio:.0%}（{organic_money or '—'}）/ "
            f"聚光{spotlight_ratio:.0%}（{spotlight_money or '—'}）。"
            f"{split_rationale}"
            " 分阶段节奏：预热期自然铺量+小预算聚光（投流20%）→"
            "爆发期爆款放大+大规模放量（投流60%）→"
            "长尾期优质续投+搜索占位（投流20%）。"
            + (f" 启动投流门槛：{start_rule}" if start_rule else "")
            + (f" 首轮探测预算{probe_money}。" if probe_money else "")
        ),
        "data_explanation": [
            f"输入：总预算¥{round(req.total_budget_cny):,}，周期{req.campaign_days}天，"
            f"核心目标「{GOAL_LABELS[req.goal]}」。",
            f"本案配比 {ratio_label}（自然{organic_ratio:.0%} : 聚光{spotlight_ratio:.0%}）。",
            split_rationale,
            f"金额：自然内容{organic_money or '—'}，聚光{spotlight_money or '—'}"
            + (f"；探测预算{probe_money}（非全案）" if probe_money else ""),
            pacing_rule,
            start_rule or "自然过门槛后再启动投流。",
            "对照表：转化/客资/直播 3:7；品牌曝光/互动 5:5；搜索增长 4:6。",
            handoff.get("note") or "本页承接赛道、画像、关键词、达人与聚光前置结果。",
        ],
        "analysis": [
            f"总预算拆分依据目标「{GOAL_LABELS[req.goal]}」：{ratio_label}",
            split_rationale,
            pacing_rule,
            *phase_lines,
            synergy.get("principle") or "",
            *[
                f"{row.get('metric')} {row.get('threshold')} → {row.get('action')}"
                for row in (synergy.get("triggers") or [])
            ],
        ] or ["节奏待生成"],
        "actions": actions,
        "success_metrics": [
            "自然/聚光金额按目标配比落地并可追溯",
            "预热期完成可比较测试并筛出可放大素材",
            "爆发期只放大过门槛素材与定向",
            "长尾期完成搜索词占位与复盘入库",
            "未达预期时按应急方案完成预算与内容双向调整",
        ],
        "evidence_boundary": (
            "配比为目标默认建议档，可在护栏内微调；"
            "阶段占比以聚光（投流）预算为分母；探测预算≠全案投放预算；"
            "自然投流门槛需用品牌历史中位数校准。"
        ),
        "is_mock": False,
        "has_partial_mock": False,
        "mock_seed": None,
        "warning": None,
        "visuals": {
            "metric_cards": [
                {"label": "总预算", "value": req.total_budget_cny, "unit": "CNY"},
                {"label": "自然预算", "value": budget.get("organic_content_cny"), "unit": "CNY"},
                {"label": "聚光预算", "value": budget.get("spotlight_cny"), "unit": "CNY"},
                {
                    "label": "建议配比",
                    "value": ratio_label,
                    "hint": f"{GOAL_LABELS[req.goal]}",
                },
                {"label": "投放周期", "value": req.campaign_days, "unit": "天"},
                {"label": "探测预算", "value": probe, "unit": "CNY", "hint": "非全案"},
            ],
            "budget_split": {
                "goal": req.goal,
                "goal_label": GOAL_LABELS[req.goal],
                "ratio_label": ratio_label,
                "organic_ratio": organic_ratio,
                "spotlight_ratio": spotlight_ratio,
                "organic_cny": budget.get("organic_content_cny"),
                "spotlight_cny": budget.get("spotlight_cny"),
                "rationale": split_rationale,
                "campaign_days": req.campaign_days,
            },
            "goal_split_matrix": [
                {
                    **row,
                    "is_current": row.get("goal") == req.goal,
                }
                for row in matrix
            ],
            "pacing_rule": pacing_rule,
            "phases": phases,
            "probe_budget_cny": probe,
            "organic_paid_synergy": synergy,
            "emergency_playbook": emergency,
            "upstream_handoff": handoff,
        },
    }


def _agent_decision_blurb(engine_key: str, output: dict[str, Any]) -> str | None:
    """从已溯源 Agent output 抽出一句可进章节 decision 的摘要。"""
    if engine_key == "module_4_spotlight_decision":
        acc = output.get("account_structure") or {}
        campaigns = acc.get("campaigns") or []
        names = [
            row.get("name")
            for row in campaigns
            if isinstance(row, dict) and row.get("name")
        ]
        bidding = output.get("bidding") or {}
        cold = bidding.get("cold_start") or {}
        bid_part = ""
        if isinstance(cold, dict) and cold.get("bid_low_cny") is not None:
            high = cold.get("bid_high_cny")
            bid_part = f"；冷启动出价 ¥{cold['bid_low_cny']}" + (
                f"–¥{high}" if high is not None else ""
            )
        split = output.get("search_feed_split") or {}
        split_part = ""
        if isinstance(split.get("search"), (int, float)):
            split_part = (
                f"；搜索{float(split['search']):.0%}/"
                f"信息流{float(split.get('feed') or 0):.0%}"
            )
        if names:
            return f"账户结构：{'、'.join(names[:3])}{split_part}{bid_part}"
        return None
    if engine_key == "module_5_budget_pacing":
        split = output.get("budget_split") or {}
        if split.get("organic_budget_cny") is not None:
            return (
                f"预算拆分：自然¥{int(round(split['organic_budget_cny'])):,} / "
                f"聚光¥{int(round(split.get('paid_budget_cny') or 0)):,}"
            )
        return None
    if engine_key == "module_2_audience_content":
        topics = output.get("topics") or []
        titles: list[str] = []
        for item in topics[:2]:
            if isinstance(item, dict) and item.get("title_template"):
                titles.append(str(item["title_template"]))
            elif isinstance(item, str) and item.strip():
                titles.append(item.strip())
        if titles:
            return f"首推选题：{'；'.join(titles)}"
        return None
    if engine_key == "module_3_keyword_creator":
        creators = (
            output.get("creator_recommendations")
            or output.get("creators")
            or output.get("creator_candidates")
            or []
        )
        names = []
        for row in creators[:3]:
            if isinstance(row, dict):
                name = row.get("creator_name") or row.get("name")
                if name:
                    names.append(str(name))
            elif isinstance(row, str) and row.strip():
                names.append(row.strip())
        if names:
            return f"优先复核达人：{'、'.join(names)}"
        return None
    if engine_key == "module_6_keyword_strategy":
        levels = output.get("keyword_levels") or {}
        words = levels.get("long_tail") or levels.get("core") or []
        if isinstance(words, list) and words:
            sample = [str(w) for w in words[:3]]
            return f"关键词策略：{'、'.join(sample)}"
        return None
    if engine_key == "module_1_market_competitor":
        for key in ("strategic_conclusion", "decision_summary", "summary"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:180]
        return None
    for key in ("decision_summary", "summary", "strategic_conclusion"):
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:180]
    return None


def _annotate_sections_with_grounded_agents(
    sections: list[dict[str, Any]], modules: dict[str, Any]
) -> None:
    """溯源通过的 Agent：批注章节 decision，并前置人工复核动作。"""
    by_chapter = {section["chapter_number"]: section for section in sections}
    for engine_key, chapter_number in _AGENT_DECISION_CHAPTER.items():
        block = modules.get(engine_key)
        if not isinstance(block, dict) or block.get("decision_source") != "llm_agent":
            continue
        decision = block.get("agent_decision")
        if not isinstance(decision, dict):
            continue
        output = decision.get("output")
        if not isinstance(output, dict):
            continue
        blurb = _agent_decision_blurb(engine_key, output)
        target = by_chapter.get(chapter_number)
        if target is None or not blurb:
            continue
        baseline = target.get("decision") or ""
        if not target.get("decision_baseline"):
            target["decision_baseline"] = baseline
        label = AGENT_MODULE_LABELS.get(engine_key, engine_key)
        target["decision"] = f"【Agent 已溯源 · {label}】{blurb} ｜ 规则基线：{baseline}"
        reviews = output.get("human_review_items") or []
        actions = list(target.get("actions") or [])
        for item in reviews[:2]:
            if not isinstance(item, str) or not item.strip():
                continue
            note = f"人工复核：{item.strip()}"
            if note not in actions:
                actions.insert(0, note)
        target["actions"] = actions


def _assign_execution_badges(sections: list[dict[str, Any]]) -> None:
    """章节级「可执行 / 需复核」徽章。"""
    for section in sections:
        ungrounded = any(
            (view.get("decision_source") == "llm_agent_ungrounded")
            or ((view.get("grounding") or {}).get("passed") is False)
            for view in (section.get("agent_decision_views") or [])
        )
        needs_review = bool(
            section.get("is_mock")
            or section.get("has_partial_mock")
            or ungrounded
            or section.get("warning")
        )
        section["execution_badge"] = "需复核" if needs_review else "可执行"
        section["execution_status"] = "needs_review" if needs_review else "executable"


def build_report_view(
    req: CampaignRequest,
    modules: dict[str, Any],
    gaps: list[EvidenceGap],
    data_confidence: str,
    mock_subagents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from competitor_benchmark_board import build_competitor_benchmark_board
    from competitor_brief_synth import synthesize_competitor_benchmark_brief

    module1 = modules["module_1_market_competitor"]
    # 用户手写 brief 优先保留；自动合成 brief 才允许 DeepSeek Agent 覆写文案
    user_authored_brief = req.competitor_benchmark_brief is not None
    if not user_authored_brief and req.competitor_evidence:
        synth = synthesize_competitor_benchmark_brief(req, modules)
        if synth is not None:
            req = req.model_copy(update={"competitor_benchmark_brief": synth})
    # 投手执行方案并入聚光投流前置决策（不再单独成页）
    actions = build_action_plan(req, modules)
    operational_risk_playbook = []
    for row in modules["module_4_spotlight_decision"].get("risk_playbook") or []:
        demo = row.get("demo_scenario") or {}
        operational_risk_playbook.append(
            {
                "issue": row.get("issue", "未命名问题"),
                "diagnosis": demo.get("example_diagnosis") or "；".join(row.get("diagnosis") or []),
                "actions_0_2h": row.get("actions_0_2h") or [],
                "actions_2_24h": row.get("actions_2_24h") or [],
                "stop_or_escalate": row.get("stop_or_escalate"),
                "owner": row.get("owner"),
                "is_mock": demo.get("is_mock") is True,
                "mock_seed": demo.get("mock_seed"),
                "warning": demo.get("warning"),
            }
        )
    sections = [
        build_market_competitor_section(
            req, module1, modules.get("module_4_spotlight_decision")
        ),
        build_audience_section(req, modules),
        build_keyword_strategy_section(req, modules),
        build_creator_keyword_section(req, modules),
        build_spotlight_decision_section(
            req,
            modules,
            operator_playbook=actions,
            operational_risk_playbook=operational_risk_playbook,
        ),
        build_budget_section(req, modules),
    ]
    for index, section in enumerate(sections, start=1):
        section["chapter_number"] = index
        boundary = section.get("evidence_boundary") or ""
        if section.get("is_mock") and "模拟" not in boundary and "Mock" not in boundary:
            section["evidence_boundary"] = f"模拟数据（Mock）：{boundary}"
        elif section.get("has_partial_mock") and "部分 Mock" not in boundary:
            section["evidence_boundary"] = f"含部分 Mock：{boundary}"
    # 先降级未溯源 Agent，再生成可渲染视图（决策来源徽章依赖 decision_source）
    agent_grounding_alerts = apply_agent_grounding_policy(modules)
    # 把六个模块 Agent 的 agent_decision 转成可渲染视图，按 engine_key 挂到对应章节。
    # 同一章节可承载多个模块视图（如第 6 章同时含 module3/module6），用列表承载。
    sections_by_chapter = {section["chapter_number"]: section for section in sections}
    for engine_key, chapter_number in _AGENT_DECISION_CHAPTER.items():
        view = build_agent_decision_view(engine_key, modules.get(engine_key) or {})
        if view is None:
            continue
        target = sections_by_chapter.get(chapter_number)
        if target is None:
            continue
        target.setdefault("agent_decision_views", []).append(view)
        # 兼容单视图键名：首个视图同时暴露为 agent_decision_view。
        if "agent_decision_view" not in target:
            target["agent_decision_view"] = view
    _annotate_sections_with_grounded_agents(sections, modules)
    _assign_execution_badges(sections)
    from tools.dashboard import build_dashboard_payload

    report_view = {
        "executive_summary": build_executive_summary(
            req,
            modules,
            gaps,
            data_confidence,
            sections,
            actions,
            agent_grounding_alerts=agent_grounding_alerts,
        ),
        "report_sections": sections,
        "benchmark_ssot": build_benchmark_ssot(
            [item.model_dump(mode="json") for item in req.benchmark_evidence]
        ),
        "action_plan": actions,
        "operational_risk_playbook": operational_risk_playbook,
        "bonus_modules": {
            "content_audit": modules.get("bonus_content_audit"),
            "ab_test": modules.get("bonus_ab_test"),
            "competitor_monitor": modules.get("bonus_competitor_monitor"),
        },
        "evidence_appendix": {
            "module_keys": [k for k in modules if not str(k).startswith("bonus_")],
            "bonus_module_keys": [k for k in modules if str(k).startswith("bonus_")],
            "evidence_gaps": [gap.model_dump(mode="json") for gap in gaps],
            "mock_subagents": mock_subagents or [],
            "instruction": "结构化证据用于追溯结论，默认折叠；不得替代报告正文。多子Agent Mock仅在缺口时注入。",
        },
        "competitor_benchmark_board": build_competitor_benchmark_board(
            req,
            modules,
            overlay_agent=not user_authored_brief,
            prefer_engine_competitor=not user_authored_brief,
        ),
    }
    report_view["dashboard"] = build_dashboard_payload(report_view, modules)
    report_view["addon_tools"] = build_addon_tools_view(report_view)
    return report_view


def build_addon_tools_view(report_view: dict[str, Any]) -> dict[str, Any]:
    """附加工具 sheet：看板集成 + 内容审核 + A/B + 竞品监控。"""
    bonus = report_view.get("bonus_modules") or {}
    dashboard = report_view.get("dashboard") or {}
    audit = bonus.get("content_audit") or {}
    ab_test = bonus.get("ab_test") or {}
    monitor = bonus.get("competitor_monitor") or {}
    return {
        "title": "附加工具",
        "subtitle": "数据看板、多模态内容审核、A/B 测试方案与竞品投放监控",
        "nav": [
            {"id": "addon-dashboard", "label": "数据看板集成"},
            {"id": "addon-audit", "label": "多模态内容审核"},
            {"id": "addon-ab", "label": "A/B测试方案生成"},
            {"id": "addon-monitor", "label": "竞品投放监控Agent"},
        ],
        "dashboard": {
            "title": "数据看板集成",
            "summary": dashboard.get("note")
            or "汇总六大模块决策、预算节奏、关键词分层与执行动作，支持刷新与导出。",
            "kpi_count": len(dashboard.get("kpis") or []),
            "panel_count": len(dashboard.get("module_panels") or []),
            "alert_count": len(dashboard.get("alerts") or []),
        },
        "content_audit": {
            "title": "多模态内容审核",
            "risk_level": audit.get("risk_level") or "low",
            "passed": audit.get("passed"),
            "finding_count": audit.get("finding_count") or len(audit.get("findings") or []),
            "findings": list(audit.get("findings") or [])[:12],
            "pending_vision": [
                row
                for row in (audit.get("findings") or [])
                if str(row.get("status") or "").startswith("pending")
            ],
            "gate_application": audit.get("gate_application") or {},
            "evidence_boundary": audit.get("evidence_boundary") or "",
            "summary": (
                "文本按官方规则与违规台账预审；图片/视频仅标记待 OCR / 帧扫描，不伪造视觉结果。"
            ),
        },
        "ab_test": {
            "title": "A/B测试方案生成",
            "summary": ab_test.get("what_it_is")
            or "自动设计标题、封面、正文要点的 A/B 组合，并给出测试指标与判断标准。",
            "status_label": ab_test.get("status_label"),
            "matrix": list(ab_test.get("matrix") or [])[:12],
            "cell_count": ab_test.get("cell_count") or 0,
            "probe_budget_cny": ab_test.get("probe_budget_cny"),
            "budget_per_cell_cny": ab_test.get("budget_per_cell_cny"),
            "success_metrics": list(ab_test.get("success_metrics") or []),
            "decision_rule": ab_test.get("decision_rule") or "",
            "how_to_read": list(ab_test.get("how_to_read") or []),
            "human_review_items": list(ab_test.get("human_review_items") or []),
        },
        "competitor_monitor": {
            "title": "竞品投放监控Agent",
            "summary": (
                "对比竞品投放快照：出现新爆款或大规模投放信号时自动预警，并给出应对策略。"
            ),
            "status": monitor.get("status") or "baseline",
            "alerts": list(monitor.get("alerts") or [])[:10],
            "alert_count": monitor.get("alert_count") or len(monitor.get("alerts") or []),
            "viral_candidates": list(monitor.get("viral_candidates") or [])[:5],
            "playbook": list(monitor.get("playbook") or []),
            "snapshot": monitor.get("snapshot") or {},
            "evidence_boundary": monitor.get("evidence_boundary") or "",
        },
    }


def _markdown_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) or "- 暂无可用信息"


# ---------------------------------------------------------------------------
# 单 B 新增：Agent 决策方案 + 基准指标 SSOT 的 Markdown 渲染（纯字符串拼接，
# 不使用含反斜杠的 f-string，兼容既有文件风格）。
# ---------------------------------------------------------------------------
def _agent_cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, list):
        return "、".join(_agent_cell_text(item) for item in value)
    if isinstance(value, dict):
        return "；".join(f"{k}:{_agent_cell_text(v)}" for k, v in value.items())
    return str(value).replace("|", "/").replace("\n", " ")


def _render_agent_decision_views_md(views: list[dict[str, Any]]) -> str:
    if not views:
        return ""
    blocks: list[str] = []
    for view in views:
        lines: list[str] = [
            "",
            f"### Agent 决策方案（decision_source: {view.get('decision_source') or 'llm_agent'}）",
            "",
        ]
        grounding = view.get("grounding") or {}
        badge = grounding.get("badge") or ""
        mark = "✅" if grounding.get("passed") else "⚠️"
        head = f"> {mark} {view.get('module_label') or ''}｜溯源：{badge}"
        status = view.get("module_status") or {}
        if status.get("label"):
            head = head + f"｜模块状态：{status.get('label')}"
        steps = view.get("steps_used")
        if steps is not None:
            head = head + f"｜推理步数：{steps}"
        lines.append(head)
        for gap in (status.get("unresolved_gaps") or [])[:8]:
            lines.append(f"> - 未解决缺口：{_agent_cell_text(gap)}")
        for mismatch in grounding.get("mismatches") or []:
            if isinstance(mismatch, dict):
                lines.append(f"> - 未溯源：{mismatch.get('path')} = {mismatch.get('value')}")
            else:
                lines.append(f"> - 未溯源：{mismatch}")
        for section in view.get("sections") or []:
            lines.append("")
            lines.append(f"**{section.get('title') or ''}**")
            lines.append("")
            kind = section.get("kind")
            if kind == "table":
                columns = section.get("columns") or []
                lines.append("| " + " | ".join(str(c.get("label") or "") for c in columns) + " |")
                lines.append("| " + " | ".join("---" for _ in columns) + " |")
                for row in section.get("rows") or []:
                    cells = [_agent_cell_text(row.get(c.get("key"))) for c in columns]
                    lines.append("| " + " | ".join(cells) + " |")
            elif kind == "kv":
                for item in section.get("items") or []:
                    lines.append(f"- **{item.get('label') or ''}**：{_agent_cell_text(item.get('value'))}")
            elif kind == "list":
                for item in section.get("items") or []:
                    lines.append(f"- {_agent_cell_text(item)}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _render_benchmark_ssot_md(ssot: dict[str, Any]) -> str:
    groups = [g for g in (ssot.get("groups") or []) if g.get("conflict")]
    if not groups:
        return ""
    lines: list[str] = [
        "## 基准指标口径（单一事实源）",
        "",
        "以下同类基准指标存在多来源冲突，报告统一按口径选用；下游模块引用时须注明来源。",
        "",
        "| 指标类别 | 选用值 | 单位 | 选用来源 | 采集时间 | 证据等级 | 其他候选 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    escalations: list[str] = []
    for group in groups:
        selected = group.get("selected") or {}
        others = [c for c in (group.get("candidates") or []) if c is not selected]
        other_text = "；".join(
            f"{_agent_cell_text(c.get('value'))}（{_agent_cell_text(c.get('source_name'))}）"
            for c in others
        )
        # 同等级数值冲突 / 仅有 Mock 候选时不给选用值，改标人工裁决（治理规范 03/04）
        escalation = group.get("escalation") or group.get("note")
        value_cell = (
            _agent_cell_text(selected.get("value"))
            if selected
            else ("待人工裁决" if escalation else _agent_cell_text(None))
        )
        if escalation:
            escalations.append(f"{group.get('category') or ''}：{escalation}")
        lines.append(
            "| "
            + " | ".join(
                [
                    _agent_cell_text(group.get("category")),
                    value_cell,
                    _agent_cell_text(selected.get("unit")),
                    _agent_cell_text(selected.get("source_name")),
                    _agent_cell_text(selected.get("collected_at")),
                    _agent_cell_text(group.get("evidence_level")),
                    other_text,
                ]
            )
            + " |"
        )
    for item in escalations:
        lines.append("")
        lines.append(f"> ⚠️ {item}")
    lines.append("")
    lines.append(f"> 选用规则：{ssot.get('policy') or ''}")
    return "\n".join(lines)


def render_report_markdown(req: CampaignRequest, report_view: dict[str, Any]) -> str:
    summary = report_view["executive_summary"]
    budget = summary["budget_focus"]
    findings = "\n".join(
        f"- **{row['title']}**：{row['conclusion']}"
        + ("（模拟数据 Mock）" if row.get("is_mock") else "")
        for row in summary["key_findings"]
    )
    priority_actions = "\n".join(
        (
            f"- **{row['priority']}｜{row['title']}**：{row['timeline']}"
            + (
                f"；{row.get('budget_label') or '预算'}¥{row['budget_cny']:,.0f}"
                if isinstance(row.get("budget_cny"), (int, float))
                else ""
            )
            + (
                f"；全案聚光¥{row['campaign_budget_cny']:,.0f}"
                if row.get("budget_kind") == "probe"
                and isinstance(row.get("campaign_budget_cny"), (int, float))
                else ""
            )
            + (
                f"；词包：{'、'.join(row['keywords'][:3])}"
                if row.get("keywords")
                else ""
            )
        )
        for row in summary["priority_actions"]
    )
    chapter_blocks: list[str] = []
    chapter_names = {
        1: "第一章",
        2: "第二章",
        3: "第三章",
        4: "第四章",
        5: "第五章",
        6: "第六章",
    }
    for section in report_view["report_sections"]:
        if section.get("is_mock"):
            mock_line = (
                f"> 数据标识：模拟数据（Mock）；种子：`{section.get('mock_seed') or '未提供'}`。"
            )
        elif section.get("has_partial_mock"):
            mock_line = "> 数据标识：真实指标为主，含部分 Mock 情景字段。"
        else:
            mock_line = "> 数据标识：真实／公开／用户导入证据与明确数据缺口。"
        badge = section.get("execution_badge") or "可执行"
        subsection_blocks = ""
        for sub in section.get("subsections") or []:
            subsection_blocks += f"""
### {sub.get('title') or sub.get('key')}

**决策**：{sub.get('decision') or '—'}

{_markdown_list(sub.get('data_explanation') or [])}

{_markdown_list(sub.get('actions') or [])}
"""
        chapter_blocks.append(
            f"""## {chapter_names[section['chapter_number']]}｜{section['title']}

{mock_line}

> 执行状态：{badge}

### 决策结论

{section['decision']}

### 数据说明

{_markdown_list(section['data_explanation'])}

### 原因分析

{_markdown_list(section['analysis'])}

### 建议动作

{_markdown_list(section['actions'])}

### 验证指标

{_markdown_list(section['success_metrics'])}

### 证据边界

{section['evidence_boundary']}
{subsection_blocks}
"""
        )
        # 单 B 新增：章末追加该章 Agent 决策方案小节（无则为空，不影响既有输出）。
        agent_md = _render_agent_decision_views_md(section.get("agent_decision_views") or [])
        if agent_md:
            chapter_blocks[-1] = chapter_blocks[-1] + agent_md + "\n"
        if section.get("key") == "spotlight_decision":
            action_blocks = "\n\n".join(
                f"""#### {row['priority']}｜{row['title']}

- **为什么做**：{row['why']}
- **负责人**：{row['owner']}
- **时间**：{row['timeline']}
- **预算／资源**：{
                    (
                        f"{row.get('budget_label') or '探测预算'} ¥{row['budget_cny']:,.0f}"
                        + (
                            f"；全案聚光 ¥{row['campaign_budget_cny']:,.0f}"
                            if isinstance(row.get('campaign_budget_cny'), (int, float))
                            else ""
                        )
                    )
                    if isinstance(row.get('budget_cny'), (int, float)) and row.get('budget_kind') == 'probe'
                    else (
                        f"¥{row['budget_cny']:,.0f}"
                        if isinstance(row.get('budget_cny'), (int, float))
                        else '待证据确认'
                    )
                }
- **执行步骤**：{'；'.join(row['steps'])}
- **成功指标**：{'；'.join(row['success_metrics'])}
- **止损／升级**：{row['stop_condition']}
- **证据依赖**：{row['evidence_dependency']}
"""
                for row in report_view.get("action_plan") or []
            )
            risk_playbook_blocks = "\n\n".join(
                f"""#### {row['issue']}{'（Mock演示情景）' if row.get('is_mock') else ''}

- **判断依据**：{row['diagnosis']}
- **0–2小时动作**：{'；'.join(row['actions_0_2h'])}
- **2–24小时动作**：{'；'.join(row['actions_2_24h'])}
- **止损／升级**：{row['stop_or_escalate']}
- **负责人**：{row['owner']}
"""
                for row in report_view.get("operational_risk_playbook") or []
            )
            chapter_blocks[-1] = (
                chapter_blocks[-1]
                + f"""
### 投手执行方案

按优先级执行；达到最小样本后依据真实成本继续、调整或停止。

{action_blocks or '暂无执行动作。'}

### 投流问题应对

{risk_playbook_blocks or '当前没有可用的投流问题应对方案。'}
"""
            )
    gaps = report_view["evidence_appendix"]["evidence_gaps"]
    gap_lines = "\n".join(
        f"- **{row['field']}**：{row['impact']}；建议来源：{row['recommended_source']}"
        for row in gaps
    ) or "- 当前关键证据齐全。"
    seed_line = (
        f"- Mock种子：`{summary['mock_seed']}`（相同种子可复现同一组模拟报告）"
        if summary.get("mock_seed") else "- Mock种子：未启用"
    )
    gap_count = int(summary.get("gap_count") or 0)
    ungrounded = int(summary.get("agent_ungrounded_count") or 0)
    agent_count = int(summary.get("agent_decision_count") or 0)
    risk_lines: list[str] = [
        f"- 证据缺口数：{gap_count}",
        f"- 模块 Agent 决策数：{agent_count}",
    ]
    if ungrounded:
        risk_lines.append(
            f"- ⚠️ 数字未溯源模块：{ungrounded}（decision_source=llm_agent_ungrounded，须人工复核）"
        )
        for alert in summary.get("agent_grounding_alerts") or []:
            risk_lines.append(
                f"  - {alert.get('module_label') or alert.get('engine_key')}："
                f"{alert.get('mismatch_count', 0)} 处未溯源数字"
            )
    risk_banner = "\n".join(risk_lines)
    # 单 B 新增：基准指标 SSOT 冲突对比表（无冲突时为空字符串，不影响既有输出）。
    benchmark_md = _render_benchmark_ssot_md(report_view.get("benchmark_ssot") or {})
    this_week = summary.get("this_week_action") or {}
    this_week_md = (
        f"- **{this_week.get('priority') or 'P1'}｜{this_week.get('title')}**"
        f"（{this_week.get('timeline') or ''}）"
        if this_week.get("title")
        else "- 待生成"
    )
    bonus = report_view.get("bonus_modules") or {}
    audit = bonus.get("content_audit") or {}
    ab_test = bonus.get("ab_test") or {}
    monitor = bonus.get("competitor_monitor") or {}
    audit_lines = "\n".join(
        f"- [{row.get('severity')}] {row.get('message')}"
        for row in (audit.get("findings") or [])[:8]
    ) or "- 文本预审未发现高风险关键词"
    ab_sample = ((ab_test.get("matrix") or [{}])[0] or {})
    ab_lines = (
        f"- 说明：{ab_test.get('what_it_is') or '预热期 A/B 实验计划，不是效果结果'}\n"
        f"- 状态：{ab_test.get('status_label') or '仅实验计划'}\n"
        f"- 格子数：{ab_test.get('cell_count') or 0}；"
        f"单格最小点击：{ab_sample.get('min_clicks', '—')}；"
        f"每格探测预算：{ab_test.get('budget_per_cell_cny') if ab_test.get('budget_per_cell_cny') is not None else '—'}\n"
        f"- 示例格子：{ab_sample.get('cell_id') or '—'} → 标题「{ab_sample.get('title_text') or ab_sample.get('title_variant') or '—'}」"
        f" / 封面「{ab_sample.get('cover_text') or ab_sample.get('cover_variant') or '—'}」\n"
        f"- 判断标准：{'；'.join(ab_test.get('success_metrics') or [])}\n"
        f"- 决策规则：{ab_test.get('decision_rule') or ''}"
    )
    monitor_lines = "\n".join(
        f"- [{row.get('severity')}] {row.get('message')} → {row.get('response')}"
        for row in (monitor.get("alerts") or [])[:5]
    ) or "- 暂无竞品预警"
    return f"""# {req.brand_name}｜{req.product_name} 小红书全域投放分析报告

## 管理层决策摘要

### 一句话战略判断

{summary['strategic_thesis']}

### 报告口径

- 报告周期：{summary['report_period']}
- 数据可信度：{summary['data_confidence']}
- 总预算：¥{budget['total_cny']:,}
- 自然内容预算：¥{budget['organic_cny']:,}
- 聚光预算：¥{budget['spotlight_cny']:,}
{seed_line}
{risk_banner}

### 关键发现（最多3条）

{findings}

### 本周唯一动作

{this_week_md}

### 优先行动

{priority_actions}
{benchmark_md}
{'\n'.join(chapter_blocks)}

## 附加工具：数据看板 / 内容审核 / A/B / 竞品监控

### 数据看板集成

- KPI 数：{(report_view.get('addon_tools') or {}).get('dashboard', {}).get('kpi_count') or len((report_view.get('dashboard') or {}).get('kpis') or [])}
- 模块面板：{(report_view.get('addon_tools') or {}).get('dashboard', {}).get('panel_count') or len((report_view.get('dashboard') or {}).get('module_panels') or [])}
- 说明：{(report_view.get('addon_tools') or {}).get('dashboard', {}).get('summary') or '见数据看板导出'}

### 多模态内容审核

- 风险等级：{audit.get('risk_level') or 'low'}；通过：{audit.get('passed')}
{audit_lines}
- 边界：{audit.get('evidence_boundary') or ''}

### A/B测试方案生成

{ab_lines}

### 竞品投放监控Agent

- 状态：{monitor.get('status') or 'baseline'}
{monitor_lines}
- 边界：{monitor.get('evidence_boundary') or ''}

## 证据附录说明

{report_view['evidence_appendix']['instruction']}

### 当前数据缺口

{gap_lines}
"""
