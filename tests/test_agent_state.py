import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


from agent_state import AgentStateStore, new_report_id, sanitize_state_payload


class AgentStateStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "agent-state.db"
        self.metadata = {
            "brand_name": "曲奇四重奏",
            "product_name": "经典蝴蝶酥礼盒",
            "category": "香港伴手礼",
            "goal": "conversion",
            "mock_seed": "state-seed",
            "data_confidence": "low",
            "source_counts": {"notes": 205, "rules": 6},
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_session_persists_and_success_count_is_atomic(self):
        store = AgentStateStore(self.db_path)
        created = store.get_or_create_session("session-a")
        self.assertEqual(created["analysis_count"], 0)

        completed = store.complete_analysis(
            "session-a",
            "rpt_one",
            {"strategic_thesis": "先搜索承接，再验证内容"},
            self.metadata,
        )
        reopened = AgentStateStore(self.db_path)

        self.assertEqual(completed["analysis_count"], 1)
        self.assertEqual(reopened.get_session("session-a")["analysis_count"], 1)
        self.assertEqual(reopened.get_session("session-a")["last_report_id"], "rpt_one")
        self.assertIsNone(reopened.get_session("session-b"))

    def test_sessions_do_not_share_analysis_history(self):
        store = AgentStateStore(self.db_path)
        store.get_or_create_session("session-a")
        store.get_or_create_session("session-b")
        store.complete_analysis("session-a", "rpt_a", {"key": "A"}, self.metadata)
        store.complete_analysis("session-b", "rpt_b", {"key": "B"}, self.metadata)

        self.assertEqual([row["report_id"] for row in store.list_runs("session-a")], ["rpt_a"])
        self.assertEqual([row["report_id"] for row in store.list_runs("session-b")], ["rpt_b"])

    def test_checkpoint_timeline_is_ordered_and_stage_is_updatable(self):
        store = AgentStateStore(self.db_path)
        store.get_or_create_session("session-a")
        store.save_checkpoint(
            "session-a", "rpt_one", "received", status="running", context={"step": 1}
        )
        store.save_checkpoint(
            "session-a", "rpt_one", "received", status="success", context={"step": 2}
        )
        store.save_checkpoint(
            "session-a", "rpt_one", "completed", status="success", context={}
        )
        updated = store.save_checkpoint(
            "session-a", "rpt_one", "received", status="success", context={"step": 3}
        )

        timeline = store.list_checkpoints("session-a", "rpt_one")
        self.assertEqual([row["stage"] for row in timeline], ["received", "completed"])
        self.assertEqual(timeline[0]["status"], "success")
        self.assertEqual(timeline[0]["context"], {"step": 3})
        self.assertEqual(updated["stage"], "received")

    def test_generated_ids_have_expected_public_shape(self):
        session = AgentStateStore(self.db_path).get_or_create_session(None)

        self.assertEqual(len(session["session_id"]), 36)
        self.assertTrue(new_report_id().startswith("rpt_"))

    def test_sensitive_keys_are_removed_recursively_before_persistence(self):
        store = AgentStateStore(self.db_path)
        payload = {
            "safe": 1,
            "Cookie": "secret-cookie",
            "nested": {
                "api_key": "secret-key",
                "proxy_url": "http://127.0.0.1:7890",
                "allowed": [1, {"authorization": "Bearer secret", "name": "保留"}],
            },
        }
        store.set_cache("rules", "cache-a", payload, ttl_seconds=60)

        self.assertEqual(
            store.get_cache("rules", "cache-a"),
            {"safe": 1, "nested": {"allowed": [1, {"name": "保留"}]}},
        )
        self.assertEqual(sanitize_state_payload(payload)["safe"], 1)

    def test_cache_expiry_and_source_version_prevent_stale_hits(self):
        store = AgentStateStore(self.db_path)
        now = datetime(2026, 7, 25, tzinfo=timezone.utc)
        store.set_cache(
            "official_rules", "food", {"count": 6}, ttl_seconds=60,
            source_version="rules-v1", now=now,
        )

        self.assertEqual(
            store.get_cache("official_rules", "food", source_version="rules-v1", now=now),
            {"count": 6},
        )
        self.assertIsNone(
            store.get_cache("official_rules", "food", source_version="rules-v2", now=now)
        )
        self.assertIsNone(
            store.get_cache(
                "official_rules", "food", source_version="rules-v1",
                now=now + timedelta(seconds=61),
            )
        )

    def test_idempotency_distinguishes_replay_processing_and_conflict(self):
        store = AgentStateStore(self.db_path)
        started = store.begin_action("key-a", "analyze", "hash-a", "session-a")
        processing = store.begin_action("key-a", "analyze", "hash-a", "session-a")
        store.complete_action("key-a", "rpt_one", {"session_id": "session-a"})
        replayed = store.begin_action("key-a", "analyze", "hash-a", "session-a")
        conflict = store.begin_action("key-a", "analyze", "hash-b", "session-a")

        self.assertEqual(started["result"], "started")
        self.assertEqual(processing["result"], "processing")
        self.assertEqual(replayed["result"], "replayed")
        self.assertEqual(replayed["report_id"], "rpt_one")
        self.assertEqual(conflict["result"], "conflict")

    def test_feedback_is_idempotent_and_mock_backfill_is_demo_only(self):
        store = AgentStateStore(self.db_path)
        store.get_or_create_session("session-a")
        first = store.save_feedback(
            session_id="session-a", report_id="rpt_one", rating="满意",
            comment="保留搜索策略", sections=["聚光投放"], idempotency_key="feedback-a",
        )
        repeated = store.save_feedback(
            session_id="session-a", report_id="rpt_one", rating="满意",
            comment="重复提交不覆盖", sections=[], idempotency_key="feedback-a",
        )
        case = store.save_backfilled_case(
            session_id="session-a", report_id="rpt_one", brand_name="曲奇四重奏",
            category="香港伴手礼", problem_summary="搜索承接不足",
            strategy_summary="提高高意向长尾词比例", evidence_grade="M",
            requested_case_type="verified_case", is_mock=True,
        )

        self.assertEqual(first["feedback_id"], repeated["feedback_id"])
        self.assertEqual(repeated["comment"], "保留搜索策略")
        self.assertEqual(case["case_type"], "demo_case")
        self.assertTrue(case["is_mock"])

    def test_reset_removes_only_session_scoped_state_and_preserves_cache(self):
        store = AgentStateStore(self.db_path)
        store.get_or_create_session("session-a")
        store.complete_analysis("session-a", "rpt_one", {"key": "A"}, self.metadata)
        store.save_checkpoint("session-a", "rpt_one", "completed", status="success", context={})
        store.set_cache("rules", "global", {"count": 6}, ttl_seconds=60)

        deleted = store.reset_session("session-a")

        self.assertTrue(deleted)
        self.assertIsNone(store.get_session("session-a"))
        self.assertEqual(store.list_runs("session-a"), [])
        self.assertEqual(store.get_cache("rules", "global"), {"count": 6})


if __name__ == "__main__":
    unittest.main()
