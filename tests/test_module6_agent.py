"""模块6 Agent 测试：伪造模型（MockTransport）按序返回工具调用与最终 JSON。

覆盖 happy / 修复 / 溯源失败 三条路径，以及实时热搜链路（mock API→DB→实时取值）：
rising_keywords 契约、_load_live_trending 的空库容错、build_user_prompt 的实时区块。
不 import engine。grounding 覆盖三级预算比例与热搜热度（词表 bid_note 为文本不溯源）。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import httpx
from pydantic import ValidationError

from models import CampaignRequest
from module_agents.module6 import (
    Module6Output,
    _load_live_trending,
    build_user_prompt,
    run_module6,
)


def _fake_model(responses: list[dict]) -> httpx.MockTransport:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tools"], "模块 Agent 必须携带工具 schema"
        return httpx.Response(200, json=queue.pop(0))

    return httpx.MockTransport(handler)


def _tool_call_response(name: str, arguments: dict, call_id: str) -> dict:
    return {"choices": [{"message": {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }],
    }}]}


def _final_response(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _fenced(obj: dict) -> str:
    return "关键词策略如下：\n```json\n" + json.dumps(obj, ensure_ascii=False) + "\n```\n"


def _sample_request() -> CampaignRequest:
    return CampaignRequest(
        brand_name="曲奇四重奏",
        category="香港蝴蝶酥伴手礼",
        product_name="经典原味蝴蝶酥礼盒",
        selling_points=["招牌经典款", "牛油香浓层次酥脆"],
        price_min=228,
        price_max=228,
        currency="HKD",
        initial_audience="到港游客与送礼人群",
        total_budget_cny=100000,
        goal="search_growth",
    )


_KEYWORD_ARGS = {
    "keywords": [
        {"keyword": "招牌蝴蝶酥", "level": "core", "intent": "high", "lane": "search", "from_evidence": True},
        {"keyword": "蝴蝶酥礼盒", "level": "core", "intent": "mid", "lane": "search", "from_evidence": True},
        {"keyword": "手工蝴蝶酥推荐", "level": "long_tail", "intent": "high", "lane": "search", "from_evidence": True},
        {"keyword": "蝴蝶酥怎么选", "level": "long_tail", "intent": "mid", "lane": "search", "from_evidence": False},
        {"keyword": "送礼伴手礼", "level": "long_tail", "intent": "mid", "lane": "feed", "from_evidence": False},
        {"keyword": "香港伴手礼", "level": "long_tail", "intent": "high", "lane": "both", "from_evidence": False},
        {"keyword": "低糖蝴蝶酥", "level": "blue_ocean", "intent": "low", "lane": "search", "from_evidence": False},
        {"keyword": "办公室下午茶", "level": "blue_ocean", "intent": "mid", "lane": "feed", "from_evidence": False},
    ],
    "level_budget_split": {"core": 0.5, "long_tail": 0.3, "blue_ocean": 0.2},
    "rationale": "核心词占主预算，长尾承接精准意向，蓝海词低价试探",
}


def _valid_output() -> dict:
    return {
        "keyword_levels": {
            "core": [
                {"keyword": "招牌蝴蝶酥", "intent": "high", "lane": "search", "bid_note": "搜索高意向抢位 1.0–1.3"},
                {"keyword": "蝴蝶酥礼盒", "intent": "mid", "lane": "search", "bid_note": "搜索中意向稳投 0.9–1.1"},
            ],
            "long_tail": [
                {"keyword": "手工蝴蝶酥推荐", "intent": "high", "lane": "search", "bid_note": "搜索高意向抢位 1.0–1.3"},
                {"keyword": "蝴蝶酥怎么选", "intent": "mid", "lane": "search", "bid_note": "搜索中意向稳投 0.9–1.1"},
                {"keyword": "送礼伴手礼", "intent": "mid", "lane": "feed", "bid_note": "信息流稳成本 0.7–1.0"},
                {"keyword": "香港伴手礼", "intent": "high", "lane": "both", "bid_note": "搜索高意向抢位 1.0–1.3"},
            ],
            "blue_ocean": [
                {"keyword": "低糖蝴蝶酥", "intent": "low", "lane": "search", "bid_note": "低价试探 0.6–0.8"},
                {"keyword": "办公室下午茶", "intent": "mid", "lane": "feed", "bid_note": "低价试探 0.6–0.8"},
            ],
        },
        "layout_rules": [
            {"position": "标题", "rule": "核心词前置，1 个核心词 + 1 个长尾词"},
            {"position": "正文", "rule": "首段自然植入核心词，长尾词分布中后段"},
            {"position": "标签", "rule": "核心词 + 蓝海词各 2-3 个，避免堆砌"},
        ],
        "level_budget_split": {"core": 0.5, "long_tail": 0.3, "blue_ocean": 0.2},
        "trending_monitor": {
            "mechanism": "每日人工复核合规趋势源，命中则新增长尾词并小额试投",
            "follow_criteria": ["互动增速连续3天上升", "与卖点强相关"],
            "data_source_status": "实时热搜待接入数据源",
        },
        "human_review_items": ["蓝海词需搜索量校准", "趋势词需合规来源确认"],
    }


class Module6HappyPathTest(unittest.TestCase):
    def test_tool_call_then_valid_json(self) -> None:
        transport = _fake_model([
            _tool_call_response("build_keyword_tiers", _KEYWORD_ARGS, "call_1"),
            _final_response(_fenced(_valid_output())),
        ])
        result = run_module6(_sample_request(), transport=transport)

        self.assertEqual(result["module"], "module6_keyword_strategy")
        self.assertEqual(result["repair_rounds_used"], 0)
        parsed = Module6Output.model_validate(result["output"])
        self.assertGreaterEqual(len(parsed.keyword_levels.long_tail), 4)
        self.assertIn("待接入数据源", parsed.trending_monitor.data_source_status)
        self.assertTrue(result["grounding_check"]["passed"], result["grounding_check"])


class Module6RepairPathTest(unittest.TestCase):
    def test_broken_then_repaired(self) -> None:
        broken = {k: v for k, v in _valid_output().items() if k != "trending_monitor"}
        transport = _fake_model([
            _tool_call_response("build_keyword_tiers", _KEYWORD_ARGS, "call_1"),
            _final_response(_fenced(broken)),          # 缺 trending_monitor
            _final_response(_fenced(_valid_output())),  # 修复轮
        ])
        result = run_module6(_sample_request(), transport=transport)

        self.assertEqual(result["repair_rounds_used"], 1)
        self.assertTrue(result["grounding_check"]["passed"])
        self.assertIn("trending_monitor", result["output"])


class Module6GroundingFailureTest(unittest.TestCase):
    def test_tampered_split_flagged(self) -> None:
        tampered = _valid_output()
        # 合计仍为 1（Pydantic 通过），但 0.45/0.35 并非工具产出 → 溯源失败
        tampered["level_budget_split"] = {"core": 0.45, "long_tail": 0.35, "blue_ocean": 0.2}
        transport = _fake_model([
            _tool_call_response("build_keyword_tiers", _KEYWORD_ARGS, "call_1"),
            _final_response(_fenced(tampered)),
        ])
        result = run_module6(_sample_request(), transport=transport)

        check = result["grounding_check"]
        self.assertFalse(check["passed"])
        paths = {m["path"] for m in check["mismatches"]}
        self.assertIn("level_budget_split.core", paths)
        self.assertIn("level_budget_split.long_tail", paths)


# ---------------------------------------------------------------------------
# 实时热搜链路：mock API → 数据库 → 模块运行时实时取值
# ---------------------------------------------------------------------------
CATEGORY = "香港蝴蝶酥伴手礼"

_TRENDING_ARGS = {
    "candidates": [
        {
            "keyword": "蝴蝶酥礼盒推荐",
            "heat_score": 82.0,
            "previous_heat": 70.0,
            "source_name": "模拟实时数据源（合规同构接口演示）",
            "is_mock": True,
        },
        {
            "keyword": "显卡降价",
            "heat_score": 91.0,
            "previous_heat": 60.0,
            "source_name": "模拟实时数据源（合规同构接口演示）",
            "is_mock": True,
        },
    ],
    "brand_terms": ["曲奇四重奏", "蝴蝶酥礼盒", "香港伴手礼"],
    "category": CATEGORY,
    "rationale": "对实时取值区的候选词做趋势与跟进判定",
}

_RISING_KEYWORDS = [
    {
        "keyword": "蝴蝶酥礼盒推荐",
        "heat_score": 82.0,
        "trend": "rising",
        "recommendation": "跟进",
        "reason": "与品类/品牌有 1 处词面匹配，且热度较上一批上升超过 5%，处于爬坡期",
    },
    {
        "keyword": "显卡降价",
        "heat_score": 91.0,
        "trend": "rising",
        "recommendation": "不跟进",
        "reason": "与品类/品牌卖点无关键词匹配，属无关热点，蹭点会拉低搜索相关性",
    },
]


def _output_with_rising(rows: list[dict]) -> dict:
    output = _valid_output()
    output["trending_monitor"]["rising_keywords"] = rows
    output["trending_monitor"]["data_source_status"] = (
        "已接入模拟实时数据源（线上实时取值），真实合规源待授权接入"
    )
    return output


class Module6RisingKeywordsContractTest(unittest.TestCase):
    def test_tool_result_flows_into_rising_keywords(self) -> None:
        transport = _fake_model([
            _tool_call_response("build_keyword_tiers", _KEYWORD_ARGS, "call_1"),
            _tool_call_response("evaluate_trending_keywords", _TRENDING_ARGS, "call_2"),
            _final_response(_fenced(_output_with_rising(_RISING_KEYWORDS))),
        ])
        result = run_module6(_sample_request(), transport=transport)

        parsed = Module6Output.model_validate(result["output"])
        rising = parsed.trending_monitor.rising_keywords
        self.assertEqual(len(rising), 2)
        self.assertEqual(rising[0].recommendation, "跟进")
        self.assertEqual(rising[1].recommendation, "不跟进")
        self.assertEqual(rising[0].trend, "rising")
        # 热度取自工具结果 → 溯源通过
        self.assertTrue(result["grounding_check"]["passed"], result["grounding_check"])

        called = [row["tool"] for row in result["trace"] if row.get("action") == "tool_call"]
        self.assertIn("evaluate_trending_keywords", called)

    def test_fabricated_heat_score_is_flagged_by_grounding(self) -> None:
        tampered = _output_with_rising([
            {**_RISING_KEYWORDS[0], "heat_score": 99.4},  # 工具结果里不存在的热度
            _RISING_KEYWORDS[1],
        ])
        transport = _fake_model([
            _tool_call_response("build_keyword_tiers", _KEYWORD_ARGS, "call_1"),
            _tool_call_response("evaluate_trending_keywords", _TRENDING_ARGS, "call_2"),
            _final_response(_fenced(tampered)),
        ])
        result = run_module6(_sample_request(), transport=transport)

        check = result["grounding_check"]
        self.assertFalse(check["passed"])
        self.assertIn(
            "trending_monitor.rising_keywords.0.heat_score",
            {item["path"] for item in check["mismatches"]},
        )

    def test_rising_keywords_defaults_to_empty_and_enforces_enum(self) -> None:
        # 旧存档（无 rising_keywords 字段）仍可通过契约校验 → 默认空数组
        legacy = Module6Output.model_validate(_valid_output())
        self.assertEqual(legacy.trending_monitor.rising_keywords, [])

        bad = _output_with_rising([{**_RISING_KEYWORDS[0], "recommendation": "再看看"}])
        with self.assertRaises(ValidationError):
            Module6Output.model_validate(bad)


class Module6LiveTrendingTest(unittest.TestCase):
    """_load_live_trending / build_user_prompt 的实时取值行为（用 tmp XHS_FEED_DB 隔离）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "feed.db"
        original = os.environ.get("XHS_FEED_DB")
        os.environ["XHS_FEED_DB"] = str(self.db_path)

        def restore() -> None:
            if original is None:
                os.environ.pop("XHS_FEED_DB", None)
            else:
                os.environ["XHS_FEED_DB"] = original

        self.addCleanup(restore)

    def _inject(self, batches: int = 2, seed: str = "module6-live") -> list:
        from realtime_feed import FeedStore, MockRealtimeFeedAdapter

        store = FeedStore()
        adapter = MockRealtimeFeedAdapter(
            seed, CATEGORY, "曲奇四重奏", product_name="经典原味蝴蝶酥礼盒"
        )
        saved = []
        for _ in range(batches):
            batch = adapter.pull()
            store.save_batch(batch)
            saved.append(batch)
        return saved

    def test_empty_store_returns_empty_without_raising(self) -> None:
        self.assertEqual(_load_live_trending(), [])
        self.assertEqual(_load_live_trending(limit=0), [])

    def test_unreadable_store_degrades_to_empty(self) -> None:
        broken = Path(self._tmp.name) / "broken.db"
        broken.write_text("not a sqlite file", encoding="utf-8")
        os.environ["XHS_FEED_DB"] = str(broken)
        self.assertEqual(_load_live_trending(), [])

    def test_prompt_has_no_live_block_when_store_empty(self) -> None:
        prompt = build_user_prompt(_sample_request())
        self.assertNotIn("实时热搜（来自数据源 DB", prompt)
        self.assertIn("无热搜数据", prompt)
        self.assertIn("rising_keywords 必须留空", prompt)
        self.assertIn("待接入数据源", prompt)

    def test_prompt_renders_live_block_after_two_mock_batches(self) -> None:
        batches = self._inject(batches=2)
        live = _load_live_trending()
        self.assertTrue(live)
        self.assertTrue(any(row["previous_heat"] is not None for row in live))

        prompt = build_user_prompt(_sample_request())
        self.assertIn("实时热搜（来自数据源 DB，线上实时取值）", prompt)
        self.assertIn("evaluate_trending_keywords", prompt)
        self.assertIn("is_mock=true", prompt)
        self.assertNotIn("无热搜数据", prompt)
        for keyword in {item.keyword for item in batches[-1].trending}:
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, prompt)
        self.assertIn("上批热度", prompt)
        self.assertIn("模拟实时数据源", prompt)

    def test_live_and_request_evidence_are_merged_and_deduplicated(self) -> None:
        self._inject(batches=2)
        live_keyword = _load_live_trending()[0]["keyword"]
        payload = _sample_request().model_dump()
        payload["trending_keyword_evidence"] = [
            {
                "keyword": live_keyword,  # 与实时取值重复 → 只渲染一次
                "source_name": "人工粘贴热搜词",
                "collected_at": "2026-07-24",
                "heat_score": 88,
            },
            {
                "keyword": "香港伴手礼",
                "source_name": "人工粘贴热搜词",
                "collected_at": "2026-07-24",
                "heat_score": 70,
            },
        ]
        prompt = build_user_prompt(CampaignRequest.model_validate(payload))
        self.assertEqual(prompt.count(f"词：{live_keyword}｜"), 1)
        self.assertIn("请求内热搜/趋势词证据：1 条", prompt)
        self.assertIn("香港伴手礼", prompt)


if __name__ == "__main__":
    unittest.main()
