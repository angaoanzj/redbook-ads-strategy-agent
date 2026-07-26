"""对标共性/空白人话：对齐珍妮金样结构。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from models import CampaignRequest, CompetitorEvidence
from organic_benchmark_insights import build_organic_benchmark_insights
from engine import run_strategy


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "examples" / "jenny_benchmark_competitor_evidence.json"


def _jenny_request(*, with_brief: bool) -> CampaignRequest:
    bench = json.loads(BENCH.read_text(encoding="utf-8"))
    return CampaignRequest(
        brand_name="曲奇四重奏",
        category="香港蝴蝶酥伴手礼",
        product_name="经典原味蝴蝶酥礼盒",
        selling_points=["日麦新西兰牛油", "酒店大厨手工", "可快递内地", "招牌经典款"],
        price_min=228,
        price_max=228,
        currency="HKD",
        initial_audience="到港游客与送礼人群",
        total_budget_cny=100000,
        goal="conversion",
        competitor_links=bench["competitor_links"],
        competitor_evidence=bench["competitor_evidence"],
        competitor_benchmark_brief=bench["competitor_benchmark_brief"] if with_brief else None,
        category_note_evidence=[
            {
                "search_keyword": "香港伴手礼",
                "search_rank": i + 1,
                "note_id": f"kb-{i}",
                "note_url": f"https://example.com/kb-{i}",
                "title": f"伴手礼{i}",
                "note_type": "视频" if i < 12 else "图集",
                "likes": 10,
                "favorites": 1,
                "comments": 0,
                "shares": 0,
                "tags": ["香港伴手礼"],
                "published_at": "2026-07-01T04:00:00Z",
                "collected_at": "2026-07-26",
                "source_name": "kb",
            }
            for i in range(142)
        ],
    )


class OrganicBenchmarkInsightsTests(unittest.TestCase):
    def test_builder_matches_jenny_shape(self):
        req = _jenny_request(with_brief=False)
        result = build_organic_benchmark_insights(
            req,
            competitor={
                "organic_hits_commonalities": {
                    "top_themes": [
                        {"theme": "珍妮曲奇"},
                        {"theme": "香港伴手礼"},
                        {"theme": "避坑假店"},
                    ],
                    "observed_formats": [{"format": "图集", "sample_count": 3}],
                },
                "content_gaps": {
                    "gap_selling_points": ["日麦新西兰牛油", "酒店大厨手工", "可快递内地"],
                    "covered_selling_points": ["招牌经典款"],
                },
            },
            organic={},
            evidence=list(req.competitor_evidence),
        )
        self.assertIn("心智", result["summary"])
        self.assertTrue(any("图集为主" in row for row in result["commonalities"]))
        self.assertTrue(any("标题模板" in row for row in result["commonalities"]))
        self.assertTrue(any("正文标配" in row for row in result["commonalities"]))
        self.assertTrue(any("评论场" in row for row in result["commonalities"]))
        self.assertTrue(any("原料" in row or "牛油" in row for row in result["gaps"]))
        self.assertTrue(any("寄送" in row or "履约" in row for row in result["gaps"]))
        self.assertTrue(any("视频占比低" in row for row in result["gaps"]))

    def test_auto_board_uses_local_organic_copy(self):
        req = _jenny_request(with_brief=False)
        out = run_strategy(req, use_model=False, allow_mock=False)
        board = out.report_view["competitor_benchmark_board"]
        org = board["section_organic"]
        self.assertEqual(org.get("organic_insight_source"), "local_organic_insights")
        self.assertIn("心智", org["summary"])
        self.assertTrue(any("图集为主" in row for row in org["commonalities"]))
        self.assertTrue(any("标题模板" in row for row in org["commonalities"]))
        self.assertGreaterEqual(len(org["gaps"]), 3)

    def test_user_brief_keeps_gold_copy(self):
        req = _jenny_request(with_brief=True)
        out = run_strategy(req, use_model=False, allow_mock=False)
        org = out.report_view["competitor_benchmark_board"]["section_organic"]
        self.assertEqual(org.get("organic_insight_source"), "user_brief")
        self.assertIn("珍妮/聪明小熊/香港伴手礼", org["summary"])


if __name__ == "__main__":
    unittest.main()
