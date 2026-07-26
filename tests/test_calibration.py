"""反馈回流校准与告警落库测试。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_state import AgentStateStore
from calibration import MIN_CALIBRATION_SAMPLES, load_brand_calibration


class CalibrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "state.db"
        self.store = AgentStateStore(self.db_path)
        self.store.get_or_create_session("session-cal")
        self.store.complete_analysis(
            "session-cal",
            "rpt_cal",
            {"ok": True},
            {
                "brand_name": "曲奇四重奏",
                "product_name": "蝴蝶酥",
                "category": "伴手礼",
                "goal": "转化",
                "mock_seed": None,
                "data_confidence": "medium",
                "summary": {},
                "source_counts": {},
            },
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_insufficient_without_samples(self) -> None:
        result = load_brand_calibration(self.store, "曲奇四重奏")
        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["sample_count"], 0)

    def test_ready_after_enough_field_corrections(self) -> None:
        for index in range(MIN_CALIBRATION_SAMPLES):
            self.store.save_feedback(
                session_id="session-cal",
                report_id="rpt_cal",
                rating="一般",
                comment=None,
                sections=["预算"],
                idempotency_key=f"fb-cal-{index}",
                field_corrections=[
                    {
                        "field": "organic_ratio",
                        "suggested_value": 0.3,
                        "actual_value": 0.28 + index * 0.01,
                    },
                    {
                        "field": "cold_start_bid_high_mult",
                        "suggested_value": 1.2,
                        "actual_value": 1.25,
                    },
                ],
            )
        result = load_brand_calibration(self.store, "曲奇四重奏")
        self.assertEqual(result["status"], "ready")
        self.assertIn("organic_ratio", result["defaults"])
        self.assertTrue(result["guardrail_suggestions"])
        self.assertIn("不会自动放宽", result["guardrail_suggestions"][0])


class AlertEventsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = AgentStateStore(Path(self.tmp.name) / "alerts.db")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_save_and_list_alerts(self) -> None:
        self.store.save_alert(
            brand_name="曲奇四重奏",
            severity="high",
            alert_type="ad_volume_spike",
            message="竞品加投",
            response="提高防守预算",
        )
        self.store.save_alert(
            brand_name="曲奇四重奏",
            severity="medium",
            alert_type="new_ad_note",
            message="新增广告笔记",
        )
        self.store.save_alert(
            brand_name="其他品牌",
            severity="high",
            alert_type="x",
            message="无关",
        )
        items = self.store.list_alerts(brand_name="曲奇四重奏", severity="high")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["alert_type"], "ad_volume_spike")
        all_brand = self.store.list_alerts(brand_name="曲奇四重奏")
        self.assertEqual(len(all_brand), 2)


if __name__ == "__main__":
    unittest.main()
