"""六模块黄金断言集：代码即数据。

每个模块三类断言：

1. `honesty_markers`：输出 JSON 序列化文本里必须出现的诚实边界标记。
   每条标记是一个 `{"id", "any_of", "why"}`：`any_of` 里任一措辞命中即算这条标记通过
   （模块契约允许同义措辞，硬编码单一字符串会把评分变成措辞考试）。
2. `numeric_invariants`：可编程校验的数字不变量，签名 `fn(output, req) -> list[str]`，
   返回违规描述列表（空列表表示通过）。**阈值一律对齐 tools/ 里的护栏常量**，
   见每个函数的注释；护栏改了这里要跟着改，否则评分会与工具打架。
3. `required_structure`：关键路径存在性（点路径，`*` 通配 list 下标 / dict 任意键），
   路径解析口径参考 module_agents/base.py 的 `_resolve_path`（此处自实现简版）。

本文件只依赖标准库，绝不 import engine / main / 模块 Agent。
"""
from __future__ import annotations

from typing import Any, Callable, Iterator

# ---------------------------------------------------------------------------
# 护栏常量（镜像 tools/ 与模块契约，改护栏时同步这里）
# ---------------------------------------------------------------------------
SHARE_TOLERANCE = 0.01  # 各类比例合计 1.0 的容差（module4/module6 契约同值）

# tools/keywords.py
MIN_CORE = 2
MIN_LONG_TAIL = 4
MIN_BLUE_OCEAN = 2

# module6 契约 TrendingMonitor.rising_keywords（镜像 tools/trending.py RECOMMENDATIONS）
RISING_KEYWORD_RECOMMENDATIONS = ("跟进", "观察", "不跟进")
MAX_RISING_KEYWORDS = 20

# tools/bidding.py STAGE_GUARDRAILS["cold_start"]
COLD_START_MULTIPLIER_BAND = (0.80, 1.30)

# tools/forecast.py
TEST_BUDGET_RATIO = 0.15
TEST_BUDGET_FLOOR_RATIO = 0.05

# tools/budget.py
ORGANIC_RATIO_BAND = (0.20, 0.70)
PHASE_RATIOS = {"预热期": 0.20, "爆发期": 0.60, "长尾期": 0.20}

# tools/creators.py amplification_ratio
AMPLIFICATION_RATIO_BAND = (0.10, 0.50)

# module2 契约 MaterialScreening
CTR_THRESHOLD_BAND = (0.03, 0.30)
ENGAGEMENT_THRESHOLD_BAND = (0.02, 0.20)

# module3 / module4 数量护栏
AD_KEYWORDS_BAND = (3, 15)
TOP_N_CREATORS = 20
RISK_PLAYBOOK_COUNT = 5
TARGETING_PACKAGE_COUNT = 3
CONTENT_DIRECTION_COUNT = 3
TOPIC_COUNT = 15
TOPICS_PER_DIRECTION_MIN = 3


# ---------------------------------------------------------------------------
# 取值工具（全部容错：契约演进/降级输出不应让评分脚本崩掉）
# ---------------------------------------------------------------------------
def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def resolve_path(obj: Any, path: str) -> Iterator[tuple[str, Any]]:
    """按点路径解析，`*` 通配 dict 任意键或 list 任意下标（简版 _resolve_path）。"""

    def walk(node: Any, segments: list[str], prefix: str) -> Iterator[tuple[str, Any]]:
        if not segments:
            yield prefix, node
            return
        head, rest = segments[0], segments[1:]
        if head == "*":
            if isinstance(node, dict):
                items: list[tuple[Any, Any]] = list(node.items())
            elif isinstance(node, (list, tuple)):
                items = list(enumerate(node))
            else:
                return
            for key, sub in items:
                yield from walk(sub, rest, f"{prefix}.{key}" if prefix else str(key))
        elif isinstance(node, dict) and head in node:
            yield from walk(node[head], rest, f"{prefix}.{head}" if prefix else head)

    yield from walk(obj, path.split("."), "")


def path_exists(obj: Any, path: str) -> bool:
    return any(True for _ in resolve_path(obj, path))


def _req_num(req: Any, key: str) -> float | None:
    return _num(_as_dict(req).get(key))


def _req_paid_budget(req: Any) -> float | None:
    """聚光付费预算：优先 spotlight_budget_cny，其次按目标默认档估算的口径留给不变量自行放宽。"""
    return _req_num(req, "spotlight_budget_cny")


def _req_baseline(req: Any, *hints: str) -> float | None:
    """从 benchmark_evidence 里取第一个命中 hint 的指标值。"""
    for row in _as_list(_as_dict(req).get("benchmark_evidence")):
        name = _text(_as_dict(row).get("metric_name")).lower()
        if any(hint in name for hint in hints):
            value = _num(_as_dict(row).get("value"))
            if value is not None:
                return value
    return None


def _sum_shares(rows: list[Any], key: str) -> float:
    total = 0.0
    for row in rows:
        value = _num(_as_dict(row).get(key))
        if value is not None:
            total += value
    return total


# ---------------------------------------------------------------------------
# 模块1：赛道与竞品
# ---------------------------------------------------------------------------
def invariant_m1_paid_landscape_sources(output: dict, req: dict) -> list[str]:
    """付费格局：每个非空数字必须带来源；三个都空时必须给 missing_notice（契约 + 铁律4）。"""
    violations: list[str] = []
    paid = _as_dict(output.get("paid_landscape"))
    pairs = (
        ("cpc_cny", "cpc_source"),
        ("cpm_cny", "cpm_source"),
        ("conversion_cost_cny", "conversion_cost_source"),
    )
    present = 0
    for value_key, source_key in pairs:
        value = _num(paid.get(value_key))
        if value is None:
            continue
        present += 1
        if not _text(paid.get(source_key)).strip():
            violations.append(f"paid_landscape.{value_key}={value:g} 缺少 {source_key} 来源")
    if present == 0 and not _text(paid.get("missing_notice")).strip():
        violations.append("paid_landscape 三个数字全为 null 时必须填写 missing_notice")
    return violations


def invariant_m1_ad_labeled_count(output: dict, req: dict) -> list[str]:
    """ad_labeled_count 必须是非负整数，且不得超过请求里的竞品证据条数（禁止凭空多算）。"""
    violations: list[str] = []
    breakdown = _as_dict(output.get("competitor_breakdown"))
    count = breakdown.get("ad_labeled_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return [f"competitor_breakdown.ad_labeled_count 必须为非负整数，当前 {count!r}"]
    evidence_count = len(_as_list(_as_dict(req).get("competitor_evidence")))
    if count > evidence_count:
        violations.append(
            f"ad_labeled_count={count} 超过请求竞品证据条数 {evidence_count}（不得凭空新增竞品）"
        )
    return violations


def invariant_m1_organic_sample(output: dict, req: dict) -> list[str]:
    """无笔记证据必须 hot_formats 留空；有证据时 sample_size 不得超过证据条数。"""
    violations: list[str] = []
    organic = _as_dict(output.get("organic_landscape"))
    note_count = len(_as_list(_as_dict(req).get("category_note_evidence")))
    hot_formats = _as_list(organic.get("hot_formats"))
    if note_count == 0 and hot_formats:
        violations.append(
            f"无品类笔记证据时 hot_formats 必须留空，当前 {len(hot_formats)} 项（编造风险）"
        )
    sample = _num(organic.get("sample_size"))
    if sample is not None and note_count and sample > note_count:
        violations.append(
            f"organic_landscape.sample_size={sample:g} 超过品类笔记证据条数 {note_count}"
        )
    return violations


# ---------------------------------------------------------------------------
# 模块2：人群与内容
# ---------------------------------------------------------------------------
def invariant_m2_directions_and_topics(output: dict, req: dict) -> list[str]:
    """恰好 3 方向 15 选题、每方向≥3、选题方向命中三方向之一、付费选题必须带目标。"""
    violations: list[str] = []
    directions = _as_list(output.get("content_directions"))
    topics = _as_list(output.get("topics"))
    if len(directions) != CONTENT_DIRECTION_COUNT:
        violations.append(
            f"content_directions 必须恰好 {CONTENT_DIRECTION_COUNT} 个，当前 {len(directions)}"
        )
    if len(topics) != TOPIC_COUNT:
        violations.append(f"topics 必须恰好 {TOPIC_COUNT} 个，当前 {len(topics)}")

    names = {_text(_as_dict(row).get("direction")).strip() for row in directions}
    names.discard("")
    counts = {name: 0 for name in names}
    orphans: list[str] = []
    missing_objective: list[str] = []
    for row in topics:
        topic = _as_dict(row)
        direction = _text(topic.get("direction")).strip()
        if direction in counts:
            counts[direction] += 1
        else:
            orphans.append(_text(topic.get("title_template")) or "(无标题)")
        if topic.get("suitable_for_paid") is True and not _text(topic.get("paid_objective")).strip():
            missing_objective.append(_text(topic.get("title_template")) or "(无标题)")
    if orphans:
        violations.append("以下选题的 direction 未命中三方向之一：" + "、".join(orphans[:5]))
    shortfalls = [name for name, count in counts.items() if count < TOPICS_PER_DIRECTION_MIN]
    if shortfalls:
        violations.append(
            f"每方向至少 {TOPICS_PER_DIRECTION_MIN} 个选题，不足：" + "、".join(shortfalls)
        )
    if missing_objective:
        violations.append(
            "付费选题缺 paid_objective：" + "、".join(missing_objective[:5])
        )
    return violations


def invariant_m2_screening_thresholds(output: dict, req: dict) -> list[str]:
    """CTR / 互动率阈值必须落在契约护栏区间内（module2.MaterialScreening）。"""
    violations: list[str] = []
    screening = _as_dict(output.get("material_screening"))
    for key, (low, high) in (
        ("ctr_threshold", CTR_THRESHOLD_BAND),
        ("engagement_threshold", ENGAGEMENT_THRESHOLD_BAND),
    ):
        value = _num(screening.get(key))
        if value is None:
            violations.append(f"material_screening.{key} 缺失")
        elif not (low <= value <= high):
            violations.append(
                f"material_screening.{key}={value:g} 越出护栏 {low}–{high}"
            )
    return violations


def invariant_m2_scores_in_range(output: dict, req: dict) -> list[str]:
    """双评分必须是 1–10 的整数（module2.ContentDirection）。"""
    violations: list[str] = []
    for row in _as_list(output.get("content_directions")):
        item = _as_dict(row)
        name = _text(item.get("direction")) or "(无方向名)"
        for key in ("organic_score", "paid_score"):
            value = _num(item.get(key))
            if value is None or not (1 <= value <= 10) or value != int(value):
                violations.append(f"方向「{name}」的 {key}={item.get(key)!r} 不是 1–10 的整数")
    return violations


# ---------------------------------------------------------------------------
# 模块3：关键词与达人
# ---------------------------------------------------------------------------
def invariant_m3_creator_plan_self_consistent(output: dict, req: dict) -> list[str]:
    """达人分层金额与 amplification_pool 自洽（tools/creators.plan_creator_tiers 的数学）。

    工具里 pool = paid×ratio、每层 spotlight = round(pool×层比例)，
    因此各层 spotlight 之和 ≈ pool，误差不超过层数（每层四舍五入最多差 0.5，取整放宽到 1）。
    """
    violations: list[str] = []
    plan = _as_dict(output.get("creator_plan"))
    tiers = _as_list(plan.get("tiers"))
    pool = _num(plan.get("amplification_pool_cny"))
    if not tiers:
        violations.append("creator_plan.tiers 不能为空")
        return violations
    if pool is None:
        violations.append("creator_plan.amplification_pool_cny 缺失")
        return violations
    spotlight_sum = _sum_shares(tiers, "spotlight_amplification_budget_cny")
    tolerance = max(1.0, float(len(tiers)))
    if abs(spotlight_sum - pool) > tolerance:
        violations.append(
            f"各层聚光放大预算合计 {spotlight_sum:g} 与 amplification_pool_cny {pool:g} "
            f"不自洽（容差 {tolerance:g}）"
        )
    for row in tiers:
        tier = _as_dict(row)
        name = _text(tier.get("tier")) or "(无层级名)"
        count = _num(tier.get("count"))
        collab = _num(tier.get("collaboration_budget_cny"))
        if count is None or count < 1:
            violations.append(f"层级「{name}」count 必须 ≥1，当前 {tier.get('count')!r}")
        if collab is None or collab < 0:
            violations.append(
                f"层级「{name}」collaboration_budget_cny 非法：{tier.get('collaboration_budget_cny')!r}"
            )
    paid_budget = _req_paid_budget(req)
    if paid_budget:
        low, high = AMPLIFICATION_RATIO_BAND
        ratio = pool / paid_budget
        if not (low - 0.01 <= ratio <= high + 0.01):
            violations.append(
                f"amplification_pool_cny {pool:g} / 聚光预算 {paid_budget:g} = {ratio:.3f}，"
                f"越出 amplification_ratio 护栏 {low}–{high}"
            )
    return violations


def invariant_m3_keyword_tracks(output: dict, req: dict) -> list[str]:
    """自然三层数量下限对齐 tools/keywords 护栏；搜索/信息流广告词 3–15 条且不重复。"""
    violations: list[str] = []
    tracks = _as_dict(output.get("keyword_tracks"))
    organic = _as_dict(tracks.get("organic"))
    for key, minimum in (
        ("core", MIN_CORE),
        ("long_tail", MIN_LONG_TAIL),
        ("blue_ocean", MIN_BLUE_OCEAN),
    ):
        count = len(_as_list(organic.get(key)))
        if count < minimum:
            violations.append(f"keyword_tracks.organic.{key} 需 ≥{minimum}，当前 {count}")
    low, high = AD_KEYWORDS_BAND
    for key in ("search_ads", "feed_ads"):
        rows = _as_list(tracks.get(key))
        if not (low <= len(rows) <= high):
            violations.append(f"keyword_tracks.{key} 需 {low}-{high} 条，当前 {len(rows)}")
        words = [_text(_as_dict(row).get("keyword")).casefold().strip() for row in rows]
        words = [word for word in words if word]
        if len(words) != len(set(words)):
            violations.append(f"keyword_tracks.{key} 存在重复关键词（工具层要求去重）")
    return violations


def invariant_m3_matched_creators(output: dict, req: dict) -> list[str]:
    """匹配名单不得超过 top20、匹配分 0–100；无达人证据时必须如实为空。"""
    violations: list[str] = []
    matched = _as_list(output.get("matched_creators"))
    if len(matched) > TOP_N_CREATORS:
        violations.append(f"matched_creators 最多 {TOP_N_CREATORS} 位，当前 {len(matched)}")
    evidence_count = len(_as_list(_as_dict(req).get("creator_evidence")))
    if evidence_count == 0 and matched:
        violations.append(
            f"无达人证据时 matched_creators 必须为空，当前 {len(matched)} 位（编造名单风险）"
        )
    if evidence_count and len(matched) > evidence_count:
        violations.append(
            f"matched_creators {len(matched)} 位超过达人证据 {evidence_count} 条（只能转录证据达人）"
        )
    for row in matched:
        item = _as_dict(row)
        score = _num(item.get("match_score"))
        if score is None or not (0 <= score <= 100):
            violations.append(
                f"达人「{_text(item.get('name')) or '(无名)'}」match_score={item.get('match_score')!r} 越界"
            )
    return violations


# ---------------------------------------------------------------------------
# 模块4：聚光投流决策
# ---------------------------------------------------------------------------
def invariant_m4_budget_shares(output: dict, req: dict) -> list[str]:
    """campaigns / targeting_packages / search_feed_split 三处比例各自合计 1（±0.01）。"""
    violations: list[str] = []
    campaigns = _as_list(_as_dict(output.get("account_structure")).get("campaigns"))
    campaign_total = _sum_shares(campaigns, "budget_share")
    if abs(campaign_total - 1.0) > SHARE_TOLERANCE:
        violations.append(
            f"account_structure.campaigns 的 budget_share 合计必须为 1.0，当前 {campaign_total:.3f}"
        )
    packages = _as_list(output.get("targeting_packages"))
    if len(packages) != TARGETING_PACKAGE_COUNT:
        violations.append(
            f"targeting_packages 必须恰好 {TARGETING_PACKAGE_COUNT} 个，当前 {len(packages)}"
        )
    package_total = _sum_shares(packages, "budget_share")
    if abs(package_total - 1.0) > SHARE_TOLERANCE:
        violations.append(
            f"targeting_packages 的 budget_share 合计必须为 1.0，当前 {package_total:.3f}"
        )
    split = _as_dict(output.get("search_feed_split"))
    search, feed = _num(split.get("search")), _num(split.get("feed"))
    if search is None or feed is None:
        violations.append("search_feed_split 缺 search / feed")
    elif abs(search + feed - 1.0) > SHARE_TOLERANCE:
        violations.append(
            f"search_feed_split 合计必须为 1.0，当前 {search + feed:.3f}"
        )
    return violations


def invariant_m4_bidding(output: dict, req: dict) -> list[str]:
    """出价：low<high；有基准 CPC 时倍率必须落在 cold_start 护栏 0.8–1.3；无基准必须双 null。"""
    violations: list[str] = []
    cold_start = _as_dict(_as_dict(output.get("bidding")).get("cold_start"))
    low = _num(cold_start.get("bid_low_cny"))
    high = _num(cold_start.get("bid_high_cny"))
    baseline = _req_baseline(req, "cpc", "cost_per_click")
    if baseline is None:
        if low is not None or high is not None:
            violations.append(
                f"无基准 CPC 证据时 bid_low/bid_high 必须为 null，当前 {low!r}/{high!r}"
            )
        return violations
    if low is None or high is None:
        # 有基准但没给出价不算编造，只提示一次
        violations.append("有基准 CPC 证据但 bidding.cold_start 出价为空（应调 calc_bid_range）")
        return violations
    if low >= high:
        violations.append(f"bid_low_cny {low:g} 必须小于 bid_high_cny {high:g}")
    band_low, band_high = COLD_START_MULTIPLIER_BAND
    for name, value in (("bid_low_cny", low), ("bid_high_cny", high)):
        multiplier = value / baseline if baseline else 0.0
        if not (band_low - 0.01 <= multiplier <= band_high + 0.01):
            violations.append(
                f"{name}={value:g} 相对基准 CPC {baseline:g} 的倍率 {multiplier:.2f} "
                f"越出 cold_start 护栏 {band_low}–{band_high}"
            )
    return violations


def invariant_m4_forecast(output: dict, req: dict) -> list[str]:
    """测试带宽必须落在聚光预算的 5%（下限）–15%（上限）之间；止损线必须高于基准。"""
    violations: list[str] = []
    forecast = _as_dict(output.get("forecast"))
    test_budget = _num(forecast.get("test_budget_cny"))
    if test_budget is None:
        violations.append("forecast.test_budget_cny 缺失")
    else:
        paid_budget = _req_paid_budget(req)
        if paid_budget:
            floor = paid_budget * TEST_BUDGET_FLOOR_RATIO
            cap = paid_budget * TEST_BUDGET_RATIO
            if test_budget < floor - 1 or test_budget > cap + 1:
                violations.append(
                    f"forecast.test_budget_cny={test_budget:g} 越出测试带宽护栏 "
                    f"[{floor:g}, {cap:g}]（聚光预算 {paid_budget:g} 的 "
                    f"{TEST_BUDGET_FLOOR_RATIO}–{TEST_BUDGET_RATIO}）"
                )
    baseline_cpc = _req_baseline(req, "cpc", "cost_per_click")
    stop_cpc = _num(forecast.get("stop_loss_cpc_cny"))
    if baseline_cpc is not None and stop_cpc is not None and stop_cpc <= baseline_cpc:
        violations.append(
            f"stop_loss_cpc_cny={stop_cpc:g} 不高于基准 CPC {baseline_cpc:g}（止损线失效）"
        )
    roi_band = _as_list(forecast.get("roi_band"))
    roi_point = _num(forecast.get("roi_point"))
    if roi_band:
        if len(roi_band) != 2:
            violations.append(f"forecast.roi_band 必须是两个数字，当前 {roi_band!r}")
        elif roi_point is not None:
            low, high = _num(roi_band[0]), _num(roi_band[1])
            if low is None or high is None or low > high:
                violations.append(f"forecast.roi_band 非法区间：{roi_band!r}")
            elif not (low <= roi_point <= high):
                violations.append(
                    f"forecast.roi_point={roi_point:g} 不在 roi_band {roi_band!r} 内"
                )
    return violations


def invariant_m4_risk_playbook(output: dict, req: dict) -> list[str]:
    """风险预案必须恰好 5 条且三字段齐全（契约 min/max=5）。"""
    violations: list[str] = []
    rows = _as_list(output.get("risk_playbook"))
    if len(rows) != RISK_PLAYBOOK_COUNT:
        violations.append(f"risk_playbook 必须恰好 {RISK_PLAYBOOK_COUNT} 条，当前 {len(rows)}")
    for index, row in enumerate(rows, start=1):
        item = _as_dict(row)
        missing = [key for key in ("problem", "symptom", "response") if not _text(item.get(key)).strip()]
        if missing:
            violations.append(f"risk_playbook 第 {index} 条缺字段：{'、'.join(missing)}")
    return violations


# ---------------------------------------------------------------------------
# 模块5：预算与节奏
# ---------------------------------------------------------------------------
def invariant_m5_budget_split(output: dict, req: dict) -> list[str]:
    """organic + paid = 总预算；organic_ratio 与金额自洽且落在 0.20–0.70 护栏内。"""
    violations: list[str] = []
    split = _as_dict(output.get("budget_split"))
    organic = _num(split.get("organic_budget_cny"))
    paid = _num(split.get("paid_budget_cny"))
    total = _req_num(req, "total_budget_cny")
    if organic is None or paid is None:
        return ["budget_split 缺 organic_budget_cny / paid_budget_cny"]
    if total is not None and abs(organic + paid - total) > 1:
        violations.append(
            f"organic {organic:g} + paid {paid:g} = {organic + paid:g} ≠ 总预算 {total:g}"
        )
    ratio = _num(split.get("organic_ratio"))
    if ratio is None:
        violations.append("budget_split.organic_ratio 缺失")
    else:
        low, high = ORGANIC_RATIO_BAND
        if not (low - 0.001 <= ratio <= high + 0.001):
            violations.append(
                f"organic_ratio={ratio:g} 越出 compute_budget_split 护栏 {low}–{high}"
            )
        if total and abs(ratio - organic / total) > 0.01:
            violations.append(
                f"organic_ratio={ratio:g} 与金额比例 {organic / total:.3f} 不自洽"
            )
    return violations


def invariant_m5_phases(output: dict, req: dict) -> list[str]:
    """三阶段付费预算合计 = paid_budget，且阶段占比对齐 20/60/20 默认档。"""
    violations: list[str] = []
    phases = _as_list(output.get("phases"))
    if len(phases) != 3:
        violations.append(f"phases 必须恰好 3 个阶段，当前 {len(phases)}")
    paid = _num(_as_dict(output.get("budget_split")).get("paid_budget_cny"))
    total_phase = _sum_shares(phases, "paid_budget_cny")
    if paid is not None and abs(total_phase - paid) > 1:
        violations.append(
            f"三阶段付费预算合计 {total_phase:g} ≠ paid_budget_cny {paid:g}"
        )
    if paid:
        for row in phases:
            item = _as_dict(row)
            name = _text(item.get("phase")).strip()
            expected_ratio = PHASE_RATIOS.get(name)
            value = _num(item.get("paid_budget_cny"))
            if expected_ratio is None:
                violations.append(f"未知阶段名「{name or '(空)'}」（只允许 预热期/爆发期/长尾期）")
                continue
            if value is None:
                violations.append(f"阶段「{name}」缺 paid_budget_cny")
                continue
            # 尾差归入爆发期，容差放宽到 1% 付费预算 + 1 元
            if abs(value - paid * expected_ratio) > paid * 0.01 + 1:
                violations.append(
                    f"阶段「{name}」{value:g} 元偏离默认档 {expected_ratio:g}×{paid:g}"
                    f"={paid * expected_ratio:g}"
                )
    return violations


def invariant_m5_creator_tier_plan(output: dict, req: dict) -> list[str]:
    """达人分层放大预算合计 ≈ amplification_pool；池子占付费预算比例落在 0.10–0.50。"""
    violations: list[str] = []
    plan = _as_dict(output.get("creator_tier_plan"))
    tiers = _as_list(plan.get("tiers"))
    pool = _num(plan.get("amplification_pool_cny"))
    if pool is None:
        return ["creator_tier_plan.amplification_pool_cny 缺失"]
    if tiers:
        spotlight_sum = _sum_shares(tiers, "spotlight_amplification_budget_cny")
        tolerance = max(1.0, float(len(tiers)))
        if abs(spotlight_sum - pool) > tolerance:
            violations.append(
                f"各层聚光放大预算合计 {spotlight_sum:g} 与 amplification_pool_cny {pool:g} 不自洽"
            )
    paid = _num(_as_dict(output.get("budget_split")).get("paid_budget_cny"))
    if paid:
        low, high = AMPLIFICATION_RATIO_BAND
        ratio = pool / paid
        if not (low - 0.01 <= ratio <= high + 0.01):
            violations.append(
                f"amplification_pool_cny {pool:g} / paid {paid:g} = {ratio:.3f} "
                f"越出 amplification_ratio 护栏 {low}–{high}"
            )
    return violations


def invariant_m5_bid_plan(output: dict, req: dict) -> list[str]:
    """无基准 CPC 证据时出价必须为 null；有证据时区间 low<high。"""
    violations: list[str] = []
    plan = _as_dict(output.get("bid_plan"))
    baseline = _req_baseline(req, "cpc", "cost_per_click")
    for stage in ("cold_start", "scaling"):
        band = plan.get(stage)
        if band is None:
            continue
        band = _as_dict(band)
        low, high = _num(band.get("low_cny")), _num(band.get("high_cny"))
        if baseline is None:
            violations.append(f"无基准 CPC 证据时 bid_plan.{stage} 必须为 null（禁止编造出价）")
            continue
        if low is None or high is None:
            violations.append(f"bid_plan.{stage} 区间不完整：{band!r}")
        elif low >= high:
            violations.append(f"bid_plan.{stage} low_cny {low:g} 必须小于 high_cny {high:g}")
    if not _text(plan.get("basis")).strip():
        violations.append("bid_plan.basis 不能为空（必须说明出价依据或证据缺口）")
    return violations


# ---------------------------------------------------------------------------
# 模块6：关键词策略
# ---------------------------------------------------------------------------
def invariant_m6_level_budget_split(output: dict, req: dict) -> list[str]:
    """三级预算比例合计 = 1（±0.01），单项落在 [0,1]。"""
    violations: list[str] = []
    split = _as_dict(output.get("level_budget_split"))
    total = 0.0
    for key in ("core", "long_tail", "blue_ocean"):
        value = _num(split.get(key))
        if value is None:
            violations.append(f"level_budget_split.{key} 缺失")
            continue
        if not (0.0 <= value <= 1.0):
            violations.append(f"level_budget_split.{key}={value:g} 越出 [0,1]")
        total += value
    if abs(total - 1.0) > SHARE_TOLERANCE:
        violations.append(f"level_budget_split 合计必须为 1.0，当前 {total:.3f}")
    return violations


def invariant_m6_keyword_levels(output: dict, req: dict) -> list[str]:
    """各级数量下限对齐 tools/keywords（core≥2/long_tail≥4/blue_ocean≥2），并全局去重。"""
    violations: list[str] = []
    levels = _as_dict(output.get("keyword_levels"))
    words: list[str] = []
    for key, minimum in (
        ("core", MIN_CORE),
        ("long_tail", MIN_LONG_TAIL),
        ("blue_ocean", MIN_BLUE_OCEAN),
    ):
        rows = _as_list(levels.get(key))
        if len(rows) < minimum:
            violations.append(f"keyword_levels.{key} 需 ≥{minimum}，当前 {len(rows)}")
        for row in rows:
            word = _text(_as_dict(row).get("keyword")).casefold().strip()
            if word:
                words.append(word)
    duplicates = sorted({word for word in words if words.count(word) > 1})
    if duplicates:
        violations.append("keyword_levels 跨级重复词（工具层要求去重）：" + "、".join(duplicates[:5]))
    return violations


def invariant_m6_trending_monitor(output: dict, req: dict) -> list[str]:
    """无合规趋势源时 data_source_status 必须标注「待接入数据源」（铁律 4）。

    接入模拟实时源后（source_name 带「模拟实时数据源」前缀）允许改写措辞，
    但必须仍然点明是模拟/待接入，不得表述为真实平台热搜。
    """
    violations: list[str] = []
    monitor = _as_dict(output.get("trending_monitor"))
    status = _text(monitor.get("data_source_status")).strip()
    if not status:
        return ["trending_monitor.data_source_status 缺失"]
    trending = _as_list(_as_dict(req).get("trending_keyword_evidence"))
    has_realtime_mock = any(
        "模拟实时数据源" in _text(_as_dict(row).get("source_name")) for row in trending
    )
    if not trending:
        if "待接入数据源" not in status:
            violations.append(
                f"无趋势词证据时 data_source_status 必须标注「待接入数据源」，当前「{status}」"
            )
    elif has_realtime_mock and not any(
        marker in status for marker in ("模拟", "演示", "待接入", "待验证")
    ):
        violations.append(
            f"接入的是模拟实时数据源，data_source_status 必须点明模拟/演示属性，当前「{status}」"
        )
    criteria = _as_list(monitor.get("follow_criteria"))
    if not (2 <= len(criteria) <= 4):
        violations.append(f"trending_monitor.follow_criteria 需 2-4 条，当前 {len(criteria)}")
    return violations


def invariant_m6_rising_keywords(output: dict, req: dict) -> list[str]:
    """rising_keywords 的三值枚举 + 诚实性：无热搜证据时必须为空。

    诚实性口径以**请求里的热搜证据**为准：模块运行时虽然会从实时数据源 DB 取值，
    但接线层（main.py 的 use_realtime_feed → merge_feed_into_request）会把实时条目
    并入 request.trending_keyword_evidence，请求因此始终是可审计的证据面；
    请求里一条热搜证据都没有却给出 rising_keywords，就是编造实时结论。

    recommendation 三值镜像 tools/trending.py 的 RECOMMENDATIONS 与
    module_agents/module6.py 的 Literal 契约，改一处要同步这里。
    """
    violations: list[str] = []
    monitor = _as_dict(output.get("trending_monitor"))
    rows = _as_list(monitor.get("rising_keywords"))
    if not rows:
        return violations

    trending = _as_list(_as_dict(req).get("trending_keyword_evidence"))
    if not trending:
        violations.append(
            f"请求无热搜词证据时 rising_keywords 必须为空（诚实性），当前 {len(rows)} 条"
        )
    if len(rows) > MAX_RISING_KEYWORDS:
        violations.append(
            f"trending_monitor.rising_keywords 最多 {MAX_RISING_KEYWORDS} 条，当前 {len(rows)}"
        )
    for index, row in enumerate(rows):
        item = _as_dict(row)
        recommendation = _text(item.get("recommendation")).strip()
        if recommendation not in RISING_KEYWORD_RECOMMENDATIONS:
            violations.append(
                f"rising_keywords[{index}].recommendation 只能是"
                f"「{'/'.join(RISING_KEYWORD_RECOMMENDATIONS)}」之一，当前「{recommendation}」"
            )
        if not _text(item.get("keyword")).strip():
            violations.append(f"rising_keywords[{index}].keyword 缺失")
        if _num(item.get("heat_score")) is None:
            violations.append(f"rising_keywords[{index}].heat_score 必须是数字（照抄数据源取值）")
    return violations


# ---------------------------------------------------------------------------
# 全局不变量：未来类数值必须区间化（六模块通用）
# ---------------------------------------------------------------------------
# docs/no-code-agent/01_全局证据与数据纪律.md 第 2 节 + 04_指标单一事实源规范.md 第 2 节：
# 未来预测、建议出价、ROI 预估必须用范围而非伪精确单点。命中下列路径提示的数字字段
# 必须成对出现区间（low/high 或 band/range）；roi_point 允许存在但必须伴随 roi_band。
FUTURE_RANGE_PATH_HINTS = ("roi", "bid", "estimate", "预估")
_RANGE_SIBLING_HINTS = ("band", "range", "区间")
_LOW_HINTS = ("low", "min", "下限")
_HIGH_HINTS = ("high", "max", "上限")


def _path_is_future_valued(path: str) -> bool:
    lowered = path.casefold()
    return any(hint in lowered for hint in FUTURE_RANGE_PATH_HINTS)


def _has_range_sibling(node: dict[str, Any]) -> bool:
    for key, value in node.items():
        lowered = str(key).casefold()
        if any(hint in lowered for hint in _RANGE_SIBLING_HINTS) and value not in (None, "", [], {}):
            return True
    return False


def _counterpart(key: str, froms: tuple[str, ...], tos: tuple[str, ...]) -> str | None:
    lowered = str(key).casefold()
    for source, target in zip(froms, tos):
        if source in lowered:
            return lowered.replace(source, target)
    return None


def _sibling_number(node: dict[str, Any], wanted_key: str) -> float | None:
    for key, value in node.items():
        if str(key).casefold() == wanted_key:
            return _num(value)
    return None


def invariant_future_values_are_ranged(output: dict, req: dict) -> list[str]:
    """roi / 出价 / 预估类数字字段必须成对区间化，单点未来值记违规。

    - `*_point`（如 forecast.roi_point）必须伴随同级 band/range 且非空；
    - `*low*` 必须有对应 `*high*`（反之亦然），两端都要有数字；
    - 其余落在 roi/bid/estimate 路径下的孤立数字，必须有同级区间或 low/high 对。
    已满足契约的输出（bidding.cold_start 的 bid_low/bid_high、forecast.roi_band）自然通过。
    """
    violations: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{path}.{key}" if path else str(key)
                if _num(value) is not None and _path_is_future_valued(child):
                    violations.extend(_check_future_number(node, str(key), child))
                walk(value, child)
        elif isinstance(node, (list, tuple)):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")

    def _check_future_number(node: dict[str, Any], key: str, path: str) -> list[str]:
        lowered = key.casefold()
        if lowered.endswith("_point") or lowered.endswith("point"):
            if not _has_range_sibling(node):
                return [f"{path} 是未来类单点值，必须同时给出区间（band/range）"]
            return []
        counterpart = _counterpart(key, _LOW_HINTS, _HIGH_HINTS)
        if counterpart is None:
            counterpart = _counterpart(key, _HIGH_HINTS, _LOW_HINTS)
        if counterpart is not None:
            if _sibling_number(node, counterpart) is None:
                return [f"{path} 缺少配对的区间另一端（{counterpart}），未来值不得给单点"]
            return []
        if _has_range_sibling(node):
            return []
        for sibling in node:
            if any(hint in str(sibling).casefold() for hint in _LOW_HINTS + _HIGH_HINTS):
                return []
        return [f"{path} 是未来类单点值，必须成对给出区间（low/high 或 band）"]

    walk(_as_dict(output), "")
    return violations


# ---------------------------------------------------------------------------
# 黄金断言集
# ---------------------------------------------------------------------------
InvariantFn = Callable[[dict, dict], list[str]]

GOLDEN_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "module1": {
        "label": "模块1：赛道与竞品分析",
        "spec_name": "module1_market_competitor",
        "honesty_markers": [
            {
                "id": "sample_not_platform_wide",
                "any_of": ["不等于全平台大盘", "不代表全平台大盘", "≠全平台大盘"],
                "why": "SYSTEM_PROMPT 铁律5：boundary_note 必须声明本样本不等于全平台大盘",
            },
            {
                "id": "no_competitor_budget_guess",
                "any_of": ["禁止推测竞品预算", "需人工核验"],
                "why": "铁律2：budget_inference_policy 取自工具，绝不写竞品预算数字",
            },
            {
                "id": "targeting_is_hypothesis",
                "any_of": ["假设"],
                "why": "铁律3：targeting_hypotheses 每条必须措辞为假设，不得表述为竞品真实定向",
            },
        ],
        "numeric_invariants": [
            invariant_m1_paid_landscape_sources,
            invariant_m1_ad_labeled_count,
            invariant_m1_organic_sample,
            invariant_future_values_are_ranged,
        ],
        "required_structure": [
            "organic_landscape.sample_size",
            "organic_landscape.boundary_note",
            "organic_landscape.content_form_advice",
            "paid_landscape",
            "competitor_breakdown.ad_labeled_count",
            "competitor_breakdown.budget_inference_policy",
            "competitor_breakdown.targeting_hypotheses",
            "risk_alerts.*.action",
            "human_review_items",
        ],
    },
    "module2": {
        "label": "模块2：用户画像与内容策略",
        "spec_name": "module2_audience_content",
        "honesty_markers": [
            {
                "id": "tag_status_needs_backend_check",
                "any_of": ["标签需在聚光后台核对可用性"],
                "why": "Persona 契约校验器强制：定向标签可用性必须回聚光后台核对",
            },
            {
                "id": "human_review_declared",
                "any_of": ["需人工", "待验证", "核对", "核验", "待确认"],
                "why": "human_review_items 必须点明需人工拍板/核验的事项",
            },
        ],
        "numeric_invariants": [
            invariant_m2_directions_and_topics,
            invariant_m2_screening_thresholds,
            invariant_m2_scores_in_range,
            invariant_future_values_are_ranged,
        ],
        "required_structure": [
            "persona.demographic",
            "persona.targeting_tags.interest_tags",
            "persona.targeting_tags.crowd_packages",
            "persona.tag_status",
            "content_directions.*.organic_score",
            "content_directions.*.paid_score",
            "topics.*.direction",
            "topics.*.outline",
            "material_screening.ctr_threshold",
            "material_screening.engagement_threshold",
            "human_review_items",
        ],
    },
    "module3": {
        "label": "模块3：关键词策略与达人匹配",
        "spec_name": "module3_keyword_creator",
        "honesty_markers": [
            {
                "id": "creator_list_needs_pgy_review",
                "any_of": ["蒲公英"],
                "why": "铁律3 + 工具 policy：达人名单必须经蒲公英/授权达人库复核，不足名额不编造",
            },
            {
                "id": "no_fabricated_slots",
                "any_of": ["不编造", "如实", "待补", "补齐", "缺口"],
                "why": "名额不足时只给 open_slots，禁止补造达人",
            },
        ],
        "numeric_invariants": [
            invariant_m3_creator_plan_self_consistent,
            invariant_m3_keyword_tracks,
            invariant_m3_matched_creators,
            invariant_future_values_are_ranged,
        ],
        "required_structure": [
            "keyword_tracks.organic.core",
            "keyword_tracks.organic.long_tail",
            "keyword_tracks.organic.blue_ocean",
            "keyword_tracks.search_ads.*.bid_note",
            "keyword_tracks.feed_ads.*.bid_note",
            "creator_plan.tiers.*.collaboration_budget_cny",
            "creator_plan.tiers.*.spotlight_amplification_budget_cny",
            "creator_plan.amplification_pool_cny",
            "matched_creators",
            "open_slots",
            "human_review_items",
        ],
    },
    "module4": {
        "label": "模块4：聚光投流前置决策",
        "spec_name": "module4_spotlight_decision",
        "honesty_markers": [
            {
                "id": "forecast_evidence_status",
                "any_of": ["证据齐全", "证据不足", "待补数据"],
                "why": "forecast.status 必须原样承接 estimate_paid_performance 的证据成色结论",
            },
            {
                "id": "demo_cvr_pending_confirmation",
                "any_of": ["待投手确认", "演示补全", "真实CVR复核", "待复核", "待确认", "待验证"],
                "why": "曲奇四重奏的 CVR 是演示补全值，基于它的预估必须带「待确认」类标注",
            },
            {
                "id": "bid_basis_declared",
                "any_of": ["基准CPC", "基准 CPC", "账户实时建议价", "建议价"],
                "why": "铁律1：出价必须写明基准与倍率来源，或说明缺基准需用账户建议价",
            },
        ],
        "numeric_invariants": [
            invariant_m4_budget_shares,
            invariant_m4_bidding,
            invariant_m4_forecast,
            invariant_m4_risk_playbook,
            invariant_future_values_are_ranged,
        ],
        "required_structure": [
            "account_structure.campaign_naming_rule",
            "account_structure.campaigns.*.budget_share",
            "account_structure.campaigns.*.placement",
            "targeting_packages.*.budget_share",
            "bidding.cold_start.basis",
            "bidding.scaling_rules",
            "search_feed_split.search",
            "search_feed_split.feed",
            "daily_schedule.*.time_range",
            "forecast.test_budget_cny",
            "forecast.status",
            "risk_playbook.*.response",
            "human_review_items",
        ],
    },
    "module5": {
        "label": "模块5：全域预算与节奏",
        "spec_name": "module5_budget_planning",
        "honesty_markers": [
            {
                "id": "bid_basis_or_gap",
                "any_of": ["基准CPC", "基准 CPC", "无历史CPC", "缺基准", "建议价"],
                "why": "铁律3：出价必须写明基准依据；无证据时说明缺口而不是编造",
            },
            {
                "id": "demo_cvr_pending_confirmation",
                "any_of": ["待投手确认", "演示补全", "待复核", "待确认", "待验证", "需人工"],
                "why": "演示补全 CVR / 无自然历史时，联动门槛与出价必须带待确认标注",
            },
        ],
        "numeric_invariants": [
            invariant_m5_budget_split,
            invariant_m5_phases,
            invariant_m5_creator_tier_plan,
            invariant_m5_bid_plan,
            invariant_future_values_are_ranged,
        ],
        "required_structure": [
            "budget_split.organic_budget_cny",
            "budget_split.paid_budget_cny",
            "budget_split.organic_ratio",
            "phases.*.paid_budget_cny",
            "phases.*.key_actions",
            "creator_tier_plan.amplification_pool_cny",
            "bid_plan.basis",
            "synergy_rules.*.action",
            "contingency_plans.*.adjustment",
            "human_review_items",
        ],
    },
    "module6": {
        "label": "模块6：关键词策略",
        "spec_name": "module6_keyword_strategy",
        "honesty_markers": [
            {
                "id": "trending_source_status",
                "any_of": ["待接入数据源", "模拟实时数据源", "实时热搜（模拟源）", "模拟源"],
                "why": "铁律4：无合规实时源必须标「待接入数据源」；接入模拟源必须点明模拟属性",
            },
            {
                "id": "seed_keywords_pending_validation",
                "any_of": ["待验证", "种子词", "需核对", "核对", "复核"],
                "why": "无证据主题时关键词只能是待验证种子词，不得当作热搜/蓝海结论",
            },
        ],
        "numeric_invariants": [
            invariant_m6_level_budget_split,
            invariant_m6_keyword_levels,
            invariant_m6_trending_monitor,
            invariant_m6_rising_keywords,
            invariant_future_values_are_ranged,
        ],
        "required_structure": [
            "keyword_levels.core.*.keyword",
            "keyword_levels.long_tail.*.keyword",
            "keyword_levels.blue_ocean.*.keyword",
            "layout_rules.*.rule",
            "level_budget_split.core",
            "level_budget_split.long_tail",
            "level_budget_split.blue_ocean",
            "trending_monitor.mechanism",
            "trending_monitor.data_source_status",
            "human_review_items",
        ],
    },
}

MODULE_KEYS: list[str] = list(GOLDEN_EXPECTATIONS)

# spec.name（如 module4_spotlight_decision）→ 规范键（module4）
_SPEC_ALIASES: dict[str, str] = {
    str(spec["spec_name"]): key for key, spec in GOLDEN_EXPECTATIONS.items()
}


def normalize_module_name(module_name: str) -> str | None:
    """把 module1 / module1_market_competitor / 模块1 之类的写法归一到规范键。"""
    name = (module_name or "").strip()
    if name in GOLDEN_EXPECTATIONS:
        return name
    if name in _SPEC_ALIASES:
        return _SPEC_ALIASES[name]
    lowered = name.casefold()
    for key in GOLDEN_EXPECTATIONS:
        if lowered.startswith(key):
            return key
    for digit, key in ((str(index), f"module{index}") for index in range(1, 7)):
        if name in (f"模块{digit}", f"m{digit}", f"M{digit}"):
            return key
    return None


def golden_for(module_name: str) -> dict[str, Any] | None:
    key = normalize_module_name(module_name)
    return GOLDEN_EXPECTATIONS.get(key) if key else None


def check_invariants(module_name: str, output: dict, req: dict) -> list[str]:
    """跑某模块的全部数字不变量，返回违规描述列表（函数本身抛异常也记成违规）。"""
    golden = golden_for(module_name)
    if not golden:
        return [f"未知模块 {module_name!r}，无黄金断言"]
    violations: list[str] = []
    for fn in golden["numeric_invariants"]:
        try:
            violations.extend(fn(_as_dict(output), _as_dict(req)))
        except Exception as exc:  # 不变量函数不应因脏数据崩掉评分
            violations.append(f"不变量 {fn.__name__} 执行异常：{exc.__class__.__name__}: {exc}")
    return violations
