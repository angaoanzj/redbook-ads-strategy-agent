"""验证 examples/mock/ 演示数据包可被解析并驱动引擎，且不破坏 allow_mock=false 行为。"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from creator_csv import parse_creator_csv
from engine import run_strategy
from models import CampaignRequest


ROOT = Path(__file__).resolve().parents[1]
MOCK_DIR = ROOT / "examples" / "mock"


def _load_full_case() -> CampaignRequest:
    raw = json.loads((MOCK_DIR / "cookie_quartet_demo_full_case.json").read_text(encoding="utf-8"))
    raw.pop("_meta", None)
    return CampaignRequest(**raw)


class MockDataFilesTests(unittest.TestCase):
    def test_mock_creators_csv_loads_with_mock_flags(self):
        text = (MOCK_DIR / "creators_demo.csv").read_text(encoding="utf-8")
        creators = parse_creator_csv(text)
        self.assertGreaterEqual(len(creators), 5)
        self.assertTrue(all(c.is_mock for c in creators))
        self.assertTrue(all("Mock" in c.source_name or "演示" in c.source_name for c in creators))
        self.assertTrue(all(c.evidence_grade == "M" for c in creators))

    def test_mock_notes_pack_loads(self):
        pack = json.loads((MOCK_DIR / "category_notes_demo.json").read_text(encoding="utf-8"))
        self.assertTrue(pack["is_mock"])
        notes = pack["category_note_evidence"]
        self.assertGreaterEqual(len(notes), 8)
        self.assertTrue(all(item["is_mock"] for item in notes))
        hours = {int(item["published_at"][11:13]) for item in notes if item.get("published_at")}
        self.assertGreaterEqual(len(hours), 5)
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
            category_note_evidence=notes,
        )
        result = run_strategy(req, use_model=False, allow_mock=False)
        market = result.modules["module_1_market_competitor"]["organic_market"]
        self.assertEqual(market["sample_size"], len(notes))
        self.assertTrue(market["is_mock"])
        self.assertIn("Mock", market["status"])
        schedules = result.modules["module_4_spotlight_decision"]["daily_schedules"]
        self.assertGreaterEqual(len(schedules["slots"]), 4)
        roles = {slot["role"] for slot in schedules["slots"]}
        self.assertGreaterEqual(len(roles), 3)

    def test_official_rules_demo_is_collected_not_fabricated(self):
        pack = json.loads((MOCK_DIR / "official_rules_demo.json").read_text(encoding="utf-8"))
        self.assertFalse(pack["_meta"]["is_mock"])
        rules = pack["official_rule_evidence"]
        self.assertGreaterEqual(len(rules), 3)
        titles = {item["title"] for item in rules}
        self.assertTrue({"食品行业规则&投放规则", "内容审核规则总则", "跨境广告内容规范"} <= titles)
        for item in rules:
            self.assertTrue(item["source_url"].startswith("https://ad.xiaohongshu.com/"))
            self.assertTrue(item["collected_at"])
            self.assertEqual(item["evidence_grade"], "A_official_public_rule")
            self.assertTrue(item["full_text"] or item["risk_items"])

    def test_full_case_runs_without_allow_mock_injection(self):
        req = _load_full_case()
        self.assertTrue(all(c.is_mock for c in req.creator_evidence))
        self.assertTrue(all(n.is_mock for n in req.category_note_evidence))
        self.assertEqual(len(req.paid_risk_demo_scenarios), 5)
        self.assertGreaterEqual(len(req.official_rule_evidence), 3)
        self.assertEqual(req.official_rule_evidence[0].title, "食品行业规则&投放规则")
        self.assertTrue(
            all(rule.evidence_grade == "A_official_public_rule" for rule in req.official_rule_evidence)
        )
        result = run_strategy(req, use_model=False, allow_mock=False)
        self.assertEqual(
            len([k for k in result.modules if not str(k).startswith("bonus_")]),
            6,
        )
        risk = result.modules["module_1_market_competitor"]["risk_warning"]
        self.assertIn("official_rules", risk)
        self.assertIn("category_high_frequency_violations", risk)
        self.assertEqual(risk["official_rules"]["status"], "已接入小红书官方公开规则")
        self.assertNotIn("待接入", risk["official_rules"]["status"])
        self.assertTrue(risk["official_rules"]["official_sources"])
        self.assertTrue(risk["official_rules"]["confirmed_types"])
        self.assertTrue(risk["category_high_frequency_violations"]["ranked_reasons"])
        self.assertNotEqual(
            risk["official_rules"]["label"],
            risk["category_high_frequency_violations"]["label"],
        )
        module3 = result.modules["module_3_keyword_creator"]
        self.assertGreater(len(module3["creator_candidates"]), 0)
        self.assertTrue(all(item["is_mock"] for item in module3["creator_candidates"]))
        self.assertTrue(all(not item["is_recommendation"] for item in module3["creator_candidates"]))
        self.assertEqual(module3["creator_roster"]["real_candidate_count"], 0)
        module4 = result.modules["module_4_spotlight_decision"]
        self.assertGreaterEqual(len(module4["daily_schedules"]["slots"]), 4)
        self.assertEqual(len(module4["risk_playbook"]), 5)
        self.assertTrue(all(item.get("demo_scenario", {}).get("is_mock") for item in module4["risk_playbook"]))
        self.assertIn("冷启动无量", result.report_markdown)
        self.assertIn("审核拒绝", result.report_markdown)
        self.assertFalse(
            any(
                row.get("stage") == "mock_fallback" and row.get("injected_fields")
                for row in result.trace
            )
        )
        self.assertIn("模拟数据（Mock）", result.report_markdown)

    def test_empty_request_without_allow_mock_still_no_fake_recommendations(self):
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
        result = run_strategy(req, use_model=False, allow_mock=False)
        module3 = result.modules["module_3_keyword_creator"]
        self.assertEqual(module3["creator_candidates"], [])
        self.assertEqual(module3["creator_recommendations_20"], [])
        self.assertEqual(module3["creator_roster"]["mock_candidate_count"], 0)


if __name__ == "__main__":
    unittest.main()
