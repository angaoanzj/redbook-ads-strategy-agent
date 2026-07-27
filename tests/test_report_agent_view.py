"""report_agent_view 单元测试（只 import report_agent_view，沙盒 3.10 可跑）。"""

import unittest

import report_agent_view as rav


def _module5_output() -> dict:
    """对齐 Module5Output 字段的手写 fixture。"""
    return {
        "budget_split": {
            "organic_budget_cny": 60000,
            "paid_budget_cny": 40000,
            "organic_ratio": 0.6,
            "needs_review": False,
        },
        "phases": [
            {"phase": "预热期", "paid_budget_cny": 8000, "key_actions": ["铺垫内容", "小额测试"]},
            {"phase": "爆发期", "paid_budget_cny": 24000, "key_actions": ["放量优质笔记"]},
            {"phase": "长尾期", "paid_budget_cny": 8000, "key_actions": ["维持搜索卡位"]},
        ],
        "creator_tier_plan": {
            "tiers": [
                {
                    "tier": "腰部",
                    "count": 3,
                    "collaboration_budget_cny": 9000,
                    "spotlight_amplification_budget_cny": 3000,
                }
            ],
            "amplification_pool_cny": 6000,
        },
        "bid_plan": {
            "cold_start": {"low_cny": 0.8, "high_cny": 1.2},
            "scaling": {"low_cny": 1.2, "high_cny": 1.6},
            "basis": "基于《数据需求.xlsx》CPC 1.60 元",
        },
        "synergy_rules": [
            {"metric": "笔记互动率", "threshold": "≥5%", "action": "启动信息流放大"},
            {"metric": "搜索点击率", "threshold": "≥3%", "action": "追加搜索预算"},
        ],
        "contingency_plans": [
            {"scenario": "自然互动低", "trigger": "48h互动<3%", "adjustment": "更换封面选题"},
            {"scenario": "付费点击低", "trigger": "CTR<2%", "adjustment": "收窄定向"},
        ],
        "human_review_items": ["核对聚光后台标签可用性"],
    }


def _block(output: dict, passed: bool = True, mismatches=None) -> dict:
    return {
        "agent_decision": {
            "output": output,
            "grounding_check": {"passed": passed, "mismatches": mismatches or []},
            "steps_used": 5,
        },
        "decision_source": "llm_agent",
    }


class BuildAgentDecisionViewTest(unittest.TestCase):
    def test_none_when_no_agent_decision(self):
        self.assertIsNone(rav.build_agent_decision_view("module_5_budget_pacing", {}))

    def test_none_when_block_not_dict(self):
        self.assertIsNone(rav.build_agent_decision_view("module_5_budget_pacing", None))

    def test_module_label_and_source(self):
        view = rav.build_agent_decision_view(
            "module_5_budget_pacing", _block(_module5_output())
        )
        self.assertEqual(view["module_label"], "全域预算与节奏 Agent")
        self.assertEqual(view["decision_source"], "llm_agent")
        self.assertEqual(view["steps_used"], 5)

    def test_section_kinds(self):
        view = rav.build_agent_decision_view(
            "module_5_budget_pacing", _block(_module5_output())
        )
        kinds = {s["title"]: s["kind"] for s in view["sections"]}
        self.assertEqual(kinds["预算拆分"], "kv")
        self.assertEqual(kinds["阶段节奏"], "table")
        self.assertEqual(kinds["达人分层"], "kv")
        self.assertEqual(kinds["出价方案"], "kv")
        self.assertEqual(kinds["自然付费联动"], "table")
        self.assertEqual(kinds["应急预案"], "table")
        self.assertEqual(kinds["需人工复核项"], "list")

    def test_table_columns_use_field_labels(self):
        view = rav.build_agent_decision_view(
            "module_5_budget_pacing", _block(_module5_output())
        )
        phases = next(s for s in view["sections"] if s["title"] == "阶段节奏")
        labels = [c["label"] for c in phases["columns"]]
        self.assertIn("阶段", labels)
        self.assertIn("付费预算(元)", labels)
        self.assertEqual(len(phases["rows"]), 3)

    def test_numbers_not_rounded(self):
        view = rav.build_agent_decision_view(
            "module_5_budget_pacing", _block(_module5_output())
        )
        budget = next(s for s in view["sections"] if s["title"] == "预算拆分")
        ratio = next(i for i in budget["items"] if i["label"] == "自然占比")
        self.assertEqual(ratio["value"], 0.6)

    def test_grounding_badge_passed(self):
        view = rav.build_agent_decision_view(
            "module_5_budget_pacing", _block(_module5_output(), passed=True)
        )
        self.assertTrue(view["grounding"]["passed"])
        self.assertEqual(view["grounding"]["badge"], "数字溯源通过")

    def test_grounding_badge_failed(self):
        block = _block(
            _module5_output(),
            passed=False,
            mismatches=[{"path": "bid_plan.cold_start.low_cny", "value": 0.8}],
        )
        view = rav.build_agent_decision_view("module_5_budget_pacing", block)
        self.assertFalse(view["grounding"]["passed"])
        self.assertEqual(view["grounding"]["badge"], "存在未溯源数字，需人工复核")
        self.assertEqual(len(view["grounding"]["mismatches"]), 1)

    def test_missing_fields_degrade(self):
        # output 非 dict、无 grounding_check 均容错；缺溯源结果按未通过处理
        block = {"agent_decision": {"output": None}}
        view = rav.build_agent_decision_view("module_6_keyword_strategy", block)
        self.assertIsNotNone(view)
        self.assertEqual(view["sections"], [])
        self.assertFalse(view["grounding"]["passed"])
        self.assertEqual(view["decision_source"], "llm_agent_ungrounded")
        self.assertEqual(view["module_label"], "关键词策略 Agent")

    def test_ungrounded_source_when_grounding_fails(self):
        block = _block(
            _module5_output(),
            passed=False,
            mismatches=[{"path": "bid_plan.cold_start.low_cny", "value": 0.8}],
        )
        view = rav.build_agent_decision_view("module_5_budget_pacing", block)
        self.assertEqual(view["decision_source"], "llm_agent_ungrounded")

    def test_apply_agent_grounding_policy_downgrades(self):
        modules = {
            "module_5_budget_pacing": _block(
                _module5_output(),
                passed=False,
                mismatches=[{"path": "x", "value": 1}],
            )
        }
        alerts = rav.apply_agent_grounding_policy(modules)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(
            modules["module_5_budget_pacing"]["decision_source"],
            "llm_agent_ungrounded",
        )

    def test_scalar_values_grouped_into_other(self):
        block = _block({"a_flag": True, "note": "hi", "topics": [{"keyword": "x"}]})
        view = rav.build_agent_decision_view("module_3_keyword_creator", block)
        titles = [s["title"] for s in view["sections"]]
        self.assertIn("其他", titles)
        other = next(s for s in view["sections"] if s["title"] == "其他")
        self.assertEqual(other["kind"], "kv")
        self.assertEqual(len(other["items"]), 2)

    def test_unknown_engine_key_falls_back(self):
        view = rav.build_agent_decision_view("module_x", _block({"foo": [1, 2, 3]}))
        self.assertEqual(view["module_label"], "module_x")
        foo = view["sections"][0]
        self.assertEqual(foo["kind"], "list")
        self.assertEqual(foo["items"], [1, 2, 3])


class BuildBenchmarkSsotTest(unittest.TestCase):
    def test_empty(self):
        ssot = rav.build_benchmark_ssot([])
        self.assertEqual(ssot["groups"], [])
        self.assertIn("账户实测值优先", ssot["policy"])

    def test_single_source_no_conflict(self):
        ssot = rav.build_benchmark_ssot(
            [
                {
                    "metric_name": "行业 CPC",
                    "value": 0.30,
                    "unit": "元",
                    "source_name": "行业参考",
                    "collected_at": "2026-01-01",
                }
            ]
        )
        self.assertEqual(len(ssot["groups"]), 1)
        group = ssot["groups"][0]
        self.assertEqual(group["category_key"], "cpc")
        self.assertFalse(group["conflict"])
        self.assertEqual(group["selected"]["value"], 0.30)

    def test_double_cpc_conflict_selects_by_source_priority(self):
        # 0.30 行业参考（采集更晚） vs 1.60 数据需求.xlsx（采集更早）
        # → conflict=True 且来源优选命中 1.60
        ssot = rav.build_benchmark_ssot(
            [
                {
                    "metric_name": "CPC 行业参考",
                    "value": 0.30,
                    "unit": "元",
                    "source_name": "某行业报告",
                    "collected_at": "2026-06-01",
                },
                {
                    "metric_name": "CPC",
                    "value": 1.60,
                    "unit": "元",
                    "source_name": "《数据需求.xlsx》",
                    "collected_at": "2026-01-01",
                },
            ]
        )
        group = ssot["groups"][0]
        self.assertTrue(group["conflict"])
        self.assertEqual(len(group["candidates"]), 2)
        self.assertEqual(group["selected"]["value"], 1.60)
        # candidates 按 collected_at 倒序：0.30 在前
        self.assertEqual(group["candidates"][0]["value"], 0.30)

    def test_same_level_divergent_values_escalate(self):
        # 两条同为 D_行业基准 的候选、数值分歧远超 ±1% → 不选值，升级人工裁决
        # 跨模块冲突：上游缺口不得被下游静默抹平
        ssot = rav.build_benchmark_ssot(
            [
                {
                    "metric_name": "CPM",
                    "value": 10,
                    "unit": "元",
                    "source_name": "行业A",
                    "collected_at": "2026-01-01",
                },
                {
                    "metric_name": "CPM",
                    "value": 20,
                    "unit": "元",
                    "source_name": "行业B",
                    "collected_at": "2026-06-01",
                },
            ]
        )
        group = ssot["groups"][0]
        self.assertEqual(group["category_key"], "cpm")
        self.assertIsNone(group["selected"])
        self.assertIn("需人工裁决", group["escalation"])
        self.assertEqual(len(group["conflict_candidates"]), 2)
        self.assertEqual(group["evidence_level"], "D_行业基准")

    def test_same_level_consistent_values_take_latest(self):
        # 同级且口径一致（±1% 内）→ 仍按最近采集选用
        ssot = rav.build_benchmark_ssot(
            [
                {
                    "metric_name": "CPM",
                    "value": 20.0,
                    "unit": "元",
                    "source_name": "行业A",
                    "collected_at": "2026-01-01",
                },
                {
                    "metric_name": "CPM",
                    "value": 20.1,
                    "unit": "元",
                    "source_name": "行业B",
                    "collected_at": "2026-06-01",
                },
            ]
        )
        group = ssot["groups"][0]
        self.assertEqual(group["selected"]["value"], 20.1)
        self.assertIsNone(group["escalation"])

    def test_missing_collected_at_degrades(self):
        ssot = rav.build_benchmark_ssot(
            [
                {"metric_name": "CTR", "value": 0.05, "unit": "%", "source_name": "账户实测"},
                {"metric_name": "CTR", "value": 0.03, "unit": "%", "source_name": "行业"},
            ]
        )
        group = ssot["groups"][0]
        self.assertEqual(group["category_key"], "ctr")
        self.assertTrue(group["conflict"])
        # 账户实测优先，即使没有 collected_at
        self.assertEqual(group["selected"]["value"], 0.05)

    def test_unknown_metric_keeps_own_bucket(self):
        ssot = rav.build_benchmark_ssot(
            [{"metric_name": "客单价", "value": 199, "unit": "元", "source_name": "用户"}]
        )
        self.assertEqual(ssot["groups"][0]["category_key"], "客单价")
        self.assertFalse(ssot["groups"][0]["conflict"])

    def test_paid_ctr_not_conflicted_with_organic_content_ctr(self):
        # 投流 CTR 与内容 CTR 来自同一工作簿不同表，口径不同，不得并成假冲突
        ssot = rav.build_benchmark_ssot(
            [
                {
                    "metric_name": "ctr",
                    "value": 0.16046,
                    "unit": "ratio",
                    "source_name": "数据需求.xlsx／投流数据／2026年1—5月加权汇总",
                    "collected_at": "2026-05-31",
                },
                {
                    "metric_name": "organic_content_ctr",
                    "value": 0.20477,
                    "unit": "ratio",
                    "source_name": "数据需求.xlsx／内容数据／2026年1—5月加权汇总",
                    "collected_at": "2026-05-31",
                },
                {
                    "metric_name": "cost_per_interaction",
                    "value": 2.8955,
                    "unit": "CNY/interaction",
                    "source_name": "数据需求.xlsx／投流数据／2026年1—5月加权汇总",
                    "collected_at": "2026-05-31",
                },
                {
                    "metric_name": "organic_interaction_rate",
                    "value": 0.02072,
                    "unit": "ratio",
                    "source_name": "数据需求.xlsx／内容数据／2026年1—5月加权汇总",
                    "collected_at": "2026-05-31",
                },
            ]
        )
        by_key = {g["category_key"]: g for g in ssot["groups"]}
        self.assertIn("ctr", by_key)
        self.assertIn("organic_content_ctr", by_key)
        self.assertIn("cost_per_interaction", by_key)
        self.assertIn("organic_interaction_rate", by_key)
        self.assertFalse(by_key["ctr"]["conflict"])
        self.assertFalse(by_key["organic_content_ctr"]["conflict"])
        self.assertFalse(by_key["cost_per_interaction"]["conflict"])
        self.assertFalse(by_key["organic_interaction_rate"]["conflict"])
        # 前端只渲染 conflict=true 的组：这四条都不应再出现「待人工裁决」
        self.assertEqual([g for g in ssot["groups"] if g["conflict"]], [])

    def test_non_dict_entries_skipped(self):
        ssot = rav.build_benchmark_ssot([None, "junk", {"metric_name": "CPC", "value": 1.0}])
        self.assertEqual(len(ssot["groups"]), 1)

    def test_conversion_category(self):
        ssot = rav.build_benchmark_ssot(
            [{"metric_name": "conversion cost", "value": 30, "unit": "元", "source_name": "账户"}]
        )
        self.assertEqual(ssot["groups"][0]["category_key"], "conversion")

    def test_select_candidate_helper_empty(self):
        self.assertIsNone(rav.select_ssot_candidate([]))

    def test_group_carries_evidence_level_and_period_formula(self):
        ssot = rav.build_benchmark_ssot(
            [
                {
                    "metric_name": "cpc",
                    "value": 0.3,
                    "unit": "CNY/click",
                    "source_name": "数据需求.xlsx",
                    "collected_at": "2026-05-31",
                    "period": "2026-01-01/2026-05-31",
                    "formula": "spend / clicks",
                    "value_kind": "historical_fact",
                    "evidence_grade": "C_user_provided",
                }
            ]
        )
        group = ssot["groups"][0]
        self.assertEqual(group["evidence_level"], "C_用户导入")
        self.assertIsNone(group["escalation"])
        selected = group["selected"]
        self.assertEqual(selected["period"], "2026-01-01/2026-05-31")
        self.assertEqual(selected["formula"], "spend / clicks")
        self.assertEqual(selected["value_kind"], "historical_fact")
        self.assertEqual(selected["evidence_level"], "C_用户导入")

    def test_mock_candidate_never_selected(self):
        ssot = rav.build_benchmark_ssot(
            [
                {
                    "metric_name": "cvr",
                    "value": 0.012,
                    "unit": "ratio",
                    "source_name": "演示补全CVR（待投手确认）",
                    "collected_at": "2026-06-30",
                    "is_mock": True,
                    "evidence_grade": "M",
                }
            ]
        )
        group = ssot["groups"][0]
        self.assertIsNone(group["selected"])
        self.assertIn("Mock", group["note"])
        self.assertEqual(group["evidence_level"], "M")

    def test_legacy_call_shape_still_supported(self):
        # 旧调用：只有 metric_name/value/source_name/collected_at，无等级字段
        ssot = rav.build_benchmark_ssot(
            [
                {
                    "metric_name": "CPC 行业参考",
                    "value": 0.30,
                    "unit": "元",
                    "source_name": "某行业报告",
                    "collected_at": "2026-06-01",
                },
                {
                    "metric_name": "CPC",
                    "value": 1.60,
                    "unit": "元",
                    "source_name": "《数据需求.xlsx》",
                    "collected_at": "2026-01-01",
                },
            ]
        )
        group = ssot["groups"][0]
        self.assertEqual(group["selected"]["value"], 1.60)
        self.assertEqual(
            rav.select_ssot_candidate(group["candidates"])["value"], 1.60
        )


class ModuleStatusBadgeViewTest(unittest.TestCase):
    def test_completed_badge_is_green(self):
        block = _block(_module5_output())
        block["agent_decision"]["module_status"] = "completed"
        block["agent_decision"]["unresolved_gaps"] = []
        view = rav.build_agent_decision_view("module_5_budget_pacing", block)
        status = view["module_status"]
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["tone"], "green")
        self.assertEqual(status["gap_count"], 0)

    def test_completed_with_gaps_badge_is_orange_and_lists_gaps(self):
        block = _block(_module5_output())
        block["agent_decision"]["module_status"] = "completed_with_gaps"
        block["agent_decision"]["unresolved_gaps"] = ["确认真实 CVR", "确认预算上限"]
        view = rav.build_agent_decision_view("module_5_budget_pacing", block)
        status = view["module_status"]
        self.assertEqual(status["tone"], "orange")
        self.assertEqual(status["gap_count"], 2)
        self.assertIn("2", status["label"])
        self.assertEqual(status["unresolved_gaps"][0], "确认真实 CVR")

    def test_blocked_badge_is_red(self):
        block = _block(_module5_output())
        block["module_status"] = "blocked"
        view = rav.build_agent_decision_view("module_5_budget_pacing", block)
        self.assertEqual(view["module_status"]["status"], "blocked")
        self.assertEqual(view["module_status"]["tone"], "red")

    def test_legacy_block_without_status_falls_back_to_grounding(self):
        passed_view = rav.build_agent_decision_view(
            "module_5_budget_pacing", _block(_module5_output(), passed=True)
        )
        self.assertEqual(passed_view["module_status"]["status"], "completed")
        failed_view = rav.build_agent_decision_view(
            "module_5_budget_pacing",
            _block(_module5_output(), passed=False, mismatches=[{"path": "x", "value": 1}]),
        )
        self.assertEqual(failed_view["module_status"]["status"], "completed_with_gaps")
        self.assertEqual(failed_view["module_status"]["tone"], "orange")


if __name__ == "__main__":
    unittest.main()
