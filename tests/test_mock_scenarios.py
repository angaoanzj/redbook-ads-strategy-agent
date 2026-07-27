import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mock_scenarios import (
    apply_demo_mock_evidence,
    build_mock_competitors,
    build_mock_creators,
    build_mock_market_scenarios,
    build_mock_notes,
    build_mock_platform_market,
    build_mock_paid_risk_scenarios,
    metric_or_mock,
)
from models import CampaignRequest, CreatorEvidence, MetricEvidence


class MockScenarioTests(unittest.TestCase):
    def test_same_seed_reproduces_market_scenarios(self):
        first = build_mock_market_scenarios(100000, "conversion", mock_seed="seed-a")
        second = build_mock_market_scenarios(100000, "conversion", mock_seed="seed-a")

        self.assertEqual(first, second)
        self.assertEqual(first["meta"]["mock_seed"], "seed-a")

    def test_different_seed_changes_market_scenarios(self):
        first = build_mock_market_scenarios(100000, "conversion", mock_seed="seed-a")
        second = build_mock_market_scenarios(100000, "conversion", mock_seed="seed-b")

        self.assertNotEqual(first["cpc"], second["cpc"])
        self.assertAlmostEqual(
            first["conversion_cost"]["base"],
            first["cpc"]["base"] / first["cvr"]["base"],
            delta=(first["cpc"]["base"] / first["cvr"]["base"]) * 0.06,
        )
        self.assertAlmostEqual(
            first["budget_share"]["search_ratio"]
            + first["budget_share"]["feed_ratio"],
            1.0,
        )
        # 搜推配比跟目标默认档，不随 seed 漂移（避免与模块4 40/60 打架）
        self.assertEqual(first["budget_share"]["search_ratio"], 0.40)
        self.assertEqual(first["budget_share"]["feed_ratio"], 0.60)
        self.assertEqual(
            first["budget_share"]["search_ratio"],
            second["budget_share"]["search_ratio"],
        )

    def test_mock_metric_has_visible_provenance(self):
        row = metric_or_mock(
            {},
            "cpc",
            label="CPC",
            mock_value=2.8,
            unit="元/点击",
            basis="首轮测试中位情景",
        )

        self.assertEqual(row["data_type"], "模拟数据（Mock）")
        self.assertTrue(row["is_mock"])
        self.assertEqual(row["evidence_grade"], "M")
        self.assertIn("不代表真实平台", row["warning"])

    def test_real_metric_wins_over_mock(self):
        row = metric_or_mock(
            {
                "cpc": {
                    "value": 1.9,
                    "unit": "元/点击",
                    "source": "品牌聚光报表",
                    "collected_at": "2026-07-01",
                }
            },
            "cpc",
            label="CPC",
            mock_value=2.8,
            unit="元/点击",
            basis="模拟",
        )

        self.assertEqual(row["value"], 1.9)
        self.assertFalse(row["is_mock"])
        self.assertEqual(row["data_type"], "真实样本")

    def test_apply_demo_mock_does_not_overwrite_real_benchmarks(self):
        req = CampaignRequest(
            brand_name="曲奇四重奏",
            category="香港曲奇伴手礼",
            product_name="曲奇礼盒",
            selling_points=["香港伴手礼"],
            price_min=120,
            price_max=320,
            initial_audience="25-40岁女性",
            total_budget_cny=100000,
            goal="conversion",
            benchmark_evidence=[
                MetricEvidence(
                    source_name="品牌聚光报表",
                    collected_at="2026-07-01",
                    metric_name="cpc",
                    value=0.3,
                    unit="CNY/click",
                    is_mock=False,
                )
            ],
        )
        filled, injected = apply_demo_mock_evidence(req)
        cpc_values = [m.value for m in filled.benchmark_evidence if m.metric_name == "cpc"]
        self.assertEqual(cpc_values, [0.3])
        self.assertTrue(any(m.is_mock and m.metric_name == "cvr" for m in filled.benchmark_evidence))
        self.assertTrue(filled.creator_evidence)
        self.assertTrue(all(c.is_mock for c in filled.creator_evidence))
        self.assertTrue(any(f["field"] == "creator_evidence" for f in injected["fields"]))

    def test_apply_demo_mock_keeps_real_creator_evidence(self):
        real = CreatorEvidence(
            name="真实达人甲",
            profile_url="https://example.com/real",
            followers=12000,
            average_interactions=900,
            quote_cny=1500,
            audience_tags=["伴手礼"],
            source_name="CSV导入",
            collected_at="2026-07-01",
            is_mock=False,
        )
        req = CampaignRequest(
            brand_name="曲奇四重奏",
            category="香港曲奇伴手礼",
            product_name="曲奇礼盒",
            selling_points=["香港伴手礼"],
            price_min=120,
            price_max=320,
            initial_audience="25-40岁女性",
            total_budget_cny=100000,
            goal="conversion",
            creator_evidence=[real],
        )
        filled, injected = apply_demo_mock_evidence(req)
        self.assertEqual([c.name for c in filled.creator_evidence], ["真实达人甲"])
        self.assertFalse(any(f["field"] == "creator_evidence" for f in injected["fields"]))

    def test_mock_notes_cover_multiple_peak_hours(self):
        req = CampaignRequest(
            brand_name="曲奇四重奏",
            category="香港曲奇伴手礼",
            product_name="曲奇礼盒",
            selling_points=["香港伴手礼"],
            price_min=120,
            price_max=320,
            initial_audience="25-40岁女性",
            total_budget_cny=100000,
            goal="conversion",
        )
        notes = build_mock_notes(req, as_of="2026-07-24")
        hours = {
            int(n.published_at[11:13])
            for n in notes
            if n.published_at
        }
        self.assertGreaterEqual(len(notes), 8)
        self.assertTrue({8, 12, 19, 20, 21}.issubset(hours))
        self.assertTrue(all(n.is_mock for n in notes))

    def test_mock_paid_risk_scenarios_cover_five_issues(self):
        req = CampaignRequest(
            brand_name="曲奇四重奏",
            category="香港曲奇伴手礼",
            product_name="曲奇礼盒",
            selling_points=["香港伴手礼"],
            price_min=120,
            price_max=320,
            initial_audience="25-40岁女性",
            total_budget_cny=100000,
            goal="conversion",
        )
        scenarios = build_mock_paid_risk_scenarios(req, as_of="2026-07-24")
        issues = [s.issue for s in scenarios]
        self.assertEqual(
            issues,
            ["冷启动无量", "点击成本过高", "点击高但转化低", "素材衰退", "审核拒绝"],
        )
        self.assertTrue(all(s.is_mock for s in scenarios))
        self.assertTrue(all("Mock" in s.example_diagnosis for s in scenarios))

    def test_mock_creators_are_twenty_and_seeded(self):
        req = CampaignRequest(
            brand_name="曲奇四重奏",
            category="香港曲奇伴手礼",
            product_name="曲奇礼盒",
            selling_points=["香港伴手礼"],
            price_min=120,
            price_max=320,
            initial_audience="25-40岁女性",
            total_budget_cny=100000,
            goal="conversion",
        )

        first = build_mock_creators(req, as_of="2026-07-25", mock_seed="creator-a")
        second = build_mock_creators(req, as_of="2026-07-25", mock_seed="creator-a")
        changed = build_mock_creators(req, as_of="2026-07-25", mock_seed="creator-b")

        self.assertEqual(len(first), 20)
        self.assertEqual(first, second)
        self.assertNotEqual(
            [item.followers for item in first],
            [item.followers for item in changed],
        )
        self.assertTrue(all(item.is_mock for item in first))
        self.assertTrue(all((item.average_interactions or 0) <= (item.followers or 0) for item in first))

    def test_platform_market_has_thirty_seeded_days(self):
        req = CampaignRequest(
            brand_name="曲奇四重奏", category="香港曲奇伴手礼", product_name="曲奇礼盒",
            selling_points=["香港伴手礼"], price_min=120, price_max=320,
            initial_audience="25-40岁女性", total_budget_cny=100000, goal="conversion",
        )
        first = build_mock_platform_market(req, mock_seed="market-a", as_of="2026-07-25")
        repeated = build_mock_platform_market(req, mock_seed="market-a", as_of="2026-07-25")
        changed = build_mock_platform_market(req, mock_seed="market-b", as_of="2026-07-25")

        self.assertEqual(first, repeated)
        self.assertNotEqual(first["series"], changed["series"])
        self.assertEqual(len(first["series"]), 30)
        self.assertTrue(first["is_mock"])
        self.assertEqual(first["mock_seed"], "market-a")
        self.assertTrue(all(row["note_count"] >= 0 and row["interactions"] >= 0 for row in first["series"]))

    def test_mock_competitors_are_anonymous_and_seeded(self):
        req = CampaignRequest(
            brand_name="曲奇四重奏", category="香港曲奇伴手礼", product_name="曲奇礼盒",
            selling_points=["香港伴手礼"], price_min=120, price_max=320,
            initial_audience="25-40岁女性", total_budget_cny=100000, goal="conversion",
        )
        first = build_mock_competitors(req, mock_seed="competitor-a", as_of="2026-07-25")
        repeated = build_mock_competitors(req, mock_seed="competitor-a", as_of="2026-07-25")

        self.assertEqual(first, repeated)
        self.assertGreaterEqual(len(first), 3)
        self.assertLessEqual(len(first), 5)
        self.assertTrue(all(item.account_name.startswith("模拟竞品 ") for item in first))
        self.assertTrue(all(item.is_mock and item.mock_seed == "competitor-a" for item in first))

    def test_apply_demo_mock_propagates_seed(self):
        req = CampaignRequest(
            brand_name="曲奇四重奏", category="香港曲奇伴手礼", product_name="曲奇礼盒",
            selling_points=["香港伴手礼"], price_min=120, price_max=320,
            initial_audience="25-40岁女性", total_budget_cny=100000, goal="conversion",
        )
        filled, injected = apply_demo_mock_evidence(req, mock_seed="all-a")

        self.assertEqual(injected["mock_seed"], "all-a")
        self.assertEqual(len(filled.creator_evidence), 20)
        self.assertGreaterEqual(len(filled.competitor_evidence), 3)
        self.assertTrue(all(item.mock_seed == "all-a" for item in filled.creator_evidence))
        self.assertTrue(all(item.mock_seed == "all-a" for item in filled.competitor_evidence))


if __name__ == "__main__":
    unittest.main()
