import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import run_strategy
from mock_agents import run_mock_subagents
from tests.test_engine import sample_request


class MockSubAgentTests(unittest.TestCase):
    def test_multiple_subagents_fill_missing_fields(self):
        filled, injected = run_mock_subagents(sample_request(), mock_seed="agents-a")
        self.assertGreaterEqual(injected["agent_count_activated"], 5)
        agent_ids = {row["agent_id"] for row in injected["subagents"]}
        self.assertIn("organic_market_agent", agent_ids)
        self.assertIn("spotlight_benchmark_agent", agent_ids)
        self.assertIn("creator_agent", agent_ids)
        self.assertTrue(filled.category_note_evidence)
        self.assertTrue(filled.creator_evidence)
        self.assertTrue(all(item.is_mock for item in filled.creator_evidence))

    def test_subagents_do_not_overwrite_real_creators(self):
        from models import CampaignRequest, CreatorEvidence
        req = CampaignRequest(
            **{
                **sample_request().model_dump(),
                "creator_evidence": [CreatorEvidence(
                    name="真实达人A",
                    profile_url="https://example.com/a",
                    followers=12000,
                    average_interactions=800,
                    quote_cny=2000,
                    audience_tags=["送礼"],
                    source_name="人工导入",
                    collected_at="2026-07-25",
                    is_mock=False,
                ).model_dump()],
            }
        )
        filled, injected = run_mock_subagents(req, mock_seed="agents-b")
        creator_agent = next(
            row for row in injected["subagents"] if row["agent_id"] == "creator_agent"
        )
        self.assertEqual(creator_agent["status"], "skipped_real_evidence_present")
        self.assertEqual(len(filled.creator_evidence), 1)
        self.assertEqual(filled.creator_evidence[0].name, "真实达人A")

    def test_engine_trace_exposes_subagents(self):
        result = run_strategy(
            sample_request(), use_model=False, allow_mock=True, mock_seed="agents-trace"
        )
        mock_trace = next(row for row in result.trace if row.get("stage") == "mock_fallback")
        self.assertEqual(mock_trace["status"], "enabled")
        self.assertGreaterEqual(mock_trace["agent_count_activated"], 5)
        self.assertTrue(any(row.get("status") == "injected_mock" for row in mock_trace["subagents"]))

    def test_hkd_price_converts_before_roi(self):
        req = sample_request().model_copy(update={
            "currency": "HKD",
            "price_min": 228,
            "price_max": 228,
            "benchmark_evidence": [
                {
                    "source_name": "账户",
                    "collected_at": "2026-07-25",
                    "metric_name": "cpc",
                    "value": 1.0,
                    "unit": "CNY/click",
                },
                {
                    "source_name": "账户",
                    "collected_at": "2026-07-25",
                    "metric_name": "ctr",
                    "value": 0.05,
                    "unit": "ratio",
                },
                {
                    "source_name": "账户",
                    "collected_at": "2026-07-25",
                    "metric_name": "cvr",
                    "value": 0.02,
                    "unit": "ratio",
                },
            ],
        })
        from models import CampaignRequest
        req = CampaignRequest(**req.model_dump())
        result = run_strategy(req, use_model=False, allow_mock=False)
        roi = result.modules["module_4_spotlight_decision"]["forecast"]["roi_range"]
        self.assertIsNotNone(roi)
        self.assertEqual(roi["currency"], "HKD")
        self.assertAlmostEqual(roi["aov_cny"], 228 * 0.92, places=2)
        # 若误把 HKD 当 CNY，点估计会更高；换汇后应明显更低
        self.assertLess(roi["point_estimate"], (1 / 1.0) * 0.02 * 228 - 1)


if __name__ == "__main__":
    unittest.main()
