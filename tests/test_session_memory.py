import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_state import AgentStateStore
from memory.session_memory import SessionMemoryStore


class SessionMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = AgentStateStore(Path(self.tmp.name) / "state.db")
        self.memory = SessionMemoryStore(self.store, ttl_seconds=60, max_items=8)

    def tearDown(self):
        self.tmp.cleanup()

    def test_saves_and_reads_recent_context(self):
        self.memory.remember(
            "session-a",
            {"recent_brand": "曲奇四重奏", "recent_product": "蝴蝶酥礼盒", "recent_intent": "预算诊断"},
        )
        result = self.memory.load("session-a")
        self.assertEqual(result["recent_product"], "蝴蝶酥礼盒")
        self.assertEqual(result["recent_intent"], "预算诊断")

    def test_expired_memory_is_not_injected(self):
        self.memory.remember("session-a", {"recent_brand": "旧品牌"}, ttl_seconds=1)
        future = datetime.now(timezone.utc) + timedelta(seconds=2)
        self.assertEqual(self.memory.load("session-a", now=future), {})

    def test_sensitive_values_are_excluded(self):
        decisions = self.memory.remember(
            "session-a",
            {"recent_brand": "品牌", "api_key": "secret", "comment": "手机号 13800138000"},
        )
        self.assertNotIn("api_key", self.memory.load("session-a"))
        self.assertNotIn("comment", self.memory.load("session-a"))
        self.assertTrue(any(item["accepted"] is False for item in decisions))

    def test_explicit_context_overrides_memory(self):
        self.memory.remember("session-a", {"recent_product": "旧产品"})
        merged = self.memory.merge("session-a", {"product_name": "新产品"})
        self.assertEqual(merged["product_name"], "新产品")
        self.assertEqual(merged["recent_product"], "旧产品")

    def test_reset_removes_memory(self):
        self.memory.remember("session-a", {"recent_brand": "品牌"})
        self.store.reset_session("session-a")
        self.assertEqual(self.memory.load("session-a"), {})


if __name__ == "__main__":
    unittest.main()
