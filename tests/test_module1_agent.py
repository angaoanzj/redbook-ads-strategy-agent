"""模块1 Agent 测试：MockTransport 按序返回工具调用与最终 JSON。

覆盖 happy / 修复 / 溯源失败 三条路径；不 import engine。ad_labeled_count 用真实
summarize_competitor_landscape 预算，保证 grounding 可通过。
"""
from __future__ import annotations

import json
import unittest

import httpx

from models import CampaignRequest
from module_agents.module1 import Module1Output, run_module1
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
        selling_points=["招牌经典款", "牛油香浓层次酥脆", "低糖健康"],
        price_min=228,
        price_max=228,
        currency="HKD",
        initial_audience="到港游客与送礼人群",
        total_budget_cny=100000,
        goal="conversion",
        competitor_evidence=[
            {"account_name": "竞品A", "profile_or_note_url": "http://x/a", "note_format": "图文",
             "interactions": 1000, "is_ad_labeled": True},
            {"account_name": "竞品B", "profile_or_note_url": "http://x/b", "note_format": "短视频",
             "interactions": 5000, "is_ad_labeled": False},
        ],
    )


_COMP_ARGS = {
    "competitors": [
        {"name": "竞品A", "note_format": "图文", "interactions": 1000, "is_ad_labeled": True, "evidence_status": "用户提供"},
        {"name": "竞品B", "note_format": "短视频", "interactions": 5000, "is_ad_labeled": False, "evidence_status": "用户提供"},
    ],
    "own_selling_points": ["招牌经典款", "牛油香浓层次酥脆", "低糖健康"],
    "covered_themes": ["牛油香浓层次酥脆"],
    "rationale": "基于两条竞品证据判读赛道格局",
}
_COMP = DEFAULT_REGISTRY.execute("summarize_competitor_landscape", _COMP_ARGS)


def _valid_output() -> dict:
    return {
        "organic_landscape": {
            "sample_size": 0,
            "hot_formats": [{"format": "短视频", "avg_interactions": 5000.0}],
            "peak_hour_hypothesis": "晚间 18-23 点为发布高峰（待验证假设）",
            "content_form_advice": ["短视频优先展示酥脆层次", "图文承接送礼场景"],
            "boundary_note": "本样本仅为观测子集，不等于全平台大盘",
        },
        "paid_landscape": {
            "cpc_cny": None, "cpc_source": None,
            "cpm_cny": None, "cpm_source": None,
            "conversion_cost_cny": None, "conversion_cost_source": None,
            "missing_notice": "无 CPC/CPM/转化成本基准证据，付费格局待补数据",
        },
        "competitor_breakdown": {
            "common_patterns": ["爆款以短视频为主", "图文强调送礼场景"],
            "content_gaps": _COMP["content_gaps"],
            "ad_labeled_count": _COMP["ad_labeled_count"],
            "targeting_hypotheses": ["假设竞品定向送礼人群，可做定向测试假设验证"],
            "budget_inference_policy": _COMP["budget_inference_policy"],
        },
        "risk_alerts": [
            {"risk": "拒审风险", "source": "通用经验，待证据补充", "action": "按官方规则整改文案资质"},
            {"risk": "同质化竞争", "source": "竞品证据", "action": "抢占低糖健康内容缺口"},
        ],
        "human_review_items": ["需补采竞品广告标识与投放时长", "付费基准 CPC/CPM 待财务确认"],
    }


class Module1HappyPathTest(unittest.TestCase):
    def test_tool_call_then_valid_json(self) -> None:
        transport = _fake_model([
            _tool_call_response("summarize_competitor_landscape", _COMP_ARGS, "call_1"),
            _final_response(_fenced(_valid_output())),
        ])
        result = run_module1(_sample_request(), transport=transport)

        self.assertEqual(result["module"], "module1_market_competitor")
        self.assertEqual(result["repair_rounds_used"], 0)
        parsed = Module1Output.model_validate(result["output"])
        self.assertEqual(parsed.competitor_breakdown.ad_labeled_count, _COMP["ad_labeled_count"])
        self.assertTrue(result["grounding_check"]["passed"], result["grounding_check"])

    def test_prompt_asks_for_plain_language_briefing(self) -> None:
        from module_agents.module1 import SYSTEM_PROMPT, build_user_prompt

        self.assertIn("投手顾问", SYSTEM_PROMPT)
        self.assertIn("禁止正确的废话", SYSTEM_PROMPT)
        self.assertIn("定向测试包", SYSTEM_PROMPT)
        prompt = build_user_prompt(_sample_request())
        self.assertIn("标题：", prompt)
        self.assertIn("投手 briefing", prompt)
        self.assertIn("确定性竞品事实层", prompt)
        self.assertIn('"conclusion_type"', prompt)
        self.assertIn("不得覆盖事实层", SYSTEM_PROMPT)
        self.assertIn("样本内未覆盖", SYSTEM_PROMPT)


class Module1RepairPathTest(unittest.TestCase):
    def test_broken_then_repaired(self) -> None:
        broken = {k: v for k, v in _valid_output().items() if k != "risk_alerts"}
        transport = _fake_model([
            _tool_call_response("summarize_competitor_landscape", _COMP_ARGS, "call_1"),
            _final_response(_fenced(broken)),           # 缺 risk_alerts
            _final_response(_fenced(_valid_output())),  # 修复轮
        ])
        result = run_module1(_sample_request(), transport=transport)

        self.assertEqual(result["repair_rounds_used"], 1)
        self.assertTrue(result["grounding_check"]["passed"])
        self.assertEqual(len(result["output"]["risk_alerts"]), 2)


def _zero_evidence_request() -> CampaignRequest:
    # 无品类笔记、无竞品证据
    return CampaignRequest(
        brand_name="曲奇四重奏",
        category="香港蝴蝶酥伴手礼",
        product_name="经典原味蝴蝶酥礼盒",
        selling_points=["招牌经典款", "牛油香浓层次酥脆", "低糖健康"],
        price_min=228,
        price_max=228,
        currency="HKD",
        initial_audience="到港游客与送礼人群",
        total_budget_cny=100000,
        goal="conversion",
    )


_EMPTY_COMP_ARGS = {
    "competitors": [],
    "own_selling_points": ["招牌经典款", "牛油香浓层次酥脆", "低糖健康"],
    "covered_themes": [],
    "rationale": "证据区无竞品，如实返回无竞品结论",
}
_EMPTY_COMP = DEFAULT_REGISTRY.execute("summarize_competitor_landscape", _EMPTY_COMP_ARGS)


def _zero_evidence_output() -> dict:
    return {
        "organic_landscape": {
            "sample_size": 0,
            "hot_formats": [],  # 无品类笔记证据：hot_formats 留空，禁止编造
            "peak_hour_hypothesis": "无笔记证据，暂按目标人群晚间活跃假设（待验证）",
            "content_form_advice": ["优先测试短视频展示酥脆层次", "图文承接送礼场景"],
            "boundary_note": "无品类笔记证据，本判读为保守假设，不等于全平台大盘",
        },
        "paid_landscape": {
            "cpc_cny": None, "cpc_source": None,
            "cpm_cny": None, "cpm_source": None,
            "conversion_cost_cny": None, "conversion_cost_source": None,
            "missing_notice": "无付费基准证据，付费格局待补数据",
        },
        "competitor_breakdown": {
            "common_patterns": ["无竞品证据，暂无爆款共性可判读，待补采"],
            "content_gaps": _EMPTY_COMP["content_gaps"],
            "ad_labeled_count": _EMPTY_COMP["ad_labeled_count"],
            "targeting_hypotheses": ["假设送礼人群为初始定向，可做定向测试假设验证"],
            "budget_inference_policy": _EMPTY_COMP["budget_inference_policy"],
        },
        "risk_alerts": [
            {"risk": "证据不足难判读", "source": "通用经验，待证据补充", "action": "优先补采品类笔记与竞品"},
            {"risk": "拒审风险", "source": "通用经验，待证据补充", "action": "按官方规则整改文案资质"},
        ],
        "human_review_items": ["需补采品类笔记与竞品证据", "付费基准 CPC/CPM 待财务确认"],
    }


class Module1ZeroEvidenceTest(unittest.TestCase):
    def test_empty_hot_formats_allowed(self) -> None:
        # 契约层：无笔记证据时 hot_formats 允许为空
        parsed = Module1Output.model_validate(_zero_evidence_output())
        self.assertEqual(parsed.organic_landscape.hot_formats, [])

    def test_zero_evidence_run_with_empty_competitors(self) -> None:
        transport = _fake_model([
            _tool_call_response("summarize_competitor_landscape", _EMPTY_COMP_ARGS, "call_1"),
            _final_response(_fenced(_zero_evidence_output())),
        ])
        result = run_module1(_zero_evidence_request(), transport=transport)
        parsed = Module1Output.model_validate(result["output"])
        self.assertEqual(parsed.organic_landscape.hot_formats, [])
        self.assertEqual(parsed.competitor_breakdown.ad_labeled_count, 0)
        self.assertEqual(
            parsed.competitor_breakdown.budget_inference_policy,
            "无竞品证据：禁止推测竞品预算",
        )
        self.assertTrue(result["grounding_check"]["passed"], result["grounding_check"])


class Module1GroundingFailureTest(unittest.TestCase):
    def test_tampered_ad_count_flagged(self) -> None:
        tampered = _valid_output()
        tampered["competitor_breakdown"]["ad_labeled_count"] = 999  # 工具从未产出该数字
        transport = _fake_model([
            _tool_call_response("summarize_competitor_landscape", _COMP_ARGS, "call_1"),
            _final_response(_fenced(tampered)),
        ])
        result = run_module1(_sample_request(), transport=transport)

        check = result["grounding_check"]
        self.assertFalse(check["passed"])
        self.assertIn("competitor_breakdown.ad_labeled_count", {m["path"] for m in check["mismatches"]})


if __name__ == "__main__":
    unittest.main()
