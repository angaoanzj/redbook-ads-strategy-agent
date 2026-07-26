"""模块3 Agent 测试：MockTransport 按序返回工具调用与最终 JSON。

覆盖 happy / 修复 / 溯源失败 三条路径；不 import engine。分层预算、匹配分与单篇
放大预算均取自真实 build_keyword_tiers / plan_creator_tiers / match_creators，保证
grounding 可通过。
"""
from __future__ import annotations

import json
import unittest

import httpx

from models import CampaignRequest
from module_agents.module3 import Module3Output, run_module3
from tools import DEFAULT_REGISTRY


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
    return "决策如下：\n```json\n" + json.dumps(obj, ensure_ascii=False) + "\n```\n"


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
        spotlight_budget_cny=35000,
        goal="conversion",
        creator_evidence=[
            {"name": "小美", "profile_url": "http://x/1", "followers": 8000, "average_interactions": 400,
             "quote_cny": 300, "audience_tags": ["美食", "送礼"], "source_name": "蒲公英", "collected_at": "2026-05"},
            {"name": "阿强", "profile_url": "http://x/2", "followers": 100000, "average_interactions": 3000,
             "quote_cny": 2000, "audience_tags": ["美食"], "source_name": "CSV", "collected_at": "2026-05"},
        ],
    )


_KW_ARGS = {
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
    "rationale": "核心词围绕招牌产品，长尾扩场景，蓝海低价试探",
}
_KW = DEFAULT_REGISTRY.execute("build_keyword_tiers", _KW_ARGS)

_PLAN_ARGS = {
    "organic_budget_cny": 15000,
    "paid_budget_cny": 35000,
    "allocations": [
        {"tier": "素人", "count": 12, "budget_ratio": 0.5},
        {"tier": "达人", "count": 6, "budget_ratio": 0.35},
        {"tier": "KOL", "count": 2, "budget_ratio": 0.15},
    ],
    "rationale": "素人铺量、腰部达人承接、KOL 点睛的分层结构",
}
_PLAN = DEFAULT_REGISTRY.execute("plan_creator_tiers", _PLAN_ARGS)
_TIER_BY_NAME = {t["tier"]: t for t in _PLAN["tiers"]}

_MATCH_ARGS = {
    "creators": [
        {"name": "小美", "followers": 8000, "average_interactions": 400, "quote_cny": 300,
         "audience_tags": ["美食", "送礼"], "source_name": "蒲公英"},
        {"name": "阿强", "followers": 100000, "average_interactions": 3000, "quote_cny": 2000,
         "audience_tags": ["美食"], "source_name": "CSV"},
    ],
    "audience_keywords": ["美食", "送礼", "伴手礼"],
    "tier_budgets": {
        "素人": _TIER_BY_NAME["素人"]["suggested_quote_per_creator_cny"],
        "达人": _TIER_BY_NAME["达人"]["suggested_quote_per_creator_cny"],
        "KOL": _TIER_BY_NAME["KOL"]["suggested_quote_per_creator_cny"],
    },
    "per_note_cap_ratio": 0.5,
    "rationale": "按受众关键词交集匹配证据达人并给单篇放大预算",
}
_MATCH = DEFAULT_REGISTRY.execute("match_creators", _MATCH_ARGS)


def _organic_entry(row: dict) -> dict:
    return {"keyword": row["keyword"], "intent": row["intent"], "lane": row["lane"]}


def _valid_output() -> dict:
    tiers = _KW["keyword_tiers"]
    return {
        "keyword_tracks": {
            "organic": {
                "core": [_organic_entry(r) for r in tiers["core"]],
                "long_tail": [_organic_entry(r) for r in tiers["long_tail"]],
                "blue_ocean": [_organic_entry(r) for r in tiers["blue_ocean"]],
            },
            "search_ads": [
                {"keyword": "招牌蝴蝶酥", "bid_note": "搜索高意向抢位"},
                {"keyword": "蝴蝶酥礼盒", "bid_note": "搜索中意向稳投"},
                {"keyword": "手工蝴蝶酥推荐", "bid_note": "搜索长尾承接"},
            ],
            "feed_ads": [
                {"keyword": "送礼伴手礼", "bid_note": "信息流稳成本"},
                {"keyword": "办公室下午茶", "bid_note": "信息流蓝海试探"},
                {"keyword": "香港伴手礼", "bid_note": "信息流泛人群拉新"},
            ],
        },
        "creator_plan": {
            "tiers": [
                {
                    "tier": t["tier"],
                    "count": t["count"],
                    "collaboration_budget_cny": t["collaboration_budget_cny"],
                    "spotlight_amplification_budget_cny": t["spotlight_amplification_budget_cny"],
                }
                for t in _PLAN["tiers"]
            ],
            "amplification_pool_cny": _PLAN["spotlight_amplification_pool_cny"],
        },
        "matched_creators": [
            {
                "name": m["name"],
                "tier": m["tier"],
                "match_score": m["match_score"],
                "suggested_note_budget_cny": m["suggested_note_budget_cny"],
                "source": m["source"],
            }
            for m in _MATCH["matched_creators"]
        ],
        "open_slots": _MATCH["open_slots"],
        "human_review_items": ["达人名额不足需导入蒲公英补齐", "关键词出价需账户实时建议价校准"],
    }


def _run(responses_tail: list[dict]) -> dict:
    transport = _fake_model([
        _tool_call_response("build_keyword_tiers", _KW_ARGS, "call_1"),
        _tool_call_response("plan_creator_tiers", _PLAN_ARGS, "call_2"),
        _tool_call_response("match_creators", _MATCH_ARGS, "call_3"),
        *responses_tail,
    ])
    return run_module3(_sample_request(), transport=transport)


class Module3HappyPathTest(unittest.TestCase):
    def test_tools_then_valid_json(self) -> None:
        result = _run([_final_response(_fenced(_valid_output()))])

        self.assertEqual(result["module"], "module3_keyword_creator")
        self.assertEqual(result["repair_rounds_used"], 0)
        parsed = Module3Output.model_validate(result["output"])
        self.assertEqual(len(parsed.matched_creators), 2)
        self.assertTrue(parsed.open_slots)  # 达人不足 20，按层有缺口
        self.assertTrue(result["grounding_check"]["passed"], result["grounding_check"])


class Module3RepairPathTest(unittest.TestCase):
    def test_broken_then_repaired(self) -> None:
        broken = {k: v for k, v in _valid_output().items() if k != "human_review_items"}
        result = _run([
            _final_response(_fenced(broken)),           # 缺 human_review_items
            _final_response(_fenced(_valid_output())),  # 修复轮
        ])

        self.assertEqual(result["repair_rounds_used"], 1)
        self.assertTrue(result["grounding_check"]["passed"])


class Module3GroundingFailureTest(unittest.TestCase):
    def test_tampered_pool_flagged(self) -> None:
        tampered = _valid_output()
        tampered["creator_plan"]["amplification_pool_cny"] = 123456  # 工具从未产出该数字
        result = _run([_final_response(_fenced(tampered))])

        check = result["grounding_check"]
        self.assertFalse(check["passed"])
        self.assertIn("creator_plan.amplification_pool_cny", {m["path"] for m in check["mismatches"]})


if __name__ == "__main__":
    unittest.main()
