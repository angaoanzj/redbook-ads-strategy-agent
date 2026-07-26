import json
import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from creator_csv import parse_creator_csv
from engine import run_strategy
from models import CampaignRequest, MetricEvidence


ROOT = Path(__file__).resolve().parents[1]


def sample_request() -> CampaignRequest:
    return CampaignRequest(
        brand_name="曲奇四重奏",
        category="香港曲奇伴手礼",
        product_name="曲奇礼盒",
        selling_points=["香港伴手礼", "多口味", "礼盒送礼"],
        price_min=120,
        price_max=320,
        initial_audience="25-40岁女性",
        total_budget_cny=100000,
        spotlight_budget_cny=70000,
        campaign_days=30,
        goal="conversion",
    )


class StrategyEngineTests(unittest.TestCase):
    def test_seed_reproduces_all_mock_modules(self):
        first = run_strategy(sample_request(), use_model=False, allow_mock=True, mock_seed="report-a")
        repeated = run_strategy(sample_request(), use_model=False, allow_mock=True, mock_seed="report-a")
        changed = run_strategy(sample_request(), use_model=False, allow_mock=True, mock_seed="report-b")

        self.assertEqual(first.modules, repeated.modules)
        self.assertNotEqual(first.modules, changed.modules)
        market = first.modules["module_1_market_competitor"]["simulated_platform_market"]
        self.assertEqual(len(market["series"]), 30)
        self.assertEqual(market["mock_seed"], "report-a")
        competitors = first.modules["module_1_market_competitor"]["competitor_full_funnel"]["accounts"]
        self.assertGreaterEqual(len(competitors), 3)
        self.assertEqual(len(first.modules["module_3_keyword_creator"]["creator_candidates"]), 20)
        mock_trace = next(row for row in first.trace if row.get("stage") == "mock_fallback")
        self.assertEqual(mock_trace["mock_seed"], "report-a")
        self.assertIn("report-a", first.report_markdown)

    def test_every_mock_object_exposes_seed_and_warning(self):
        result = run_strategy(
            sample_request(), use_model=False, allow_mock=True, mock_seed="audit-a"
        )
        missing = []

        def walk(value, path="modules"):
            if isinstance(value, dict):
                if value.get("is_mock") is True:
                    for field in (
                        "data_type", "evidence_grade", "source_name",
                        "mock_basis", "mock_seed", "warning",
                    ):
                        if not value.get(field):
                            missing.append(f"{path}.{field}")
                for key, child in value.items():
                    walk(child, f"{path}.{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, f"{path}[{index}]")

        walk(result.modules)
        self.assertEqual(missing, [])

    def test_allow_mock_completes_missing_spotlight_metrics(self):
        result = run_strategy(sample_request(), use_model=False, allow_mock=True)
        cpc = result.modules["module_1_market_competitor"]["spotlight_market"]["average_cpc"]

        self.assertTrue(cpc["is_mock"])
        self.assertEqual(cpc["data_type"], "模拟数据（Mock）")
        self.assertIsNotNone(cpc["value"])
        self.assertIn("不代表真实平台", cpc["warning"])
        self.assertIn("模拟数据（Mock）", result.report_markdown)
        self.assertIn("转化成本", result.report_markdown)
        targeting = result.modules["module_1_market_competitor"]["competitor_full_funnel"]["targeting_inference"]
        self.assertEqual(
            targeting["warning"],
            "仅用于方案演示和敏感性分析，不代表真实平台、竞品或账户数据。",
        )
        # Mock 可补齐演示缺口，但不得伪装成真实推荐/实时热搜
        module3 = result.modules["module_3_keyword_creator"]
        self.assertGreater(len(module3["creator_candidates"]), 0)
        self.assertTrue(all(item["is_mock"] for item in module3["creator_candidates"]))
        self.assertTrue(all(not item["is_recommendation"] for item in module3["creator_candidates"]))
        self.assertTrue(all("Mock" in (item["source"] or "") for item in module3["creator_candidates"]))
        self.assertEqual(module3["creator_roster"]["real_candidate_count"], 0)
        self.assertGreater(module3["creator_roster"]["mock_candidate_count"], 0)
        self.assertIn("Mock 演示达人", result.report_markdown)
        self.assertNotIn("待筛选达人", result.report_markdown)
        trending = result.modules["module_6_keyword_strategy"]["trending_monitor"]
        self.assertIn("Mock", trending["status"])
        self.assertTrue(all(row["is_mock"] for row in trending["scored_keywords"]))
        self.assertTrue(
            any(row.get("injected_fields") for row in result.trace if row.get("stage") == "mock_fallback")
        )
        self.assertEqual(result.data_confidence, "low")
        self.assertTrue(any("Mock" in gap.impact for gap in result.evidence_gaps))

    def test_disallow_mock_preserves_spotlight_gap(self):
        result = run_strategy(sample_request(), use_model=False, allow_mock=False)
        cpc = result.modules["module_1_market_competitor"]["spotlight_market"]["average_cpc"]

        self.assertIsNone(cpc["value"])
        self.assertFalse(cpc["is_mock"])
        module3 = result.modules["module_3_keyword_creator"]
        self.assertEqual(module3["creator_candidates"], [])
        self.assertEqual(module3["creator_recommendations_20"], [])
        self.assertEqual(module3["creator_roster"]["mock_candidate_count"], 0)
        self.assertGreater(module3["creator_roster"]["open_slot_count"], 0)
        self.assertTrue(module3["creator_roster"]["open_slots"])
        self.assertNotIn("待筛选达人", result.report_markdown)

    def test_real_creator_csv_not_padded_with_mock(self):
        creators = parse_creator_csv(
            (ROOT / "examples" / "creators_cookie_quartet.csv").read_text(encoding="utf-8")
        )
        request = sample_request().model_copy(update={"creator_evidence": creators})
        result = run_strategy(request, use_model=False, allow_mock=True)
        module3 = result.modules["module_3_keyword_creator"]
        self.assertEqual(len(module3["creator_candidates"]), len(creators))
        self.assertEqual(module3["creator_roster"]["real_candidate_count"], len(creators))
        self.assertEqual(module3["creator_roster"]["mock_candidate_count"], 0)
        self.assertTrue(all(item["is_recommendation"] for item in module3["creator_candidates"]))
        self.assertTrue(all(not item["is_mock"] for item in module3["creator_candidates"]))
        self.assertFalse(
            any(
                field.get("field") == "creator_evidence"
                for row in result.trace
                if row.get("stage") == "mock_fallback"
                for field in row.get("injected_fields") or []
            )
        )

    def test_real_benchmark_replaces_mock(self):
        request = sample_request().model_copy(update={
            "benchmark_evidence": [MetricEvidence(
                source_name="品牌聚光报表",
                collected_at="2026-07-01",
                metric_name="cpc",
                value=1.9,
                unit="元/点击",
                evidence_grade="A_authorized",
            )],
        })
        result = run_strategy(request, use_model=False, allow_mock=True)
        cpc = result.modules["module_1_market_competitor"]["spotlight_market"]["average_cpc"]

        self.assertEqual(cpc["value"], 1.9)
        self.assertFalse(cpc["is_mock"])
        self.assertEqual(cpc["data_type"], "真实样本")

    def test_generates_all_six_modules_and_budget_balance(self):
        result = run_strategy(sample_request(), use_model=False)
        self.assertEqual(
            len([k for k in result.modules if not str(k).startswith("bonus_")]),
            6,
        )
        budget = result.modules["module_5_budget_pacing"]["budget"]
        self.assertEqual(budget["organic_content_cny"] + budget["spotlight_cny"], 100000)
        # 转化目标默认 3:7
        self.assertEqual(budget["ratio_label"], "3:7")
        self.assertEqual(budget["organic_ratio"], 0.30)
        self.assertEqual(budget["spotlight_ratio"], 0.70)
        self.assertIn("成交", budget["split_rationale"])
        self.assertEqual(len(budget["goal_split_matrix"]), 6)
        self.assertEqual(result.data_confidence, "low")

    def test_budget_split_follows_goal_defaults(self):
        awareness = sample_request().model_copy(update={"goal": "awareness"})
        search = sample_request().model_copy(update={"goal": "search_growth"})
        a_budget = run_strategy(awareness, use_model=False).modules["module_5_budget_pacing"]["budget"]
        s_budget = run_strategy(search, use_model=False).modules["module_5_budget_pacing"]["budget"]
        self.assertEqual(a_budget["ratio_label"], "5:5")
        self.assertEqual(a_budget["organic_ratio"], 0.50)
        self.assertIn("曝光", a_budget["split_rationale"])
        self.assertEqual(s_budget["ratio_label"], "4:6")
        self.assertEqual(s_budget["organic_ratio"], 0.40)
        section = next(
            row
            for row in run_strategy(awareness, use_model=False).report_view["report_sections"]
            if row["key"] == "budget"
        )
        self.assertEqual(section["visuals"]["budget_split"]["ratio_label"], "5:5")
        self.assertTrue(any(row.get("is_current") for row in section["visuals"]["goal_split_matrix"]))

    def test_keyword_strategy_handoff_to_creator_module(self):
        result = run_strategy(sample_request(), use_model=False)
        module6 = result.modules["module_6_keyword_strategy"]
        module3 = result.modules["module_3_keyword_creator"]
        self.assertTrue(module6["keyword_levels"]["core"])
        self.assertTrue(module6["keyword_levels"]["long_tail"])
        self.assertIn("blue_ocean", module6["keyword_levels"])
        self.assertAlmostEqual(
            sum(module6["level_budget_split"].values()), 1.0, places=2
        )
        self.assertIn("layout_plan", module6["layout"])
        self.assertIn("trending_monitor", module6)
        ref = module3["keyword_strategy_ref"]
        self.assertEqual(ref["levels"]["core"], module6["keyword_levels"]["core"])
        section = next(
            s for s in result.report_view["report_sections"] if s["key"] == "creator_keyword"
        )
        self.assertIn("承接", section["decision"])
        self.assertTrue(section["visuals"].get("keyword_strategy_ref"))

    def test_campaign_phases_follow_warmup_burst_tail(self):
        result = run_strategy(sample_request(), use_model=False)
        module5 = result.modules["module_5_budget_pacing"]
        phases = module5["phases"]
        self.assertEqual([p["name"] for p in phases], ["预热期", "爆发期", "长尾期"])
        self.assertEqual([p["paid_ratio"] for p in phases], [0.20, 0.60, 0.20])
        paid_total = module5["budget"]["spotlight_cny"]
        self.assertEqual(sum(p["paid_budget_cny"] for p in phases), paid_total)
        self.assertEqual(sum(p["days"] for p in phases), 30)
        self.assertIn("自然内容铺量", phases[0]["summary"])
        self.assertIn("小预算聚光", phases[0]["paid_focus"])
        self.assertIn("大规模放量", phases[1]["summary"])
        self.assertIn("搜索词占位", phases[2]["summary"])
        self.assertTrue(phases[0]["key_actions"])
        synergy = module5["organic_paid_synergy"]
        self.assertIn("CTR", synergy["start_paid_when"]["rule_text"])
        self.assertGreaterEqual(len(synergy["triggers"]), 2)
        self.assertTrue(synergy["recirculation_loops"])
        self.assertGreaterEqual(len(module5["emergency_playbook"]), 3)
        self.assertTrue(module5["upstream_handoff"]["note"])
        section = next(s for s in result.report_view["report_sections"] if s["key"] == "budget")
        self.assertEqual(section["title"], "全域预算与节奏规划")
        self.assertIn("预热期", section["decision"])
        self.assertEqual(len(section["visuals"]["phases"]), 3)
        self.assertTrue(section["visuals"]["organic_paid_synergy"]["triggers"])
        self.assertGreaterEqual(len(section["visuals"]["emergency_playbook"]), 3)

    def test_missing_live_data_is_disclosed_not_invented(self):
        result = run_strategy(sample_request(), use_model=False)
        self.assertGreaterEqual(len(result.evidence_gaps), 3)
        module3 = result.modules["module_3_keyword_creator"]
        creators = module3["creator_recommendations_20"]
        self.assertEqual(creators, [])
        self.assertEqual(module3["creator_roster"]["real_candidate_count"], 0)
        self.assertGreater(module3["creator_roster"]["open_slot_count"], 0)
        self.assertIn("不输出推荐名单", module3["creator_data_status"])
        self.assertEqual(len(module3["creator_tier_plan"]["tiers"]), 3)
        trending = result.modules["module_6_keyword_strategy"]["trending_monitor"]
        self.assertIn("人工粘贴", trending["status"])
        forecast = result.modules["module_4_spotlight_decision"]["forecast"]
        self.assertIn("cold_start_budget_cny", forecast["test_bandwidth"])
        self.assertIn("formula", forecast["stop_loss"])
        self.assertEqual(len(result.modules["module_4_spotlight_decision"]["risk_playbook"]), 5)
        # 无演示情景时 SOP 仍完整，但不挂 demo_scenario
        self.assertTrue(
            all("demo_scenario" not in item for item in result.modules["module_4_spotlight_decision"]["risk_playbook"])
        )
        self.assertIn(
            "官方规则",
            result.modules["module_1_market_competitor"]["risk_warning"]["official_rules"]["label"],
        )

    def test_keyword_tiers_are_globally_deduped_from_kb_notes(self):
        payload = sample_request().model_dump()
        payload["category_note_evidence"] = [
            {
                "search_keyword": "香港伴手礼",
                "search_sort": "综合",
                "search_rank": index,
                "note_id": f"kw-note-{index}",
                "note_url": f"https://example.com/kw-note-{index}",
                "title": title,
                "note_type": "图文",
                "likes": 80 + index,
                "favorites": 20,
                "comments": 3,
                "shares": 1,
                "tags": tags,
                "published_at": "2026-07-01T12:00:00Z",
                "collected_at": "2026-07-24T00:00:00Z",
                "source_name": "个人研究公开样本",
            }
            for index, (title, tags) in enumerate(
                [
                    ("香港伴手礼推荐", ["香港伴手礼", "送礼"]),
                    ("蝴蝶酥怎么选", ["蝴蝶酥", "怎么选"]),
                    ("曲奇礼盒测评", ["曲奇礼盒", "测评"]),
                    ("小众手信清单", ["小众手信", "清单"]),
                    ("港式下午茶", ["港式下午茶"]),
                ],
                start=1,
            )
        ]
        result = run_strategy(CampaignRequest(**payload), use_model=False)
        dual = result.modules["module_3_keyword_creator"]["dual_track_keyword_library"]
        organic = dual["organic_traffic"]
        core = organic["core_keywords"]
        long_tail = organic["long_tail_keywords"]
        blue = organic["blue_ocean_candidates_to_validate"]
        self.assertGreaterEqual(len(core), 2)
        self.assertGreaterEqual(len(long_tail), 4)
        self.assertGreaterEqual(len(blue), 2)
        folded = [k.casefold() for k in (*core, *long_tail, *blue)]
        self.assertEqual(len(folded), len(set(folded)), folded)
        self.assertIn("知识库", dual.get("pipeline") or dual.get("status") or "")
        self.assertTrue(
            "香港伴手礼" in (*core, *long_tail, *blue)
            or "蝴蝶酥" in (*core, *long_tail, *blue)
            or "曲奇礼盒" in (*core, *long_tail, *blue)
        )
        # 场景词应从知识库标签/标题识别（送礼、下午茶等），而非品牌拼接
        scene = organic["scene_keywords"]
        self.assertTrue(any(k in scene for k in ("送礼", "港式下午茶", "小众手信")))

    def test_scene_audience_keywords_mined_from_knowledge_notes(self):
        payload = sample_request().model_dump()
        payload["category_note_evidence"] = [
            {
                "search_keyword": "香港伴手礼",
                "search_sort": "综合",
                "search_rank": 1,
                "note_id": "role-1",
                "note_url": "https://example.com/role-1",
                "title": "25岁女生送礼攻略",
                "description": "上班族下午茶也适用",
                "note_type": "图文",
                "likes": 120,
                "favorites": 30,
                "comments": 4,
                "shares": 2,
                "tags": ["送礼", "宝妈", "下午茶"],
                "published_at": "2026-07-01T12:00:00Z",
                "collected_at": "2026-07-24T00:00:00Z",
                "source_name": "个人研究公开样本",
            },
            {
                "search_keyword": "职场女性",
                "search_sort": "综合",
                "search_rank": 2,
                "note_id": "role-2",
                "note_url": "https://example.com/role-2",
                "title": "职场女性伴手礼",
                "description": "办公室茶歇",
                "note_type": "图文",
                "likes": 90,
                "favorites": 20,
                "comments": 2,
                "shares": 1,
                "tags": ["职场女性", "办公室"],
                "published_at": "2026-07-02T12:00:00Z",
                "collected_at": "2026-07-24T00:00:00Z",
                "source_name": "个人研究公开样本",
            },
        ]
        result = run_strategy(CampaignRequest(**payload), use_model=False)
        organic = result.modules["module_3_keyword_creator"]["dual_track_keyword_library"][
            "organic_traffic"
        ]
        scene = set(organic["scene_keywords"])
        audience = set(organic["audience_keywords"])
        self.assertTrue(scene & {"送礼", "下午茶", "办公室"})
        self.assertTrue(audience & {"宝妈", "职场女性", "女生", "上班族"})

    def test_module_3_matches_assignment_contract_with_history_cpc(self):
        payload = sample_request().model_dump()
        payload["benchmark_evidence"] = [
            {
                "source_name": "品牌历史聚光报表",
                "collected_at": "2026-05-31",
                "metric_name": "cpc",
                "value": 0.30,
                "unit": "CNY/click",
            }
        ]
        result = run_strategy(CampaignRequest(**payload), use_model=False)
        module3 = result.modules["module_3_keyword_creator"]
        dual = module3["dual_track_keyword_library"]
        organic = dual["organic_traffic"]
        self.assertTrue(organic["long_tail_keywords"])
        self.assertTrue(organic["core_keywords"])
        self.assertTrue(organic["scene_keywords"])
        self.assertTrue(organic["audience_keywords"])
        folded = [
            k.casefold()
            for k in (
                *organic["core_keywords"],
                *organic["long_tail_keywords"],
                *organic["blue_ocean_candidates_to_validate"],
            )
        ]
        self.assertEqual(len(folded), len(set(folded)), folded)
        self.assertIn("title_keywords", organic["layout_plan"])
        self.assertIn("body_keywords", organic["layout_plan"])
        self.assertIn("tag_keywords", organic["layout_plan"])
        self.assertTrue(organic["layout_plan"].get("example"))
        search_rows = dual["spotlight_paid"]["search_promotion"]["keywords"]
        feed_rows = dual["spotlight_paid"]["feed_interest"]["keywords"]
        self.assertGreaterEqual(len(feed_rows), 3)
        feed_keyword = feed_rows[0]
        self.assertTrue(feed_keyword.get("interest_word") or feed_keyword.get("keyword"))
        # 搜索词按意向分档，禁止全表同一出价带
        bid_pairs = {
            (
                row["suggested_bid_range"]["low_cny_per_click"],
                row["suggested_bid_range"]["high_cny_per_click"],
            )
            for row in search_rows
        }
        self.assertGreaterEqual(len(bid_pairs), 2)
        high_row = next(row for row in search_rows if row.get("intent_code") == "high")
        mid_row = next(row for row in search_rows if row.get("intent_code") == "mid")
        # CPC=0.30：高意向 1.0–1.3 → 0.30–0.39；中意向 0.9–1.1 → 0.27–0.33
        self.assertEqual(high_row["suggested_bid_range"]["low_cny_per_click"], 0.30)
        self.assertEqual(high_row["suggested_bid_range"]["high_cny_per_click"], 0.39)
        self.assertEqual(mid_row["suggested_bid_range"]["low_cny_per_click"], 0.27)
        self.assertEqual(mid_row["suggested_bid_range"]["high_cny_per_click"], 0.33)
        # 信息流兴趣词：0.7–1.0 → 0.21–0.30
        self.assertEqual(feed_keyword["suggested_bid_range"]["low_cny_per_click"], 0.21)
        self.assertEqual(feed_keyword["suggested_bid_range"]["high_cny_per_click"], 0.30)
        self.assertIn("suggested_spotlight_per_note_cny", module3["creator_tier_plan"]["tiers"][0])

    def test_category_note_import_builds_market_summary_and_topics(self):
        payload = sample_request().model_dump()
        payload["category_note_evidence"] = [
            {
                "search_keyword": "香港伴手礼",
                "search_sort": "综合",
                "search_rank": 1,
                "note_id": "note-1",
                "note_url": "https://example.com/note-1",
                "title": "伴手礼推荐",
                "note_type": "图集",
                "likes": 100,
                "favorites": 50,
                "comments": 10,
                "shares": 5,
                "tags": ["香港伴手礼", "送礼"],
                "published_at": "2026-07-01T12:00:00Z",
                "collected_at": "2026-07-24T00:00:00Z",
                "source_name": "个人研究公开样本",
            }
        ]
        result = run_strategy(CampaignRequest(**payload), use_model=False)
        market = result.modules["module_1_market_competitor"]["organic_market"]
        self.assertEqual(market["sample_size"], 1)
        self.assertEqual(market["total_interactions"], 165)
        self.assertEqual(market["top_tags"][0]["tag"], "送礼")
        competitor = result.modules["module_1_market_competitor"]["competitor_full_funnel"]
        self.assertEqual(
            competitor["organic_hits_commonalities"]["status"],
            "基于品类笔记样本统计（对标主题尚未拆解）",
        )
        self.assertTrue(competitor["content_gaps"]["opportunities"])
        module2 = result.modules["module_2_audience_content"]
        self.assertIn("卖点", module2["topic_pipeline"])
        self.assertIn("画像", module2["topics"][0]["pipeline"])
        outlines = ["｜".join(t["outline"]) for t in module2["topics"]]
        self.assertGreaterEqual(len(set(outlines)), 10)
        schedules = result.modules["module_4_spotlight_decision"]["daily_schedules"]
        self.assertTrue(schedules["slots"])

    def test_paid_risk_demo_scenarios_attach_to_playbook(self):
        payload = sample_request().model_dump()
        payload["category_note_evidence"] = [
            {
                "search_keyword": "香港伴手礼",
                "search_rank": 1,
                "note_id": f"n-{hour}",
                "note_url": f"https://example.com/n-{hour}",
                "title": f"时段{hour}",
                "note_type": "图集",
                "likes": 500 + hour * 10,
                "favorites": 200,
                "comments": 20,
                "shares": 10,
                "tags": ["送礼"],
                "published_at": f"2026-07-24T{hour:02d}:00:00+00:00",
                "collected_at": "2026-07-24",
                "source_name": "Mock 时段样本",
                "is_mock": True,
            }
            for hour in (8, 12, 19, 20, 21)
            for _repeat in range(3)  # 单时段需≥3条才输出高峰建议
        ]
        payload["paid_risk_demo_scenarios"] = [
            {
                "issue": issue,
                "example_diagnosis": f"Mock：{issue}演示诊断",
                "demo_signals": {"flag": True},
                "source_name": "系统演示 Mock 补足",
                "collected_at": "2026-07-24",
                "is_mock": True,
                "evidence_grade": "M",
            }
            for issue in (
                "冷启动无量",
                "点击成本过高",
                "点击高但转化低",
                "素材衰退",
                "审核拒绝",
            )
        ]
        result = run_strategy(CampaignRequest(**payload), use_model=False, allow_mock=False)
        schedules = result.modules["module_4_spotlight_decision"]["daily_schedules"]
        self.assertEqual(len(schedules["slots"]), 5)
        roles = {slot["role"] for slot in schedules["slots"]}
        self.assertIn("夜间决策下单窗", roles)
        self.assertIn("午间碎片消费窗", roles)
        playbook = result.modules["module_4_spotlight_decision"]["risk_playbook"]
        self.assertEqual(len(playbook), 5)
        for item in playbook:
            self.assertTrue(item["demo_scenario"]["is_mock"])
            self.assertIn("Mock", item["demo_scenario"]["example_diagnosis"])
        self.assertIn("冷启动无量", result.report_markdown)

    def test_creator_csv_and_trending_scoring(self):
        creators = parse_creator_csv(
            (ROOT / "examples" / "creators_cookie_quartet.csv").read_text(encoding="utf-8")
        )
        payload = sample_request().model_dump()
        payload["creator_evidence"] = [item.model_dump(mode="json") for item in creators]
        payload["trending_keyword_evidence"] = [
            {
                "keyword": "香港伴手礼",
                "source_name": "人工粘贴热搜词",
                "collected_at": "2026-07-24",
                "heat_score": 90,
            },
            {
                "keyword": "最好吃的曲奇",
                "source_name": "人工粘贴热搜词",
                "collected_at": "2026-07-24",
                "heat_score": 80,
            },
        ]
        payload["account_violation_evidence"] = [
            {
                "reason": "绝对化用语",
                "occurrence_count": 4,
                "period": "2026-Q2",
                "source_name": "拒审台账",
                "collected_at": "2026-06-30",
            }
        ]
        result = run_strategy(CampaignRequest(**payload), use_model=False)
        module3 = result.modules["module_3_keyword_creator"]
        self.assertEqual(len(module3["creator_candidates"]), 8)
        self.assertTrue(all(item["is_recommendation"] for item in module3["creator_candidates"]))
        self.assertEqual(module3["creator_roster"]["real_candidate_count"], 8)
        self.assertGreaterEqual(module3["creator_roster"]["open_slot_count"], 12)
        self.assertTrue(module3["creator_roster"]["open_slots"])
        scored = result.modules["module_6_keyword_strategy"]["trending_monitor"]["scored_keywords"]
        self.assertEqual(len(scored), 2)
        risky = next(item for item in scored if item["keyword"] == "最好吃的曲奇")
        self.assertEqual(risky["scores"]["brand_risk_safety"], 1)
        freq = result.modules["module_1_market_competitor"]["risk_warning"][
            "category_high_frequency_violations"
        ]
        self.assertEqual(freq["ranked_reasons"][0]["reason"], "绝对化用语")

    def test_full_case_example_runs(self):
        payload = json.loads((ROOT / "examples" / "cookie_quartet_full_case.json").read_text())
        # Keep the case lean for unit speed while still covering filled evidence.
        payload["category_note_evidence"] = payload["category_note_evidence"][:12]
        result = run_strategy(CampaignRequest(**payload), use_model=False)
        self.assertEqual(
            len([k for k in result.modules if not str(k).startswith("bonus_")]),
            6,
        )
        self.assertGreater(len(result.modules["module_3_keyword_creator"]["creator_candidates"]), 0)
        self.assertIsNotNone(
            result.modules["module_4_spotlight_decision"]["forecast"]["test_bandwidth"][
                "cold_start_budget_cny"
            ]
        )
        self.assertTrue(result.report_markdown.startswith("# 曲奇四重奏"))

    def test_module_1_exposes_required_paid_competitor_and_risk_sections(self):
        result = run_strategy(sample_request(), use_model=False)
        module1 = result.modules["module_1_market_competitor"]
        self.assertIsNone(module1["spotlight_market"]["average_cpc"]["value"])
        spotlight = module1["spotlight_market"]
        for key in (
            "average_cpc",
            "average_cpm",
            "average_ctr",
            "interaction_cost",
            "conversion_cost",
            "popular_promotion_goals",
            "search_feed_budget_share",
            "latest_traffic_direction_2026",
        ):
            self.assertTrue(spotlight[key]["decision_conclusion"])
        self.assertIsInstance(spotlight["search_feed_budget_share"].get("search_ratio"), float)
        self.assertTrue(spotlight["popular_promotion_goals"].get("market_ranking"))
        competitor = module1["competitor_full_funnel"]
        for key in (
            "organic_hits_commonalities",
            "content_gaps",
            "paid_notes",
            "targeting_inference",
            "budget_range",
        ):
            self.assertTrue(competitor[key]["decision_conclusion"])
        risk = module1["risk_warning"]
        self.assertTrue(risk["recent_restricted_content_types"]["decision_conclusion"])
        self.assertTrue(risk["frequent_ad_rejection_reasons"]["decision_conclusion"])
        self.assertTrue(risk["official_rules"]["decision_conclusion"])
        self.assertTrue(risk["category_high_frequency_violations"]["decision_conclusion"])

    def test_rejects_invalid_budget(self):
        payload = sample_request().model_dump()
        payload["spotlight_budget_cny"] = 110000
        with self.assertRaises(ValidationError):
            CampaignRequest(**payload)


if __name__ == "__main__":
    unittest.main()
