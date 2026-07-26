"""模块2：画像 / 方向双评分 / 15选题 / 投流门槛 / 知识库标签。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine import run_strategy
from knowledge_base import KnowledgeBase
from models import CampaignRequest

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "examples" / "knowledge" / "juguang_targeting_catalog.json"


class Module2OutputTests(unittest.TestCase):
    def test_module2_emits_homework_fields_with_kb_tags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            knowledge = KnowledgeBase(Path(directory) / "knowledge.db")
            knowledge.import_targeting_catalog(json.loads(CATALOG.read_text(encoding="utf-8")))
            pack = knowledge.targeting_pack_for_campaign(
                category="香港蝴蝶酥伴手礼",
                product_name="经典－原味蝴蝶酥礼盒",
                initial_audience="25-35岁到港女性游客",
                selling_points=["牛油香浓", "层次酥脆", "适合作为香港伴手礼"],
            )
            req = CampaignRequest(
                brand_name="曲奇四重奏",
                category="香港蝴蝶酥伴手礼",
                product_name="经典－原味蝴蝶酥礼盒",
                selling_points=["牛油香浓", "层次酥脆", "适合作为香港伴手礼"],
                price_min=228,
                price_max=228,
                currency="HKD",
                initial_audience="25-35岁到港女性游客",
                total_budget_cny=100000,
                spotlight_budget_cny=70000,
                campaign_days=30,
                goal="conversion",
                targeting_knowledge_pack=pack,
            )
            result = run_strategy(req, use_model=False, allow_mock=False)
            m2 = result.modules["module_2_audience_content"]
            persona = m2["persona"]
            self.assertIsInstance(persona["demographic"], list)
            self.assertTrue(persona["behavioral"])
            self.assertTrue(persona["psychological"])
            tags = persona["targeting_tags"]
            self.assertTrue(tags["interest_tags"])
            self.assertTrue(tags["behavior_tags"])
            self.assertTrue(tags["crowd_packages"])
            self.assertIn("食品饮料", " ".join(tags["interest_tags"]))
            self.assertEqual(len(m2["content_directions"]), 3)
            for direction in m2["content_directions"]:
                self.assertIn("organic_score", direction)
                self.assertIn("paid_score", direction)
            self.assertEqual(len(m2["topics"]), 15)
            topic = m2["topics"][0]
            self.assertTrue(topic["title_template"])
            self.assertTrue(topic.get("cover_suggestion") or topic.get("cover"))
            self.assertTrue(topic["outline"])
            self.assertIn("suitable_for_paid", topic)
            self.assertIn("paid_objective", topic)
            outlines = ["｜".join(t["outline"]) for t in m2["topics"]]
            self.assertGreaterEqual(len(set(outlines)), 12)
            titles = [t["title_template"] for t in m2["topics"]]
            self.assertGreaterEqual(len(set(titles)), 12)
            focused_points = {t.get("selling_point_focus") for t in m2["topics"]}
            self.assertTrue({"牛油香浓", "层次酥脆", "适合作为香港伴手礼"} <= focused_points)
            for row in m2["topics"]:
                blob = "｜".join(row["outline"])
                self.assertTrue(
                    row["selling_point_focus"] in blob
                    or row["persona_hook"]["demographic"] in blob
                )
            gate = m2["material_screening"]
            self.assertEqual(gate["ctr_percent"], 10)
            self.assertEqual(gate["engagement_rate_percent"], 7)
            section = result.report_view["report_sections"]
            audience = next(item for item in section if item["key"] == "audience")
            visuals = audience["visuals"]
            self.assertEqual(len(visuals["topics"]), 15)
            self.assertTrue(visuals["targeting_tags"]["interest_tags"])
            self.assertIn("CTR", visuals["material_screening"]["rule_text"])


if __name__ == "__main__":
    unittest.main()
