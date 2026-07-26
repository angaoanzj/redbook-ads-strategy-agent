import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch


warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated.*")
from fastapi.testclient import TestClient

import main
from agent_state import AgentStateStore
from tests.test_engine import sample_request


class AgentStateApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_state = main.STATE if hasattr(main, "STATE") else None
        main.STATE = AgentStateStore(Path(self.temp_dir.name) / "api-state.db")
        self.client = TestClient(main.app)
        self.url = "/analyze?use_model=false&use_knowledge=false&allow_mock=false"
        self.payload = sample_request().model_dump(mode="json")

    def tearDown(self):
        if self.original_state is None:
            delattr(main, "STATE")
        else:
            main.STATE = self.original_state
        self.temp_dir.cleanup()

    def test_analyze_returns_persistent_session_state(self):
        first = self.client.post(
            self.url,
            headers={"X-Session-ID": "session-a", "Idempotency-Key": "analysis-a"},
            json=self.payload,
        )
        second = self.client.post(
            self.url,
            headers={"X-Session-ID": "session-a", "Idempotency-Key": "analysis-b"},
            json=self.payload,
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(first.json()["report_id"].startswith("rpt_"))
        self.assertEqual(first.json()["session_state"]["analysis_count"], 1)
        self.assertEqual(second.json()["session_state"]["analysis_count"], 2)
        reopened = AgentStateStore(main.STATE.path)
        self.assertEqual(reopened.get_session("session-a")["analysis_count"], 2)

    def test_repeated_idempotency_key_replays_without_increment(self):
        headers = {"X-Session-ID": "session-a", "Idempotency-Key": "same-analysis"}
        first = self.client.post(self.url, headers=headers, json=self.payload)
        repeated = self.client.post(self.url, headers=headers, json=self.payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(first.json()["report_id"], repeated.json()["report_id"])
        self.assertEqual(repeated.json()["session_state"]["analysis_count"], 1)
        self.assertEqual(main.STATE.get_session("session-a")["analysis_count"], 1)

    def test_reusing_idempotency_key_for_different_request_is_conflict(self):
        headers = {"X-Session-ID": "session-a", "Idempotency-Key": "conflict-analysis"}
        first = self.client.post(self.url, headers=headers, json=self.payload)
        changed = {**self.payload, "product_name": "不同产品"}
        conflict = self.client.post(self.url, headers=headers, json=changed)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(conflict.status_code, 409)

    def test_successful_analyze_records_complete_checkpoint_timeline(self):
        response = self.client.post(
            self.url,
            headers={"X-Session-ID": "session-a", "Idempotency-Key": "checkpoint-a"},
            json=self.payload,
        )
        report_id = response.json()["report_id"]

        stages = [
            row["stage"]
            for row in main.STATE.list_checkpoints("session-a", report_id)
        ]
        self.assertEqual(
            stages,
            [
                "received",
                "evidence_ready",
                "strategy_generated",
                "report_generated",
                "completed",
            ],
        )

    def test_failed_analyze_records_failure_without_incrementing_session(self):
        failing_client = TestClient(main.app, raise_server_exceptions=False)
        headers = {
            "X-Session-ID": "session-a",
            "Idempotency-Key": "failed-analysis",
        }

        with patch.object(
            main,
            "_analyze_core",
            side_effect=RuntimeError("Cookie=should-never-be-stored"),
        ):
            response = failing_client.post(self.url, headers=headers, json=self.payload)

        action = main.STATE.get_action("failed-analysis")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(action["status"], "failed")
        self.assertIsNotNone(action["report_id"])
        self.assertEqual(main.STATE.get_session("session-a")["analysis_count"], 0)
        timeline = main.STATE.list_checkpoints("session-a", action["report_id"])
        self.assertEqual([row["stage"] for row in timeline], ["received", "failed"])
        self.assertEqual(timeline[-1]["error_summary"], "RuntimeError")
        self.assertNotIn("should-never-be-stored", str(timeline))

    def test_session_runs_workflow_and_status_endpoints_are_queryable(self):
        created = self.client.post(
            self.url,
            headers={"X-Session-ID": "session-a", "Idempotency-Key": "query-a"},
            json=self.payload,
        ).json()
        report_id = created["report_id"]

        session = self.client.get("/sessions/session-a")
        runs = self.client.get("/sessions/session-a/runs?limit=10")
        workflow = self.client.get(f"/workflows/session-a/{report_id}")
        status = self.client.get("/state/status")

        self.assertEqual(session.status_code, 200)
        self.assertEqual(session.json()["analysis_count"], 1)
        self.assertEqual(runs.json()["runs"][0]["report_id"], report_id)
        self.assertEqual(workflow.json()["checkpoints"][-1]["stage"], "completed")
        self.assertEqual(status.json()["agent_sessions"], 1)
        self.assertEqual(self.client.get("/sessions/missing").status_code, 404)

    def test_feedback_endpoint_is_idempotent_and_detects_conflict(self):
        created = self.client.post(
            self.url,
            headers={"X-Session-ID": "session-a", "Idempotency-Key": "feedback-report"},
            json=self.payload,
        ).json()
        feedback = {
            "session_id": "session-a",
            "report_id": created["report_id"],
            "rating": "满意",
            "comment": "报告结构清晰",
            "sections": ["自然流量"],
        }
        headers = {"Idempotency-Key": "feedback-once"}

        first = self.client.post("/feedback", headers=headers, json=feedback)
        replayed = self.client.post("/feedback", headers=headers, json=feedback)
        changed = self.client.post(
            "/feedback", headers=headers, json={**feedback, "rating": "一般"}
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replayed.status_code, 200)
        self.assertEqual(first.json()["feedback_id"], replayed.json()["feedback_id"])
        self.assertEqual(changed.status_code, 409)

    def test_mock_report_backfill_is_demo_and_requires_confirmation(self):
        created = self.client.post(
            self.url.replace("allow_mock=false", "allow_mock=true&mock_seed=backfill-a"),
            headers={"X-Session-ID": "session-a", "Idempotency-Key": "mock-report"},
            json=self.payload,
        ).json()
        body = {
            "session_id": "session-a",
            "report_id": created["report_id"],
            "brand_name": "曲奇四重奏",
            "category": "香港伴手礼",
            "problem_summary": "搜索承接不足",
            "strategy_summary": "验证高意向长尾词",
            "evidence_grade": "M",
            "requested_case_type": "verified_case",
            "confirmed": True,
        }

        accepted = self.client.post("/backfilled-cases", json=body)
        rejected = self.client.post(
            "/backfilled-cases", json={**body, "confirmed": False}
        )

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["case_type"], "demo_case")
        self.assertTrue(accepted.json()["is_mock"])
        self.assertEqual(rejected.status_code, 422)

    def test_reset_endpoint_clears_session_but_preserves_common_cache(self):
        self.client.post(
            self.url,
            headers={"X-Session-ID": "session-a", "Idempotency-Key": "reset-a"},
            json=self.payload,
        )
        main.STATE.set_cache("rules", "global", {"count": 6}, ttl_seconds=60)

        reset = self.client.post("/sessions/session-a/reset")

        self.assertEqual(reset.status_code, 200)
        self.assertEqual(self.client.get("/sessions/session-a").status_code, 404)
        self.assertEqual(main.STATE.get_cache("rules", "global"), {"count": 6})


if __name__ == "__main__":
    unittest.main()
