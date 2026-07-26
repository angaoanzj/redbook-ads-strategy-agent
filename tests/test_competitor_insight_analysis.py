"""Contract tests for deterministic, evidence-backed competitor insights."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from competitor_insight_analysis import assess_content_gaps, build_competitor_insight_rows
from models import CompetitorEvidence


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "examples" / "jenny_benchmark_competitor_evidence.json"


class CompetitorInsightAnalysisTests(unittest.TestCase):
    def test_jenny_rows_are_compatible_and_evidence_backed(self):
        payload = json.loads(BENCH.read_text(encoding="utf-8"))
        evidence = [
            CompetitorEvidence.model_validate(row)
            for row in payload["competitor_evidence"]
        ]
        gaps = assess_content_gaps(
            ["招牌经典款", "采用日本小麦粉与新西兰牛油", "适合作为香港伴手礼"],
            evidence,
        )
        rows = build_competitor_insight_rows(
            evidence,
            content_gap_analysis=gaps,
            observed_formats=[{"format": "图集", "sample_count": 3}],
        )
        by_dimension = {row["dimension"]: row for row in rows}
        self.assertIn("observation", by_dimension["选题"])
        self.assertEqual(by_dimension["选题"]["total_samples"], 3)
        self.assertEqual(by_dimension["选题"]["confidence"], "low")
        self.assertTrue(by_dimension["选题"]["evidence"])
        self.assertIn("评论", by_dimension["互动引擎"]["observation"])

    def test_cash_alone_is_not_trust(self):
        rows = build_competitor_insight_rows([
            CompetitorEvidence(
                account_name="A",
                profile_or_note_url="https://www.xiaohongshu.com/explore/cash-only",
                title="只收现金",
                content_themes=["只收现金"],
            )
        ])
        trust = next(row for row in rows if row["dimension"] == "信任机制")
        self.assertEqual(trust["conclusion_type"], "evidence_insufficient")
        self.assertNotIn("现金", trust["observation"])

    def test_fake_shop_word_alone_is_not_spread_risk(self):
        rows = build_competitor_insight_rows([
            CompetitorEvidence(
                account_name="A",
                profile_or_note_url="https://www.xiaohongshu.com/explore/fake-shop",
                title="避坑假店",
                content_themes=["避坑假店"],
            )
        ])
        risk = next(row for row in rows if row["dimension"] == "扩散风险")
        self.assertEqual(risk["conclusion_type"], "evidence_insufficient")

    def test_no_comment_signal_keeps_insufficient_interaction_row(self):
        rows = build_competitor_insight_rows([
            CompetitorEvidence(
                account_name="A",
                profile_or_note_url="https://www.xiaohongshu.com/explore/unboxing",
                title="伴手礼开箱",
                content_themes=["伴手礼"],
            )
        ])
        row = next(row for row in rows if row["dimension"] == "互动引擎")
        self.assertEqual(row["conclusion_type"], "evidence_insufficient")
        self.assertTrue(row["missing_evidence"])


if __name__ == "__main__":
    unittest.main()
