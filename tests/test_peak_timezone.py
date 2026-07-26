"""高峰时段：published_at UTC → 北京时间分桶与绘图数据。"""
from __future__ import annotations

import unittest

from models import CampaignRequest, CategoryNoteEvidence
from module_agents._evidence_aggregation import (
    aggregate_peak_display_slots,
    extract_hour,
    peak_display_bucket,
)
from engine import _category_market_summary


def _note(note_id: str, published_at: str, likes: int = 100) -> CategoryNoteEvidence:
    return CategoryNoteEvidence(
        search_keyword="香港伴手礼",
        search_rank=1,
        note_id=note_id,
        note_url=f"https://example.com/{note_id}",
        title=note_id,
        note_type="图集",
        likes=likes,
        favorites=10,
        comments=2,
        shares=1,
        tags=["伴手礼"],
        published_at=published_at,
        collected_at="2026-07-26",
        source_name="unit-test",
    )


class PeakTimezoneTests(unittest.TestCase):
    def test_extract_hour_converts_utc_to_beijing(self):
        # UTC 04:00 → 北京 12:00 → 11-14
        self.assertEqual(extract_hour("2026-07-24T04:00:00Z"), 12)
        self.assertEqual(peak_display_bucket(12), "11-14点")
        # UTC 10:00 → 北京 18:00 → 16-20
        self.assertEqual(extract_hour("2026-07-24T10:00:00+00:00"), 18)
        self.assertEqual(peak_display_bucket(18), "16-20点")
        # UTC 20:00 → 北京 次日 04:00 → 其他
        self.assertEqual(extract_hour("2026-07-24T20:00:00Z"), 4)
        self.assertEqual(peak_display_bucket(4), "其他")

    def test_aggregate_peak_display_slots_order(self):
        notes = [
            *[_note(f"a{i}", "2026-07-24T04:00:00Z") for i in range(3)],  # 北京12
            *[_note(f"b{i}", "2026-07-24T10:00:00Z") for i in range(5)],  # 北京18
            *[_note(f"c{i}", "2026-07-24T20:00:00Z") for i in range(2)],  # 北京4
        ]
        slots = aggregate_peak_display_slots(notes)
        self.assertEqual([row["slot"] for row in slots], ["11-14点", "16-20点", "其他"])
        by_slot = {row["slot"]: row["count"] for row in slots}
        self.assertEqual(by_slot["11-14点"], 3)
        self.assertEqual(by_slot["16-20点"], 5)
        self.assertEqual(by_slot["其他"], 2)

    def test_category_market_summary_exposes_beijing_slots(self):
        req = CampaignRequest(
            brand_name="曲奇四重奏",
            category="香港蝴蝶酥伴手礼",
            product_name="经典原味",
            selling_points=["牛油香浓"],
            price_min=228,
            price_max=228,
            currency="HKD",
            initial_audience="到港游客",
            total_budget_cny=100000,
            goal="conversion",
            category_note_evidence=[
                *[_note(f"n{i}", "2026-07-24T04:30:00Z", likes=200) for i in range(4)],
                *[_note(f"m{i}", "2026-07-24T09:30:00Z", likes=300) for i in range(4)],
            ],
        )
        organic = _category_market_summary(req)
        peak = organic["traffic_peak_hours"]
        self.assertEqual(peak["timezone"], "Asia/Shanghai")
        slots = {row["slot"]: row["count"] for row in peak["slots"]}
        self.assertIn("11-14点", slots)
        self.assertIn("16-20点", slots)
        self.assertIn("北京时间", peak["decision_conclusion"])
        # 小时明细也应是北京时间标签对应的小时
        hour_labels = [row["hour"] for row in peak["hours"]]
        self.assertTrue(any(label.startswith("12:") for label in hour_labels))


if __name__ == "__main__":
    unittest.main()
