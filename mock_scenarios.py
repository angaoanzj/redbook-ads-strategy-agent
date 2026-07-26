"""Deterministic scenario fallbacks with explicit, field-level provenance."""
from __future__ import annotations

import hashlib
import random
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any

from models import (
    AccountViolationEvidence,
    CampaignRequest,
    CategoryNoteEvidence,
    CreatorEvidence,
    MetricEvidence,
    PaidRiskDemoScenario,
    TrendKeywordEvidence,
)


MOCK_DATA_TYPE = "模拟数据（Mock）"
MOCK_WARNING = "仅用于方案演示和敏感性分析，不代表真实平台、竞品或账户数据。"
MOCK_SOURCE = "系统演示 Mock 补足"


def normalize_mock_seed(seed: str | None) -> str:
    cleaned = str(seed or "").strip()[:128]
    return cleaned or secrets.token_hex(8)


def rng_for(seed: str, namespace: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}:{namespace}".encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def evidence_meta(
    data_type: str,
    *,
    source_name: str,
    source_url: str | None = None,
    as_of: str | None = None,
    evidence_grade: str,
    is_mock: bool,
    mock_basis: str | None = None,
    warning: str | None = None,
    mock_seed: str | None = None,
) -> dict[str, Any]:
    return {
        "data_type": data_type,
        "is_mock": is_mock,
        "source_name": source_name,
        "source_url": source_url,
        "as_of": as_of or date.today().isoformat(),
        "evidence_grade": evidence_grade,
        "mock_basis": mock_basis,
        "warning": warning,
        "mock_seed": mock_seed,
    }


def metric_or_mock(
    benchmarks: dict[str, dict[str, Any]],
    metric_name: str,
    *,
    label: str,
    mock_value: float,
    unit: str,
    basis: str,
    low: float | None = None,
    high: float | None = None,
    allow_mock: bool = True,
    mock_seed: str | None = None,
) -> dict[str, Any]:
    real = benchmarks.get(metric_name)
    if real:
        is_mock_metric = bool(real.get("is_mock"))
        return {
            "status": "模拟情景，待真实数据替换" if is_mock_metric else "有来源证据",
            **real,
            **evidence_meta(
                MOCK_DATA_TYPE if is_mock_metric else "真实样本",
                source_name=real.get("source") or ("系统情景模拟" if is_mock_metric else "用户导入证据"),
                source_url=real.get("source_url"),
                as_of=real.get("collected_at"),
                evidence_grade="M" if is_mock_metric else (real.get("evidence_grade") or "B"),
                is_mock=is_mock_metric,
                mock_basis=real.get("notes") if is_mock_metric else None,
                warning=MOCK_WARNING if is_mock_metric else None,
                mock_seed=real.get("mock_seed") if is_mock_metric else None,
            ),
            "decision_conclusion": (
                f"暂按{label}中位情景进行预算敏感性测试；上线后必须以账户数据替换。"
                if is_mock_metric
                else f"以该{label}作为首轮参考，按素材和版位拆分验证。"
            ),
        }
    if not allow_mock:
        return {
            "status": "待导入聚光账户或官方行业基准",
            "value": None,
            "unit": unit,
            **evidence_meta(
                "数据缺口",
                source_name="尚无可用来源",
                evidence_grade="D",
                is_mock=False,
                warning=f"当前不能给出可信{label}；需要品牌聚光报表或有统计口径的公开资料。",
            ),
            "decision_conclusion": f"当前不能给出可信{label}行业均值；首轮仅采用账户实时建议价。",
        }
    scenario = {"base": mock_value}
    if low is not None:
        scenario["low"] = low
    if high is not None:
        scenario["high"] = high
    return {
        "status": "模拟情景，待真实数据替换",
        "value": mock_value,
        "unit": unit,
        "scenario": scenario,
        **evidence_meta(
            MOCK_DATA_TYPE,
            source_name="系统情景模拟",
            evidence_grade="M",
            is_mock=True,
            mock_basis=basis,
            warning=MOCK_WARNING,
            mock_seed=mock_seed,
        ),
        "decision_conclusion": f"暂按{label}中位情景进行预算敏感性测试；上线后必须以账户数据替换。",
    }


def build_mock_market_scenarios(
    total_budget_cny: float,
    goal: str,
    *,
    mock_seed: str | None = None,
) -> dict[str, Any]:
    seed = normalize_mock_seed(mock_seed)
    rng = rng_for(seed, "market")
    cpc_base = round(rng.uniform(0.8, 3.8), 2)
    ctr_base = round(rng.uniform(0.018, 0.065), 4)
    cvr_base = round(rng.uniform(0.006, 0.025), 4)
    cpm_base = round(cpc_base * ctr_base * 1000, 2)
    conversion_base = round((cpc_base / cvr_base) * rng.uniform(0.95, 1.05), 2)
    share_center = 0.60 if goal in {"conversion", "leads", "search_growth"} else 0.50
    search_ratio = round(min(0.75, max(0.35, share_center + rng.uniform(-0.08, 0.08))), 2)
    daily_budget = round(total_budget_cny / 30, 2)
    common = evidence_meta(
        MOCK_DATA_TYPE,
        source_name="系统情景模拟",
        evidence_grade="M",
        is_mock=True,
        mock_basis="基于本次目标和预算形成的首轮 A/B 测试情景，不使用竞品私有数据。",
        warning=MOCK_WARNING,
        mock_seed=seed,
    )
    return {
        "cpc": {"low": round(cpc_base * 0.75, 2), "base": cpc_base, "high": round(cpc_base * 1.35, 2), "unit": "元/点击"},
        "cpm": {"low": round(cpm_base * 0.75, 2), "base": cpm_base, "high": round(cpm_base * 1.35, 2), "unit": "元/千次曝光"},
        "ctr": {"low": round(ctr_base * 0.75, 4), "base": ctr_base, "high": round(ctr_base * 1.25, 4), "unit": "比例"},
        "cvr": {"low": round(cvr_base * 0.70, 4), "base": cvr_base, "high": round(cvr_base * 1.30, 4), "unit": "比例"},
        "conversion_cost": {"low": round(conversion_base * 0.70, 2), "base": conversion_base, "high": round(conversion_base * 1.35, 2), "unit": "元/次转化"},
        "budget_share": {
            "search_ratio": search_ratio,
            "feed_ratio": round(1 - search_ratio, 2),
        },
        "competitor_hypothesis": {
            "duration_days": {"low": 7, "base": 14, "high": 30},
            "budget_cny": {
                "low": round(daily_budget * 7),
                "base": round(daily_budget * 14),
                "high": round(daily_budget * 30),
            },
            "targeting_tests": ["品类兴趣人群", "伴手礼搜索意向人群", "送礼场景人群"],
        },
        "meta": common,
    }


def _as_of(as_of: str | None = None) -> str:
    return as_of or datetime.now(timezone.utc).date().isoformat()


def build_mock_creators(
    req: CampaignRequest,
    *,
    as_of: str | None = None,
    mock_seed: str | None = None,
) -> list[CreatorEvidence]:
    """演示用达人候选：显式 Mock，禁止当作真实推荐名单。

    固定产出 20 人：素人 12 / 达人 6 / KOL 2，覆盖模块3「Top20 名单」演示缺口。
    报价、粉丝画像、过往投流效果均为可复现随机情景，不是蒲公英真实数据。
    """
    seed = normalize_mock_seed(mock_seed)
    rng = rng_for(seed, "creators")
    as_of = _as_of(as_of)
    category_tokens = [
        part.strip()
        for part in re.split(r"[/｜|、，,\s]+", req.category or "")
        if part.strip()
    ][:4]
    product_tokens = [
        part.strip()
        for part in re.split(r"[/｜|、，,\s]+", req.product_name or "")
        if part.strip()
    ][:3]
    base_tags = [*category_tokens, *product_tokens, *list(req.selling_points)[:3]]
    tier_specs = [
        ("素人", 12, (1_000, 9_999), (0.02, 0.12), (300, 1_200), ["探店", "测评", "开箱"]),
        ("达人", 6, (10_000, 499_999), (0.015, 0.08), (1_500, 12_000), ["送礼", "旅行攻略", "伴手礼"]),
        ("KOL", 2, (500_000, 1_500_000), (0.01, 0.05), (15_000, 50_000), ["生活方式", "礼赠场景", "香港旅行"]),
    ]
    creators: list[CreatorEvidence] = []
    global_index = 1
    for tier, count, follower_range, rate_range, quote_range, tags in tier_specs:
        for tier_index in range(1, count + 1):
            followers = rng.randint(*follower_range)
            interaction_rate = rng.uniform(*rate_range)
            interactions = max(1, round(followers * interaction_rate))
            quote = round(rng.uniform(*quote_range) / 100) * 100
            boost = round(quote * rng.uniform(0.3, 0.8) / 50) * 50
            demo_ctr = round(rng.uniform(3.5, 12.0), 1)
            demo_cpc = round(rng.uniform(0.4, 2.8), 2)
            demo_eng = round(rng.uniform(4.0, 11.0), 1)
            audience_tags = list(dict.fromkeys([*tags, *base_tags]))
            creators.append(CreatorEvidence(
                name=f"模拟达人-{tier}{tier_index:02d}",
                profile_url=f"https://example.com/mock-creator/{seed}/{global_index}",
                followers=followers,
                average_interactions=interactions,
                quote_cny=quote,
                audience_tags=audience_tags,
                past_campaign_result=(
                    f"Mock演示合作（非真实投流）：图文合作1篇；建议笔记二次放大约{boost:.0f}元；"
                    f"演示CTR {demo_ctr}% / CPC {demo_cpc}元 / 互动率 {demo_eng}%；"
                    f"粉丝画像匹配仅供分层演示，下单前须蒲公英复核"
                ),
                source_name="系统可复现随机 Mock 模拟",
                collected_at=as_of,
                is_mock=True,
                evidence_grade="M",
                mock_seed=seed,
            ))
            global_index += 1
    return creators


def build_mock_competitors(
    req: CampaignRequest,
    *,
    as_of: str | None = None,
    mock_seed: str | None = None,
) -> list[Any]:
    from models import CompetitorEvidence

    seed = normalize_mock_seed(mock_seed)
    rng = rng_for(seed, "competitors")
    as_of = _as_of(as_of)
    formats = ["图集测评", "短视频开箱", "场景种草", "横向对比"]
    audiences = ["伴手礼搜索意向人群", "旅行兴趣人群", "节日送礼人群", "品质零食人群"]
    rows: list[CompetitorEvidence] = []
    for index in range(rng.randint(3, 5)):
        low = rng.randint(8_000, 35_000)
        high = low + rng.randint(20_000, 120_000)
        rows.append(CompetitorEvidence(
            account_name=f"模拟竞品 {chr(65 + index)}",
            profile_or_note_url=f"https://example.com/mock-competitor/{seed}/{index + 1}",
            note_format=rng.choice(formats),
            interactions=rng.randint(1_000, 35_000),
            is_ad_labeled=rng.choice([True, False]),
            campaign_duration_days=rng.randint(7, 45),
            estimated_budget_low_cny=low,
            estimated_budget_high_cny=high,
            observed_audience=rng.sample(audiences, k=2),
            notes="模拟竞品投放情景，所有字段均待真实证据验证",
            source_name="系统可复现随机 Mock 模拟",
            collected_at=as_of,
            is_mock=True,
            evidence_grade="M",
            mock_seed=seed,
        ))
    return rows


def build_mock_platform_market(
    req: CampaignRequest,
    *,
    as_of: str | None = None,
    mock_seed: str | None = None,
) -> dict[str, Any]:
    seed = normalize_mock_seed(mock_seed)
    rng = rng_for(seed, "platform-market")
    end_day = date.fromisoformat(_as_of(as_of))
    base_notes = rng.randint(70, 180)
    slope = rng.uniform(-0.8, 2.2)
    series: list[dict[str, Any]] = []
    for index in range(30):
        day = end_day - timedelta(days=29 - index)
        weekend_factor = 1.16 if day.weekday() >= 5 else 1.0
        note_count = max(5, round((base_notes + slope * index) * weekend_factor * rng.uniform(0.82, 1.18)))
        avg_interactions = rng.randint(180, 950)
        interactions = note_count * avg_interactions
        series.append({
            "date": day.isoformat(),
            "note_count": note_count,
            "interactions": interactions,
            "average_interactions": avg_interactions,
            "interaction_rate": round(rng.uniform(0.035, 0.14), 4),
            "is_mock": True,
            "data_type": MOCK_DATA_TYPE,
            "evidence_grade": "M",
            "source_name": "系统可复现随机 Mock 模拟",
            "mock_basis": "30天基础趋势×周末效应×有限随机波动的单日明细。",
            "mock_seed": seed,
            "warning": MOCK_WARNING,
        })
    total_notes = sum(row["note_count"] for row in series)
    total_interactions = sum(row["interactions"] for row in series)
    return {
        "status": "模拟平台自然流量大盘，非真实平台统计",
        "series": series,
        "total_note_count": total_notes,
        "total_interactions": total_interactions,
        "average_interactions_per_note": round(total_interactions / total_notes, 1),
        "traffic_peak_hours": rng.sample(["08:00–10:00", "12:00–14:00", "18:00–20:00", "20:00–22:00", "22:00–24:00"], k=3),
        "hot_tags": rng.sample([req.category, req.product_name, "送礼", "开箱", "测评", "旅行必买"], k=4),
        "popular_formats": rng.sample(["图集", "短视频", "开箱", "横向对比"], k=3),
        **evidence_meta(
            MOCK_DATA_TYPE,
            source_name="系统可复现随机 Mock 模拟",
            evidence_grade="M",
            is_mock=True,
            mock_seed=seed,
            mock_basis="30天基础趋势×周末效应×有限随机波动；汇总由每日明细计算。",
            warning=MOCK_WARNING,
        ),
    }


def build_mock_trending(
    req: CampaignRequest, *, as_of: str | None = None, mock_seed: str | None = None
) -> list[TrendKeywordEvidence]:
    seed = normalize_mock_seed(mock_seed)
    rng = rng_for(seed, "trending")
    as_of = _as_of(as_of)
    candidates = [
        req.category,
        f"{req.product_name}推荐",
        f"{req.product_name}怎么选",
        f"{req.category}测评",
        f"{req.category}送长辈",
        f"{req.category}商务送礼",
        "香港旅行必买",
        "节日礼盒推荐",
        "低甜曲奇推荐",
        "最好吃的伴手礼",
    ]
    return [
        TrendKeywordEvidence(
            keyword=keyword,
            source_name="系统可复现随机 Mock 模拟",
            collected_at=as_of,
            heat_score=rng.randint(45, 96),
            notes="演示热搜情景，非平台实时热搜榜；热度为可复现随机值",
            is_mock=True,
            evidence_grade="M",
            mock_seed=seed,
        )
        for keyword in candidates
    ]


def build_mock_violations(
    *, as_of: str | None = None, mock_seed: str | None = None
) -> list[AccountViolationEvidence]:
    """曲奇四重奏赛道向的 Mock 拒审台账，供模块1高频违规 + 模块4审核拒绝 SOP 演示。"""
    seed = normalize_mock_seed(mock_seed)
    rng = rng_for(seed, "violations")
    as_of = _as_of(as_of)
    rows = [
        (
            "绝对化用语（最好吃/第一伴手礼）",
            5,
            "Mock：标题出现“最好吃的香港曲奇”，演示拒审高发词",
        ),
        (
            "食品功效/养生暗示",
            3,
            "Mock：正文写“养胃不长胖”，食品赛道常见功效暗示拒审",
        ),
        (
            "跨境/进口食品资质不全",
            3,
            "Mock：礼盒含进口黄油表述但未附合规资质截图",
        ),
        (
            "未披露商业合作",
            2,
            "Mock：达人探店笔记未打合作标识",
        ),
        (
            "虚假稀缺/限时误导",
            2,
            "Mock：封面写“最后100盒”但无库存证据",
        ),
    ]
    return [
        AccountViolationEvidence(
            reason=reason,
            occurrence_count=max(1, count + rng.randint(-1, 4)),
            period="演示-近90天",
            source_name=MOCK_SOURCE,
            collected_at=as_of,
            notes=notes,
            is_mock=True,
            evidence_grade="M",
            mock_seed=seed,
        )
        for reason, count, notes in rows
    ]


def build_mock_paid_risk_scenarios(
    req: CampaignRequest, *, as_of: str | None = None, mock_seed: str | None = None
) -> list[PaidRiskDemoScenario]:
    """五类投流问题的曲奇四重奏 Mock 诊断情景，挂到模块4 risk_playbook.demo_scenario。"""
    seed = normalize_mock_seed(mock_seed)
    rng = rng_for(seed, "paid-risk")
    as_of = _as_of(as_of)
    brand = f"{req.brand_name}·{req.product_name}"
    catalog = [
        (
            "冷启动无量",
            f"Mock：{brand}搜索单元出价低于建议价约35%，定向仅「香港旅行」兴趣包，24h曝光不足200",
            {
                "impressions_24h": 160,
                "suggested_bid_gap_pct": -35,
                "targeting_est_reach": "偏低",
                "unit_status": "投放中-量极低",
            },
        ),
        (
            "点击成本过高",
            f"Mock：{brand}信息流 CPC≈4.6（历史中位情景×1.6），CTR 仅1.1%，宽词“零食”消耗偏高",
            {
                "cpc_cny": 4.6,
                "historical_cpc_cny": 2.8,
                "cpc_vs_history_ratio": 1.64,
                "ctr": 0.011,
                "waste_search_terms": ["零食", "饼干推荐"],
            },
        ),
        (
            "点击高但转化低",
            f"Mock：{brand}点击充足但 CVR≈0.3%（演示情景1.2%的1/4），落地页价带与笔记钩子不一致",
            {
                "clicks_24h": 420,
                "orders_24h": 1,
                "cvr": 0.003,
                "demo_baseline_cvr": 0.012,
                "landing_issue": "笔记主推节日礼盒，落地页默认单盒无券",
            },
        ),
        (
            "素材衰退",
            f"Mock：{brand}「开箱对比」封面连续4日 CTR 从4.2%滑至2.6%（跌幅约38%），频次偏高",
            {
                "creative_name": "开箱对比-金箔礼盒封面",
                "ctr_peak": 0.042,
                "ctr_latest": 0.026,
                "ctr_drop_pct": 38,
                "days_in_flight": 4,
                "frequency": 3.8,
            },
        ),
        (
            "审核拒绝",
            f"Mock：{brand}标题含“最好吃伴手礼”+功效暗示，拒审原因与台账前两项一致",
            {
                "reject_reasons": [
                    "绝对化用语（最好吃/第一伴手礼）",
                    "食品功效/养生暗示",
                ],
                "reject_count_7d": 2,
                "asset_type": "搜索推广创意",
            },
        ),
    ]
    return [
        PaidRiskDemoScenario(
            issue=issue,
            example_diagnosis=f"Mock随机诊断：{issue}；{diagnosis.split('Mock：', 1)[-1].split('，')[0]}，具体数值仅用于演示",
            demo_signals={
                key: (
                    max(1, round(value * rng.uniform(0.8, 1.2)))
                    if isinstance(value, int) and not isinstance(value, bool)
                    else round(value * rng.uniform(0.85, 1.15), 4)
                    if isinstance(value, float)
                    else value
                )
                for key, value in signals.items()
            },
            source_name="系统可复现随机 Mock 模拟",
            collected_at=as_of,
            notes="Mock 投流问题演示情景，非真实账户事故；上线前用聚光后台替换",
            is_mock=True,
            evidence_grade="M",
            mock_seed=seed,
        )
        for issue, diagnosis, signals in catalog
    ]


def build_mock_notes(
    req: CampaignRequest, *, as_of: str | None = None, mock_seed: str | None = None
) -> list[CategoryNoteEvidence]:
    """演示笔记样本：published_at 覆盖早/午/晚/夜多高峰，供 daily_schedules 演示。"""
    seed = normalize_mock_seed(mock_seed)
    rng = rng_for(seed, "notes")
    as_of = _as_of(as_of)
    point = req.selling_points[0]
    # (title, tags含note_type, hour, likes, favorites, comments, shares)
    # 互动刻意拉开：晚高峰 > 夜决策 > 午间 > 早通勤，保证多时段清晰排序
    templates = [
        (
            f"下班后来份{req.category}开箱",
            ["视频", "开箱", "送礼", req.category],
            20,
            1280,
            520,
            86,
            42,
        ),
        (
            f"节日送礼｜{req.product_name}对比清单",
            ["图集", "送礼", "对比", point],
            19,
            1180,
            490,
            78,
            38,
        ),
        (
            f"晚上刷到的{point}礼盒真实体验",
            ["图集", point, "真实体验", req.product_name],
            21,
            980,
            410,
            64,
            30,
        ),
        (
            f"深夜种草｜第一次买{req.product_name}避坑",
            ["图集", "避坑", req.product_name, "送礼"],
            21,
            920,
            380,
            58,
            28,
        ),
        (
            f"午饭时间想好伴手礼：{req.category}怎么选",
            ["图集", req.category, "怎么选", point],
            12,
            860,
            340,
            52,
            24,
        ),
        (
            f"午休碎片｜{req.product_name}口味测评",
            ["视频", "测评", req.product_name, point],
            12,
            820,
            320,
            48,
            22,
        ),
        (
            f"通勤路上刷到的{req.category}",
            ["图集", "通勤", req.category, point],
            8,
            640,
            240,
            36,
            16,
        ),
        (
            f"早起备礼｜{point}三分钟看懂",
            ["图集", point, "备礼", req.category],
            9,
            600,
            220,
            32,
            14,
        ),
        (
            f"下午茶场景下的{req.product_name}",
            ["图集", "下午茶", req.product_name, point],
            15,
            480,
            180,
            24,
            10,
        ),
        (
            f"{req.category}值得吗？样本测评（对照窗）",
            ["图集", "测评", req.category, point],
            15,
            420,
            150,
            20,
            8,
        ),
    ]
    notes: list[CategoryNoteEvidence] = []
    for index in range(1, 31):
        title, tags, base_hour, likes, favorites, comments, shares = templates[(index - 1) % len(templates)]
        hour = base_hour if index <= len(templates) else max(0, min(23, base_hour + rng.choice([-1, 0, 0, 1])))
        factor = rng.uniform(0.65, 1.45)
        likes = max(1, round(likes * factor))
        favorites = max(0, round(favorites * factor * rng.uniform(0.85, 1.10)))
        comments = max(0, round(comments * factor * rng.uniform(0.80, 1.15)))
        shares = max(0, round(shares * factor * rng.uniform(0.75, 1.20)))
        day_offset = index - 1
        try:
            day = (date.fromisoformat(as_of) - timedelta(days=day_offset)).isoformat()
        except ValueError:
            day = as_of
        notes.append(
            CategoryNoteEvidence(
                search_keyword=req.category,
                search_sort="综合",
                search_rank=index,
                note_id=f"mock-note-{hashlib.sha256(seed.encode()).hexdigest()[:8]}-{index:02d}",
                note_url=f"https://example.com/mock-note/{seed}/{index}",
                title=title,
                description=(
                    f"Mock 演示正文：围绕{point}与{req.category}的场景说明；"
                    f"发布时间刻意落在演示高峰窗 {hour:02d}:00。"
                ),
                note_type=tags[0],
                author_nickname=f"演示作者{index}",
                likes=likes,
                favorites=favorites,
                comments=comments,
                shares=shares,
                tags=tags[1:],
                published_at=f"{day}T{hour:02d}:00:00+00:00",
                is_mock=True,
                collected_at=as_of,
                source_name=MOCK_SOURCE,
                evidence_grade="M",
                mock_seed=seed,
            )
        )
    return notes


def build_mock_benchmarks(
    req: CampaignRequest, *, as_of: str | None = None, mock_seed: str | None = None
) -> list[MetricEvidence]:
    """仅补缺失的核心投放指标，已有同名真实指标不会被覆盖。"""
    as_of = _as_of(as_of)
    seed = normalize_mock_seed(mock_seed)
    scenarios = build_mock_market_scenarios(req.total_budget_cny, req.goal, mock_seed=seed)
    catalog = {
        "cpc": (scenarios["cpc"]["base"], "CNY/click", "首轮冷启动中位 CPC 情景"),
        "cpm": (scenarios["cpm"]["base"], "CNY/1000 impressions", "首轮冷启动中位 CPM 情景"),
        "ctr": (scenarios["ctr"]["base"], "ratio", "品类演示 CTR 可复现随机情景"),
        "cvr": (scenarios["cvr"]["base"], "ratio", "品类演示 CVR 可复现随机情景，仅用于敏感性分析"),
    }
    existing = {item.metric_name.casefold() for item in req.benchmark_evidence}
    return [
        MetricEvidence(
            source_name=MOCK_SOURCE,
            collected_at=as_of,
            metric_name=name,
            value=value,
            unit=unit,
            notes=basis,
            evidence_grade="M",
            is_mock=True,
            mock_seed=seed,
        )
        for name, (value, unit, basis) in catalog.items()
        if name not in existing
    ]


def apply_demo_mock_evidence(
    req: CampaignRequest, *, mock_seed: str | None = None
) -> tuple[CampaignRequest, dict[str, Any]]:
    """
    在 allow_mock=True 时，用显式 Mock 补齐演示所需缺口。
    不覆盖用户已提供的真实/导入证据；Mock 不得伪装成实时平台事实。
    """
    seed = normalize_mock_seed(mock_seed)
    injected: dict[str, Any] = {"fields": [], "policy": MOCK_WARNING, "mock_seed": seed}
    updates: dict[str, Any] = {}

    mock_benchmarks = build_mock_benchmarks(req, mock_seed=seed)
    if mock_benchmarks:
        updates["benchmark_evidence"] = [*req.benchmark_evidence, *mock_benchmarks]
        injected["fields"].append({
            "field": "benchmark_evidence",
            "count": len(mock_benchmarks),
            "is_mock": True,
        })

    if not req.creator_evidence:
        creators = build_mock_creators(req, mock_seed=seed)
        updates["creator_evidence"] = creators
        injected["fields"].append({
            "field": "creator_evidence",
            "count": len(creators),
            "is_mock": True,
            "note": "演示候选，非真实推荐名单",
        })

    if not req.trending_keyword_evidence:
        trending = build_mock_trending(req, mock_seed=seed)
        updates["trending_keyword_evidence"] = trending
        injected["fields"].append({
            "field": "trending_keyword_evidence",
            "count": len(trending),
            "is_mock": True,
            "note": "演示热搜情景，非实时热搜",
        })

    if not req.account_violation_evidence:
        violations = build_mock_violations(mock_seed=seed)
        updates["account_violation_evidence"] = violations
        injected["fields"].append({
            "field": "account_violation_evidence",
            "count": len(violations),
            "is_mock": True,
        })

    if not req.category_note_evidence:
        notes = build_mock_notes(req, mock_seed=seed)
        updates["category_note_evidence"] = notes
        injected["fields"].append({
            "field": "category_note_evidence",
            "count": len(notes),
            "is_mock": True,
            "note": "演示笔记样本，不代表平台大盘",
        })

    if not req.paid_risk_demo_scenarios:
        scenarios = build_mock_paid_risk_scenarios(req, mock_seed=seed)
        updates["paid_risk_demo_scenarios"] = scenarios
        injected["fields"].append({
            "field": "paid_risk_demo_scenarios",
            "count": len(scenarios),
            "is_mock": True,
            "note": "五类投流问题 Mock 诊断情景，非真实账户事故",
        })

    if not req.competitor_evidence:
        competitors = build_mock_competitors(req, mock_seed=seed)
        updates["competitor_evidence"] = competitors
        injected["fields"].append({
            "field": "competitor_evidence",
            "count": len(competitors),
            "is_mock": True,
            "note": "匿名模拟竞品，非真实品牌投放证据",
        })

    if not updates:
        return req, injected
    return req.model_copy(update=updates), injected
