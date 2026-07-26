"""模块4 Agent 测试：伪造模型（MockTransport）按序返回工具调用与最终 JSON。

覆盖 happy / 修复 / 溯源失败 三条路径；不 import engine。数字通过真实工具
预先计算，保证最终 JSON 与工具结果一致（grounding 可通过）。
"""
from __future__ import annotations

import json
import unittest

import httpx

from models import CampaignRequest
from module_agents.module4 import Module4Output, run_module4
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
        spotlight_budget_cny=70000,
        goal="conversion",
        benchmark_evidence=[
            {"source_name": "数据需求.xlsx", "collected_at": "2026-05", "metric_name": "加权CPC", "value": 1.6, "unit": "元"},
            {"source_name": "数据需求.xlsx", "collected_at": "2026-05", "metric_name": "CTR", "value": 0.05, "unit": ""},
            {"source_name": "数据需求.xlsx", "collected_at": "2026-05", "metric_name": "CVR转化率", "value": 0.04, "unit": ""},
        ],
    )


_BID_ARGS = {
    "stage": "cold_start",
    "baseline_cpc_cny": 1.6,
    "baseline_source": "数据需求.xlsx",
    "low_multiplier": 0.9,
    "high_multiplier": 1.1,
    "rationale": "围绕历史加权CPC小幅试探冷启动出价",
}
_FORECAST_ARGS = {
    "paid_budget_cny": 70000,
    "baseline_cpc_cny": 1.6,
    "baseline_cpc_source": "数据需求.xlsx",
    "baseline_ctr": 0.05,
    "baseline_ctr_source": "数据需求.xlsx",
    "baseline_cvr": 0.04,
    "baseline_cvr_source": "数据需求.xlsx",
    "aov_cny": 209.76,
    "rationale": "CPC/CTR/CVR 齐全且客单价换汇为CNY，给测试带宽/止损/ROI",
}

# 用真实工具预算出与 grounding 一致的数字
_BID = DEFAULT_REGISTRY.execute("calc_bid_range", _BID_ARGS)
_FC = DEFAULT_REGISTRY.execute("estimate_paid_performance", _FORECAST_ARGS)


def _valid_output() -> dict:
    return {
        "account_structure": {
            "campaign_naming_rule": "品牌_目标_版位_日期",
            "unit_naming_rule": "定向包_素材类型_序号",
            "campaigns": [
                {"name": "成交-搜索", "objective": "商品成交", "budget_share": 0.6, "placement": "搜索推广"},
                {"name": "成交-信息流", "objective": "商品成交", "budget_share": 0.4, "placement": "信息流推广"},
            ],
        },
        "targeting_packages": [
            {"package": "精准定向", "audience_desc": "搜索过伴手礼的到港游客", "budget_share": 0.5, "applicable_stage": "冷启动", "smart_expansion": False},
            {"package": "宽定向", "audience_desc": "泛送礼与美食人群", "budget_share": 0.3, "applicable_stage": "放量", "smart_expansion": True},
            {"package": "达人相似定向", "audience_desc": "腰部美食达人相似受众", "budget_share": 0.2, "applicable_stage": "放量", "smart_expansion": True},
        ],
        "bidding": {
            "cold_start": {
                "method": "稳定成本出价",
                "bid_low_cny": _BID["low_cny_per_click"],
                "bid_high_cny": _BID["high_cny_per_click"],
                "basis": _BID["basis"],
            },
            "scaling_rules": ["成本低于目标10%则提价5%", "转化数达标后逐步放宽定向"],
        },
        "search_feed_split": {"search": 0.6, "feed": 0.4, "synergy_note": "搜索承接高意向，信息流二次触达点击未转化人群"},
        "daily_schedule": [
            {"time_range": "09:00-12:00", "action": "检查昨日消耗与成本，暂停超阈值素材"},
            {"time_range": "19:00-23:00", "action": "晚高峰加投胜出素材，监控实时成本"},
        ],
        "forecast": {
            "test_budget_cny": _FC["test_budget_cny"],
            "stop_loss_cpc_cny": _FC["stop_loss"]["cpc_stop_cny"],
            "stop_loss_cpa_cny": _FC["stop_loss"]["cpa_stop_cny"],
            "roi_point": _FC["roi_point"],
            "roi_band": _FC["roi_band"],
            "status": _FC["forecast_status"],
        },
        "risk_playbook": [
            {"problem": "冷启动失败", "symptom": "72小时无有效转化", "response": "换素材重启，缩小定向重新冷启"},
            {"problem": "成本过高", "symptom": "CPA 超目标1.2倍", "response": "触发止损，降低出价并优化落地承接"},
            {"problem": "流量跑不动", "symptom": "预算消耗不足30%", "response": "放宽定向或提高出价试探"},
            {"problem": "拒审", "symptom": "笔记被拒或限流", "response": "按官方规则整改文案与资质后重提"},
            {"problem": "衰退", "symptom": "同素材CTR持续下滑", "response": "轮换素材，补充新选题续投"},
        ],
        "human_review_items": ["聚光预算上限需财务确认", "达人相似定向种子账号需人工挑选"],
    }


class Module4HappyPathTest(unittest.TestCase):
    def test_tool_calls_then_valid_json(self) -> None:
        transport = _fake_model([
            _tool_call_response("calc_bid_range", _BID_ARGS, "call_1"),
            _tool_call_response("estimate_paid_performance", _FORECAST_ARGS, "call_2"),
            _final_response(_fenced(_valid_output())),
        ])
        result = run_module4(_sample_request(), transport=transport)

        self.assertEqual(result["module"], "module4_spotlight_decision")
        self.assertEqual(result["repair_rounds_used"], 0)
        parsed = Module4Output.model_validate(result["output"])
        self.assertEqual(len(parsed.targeting_packages), 3)
        self.assertEqual(len(parsed.risk_playbook), 5)
        self.assertEqual(parsed.forecast.test_budget_cny, _FC["test_budget_cny"])
        self.assertTrue(result["grounding_check"]["passed"], result["grounding_check"])


class Module4RepairPathTest(unittest.TestCase):
    def test_broken_then_repaired(self) -> None:
        broken = {k: v for k, v in _valid_output().items() if k != "risk_playbook"}
        transport = _fake_model([
            _tool_call_response("calc_bid_range", _BID_ARGS, "call_1"),
            _tool_call_response("estimate_paid_performance", _FORECAST_ARGS, "call_2"),
            _final_response(_fenced(broken)),          # 缺 risk_playbook
            _final_response(_fenced(_valid_output())),  # 修复轮
        ])
        result = run_module4(_sample_request(), transport=transport)

        self.assertEqual(result["repair_rounds_used"], 1)
        self.assertTrue(result["grounding_check"]["passed"])
        self.assertEqual(len(result["output"]["risk_playbook"]), 5)


class Module4CampaignEnumTest(unittest.TestCase):
    def test_placement_natural_content_rejected(self) -> None:
        # placement 传「自然内容」（非付费版位）应被契约拒绝
        bad = _valid_output()
        bad["account_structure"]["campaigns"][0]["placement"] = "自然内容"
        with self.assertRaises(Exception):
            Module4Output.model_validate(bad)

    def test_objective_brand_exposure_rejected(self) -> None:
        # objective 传「品牌曝光」（非聚光推广目标）应被契约拒绝
        bad = _valid_output()
        bad["account_structure"]["campaigns"][0]["objective"] = "品牌曝光"
        with self.assertRaises(Exception):
            Module4Output.model_validate(bad)

    def test_valid_enum_fields_accepted(self) -> None:
        parsed = Module4Output.model_validate(_valid_output())
        self.assertEqual(parsed.account_structure.campaigns[0].placement, "搜索推广")
        self.assertEqual(parsed.account_structure.campaigns[0].objective, "商品成交")


class Module4GroundingFailureTest(unittest.TestCase):
    def test_tampered_forecast_flagged(self) -> None:
        tampered = _valid_output()
        tampered["forecast"]["roi_point"] = 999.99  # 工具从未产出该数字
        transport = _fake_model([
            _tool_call_response("calc_bid_range", _BID_ARGS, "call_1"),
            _tool_call_response("estimate_paid_performance", _FORECAST_ARGS, "call_2"),
            _final_response(_fenced(tampered)),
        ])
        result = run_module4(_sample_request(), transport=transport)

        check = result["grounding_check"]
        self.assertFalse(check["passed"])
        self.assertIn("forecast.roi_point", {m["path"] for m in check["mismatches"]})
        self.assertIn(999.99, {m["value"] for m in check["mismatches"]})


if __name__ == "__main__":
    unittest.main()
