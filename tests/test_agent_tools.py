"""工具层与最小 Agent Loop 测试：不依赖真实模型 Key。"""
from __future__ import annotations

import json
import unittest

import httpx

from agent_core import AgentLoop, AgentLoopError
from tools import DEFAULT_REGISTRY


class ToolRegistryTest(unittest.TestCase):
    def test_schemas_are_function_calling_compatible(self) -> None:
        schemas = DEFAULT_REGISTRY.openai_schemas()
        self.assertEqual(
            {item["function"]["name"] for item in schemas},
            {
                "compute_budget_split",
                "calc_bid_range",
                "plan_creator_tiers",
                "estimate_paid_performance",
                "build_keyword_tiers",
                "summarize_competitor_landscape",
                "score_content_topics",
                "match_creators",
                "audit_note_content",
                "build_ab_test_matrix",
                "monitor_competitor_ads",
                "evaluate_trending_keywords",
            },
        )
        for item in schemas:
            self.assertIn("properties", item["function"]["parameters"])

    def test_unknown_tool_returns_error_not_exception(self) -> None:
        result = DEFAULT_REGISTRY.execute("no_such_tool", "{}")
        self.assertIn("error", result)
        self.assertIn("hint", result)


class BudgetToolTest(unittest.TestCase):
    def test_conversion_goal_defaults_to_30_70(self) -> None:
        result = DEFAULT_REGISTRY.execute("compute_budget_split", {
            "total_budget_cny": 50000,
            "goal": "conversion",
            "rationale": "转化目标采用默认档 3:7",
        })
        self.assertEqual(result["organic_budget_cny"], 15000)
        self.assertEqual(result["paid_budget_cny"], 35000)
        self.assertTrue(result["arithmetic_check"])
        self.assertFalse(result["needs_review"])
        # 三阶段之和必须精确等于付费预算
        self.assertEqual(
            sum(item["paid_budget_cny"] for item in result["paid_phases"]), 35000
        )

    def test_llm_can_override_ratio_within_guardrail(self) -> None:
        result = DEFAULT_REGISTRY.execute("compute_budget_split", {
            "total_budget_cny": 50000,
            "goal": "conversion",
            "organic_ratio": 0.45,
            "rationale": "品牌自然流量基础弱，需要加大内容生产投入作为证据补充",
        })
        self.assertEqual(result["organic_ratio"], 0.45)
        self.assertTrue(result["needs_review"])  # 偏离默认档 >0.10，标记人工复核

    def test_out_of_guardrail_ratio_rejected(self) -> None:
        result = DEFAULT_REGISTRY.execute("compute_budget_split", {
            "total_budget_cny": 50000,
            "goal": "conversion",
            "organic_ratio": 0.9,
            "rationale": "全部做自然内容",
        })
        self.assertIn("error", result)


class BiddingToolTest(unittest.TestCase):
    def test_missing_baseline_returns_evidence_gap(self) -> None:
        result = DEFAULT_REGISTRY.execute("calc_bid_range", {
            "stage": "cold_start",
            "baseline_cpc_cny": None,
            "low_multiplier": 0.9,
            "high_multiplier": 1.1,
            "rationale": "无历史CPC证据，先用账户建议价测试",
        })
        self.assertIsNone(result["low_cny_per_click"])
        self.assertEqual(result["evidence_status"], "待补数据")

    def test_stage_guardrail_enforced(self) -> None:
        result = DEFAULT_REGISTRY.execute("calc_bid_range", {
            "stage": "cold_start",
            "baseline_cpc_cny": 1.6,
            "baseline_source": "数据需求.xlsx",
            "low_multiplier": 0.9,
            "high_multiplier": 1.5,  # cold_start 上限 1.3
            "rationale": "冷启动激进放量测试",
        })
        self.assertIn("error", result)

    def test_accepts_baseline_cpc_source_alias(self) -> None:
        """LLM 常把 forecast 的 baseline_cpc_source 误传到出价工具，应兼容。"""
        result = DEFAULT_REGISTRY.execute("calc_bid_range", {
            "stage": "cold_start",
            "baseline_cpc_cny": 1.6,
            "baseline_cpc_source": "数据需求.xlsx",  # 别名
            "low_multiplier": 0.9,
            "high_multiplier": 1.1,
            "rationale": "兼容 baseline_cpc_source 别名，避免工具循环烧步数",
        })
        self.assertNotIn("error", result)
        self.assertEqual(result["low_cny_per_click"], 1.44)
        self.assertEqual(result["high_cny_per_click"], 1.76)


class CreatorToolTest(unittest.TestCase):
    def test_ratio_sum_must_be_one(self) -> None:
        result = DEFAULT_REGISTRY.execute("plan_creator_tiers", {
            "organic_budget_cny": 15000,
            "paid_budget_cny": 35000,
            "allocations": [
                {"tier": "素人", "count": 12, "budget_ratio": 0.5},
                {"tier": "达人", "count": 6, "budget_ratio": 0.4},
            ],
            "rationale": "素人与腰部达人为主的分层结构",
        })
        self.assertIn("error", result)

    def test_math_adds_up(self) -> None:
        result = DEFAULT_REGISTRY.execute("plan_creator_tiers", {
            "organic_budget_cny": 15000,
            "paid_budget_cny": 35000,
            "allocations": [
                {"tier": "素人", "count": 12, "budget_ratio": 0.5},
                {"tier": "达人", "count": 6, "budget_ratio": 0.35},
                {"tier": "KOL", "count": 2, "budget_ratio": 0.15},
            ],
            "rationale": "沿用作业默认分层结构进行验证",
        })
        self.assertEqual(result["spotlight_amplification_pool_cny"], 10500)
        tiers = {item["tier"]: item for item in result["tiers"]}
        self.assertEqual(tiers["素人"]["collaboration_budget_cny"], 7500)
        self.assertEqual(tiers["KOL"]["suggested_quote_per_creator_cny"], 1125)


def _fake_model(responses: list[dict]) -> httpx.MockTransport:
    """按顺序返回预置的 /chat/completions 响应。"""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tools"], "AgentLoop 必须携带工具 schema"
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


class AgentLoopRetryTest(unittest.TestCase):
    """瞬时断连应自动重试，而不是立刻把整个模块 Agent 打挂。"""

    def test_retries_remote_protocol_error_then_succeeds(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
            return httpx.Response(
                200,
                json={
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "重试后收敛",
                        }
                    }]
                },
            )

        agent = AgentLoop(
            "测试系统提示",
            DEFAULT_REGISTRY,
            transport=httpx.MockTransport(handler),
            max_retries=3,
            retry_backoff_sec=0,  # 单测不等待
        )
        outcome = agent.run("任意用户输入", max_steps=3)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(outcome["final"], "重试后收敛")

    def test_exhausted_retries_raise_agent_loop_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.RemoteProtocolError("still down")

        agent = AgentLoop(
            "测试系统提示",
            DEFAULT_REGISTRY,
            transport=httpx.MockTransport(handler),
            max_retries=3,
            retry_backoff_sec=0,
        )
        with self.assertRaises(AgentLoopError) as ctx:
            agent.run("任意用户输入", max_steps=2)
        self.assertIn("3 次尝试后仍失败", str(ctx.exception))
        self.assertIn("RemoteProtocolError", str(ctx.exception))


class AgentLoopSelfCorrectionTest(unittest.TestCase):
    """伪造模型：先提交非法参数 → 收到校验错误 → 修正 → 给出最终答案。"""

    def test_loop_feeds_validation_error_back_and_converges(self) -> None:
        bad_args = {
            "total_budget_cny": 50000,
            "goal": "conversion",
            "organic_ratio": 0.9,  # 越过护栏
            "rationale": "尝试全自然内容策略",
        }
        good_args = {
            "total_budget_cny": 50000,
            "goal": "conversion",
            "rationale": "护栏拒绝后改用默认档 3:7",
        }
        transport = _fake_model([
            _tool_call_response("compute_budget_split", bad_args, "call_1"),
            _tool_call_response("compute_budget_split", good_args, "call_2"),
            {"choices": [{"message": {"role": "assistant", "content": "预算拆分完成：自然15000/聚光35000"}}]},
        ])
        agent = AgentLoop("测试系统提示", DEFAULT_REGISTRY, transport=transport)
        outcome = agent.run("拆分曲奇四重奏 50000 元预算", max_steps=5)

        self.assertEqual(outcome["steps_used"], 3)
        tool_steps = [row for row in outcome["trace"] if row["action"] == "tool_call"]
        self.assertFalse(tool_steps[0]["ok"])  # 第一次被护栏拒绝
        self.assertTrue(tool_steps[1]["ok"])   # 修正后通过
        self.assertIn("15000", outcome["final"])
        # 校验错误必须以 tool 消息形式回传给模型
        tool_messages = [m for m in outcome["messages"] if m["role"] == "tool"]
        self.assertIn("参数校验失败", tool_messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
