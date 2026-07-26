"""双通道模型配置测试。"""
from __future__ import annotations

import os
import unittest

from model_config import (
    DEEPSEEK_DEFAULT_MODEL,
    LOCAL_ENV_CANDIDATES,
    PROJECT_ROOT,
    chat_request_extras,
    load_analyzer_config,
    load_embedding_config,
)


class ModelConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            key: os.environ.get(key)
            for key in [
                "AGENT_ANALYZER_API_KEY",
                "AGENT_ANALYZER_BASE_URL",
                "AGENT_ANALYZER_MODEL",
                "AGENT_EMBEDDING_API_KEY",
                "AGENT_EMBEDDING_BASE_URL",
                "AGENT_EMBEDDING_MODEL",
                "AGENT_OPENAI_API_KEY",
                "AGENT_OPENAI_BASE_URL",
                "AGENT_OPENAI_MODEL",
            ]
        }
        for key in self._saved:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_env_candidates_stay_inside_project_root(self) -> None:
        """独立交付：不得读取上级课程仓 agent-course-versions/course.env。"""
        for path in LOCAL_ENV_CANDIDATES:
            self.assertEqual(path.parent, PROJECT_ROOT)
            self.assertNotIn("agent-course-versions", str(path))

    def test_inline_comment_stripped_from_model(self) -> None:
        os.environ["AGENT_ANALYZER_API_KEY"] = "sk-test"
        os.environ["AGENT_ANALYZER_BASE_URL"] = "https://api.deepseek.com"
        os.environ["AGENT_ANALYZER_MODEL"] = "deepseek-v4-flash   # 或 deepseek-v4-pro"
        config = load_analyzer_config()
        self.assertEqual(config["model"], "deepseek-v4-flash")

        os.environ["AGENT_ANALYZER_API_KEY"] = "sk-test"
        os.environ["AGENT_ANALYZER_BASE_URL"] = "https://api.deepseek.com"
        os.environ["AGENT_ANALYZER_MODEL"] = "deepseek-chat"
        config = load_analyzer_config()
        self.assertEqual(config["model"], DEEPSEEK_DEFAULT_MODEL)

    def test_dual_channel_separation(self) -> None:
        os.environ["AGENT_ANALYZER_API_KEY"] = "sk-deepseek"
        os.environ["AGENT_ANALYZER_BASE_URL"] = "https://api.deepseek.com"
        os.environ["AGENT_ANALYZER_MODEL"] = "deepseek-v4-flash"
        os.environ["AGENT_EMBEDDING_API_KEY"] = "sk-silicon"
        os.environ["AGENT_EMBEDDING_BASE_URL"] = "https://api.siliconflow.cn/v1"
        os.environ["AGENT_EMBEDDING_MODEL"] = "Qwen/Qwen3-Embedding-4B"
        analyzer = load_analyzer_config()
        embedding = load_embedding_config()
        self.assertEqual(analyzer["base_url"], "https://api.deepseek.com")
        self.assertEqual(analyzer["model"], "deepseek-v4-flash")
        self.assertEqual(embedding["base_url"], "https://api.siliconflow.cn/v1")
        self.assertIn("Embedding", embedding["model"])

    def test_deepseek_extras_disable_thinking(self) -> None:
        extras = chat_request_extras({
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
        })
        self.assertEqual(extras.get("thinking"), {"type": "disabled"})
        self.assertNotIn("enable_thinking", extras)


if __name__ == "__main__":
    unittest.main()
