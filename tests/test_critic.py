"""强模型 Critic 二审测试：不依赖真实模型 Key，不 import engine。

沿用 tests/test_module5_agent.py 的 MockTransport 范式：伪造模型按序返回预置的
/chat/completions 响应，覆盖 契约 / happy / 坏 JSON 重试后降级 / 网络异常降级 四条路径。
核心断言之一：Critic 是增强不是闸门——任何失败都只返回 degraded，绝不抛异常。
"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

import httpx
from pydantic import ValidationError

from module_agents.critic import (
    CriticReport,
    critic_enabled,
    load_critic_config,
    run_critic,
)


def _fake_model(responses: list[dict]) -> tuple[httpx.MockTransport, list[dict]]:
    """按序返回预置响应；同时把每次请求体记下来供断言（Critic 不得携带 tools）。"""
    queue = list(responses)
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        assert "tools" not in body, "Critic 是纯文本二审，不应携带工具 schema"
        return httpx.Response(200, json=queue.pop(0))

    return httpx.MockTransport(handler), seen


def _final_response(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _fenced(obj: dict) -> str:
    return "二审结论如下：\n```json\n" + json.dumps(obj, ensure_ascii=False) + "\n```\n"


_VALID_REPORT = {
    "verdict": "revise",
    "dimension_scores": {
        "evidence_citation": 6,
        "executability": 5,
        "compliance_wording": 8,
        "consistency": 7,
    },
    "issues": [
        {
            "path": "account_structure.campaigns.0.placement",
            "severity": "high",
            "problem": "版位写成「自然内容」，不是聚光付费版位",
            "suggestion": "改为「搜索推广」或「信息流推广」",
        },
        {
            "path": "daily_schedule.1.action",
            "severity": "medium",
            "problem": "写成「总结当日数据」的值班表事项，不是投放动作",
            "suggestion": "改为具体的加价/加预算/暂停计划等投放动作",
        },
    ],
    "summary": "结构可用，但版位与时段动作需要修正。",
}

_SAMPLE_OUTPUT = {
    "account_structure": {"campaigns": [{"name": "搜索-成交", "placement": "自然内容"}]},
    "daily_schedule": [{"time_range": "20:00-22:00", "action": "总结当日数据"}],
}
_SAMPLE_DIGEST = "品牌：曲奇四重奏（香港蝴蝶酥伴手礼）\n目标：conversion｜总预算：100000 元"


class CriticReportContractTest(unittest.TestCase):
    def test_valid_report_round_trips(self) -> None:
        report = CriticReport.model_validate(_VALID_REPORT)
        self.assertEqual(report.verdict, "revise")
        self.assertEqual(report.dimension_scores.executability, 5)
        self.assertEqual(len(report.issues), 2)
        self.assertEqual(report.issues[0].severity, "high")
        self.assertEqual(CriticReport.model_validate(report.model_dump()), report)

    def test_pass_with_empty_issues_allowed(self) -> None:
        payload = {**_VALID_REPORT, "verdict": "pass", "issues": []}
        report = CriticReport.model_validate(payload)
        self.assertEqual(report.issues, [])

    def test_score_out_of_range_rejected(self) -> None:
        payload = json.loads(json.dumps(_VALID_REPORT))
        payload["dimension_scores"]["consistency"] = 11
        with self.assertRaises(ValidationError):
            CriticReport.model_validate(payload)

    def test_bad_verdict_and_severity_rejected(self) -> None:
        bad_verdict = {**_VALID_REPORT, "verdict": "fail"}
        with self.assertRaises(ValidationError):
            CriticReport.model_validate(bad_verdict)
        payload = json.loads(json.dumps(_VALID_REPORT))
        payload["issues"][0]["severity"] = "critical"
        with self.assertRaises(ValidationError):
            CriticReport.model_validate(payload)

    def test_issues_capped_at_ten(self) -> None:
        payload = json.loads(json.dumps(_VALID_REPORT))
        payload["issues"] = [payload["issues"][0]] * 11
        with self.assertRaises(ValidationError):
            CriticReport.model_validate(payload)


class CriticHappyPathTest(unittest.TestCase):
    def test_single_call_returns_ok_report(self) -> None:
        transport, seen = _fake_model([_final_response(_fenced(_VALID_REPORT))])
        result = run_critic(
            "module4", "模块4：聚光投流前置决策",
            _SAMPLE_OUTPUT, _SAMPLE_DIGEST, transport=transport,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["report"]["verdict"], "revise")
        self.assertEqual(result["report"]["dimension_scores"]["compliance_wording"], 8)
        self.assertEqual(len(result["report"]["issues"]), 2)
        # 只发一次请求；prompt 里带上模块输出与证据摘要
        self.assertEqual(len(seen), 1)
        user_content = seen[0]["messages"][1]["content"]
        self.assertIn("模块4：聚光投流前置决策", user_content)
        self.assertIn("自然内容", user_content)
        self.assertIn("曲奇四重奏", user_content)

    def test_model_override_takes_effect(self) -> None:
        transport, seen = _fake_model([_final_response(_fenced(_VALID_REPORT))])
        result = run_critic(
            "module1", "模块1", _SAMPLE_OUTPUT, "", transport=transport,
            model="deepseek-v4-pro",
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(seen[0]["model"], "deepseek-v4-pro")


class CriticRepairThenDegradeTest(unittest.TestCase):
    def test_bad_json_retried_once_then_degraded(self) -> None:
        transport, seen = _fake_model([
            _final_response("这次忘了输出 JSON，只写了一段自然语言点评。"),
            _final_response(_fenced({"verdict": "pass"})),  # 仍不合契约
        ])
        result = run_critic(
            "module5", "模块5", _SAMPLE_OUTPUT, _SAMPLE_DIGEST, transport=transport,
        )

        self.assertEqual(result["status"], "degraded")
        self.assertIn("reason", result)
        # 恰好重试一次，且把校验错误发回给了模型
        self.assertEqual(len(seen), 2)
        repair_prompt = seen[1]["messages"][-1]["content"]
        self.assertIn("校验失败", repair_prompt)

    def test_repair_round_can_succeed(self) -> None:
        transport, seen = _fake_model([
            _final_response("忘了给 JSON"),
            _final_response(_fenced(_VALID_REPORT)),
        ])
        result = run_critic(
            "module5", "模块5", _SAMPLE_OUTPUT, _SAMPLE_DIGEST, transport=transport,
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(seen), 2)


class CriticNetworkFailureTest(unittest.TestCase):
    def test_connect_error_degrades_without_raising(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("网关掐了连接")

        with mock.patch("module_agents.critic.time.sleep"):
            result = run_critic(
                "module2", "模块2", _SAMPLE_OUTPUT, _SAMPLE_DIGEST,
                transport=httpx.MockTransport(handler),
            )

        self.assertEqual(result["status"], "degraded")
        self.assertIn("ConnectError", result["reason"])

    def test_non_retryable_status_degrades(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "bad request"})

        result = run_critic(
            "module3", "模块3", _SAMPLE_OUTPUT, _SAMPLE_DIGEST,
            transport=httpx.MockTransport(handler),
        )
        self.assertEqual(result["status"], "degraded")
        self.assertIn("400", result["reason"])

    def test_malformed_response_body_degrades(self) -> None:
        transport, _ = _fake_model([{"unexpected": "shape"}])
        result = run_critic(
            "module6", "模块6", _SAMPLE_OUTPUT, _SAMPLE_DIGEST, transport=transport,
        )
        self.assertEqual(result["status"], "degraded")


class CriticConfigTest(unittest.TestCase):
    def test_enabled_flag_parsing(self) -> None:
        for value, expected in [
            ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
            ("0", False), ("false", False), ("", False),
        ]:
            with mock.patch.dict(os.environ, {"AGENT_CRITIC_ENABLED": value}):
                self.assertIs(critic_enabled(), expected, value)

    def test_disabled_by_default(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "AGENT_CRITIC_ENABLED"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(critic_enabled())

    def test_model_override_falls_back_to_analyzer_model(self) -> None:
        with mock.patch.dict(os.environ, {"AGENT_CRITIC_MODEL": "deepseek-v4-pro"}):
            self.assertEqual(load_critic_config()["model"], "deepseek-v4-pro")
        env = {k: v for k, v in os.environ.items() if k != "AGENT_CRITIC_MODEL"}
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_critic_config()
        self.assertTrue(config["model"])
        self.assertEqual(config["role"], "critic")

    def test_inline_comment_stripped_from_model_name(self) -> None:
        with mock.patch.dict(
            os.environ, {"AGENT_CRITIC_MODEL": "deepseek-v4-pro # 强模型二审"}
        ):
            self.assertEqual(load_critic_config()["model"], "deepseek-v4-pro")


class CriticApplyHelpersTest(unittest.TestCase):
    def test_merge_issues_into_human_review_items(self) -> None:
        from module_agents.critic import (
            has_high_severity_issues,
            merge_critic_issues_into_output,
        )

        review = {
            "status": "ok",
            "report": {
                "verdict": "revise",
                "dimension_scores": {
                    "evidence_citation": 5,
                    "executability": 5,
                    "compliance_wording": 8,
                    "consistency": 7,
                },
                "issues": [
                    {
                        "path": "a",
                        "severity": "high",
                        "problem": "错",
                        "suggestion": "改",
                    },
                    {
                        "path": "b",
                        "severity": "medium",
                        "problem": "弱",
                        "suggestion": "补",
                    },
                ],
                "summary": "需改",
            },
        }
        self.assertTrue(has_high_severity_issues(review))
        merged = merge_critic_issues_into_output(
            {"human_review_items": ["原有项"]}, review
        )
        self.assertTrue(any("Critic/high" in item for item in merged["human_review_items"]))
        self.assertTrue(any("Critic/medium" in item for item in merged["human_review_items"]))
        only_med = merge_critic_issues_into_output(
            {"human_review_items": ["原有项"]}, review, severities={"medium", "low"}
        )
        self.assertFalse(any("Critic/high" in item for item in only_med["human_review_items"]))
        self.assertTrue(any("Critic/medium" in item for item in only_med["human_review_items"]))

    def test_module_checklists_cover_six_modules(self) -> None:
        from module_agents.critic import MODULE_CRITIC_CHECKLISTS, build_critic_prompt

        for name in ("module1", "module2", "module3", "module4", "module5", "module6"):
            self.assertIn(name, MODULE_CRITIC_CHECKLISTS)
            prompt = build_critic_prompt(name, name, {"x": 1}, "证据")
            self.assertIn("本模块重点检查项", prompt)
            self.assertIn(MODULE_CRITIC_CHECKLISTS[name][0], prompt)


if __name__ == "__main__":
    unittest.main()
