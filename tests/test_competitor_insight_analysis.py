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

    def test_bare_question_word_does_not_turn_title_price_into_comment_evidence(self):
        rows = build_competitor_insight_rows([
            CompetitorEvidence(
                account_name="A",
                profile_or_note_url="https://www.xiaohongshu.com/explore/question-title",
                title="价格问题整理",
                content_themes=["购买问答"],
            )
        ])

        interaction = next(row for row in rows if row["dimension"] == "互动引擎")

        self.assertEqual(interaction["conclusion_type"], "evidence_insufficient")
        self.assertNotIn("价格", interaction["observation"])

    def test_comment_marker_and_topic_must_share_an_explicit_comment_fragment(self):
        rows = build_competitor_insight_rows([
            CompetitorEvidence(
                account_name="A",
                profile_or_note_url="https://www.xiaohongshu.com/explore/separate-fragments",
                title="价格攻略",
                notes="评论区很热闹；正文整理门店信息",
            )
        ])

        interaction = next(row for row in rows if row["dimension"] == "互动引擎")

        self.assertEqual(interaction["conclusion_type"], "evidence_insufficient")
        self.assertFalse(interaction["evidence"])

    def test_explicit_comment_fragment_supplies_interaction_provenance(self):
        rows = build_competitor_insight_rows([
            CompetitorEvidence(
                account_name="A",
                profile_or_note_url="https://www.xiaohongshu.com/explore/comment-price",
                title="门店攻略",
                notes="正文介绍门店；评论高频咨询价格与限购",
            )
        ])

        interaction = next(row for row in rows if row["dimension"] == "互动引擎")

        self.assertIn("价格", interaction["observation"])
        self.assertEqual(interaction["evidence"][0]["source"], "notes:comment_fragment")

    def test_neutral_better_tasting_comparison_is_not_a_spread_risk(self):
        rows = build_competitor_insight_rows([
            CompetitorEvidence(
                account_name="A",
                profile_or_note_url="https://www.xiaohongshu.com/explore/taste-comparison",
                title="两款曲奇哪款更好吃",
            )
        ])

        risk = next(row for row in rows if row["dimension"] == "扩散风险")

        self.assertEqual(risk["conclusion_type"], "evidence_insufficient")
        self.assertNotIn("原料/口感争议", risk["observation"])

    def test_direct_dispute_signals_and_disputed_comparison_remain_spread_risks(self):
        evidence = [
            CompetitorEvidence(
                account_name="A",
                profile_or_note_url="https://www.xiaohongshu.com/explore/direct-risk",
                notes="评论出现香精与人造奶油质疑",
            ),
            CompetitorEvidence(
                account_name="B",
                profile_or_note_url="https://www.xiaohongshu.com/explore/disputed-comparison",
                notes="哪款更好吃的说法引发争议",
            ),
        ]

        risk = next(
            row
            for row in build_competitor_insight_rows(evidence)
            if row["dimension"] == "扩散风险"
        )

        self.assertIn("原料/口感争议", risk["observation"])
        self.assertEqual(risk["sample_count"], 2)

    def test_observed_formats_without_matching_raw_formats_are_aggregate_only(self):
        rows = build_competitor_insight_rows(
            [
                CompetitorEvidence(
                    account_name="A",
                    profile_or_note_url="https://www.xiaohongshu.com/explore/a",
                ),
                CompetitorEvidence(
                    account_name="B",
                    profile_or_note_url="https://www.xiaohongshu.com/explore/b",
                ),
            ],
            observed_formats=[{"format": "图集", "sample_count": 2}],
        )
        format_row = next(row for row in rows if row["dimension"] == "内容形式")
        self.assertEqual(format_row["sample_count"], 0)
        self.assertEqual(format_row["coverage"], 0.0)
        self.assertEqual(len(format_row["evidence"]), 1)
        self.assertEqual(format_row["evidence"][0]["provenance"], "aggregate_only")
        self.assertTrue(format_row["missing_evidence"])

    def test_observed_format_refs_are_grouped_by_each_samples_normalized_format(self):
        gallery_url = "https://www.xiaohongshu.com/explore/gallery"
        video_url = "https://www.xiaohongshu.com/explore/video"
        rows = build_competitor_insight_rows(
            [
                CompetitorEvidence(
                    account_name="Video",
                    profile_or_note_url=video_url,
                    note_format=" short VIDEO ",
                ),
                CompetitorEvidence(
                    account_name="Gallery",
                    profile_or_note_url=gallery_url,
                    note_format="图集",
                ),
            ],
            observed_formats=[
                {"format": " 图集 ", "sample_count": 1},
                {"format": "SHORT video", "sample_count": 1},
            ],
        )
        format_row = next(row for row in rows if row["dimension"] == "内容形式")
        raw_refs = {
            ref["signal"]: ref["url"]
            for ref in format_row["evidence"]
            if ref["provenance"] == "raw_note"
        }

        self.assertEqual(raw_refs["图集"], gallery_url)
        self.assertEqual(raw_refs["SHORT video"], video_url)
        self.assertFalse(format_row["missing_evidence"])

    def test_evidence_identity_uses_canonical_url_not_account_title_collision(self):
        rows = build_competitor_insight_rows([
            CompetitorEvidence(
                account_name="同名账号",
                profile_or_note_url="https://www.xiaohongshu.com/explore/note-a?token=one",
                title="伴手礼攻略",
            ),
            CompetitorEvidence(
                account_name="同名账号",
                profile_or_note_url="https://www.xiaohongshu.com/explore/note-b?token=two",
                title="伴手礼攻略",
            ),
        ])
        topic = next(row for row in rows if row["dimension"] == "选题")

        self.assertEqual(topic["sample_count"], 2)
        self.assertEqual(
            {ref["url"] for ref in topic["evidence"]},
            {
                "https://www.xiaohongshu.com/explore/note-a",
                "https://www.xiaohongshu.com/explore/note-b",
            },
        )
        self.assertEqual(len({ref["note_id"] for ref in topic["evidence"]}), 2)

    def test_validated_content_gap_is_fact_in_assessment_and_chapter_row(self):
        evidence = [
            CompetitorEvidence(
                account_name="A",
                profile_or_note_url="https://www.xiaohongshu.com/explore/classic",
                title="经典曲奇开箱",
            )
        ]
        gaps = assess_content_gaps(
            ["低糖礼盒"],
            evidence,
            validated_points=["低糖礼盒"],
        )
        rows = build_competitor_insight_rows(evidence, content_gap_analysis=gaps)
        gap_row = next(row for row in rows if row["dimension"] == "内容空白")

        self.assertEqual(gaps["candidates"][0]["conclusion_type"], "fact")
        self.assertIn("已验证机会", gaps["decision_conclusion"])
        self.assertEqual(gaps["missing_evidence"], [])
        self.assertEqual(gap_row["conclusion_type"], "fact")
        self.assertIn("已验证机会", gap_row["observation"])
        self.assertEqual(gap_row["missing_evidence"], [])

    def test_demand_only_content_gap_stays_hypothetical_but_does_not_reask_for_demand(self):
        evidence = [
            CompetitorEvidence(
                account_name="A",
                profile_or_note_url="https://www.xiaohongshu.com/explore/classic",
                title="经典曲奇开箱",
            )
        ]
        gaps = assess_content_gaps(
            ["低糖礼盒"],
            evidence,
            demand_signals=["低糖礼盒搜索增长"],
        )
        rows = build_competitor_insight_rows(evidence, content_gap_analysis=gaps)
        gap_row = next(row for row in rows if row["dimension"] == "内容空白")

        self.assertEqual(gaps["candidates"][0]["conclusion_type"], "hypothesis")
        self.assertIn("需求信号支持", gaps["decision_conclusion"])
        self.assertNotIn("用户需求或搜索信号", gaps["missing_evidence"])
        self.assertIn("自然/付费测试效果", gaps["missing_evidence"])
        self.assertEqual(gap_row["conclusion_type"], "hypothesis")
        self.assertIn("效果待验证", gap_row["observation"])


if __name__ == "__main__":
    unittest.main()
