"""模块2 Agent 测试：MockTransport 按序返回工具调用与最终 JSON。

覆盖 happy / 修复 / 溯源失败 三条路径；不 import engine。方向双评分与两个筛选阈值
用真实 score_content_topics 预算，保证 grounding 可通过。
"""
from __future__ import annotations

import copy
import json
import unittest

import httpx

from models import CampaignRequest
from module_agents.module2 import Module2Output, run_module2
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
        goal="conversion",
    )


_DIRECTIONS = [
    {"direction": "送礼场景", "organic_score": 8, "paid_score": 6, "rationale": "送礼场景自然流量强，付费可承接成交"},
    {"direction": "口味测评", "organic_score": 7, "paid_score": 7, "rationale": "口味测评兼顾种草与转化"},
    {"direction": "到港攻略", "organic_score": 6, "paid_score": 8, "rationale": "到港攻略付费拉新效率高"},
]


def _topic(direction: str, index: int, paid: bool) -> dict:
    return {
        "title_template": f"选题标题模板{direction}{index}",
        "cover_suggestion": "封面建议文案",
        "outline": ["大纲要点一", "大纲要点二"],
        "direction": direction,
        "suitable_for_paid": paid,
        "paid_objective": "成交" if paid else None,
    }


def _topics() -> list[dict]:
    topics = []
    for d in ("送礼场景", "口味测评", "到港攻略"):
        for i in range(5):
            topics.append(_topic(d, i, paid=(i == 0)))
    return topics


_TOPIC_ARGS = {
    "directions": _DIRECTIONS,
    "topics": _topics(),
    "rationale": "三方向均衡分布，各 5 个选题",
}
_TOPIC = DEFAULT_REGISTRY.execute("score_content_topics", _TOPIC_ARGS)


def _valid_output() -> dict:
    return copy.deepcopy({
        "persona": {
            "demographic": ["25-40 岁女性", "一二线城市"],
            "behavioral": ["搜索伴手礼", "关注美食博主"],
            "psychological": ["重视送礼体面", "追求品质"],
            "targeting_tags": {
                "interest_tags": ["美食", "伴手礼", "下午茶"],
                "behavior_tags": ["搜索送礼", "收藏美食", "到店打卡"],
                "crowd_packages": ["送礼人群包", "到港游客包"],
            },
            "tag_status": "以上标签需在聚光后台核对可用性后再投放",
        },
        "content_directions": _DIRECTIONS,
        "topics": _topics(),
        "material_screening": {
            "ctr_threshold": _TOPIC["material_screening"]["ctr_threshold"],
            "engagement_threshold": _TOPIC["material_screening"]["engagement_threshold"],
            "extra_rules": ["评论正向占比人工判断", "3 秒完播率作为短视频补充指标"],
        },
        "human_review_items": ["定向标签可用性需后台核对", "选题排期需内容团队确认"],
    })


class Module2HappyPathTest(unittest.TestCase):
    def test_tool_call_then_valid_json(self) -> None:
        transport = _fake_model([
            _tool_call_response("score_content_topics", _TOPIC_ARGS, "call_1"),
            _final_response(_fenced(_valid_output())),
        ])
        result = run_module2(_sample_request(), transport=transport)

        self.assertEqual(result["module"], "module2_audience_content")
        self.assertEqual(result["repair_rounds_used"], 0)
        parsed = Module2Output.model_validate(result["output"])
        self.assertEqual(len(parsed.content_directions), 3)
        self.assertEqual(len(parsed.topics), 15)
        self.assertTrue(result["grounding_check"]["passed"], result["grounding_check"])


class Module2RepairPathTest(unittest.TestCase):
    def test_broken_then_repaired(self) -> None:
        broken = {k: v for k, v in _valid_output().items() if k != "material_screening"}
        transport = _fake_model([
            _tool_call_response("score_content_topics", _TOPIC_ARGS, "call_1"),
            _final_response(_fenced(broken)),            # 缺 material_screening
            _final_response(_fenced(_valid_output())),   # 修复轮
        ])
        result = run_module2(_sample_request(), transport=transport)

        self.assertEqual(result["repair_rounds_used"], 1)
        self.assertTrue(result["grounding_check"]["passed"])


class Module2GroundingFailureTest(unittest.TestCase):
    def test_tampered_score_flagged(self) -> None:
        tampered = _valid_output()
        # 9 合法（1-10）但工具从未产出该数字，可过契约却触发溯源失败
        tampered["content_directions"][0]["organic_score"] = 9
        transport = _fake_model([
            _tool_call_response("score_content_topics", _TOPIC_ARGS, "call_1"),
            _final_response(_fenced(tampered)),
        ])
        result = run_module2(_sample_request(), transport=transport)

        check = result["grounding_check"]
        self.assertFalse(check["passed"])
        self.assertIn("content_directions.0.organic_score", {m["path"] for m in check["mismatches"]})
        self.assertIn(9.0, {m["value"] for m in check["mismatches"]})


if __name__ == "__main__":
    unittest.main()
