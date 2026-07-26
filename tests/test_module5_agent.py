"""模块5 Agent 底座测试：不依赖真实模型 Key，不 import engine。

沿用 tests/test_agent_tools.py 的 MockTransport 范式：伪造模型按序返回
预置的 /chat/completions 响应，覆盖 happy / 修复 / 溯源失败 / JSON 提取四条路径。
"""
from __future__ import annotations

import json
import unittest

import httpx

from models import CampaignRequest
from module_agents.base import extract_json_object
from module_agents.module5 import Module5Output, run_module5


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


# 与工具在 total=100000 / conversion 下的确定性输出一致的数字：
#   compute_budget_split -> organic 30000 / paid 70000 / 三阶段 14000/42000/14000
#   plan_creator_tiers(30000, 70000, 0.30, 素人0.5/达人0.35/KOL0.15)
#     pool 21000; collab 15000/10500/4500; spotlight 10500/7350/3150
_BUDGET_ARGS = {
    "total_budget_cny": 100000,
    "goal": "conversion",
    "rationale": "转化目标采用默认档 3:7，符合作业基准配比",
}
_CREATOR_ARGS = {
    "organic_budget_cny": 30000,
    "paid_budget_cny": 70000,
    "amplification_ratio": 0.30,
    "allocations": [
        {"tier": "素人", "count": 12, "budget_ratio": 0.5},
        {"tier": "达人", "count": 6, "budget_ratio": 0.35},
        {"tier": "KOL", "count": 2, "budget_ratio": 0.15},
    ],
    "rationale": "以素人与腰部达人为主，KOL 占位小比例，贴合转化目标",
}

_VALID_OUTPUT = {
    "budget_split": {
        "organic_budget_cny": 30000,
        "paid_budget_cny": 70000,
        "organic_ratio": 0.30,
        "needs_review": False,
    },
    "phases": [
        {"phase": "预热期", "paid_budget_cny": 14000, "key_actions": ["自然内容铺量", "小预算验证"]},
        {"phase": "爆发期", "paid_budget_cny": 42000, "key_actions": ["放大胜出素材"]},
        {"phase": "长尾期", "paid_budget_cny": 14000, "key_actions": ["优质内容续投", "搜索词占位"]},
    ],
    "creator_tier_plan": {
        "tiers": [
            {"tier": "素人", "count": 12, "collaboration_budget_cny": 15000, "spotlight_amplification_budget_cny": 10500},
            {"tier": "达人", "count": 6, "collaboration_budget_cny": 10500, "spotlight_amplification_budget_cny": 7350},
            {"tier": "KOL", "count": 2, "collaboration_budget_cny": 4500, "spotlight_amplification_budget_cny": 3150},
        ],
        "amplification_pool_cny": 21000,
    },
    "bid_plan": {"cold_start": None, "scaling": None, "basis": "无历史 CPC 证据，首轮用账户建议价测试"},
    "synergy_rules": [
        {"metric": "自然笔记互动率", "threshold": "达到校准门槛后", "action": "进入聚光小预算测试"},
        {"metric": "付费转化数据", "threshold": "跑通后", "action": "回流优化选题与关键词"},
    ],
    "contingency_plans": [
        {"scenario": "自然互动低", "trigger": "互动率低于门槛", "adjustment": "暂停扩产，重做首屏与选题"},
        {"scenario": "付费点击低", "trigger": "CTR 明显偏低", "adjustment": "先换素材再调定向，不同时多变量"},
    ],
    "human_review_items": ["工作簿数据来源需数据负责人确认", "达人候选名单需人工补充"],
}


def _fenced(obj: dict) -> str:
    return "根据工具计算，最终决策如下：\n```json\n" + json.dumps(obj, ensure_ascii=False) + "\n```\n"


class Module5HappyPathTest(unittest.TestCase):
    def test_two_tool_calls_then_valid_json(self) -> None:
        transport = _fake_model([
            _tool_call_response("compute_budget_split", _BUDGET_ARGS, "call_1"),
            _tool_call_response("plan_creator_tiers", _CREATOR_ARGS, "call_2"),
            _final_response(_fenced(_VALID_OUTPUT)),
        ])
        result = run_module5(_sample_request(), transport=transport)

        self.assertEqual(result["module"], "module5_budget_planning")
        self.assertEqual(result["repair_rounds_used"], 0)
        # 输出结构可被契约重新校验
        parsed = Module5Output.model_validate(result["output"])
        self.assertEqual(len(parsed.phases), 3)
        self.assertEqual(parsed.budget_split.paid_budget_cny, 70000)
        self.assertEqual(parsed.creator_tier_plan.amplification_pool_cny, 21000)
        # 溯源通过
        self.assertTrue(result["grounding_check"]["passed"], result["grounding_check"])
        self.assertEqual(result["grounding_check"]["mismatches"], [])


class Module5RepairPathTest(unittest.TestCase):
    def test_missing_field_then_repair(self) -> None:
        broken = {k: v for k, v in _VALID_OUTPUT.items() if k != "human_review_items"}
        transport = _fake_model([
            _tool_call_response("compute_budget_split", _BUDGET_ARGS, "call_1"),
            _tool_call_response("plan_creator_tiers", _CREATOR_ARGS, "call_2"),
            _final_response(_fenced(broken)),        # 首次：缺 human_review_items
            _final_response(_fenced(_VALID_OUTPUT)),  # 修复轮：合法 JSON
        ])
        result = run_module5(_sample_request(), transport=transport)

        self.assertEqual(result["repair_rounds_used"], 1)
        self.assertTrue(result["grounding_check"]["passed"])
        self.assertIn("human_review_items", result["output"])


class Module5GroundingFailureTest(unittest.TestCase):
    def test_untraceable_budget_flagged(self) -> None:
        tampered = json.loads(json.dumps(_VALID_OUTPUT))
        tampered["budget_split"]["organic_budget_cny"] = 88888  # 工具从未产出该数字
        transport = _fake_model([
            _tool_call_response("compute_budget_split", _BUDGET_ARGS, "call_1"),
            _tool_call_response("plan_creator_tiers", _CREATOR_ARGS, "call_2"),
            _final_response(_fenced(tampered)),
        ])
        result = run_module5(_sample_request(), transport=transport)

        check = result["grounding_check"]
        self.assertFalse(check["passed"])
        paths = {m["path"] for m in check["mismatches"]}
        self.assertIn("budget_split.organic_budget_cny", paths)
        self.assertIn(88888.0, {m["value"] for m in check["mismatches"]})


class Module5ModuleStatusTest(unittest.TestCase):
    """module_state 判定三态（docs/no-code-agent/02_模块状态输出契约.md）。"""

    def _run(self, output: dict) -> dict:
        transport = _fake_model([
            _tool_call_response("compute_budget_split", _BUDGET_ARGS, "call_1"),
            _tool_call_response("plan_creator_tiers", _CREATOR_ARGS, "call_2"),
            _final_response(_fenced(output)),
        ])
        return run_module5(_sample_request(), transport=transport)

    def test_clean_output_is_completed(self) -> None:
        result = self._run(_VALID_OUTPUT)
        self.assertEqual(result["module_status"], "completed")
        self.assertEqual(result["unresolved_gaps"], [])

    def test_grounding_failure_is_completed_with_gaps(self) -> None:
        tampered = json.loads(json.dumps(_VALID_OUTPUT))
        tampered["budget_split"]["organic_budget_cny"] = 88888  # 工具从未产出该数字
        result = self._run(tampered)

        self.assertFalse(result["grounding_check"]["passed"])
        self.assertEqual(result["module_status"], "completed_with_gaps")
        self.assertTrue(result["unresolved_gaps"])
        self.assertIn("budget_split.organic_budget_cny", result["unresolved_gaps"][0])

    def test_pending_marker_is_completed_with_gaps_and_lists_review_items(self) -> None:
        marked = json.loads(json.dumps(_VALID_OUTPUT))
        marked["bid_plan"]["basis"] = "演示补全 CVR，出价待投手确认后再执行"
        marked["human_review_items"] = ["投手确认首轮出价", "补齐账户级 CPC"]
        result = self._run(marked)

        self.assertTrue(result["grounding_check"]["passed"], result["grounding_check"])
        self.assertEqual(result["module_status"], "completed_with_gaps")
        self.assertEqual(
            result["unresolved_gaps"], ["投手确认首轮出价", "补齐账户级 CPC"]
        )

    def test_status_never_blocked_at_base_layer(self) -> None:
        # blocked 只由编排层按硬前序判定
        result = self._run(_VALID_OUTPUT)
        self.assertNotEqual(result["module_status"], "blocked")


class JsonExtractionTest(unittest.TestCase):
    def test_fenced_and_bare_both_parse(self) -> None:
        fenced = "前言\n```json\n{\"a\": 1, \"b\": {\"c\": 2}}\n```\n后记"
        bare = "这里直接给对象 {\"a\": 1, \"b\": {\"c\": 2}} 结束"
        self.assertEqual(extract_json_object(fenced), {"a": 1, "b": {"c": 2}})
        self.assertEqual(extract_json_object(bare), {"a": 1, "b": {"c": 2}})

    def test_first_parseable_object_wins(self) -> None:
        text = "坏的 {not json} 好的 {\"ok\": true}"
        self.assertEqual(extract_json_object(text), {"ok": True})

    def test_none_when_no_object(self) -> None:
        self.assertIsNone(extract_json_object("没有任何 JSON 对象"))


if __name__ == "__main__":
    unittest.main()
