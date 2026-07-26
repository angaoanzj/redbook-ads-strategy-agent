"""评测基准集与回归评分测试：不依赖模型 Key，不 import engine/main。

覆盖：
- 四个评分维度各至少一条满分路径 + 一条扣分路径；
- 用 bench/fixtures/regression_outputs.json 跑 score_run，断言确定分值（回归基线）；
- golden 的数字不变量对故意破坏的输出（比例合计 1.1、少一个选题等）能报违规；
- markdown 报告含评分表、违规明细与「较上次」分差列。
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from bench.golden import (
    GOLDEN_EXPECTATIONS,
    MODULE_KEYS,
    check_invariants,
    invariant_future_values_are_ranged,
    normalize_module_name,
    path_exists,
)
from bench.score import (
    MAX_TOTAL,
    WEIGHT_GROUNDING,
    WEIGHT_HONESTY,
    WEIGHT_INVARIANTS,
    WEIGHT_STRUCTURE,
    WEIGHT_TEXT,
    render_markdown,
    score_module,
    score_run,
    score_text_from_critic,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "bench" / "fixtures" / "regression_outputs.json"
REQUEST = ROOT / "examples" / "cookie_quartet_full_case.json"


def load_archive() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def load_request() -> dict:
    return json.loads(REQUEST.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 黄金断言集自身的形状
# ---------------------------------------------------------------------------
class GoldenShapeTest(unittest.TestCase):
    def test_covers_six_modules_with_three_assertion_kinds(self) -> None:
        self.assertEqual(MODULE_KEYS, [f"module{index}" for index in range(1, 7)])
        for key, golden in GOLDEN_EXPECTATIONS.items():
            with self.subTest(module=key):
                self.assertTrue(golden["honesty_markers"], "每模块至少一条诚实标记")
                self.assertTrue(golden["numeric_invariants"], "每模块至少一个数字不变量")
                self.assertTrue(golden["required_structure"], "每模块至少一条关键路径")
                for marker in golden["honesty_markers"]:
                    self.assertTrue(marker.get("any_of"), f"{marker.get('id')} 缺 any_of")
                    self.assertTrue(marker.get("why"), f"{marker.get('id')} 缺 why 说明")

    def test_normalize_module_name_accepts_spec_names_and_aliases(self) -> None:
        self.assertEqual(normalize_module_name("module4"), "module4")
        self.assertEqual(normalize_module_name("module4_spotlight_decision"), "module4")
        self.assertEqual(normalize_module_name("模块4"), "module4")
        self.assertIsNone(normalize_module_name("module9"))

    def test_resolve_path_supports_wildcards(self) -> None:
        payload = {"a": [{"b": 1}, {"b": 2}], "c": {"d": {"e": 3}}}
        self.assertTrue(path_exists(payload, "a.*.b"))
        self.assertTrue(path_exists(payload, "c.d.e"))
        self.assertFalse(path_exists(payload, "a.*.z"))
        self.assertFalse(path_exists(payload, "missing"))


# ---------------------------------------------------------------------------
# 维度评分：每维度一条满分路径 + 一条扣分路径
# ---------------------------------------------------------------------------
class ScoreDimensionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.archive = load_archive()
        self.req = load_request()

    def score(self, module: str, result: dict) -> dict:
        return score_module(module, result, self.req)

    # -- grounding --
    def test_grounding_full_marks_when_passed(self) -> None:
        entry = self.score("module4", self.archive["module4"])
        self.assertEqual(entry["dimensions"]["grounding"], WEIGHT_GROUNDING)
        self.assertEqual(entry["total"], MAX_TOTAL)

    def test_grounding_zero_when_mismatch(self) -> None:
        result = copy.deepcopy(self.archive["module4"])
        result["grounding_check"] = {
            "passed": False,
            "mismatches": [{"path": "forecast.test_budget_cny", "value": 3500}],
        }
        entry = self.score("module4", result)
        self.assertEqual(entry["dimensions"]["grounding"], 0.0)
        self.assertEqual(entry["total"], MAX_TOTAL - WEIGHT_GROUNDING)
        self.assertEqual(entry["detail"]["grounding_mismatch_count"], 1)

    # -- honesty --
    def test_honesty_full_marks_on_reference_output(self) -> None:
        entry = self.score("module1", self.archive["module1"])
        self.assertEqual(entry["dimensions"]["honesty"], WEIGHT_HONESTY)
        self.assertEqual(entry["missing_markers"], [])

    def test_honesty_deducted_when_boundary_marker_removed(self) -> None:
        result = copy.deepcopy(self.archive["module1"])
        result["output"]["organic_landscape"]["boundary_note"] = "样本代表全平台格局"
        entry = self.score("module1", result)
        markers = len(GOLDEN_EXPECTATIONS["module1"]["honesty_markers"])
        self.assertAlmostEqual(
            entry["dimensions"]["honesty"], WEIGHT_HONESTY * (markers - 1) / markers, places=2
        )
        self.assertEqual(
            [marker["id"] for marker in entry["missing_markers"]],
            ["sample_not_platform_wide"],
        )

    # -- invariants --
    def test_invariants_full_marks_on_reference_output(self) -> None:
        entry = self.score("module6", self.archive["module6"])
        self.assertEqual(entry["dimensions"]["invariants"], WEIGHT_INVARIANTS)
        self.assertEqual(entry["violations"], [])

    def test_invariants_deduct_five_per_violation(self) -> None:
        result = copy.deepcopy(self.archive["module6"])
        result["output"]["level_budget_split"] = {
            "core": 0.6, "long_tail": 0.3, "blue_ocean": 0.2,
        }  # 合计 1.1
        entry = self.score("module6", result)
        self.assertEqual(len(entry["violations"]), 1)
        self.assertEqual(entry["dimensions"]["invariants"], WEIGHT_INVARIANTS - 5)
        self.assertIn("合计必须为 1.0", entry["violations"][0])

    def test_invariants_floor_at_zero(self) -> None:
        result = copy.deepcopy(self.archive["module4"])
        result["output"]["account_structure"]["campaigns"][0]["budget_share"] = 0.9
        result["output"]["targeting_packages"][0]["budget_share"] = 0.9
        result["output"]["search_feed_split"] = {
            "search": 0.9, "feed": 0.9, "synergy_note": "破坏用",
        }
        result["output"]["risk_playbook"] = result["output"]["risk_playbook"][:2]
        result["output"]["forecast"]["test_budget_cny"] = 60000
        result["output"]["bidding"]["cold_start"]["bid_low_cny"] = 9.9
        entry = self.score("module4", result)
        self.assertGreaterEqual(len(entry["violations"]), 5)
        self.assertEqual(entry["dimensions"]["invariants"], 0.0)

    # -- structure --
    def test_structure_full_marks_on_reference_output(self) -> None:
        entry = self.score("module5", self.archive["module5"])
        self.assertEqual(entry["dimensions"]["structure"], WEIGHT_STRUCTURE)
        self.assertEqual(entry["missing_paths"], [])

    def test_structure_deducted_when_path_missing(self) -> None:
        result = copy.deepcopy(self.archive["module5"])
        result["output"].pop("contingency_plans")
        entry = self.score("module5", result)
        total_paths = len(GOLDEN_EXPECTATIONS["module5"]["required_structure"])
        self.assertEqual(entry["missing_paths"], ["contingency_plans.*.adjustment"])
        self.assertAlmostEqual(
            entry["dimensions"]["structure"],
            WEIGHT_STRUCTURE * (total_paths - 1) / total_paths,
            places=2,
        )

    # -- 未知模块 --
    def test_unknown_module_scores_zero_and_is_flagged(self) -> None:
        entry = score_module("module9", {"output": {}}, self.req)
        self.assertFalse(entry["known_module"])
        self.assertEqual(entry["total"], 0.0)

    # -- text / Critic --
    def test_text_skipped_without_critic_keeps_full_total(self) -> None:
        entry = self.score("module4", self.archive["module4"])
        self.assertEqual(entry["dimensions"]["text"], WEIGHT_TEXT)
        self.assertEqual(entry["detail"]["text"]["status"], "skipped")
        self.assertEqual(entry["total"], MAX_TOTAL)

    def test_text_penalty_when_critic_reports_high_issues(self) -> None:
        result = copy.deepcopy(self.archive["module4"])
        result["critic_review"] = {
            "status": "ok",
            "report": {
                "verdict": "revise",
                "dimension_scores": {
                    "evidence_citation": 5,
                    "executability": 4,
                    "compliance_wording": 8,
                    "consistency": 6,
                },
                "issues": [
                    {
                        "path": "x",
                        "severity": "high",
                        "problem": "p",
                        "suggestion": "s",
                    },
                    {
                        "path": "y",
                        "severity": "medium",
                        "problem": "p2",
                        "suggestion": "s2",
                    },
                ],
                "summary": "需改",
            },
        }
        info = score_text_from_critic(result)
        self.assertEqual(info["status"], "scored")
        self.assertGreater(info["penalty"], 0)
        entry = self.score("module4", result)
        self.assertLess(entry["total"], MAX_TOTAL)
        self.assertAlmostEqual(entry["total"], MAX_TOTAL - info["penalty"], places=2)


# ---------------------------------------------------------------------------
# 回归基线
# ---------------------------------------------------------------------------
class RegressionBaselineTest(unittest.TestCase):
    """bench/fixtures/regression_outputs.json 是六模块的「合法满分」参照输出。

    分值变化 = 黄金断言集或评分口径变了，必须在变更记录里说明原因。
    """

    def setUp(self) -> None:
        self.summary = score_run(load_archive(), load_request())

    def test_overall_baseline_is_100(self) -> None:
        self.assertEqual(self.summary["overall"], 100.0)
        self.assertEqual(self.summary["module_count"], 6)
        self.assertEqual(self.summary["missing_modules"], [])
        self.assertEqual(self.summary["unknown_modules"], [])

    def test_every_module_scores_full_marks(self) -> None:
        for key in MODULE_KEYS:
            with self.subTest(module=key):
                entry = self.summary["modules"][key]
                self.assertEqual(entry["total"], 100.0)
                self.assertEqual(entry["violations"], [])
                self.assertEqual(entry["missing_markers"], [])
                self.assertEqual(entry["missing_paths"], [])

    def test_dimension_average_baseline(self) -> None:
        self.assertEqual(
            self.summary["dimension_avg"],
            {
                "grounding": 40.0,
                "honesty": 25.0,
                "invariants": 25.0,
                "structure": 10.0,
                "text": 15.0,
            },
        )

    def test_missing_module_is_reported(self) -> None:
        archive = load_archive()
        archive.pop("module3")
        summary = score_run(archive, load_request())
        self.assertEqual(summary["missing_modules"], ["module3"])
        self.assertEqual(summary["module_count"], 5)
        self.assertEqual(summary["overall"], 100.0)


# ---------------------------------------------------------------------------
# 故意破坏的输出必须被不变量抓住
# ---------------------------------------------------------------------------
class BrokenOutputTest(unittest.TestCase):
    def setUp(self) -> None:
        self.archive = load_archive()
        self.req = load_request()

    def test_m4_budget_share_sum_1_1_is_reported(self) -> None:
        output = copy.deepcopy(self.archive["module4"]["output"])
        output["account_structure"]["campaigns"][0]["budget_share"] = 0.6  # 合计 1.1
        violations = check_invariants("module4", output, self.req)
        self.assertTrue(
            any("campaigns 的 budget_share 合计必须为 1.0" in item for item in violations),
            violations,
        )

    def test_m4_targeting_share_sum_1_1_is_reported(self) -> None:
        output = copy.deepcopy(self.archive["module4"]["output"])
        output["targeting_packages"][2]["budget_share"] = 0.3  # 合计 1.1
        violations = check_invariants("module4", output, self.req)
        self.assertTrue(
            any("targeting_packages 的 budget_share 合计必须为 1.0" in item for item in violations),
            violations,
        )

    def test_m2_missing_one_topic_is_reported(self) -> None:
        output = copy.deepcopy(self.archive["module2"]["output"])
        output["topics"] = output["topics"][:-1]  # 少一个选题
        violations = check_invariants("module2", output, self.req)
        self.assertTrue(any("topics 必须恰好 15 个" in item for item in violations), violations)

    def test_m2_direction_shortfall_is_reported(self) -> None:
        output = copy.deepcopy(self.archive["module2"]["output"])
        for topic in output["topics"]:
            if topic["direction"] == "香港攻略":
                topic["direction"] = "送礼场景"
        violations = check_invariants("module2", output, self.req)
        self.assertTrue(any("每方向至少 3 个选题" in item for item in violations), violations)

    def test_m5_budget_split_not_matching_total_is_reported(self) -> None:
        output = copy.deepcopy(self.archive["module5"]["output"])
        output["budget_split"]["paid_budget_cny"] = 80000  # 30000 + 80000 ≠ 100000
        violations = check_invariants("module5", output, self.req)
        self.assertTrue(any("≠ 总预算" in item for item in violations), violations)

    def test_m5_phase_sum_mismatch_is_reported(self) -> None:
        output = copy.deepcopy(self.archive["module5"]["output"])
        output["phases"][1]["paid_budget_cny"] = 30000
        violations = check_invariants("module5", output, self.req)
        self.assertTrue(
            any("三阶段付费预算合计" in item for item in violations), violations
        )

    def test_m3_amplification_pool_inconsistent_is_reported(self) -> None:
        output = copy.deepcopy(self.archive["module3"]["output"])
        output["creator_plan"]["amplification_pool_cny"] = 30000
        violations = check_invariants("module3", output, self.req)
        self.assertTrue(any("不自洽" in item for item in violations), violations)

    def test_m3_fabricated_creators_beyond_evidence_is_reported(self) -> None:
        output = copy.deepcopy(self.archive["module3"]["output"])
        output["matched_creators"].append({
            "name": "凭空达人", "tier": "KOL", "match_score": 90,
            "suggested_note_budget_cny": 788, "source": "编造",
        })
        violations = check_invariants("module3", output, self.req)
        self.assertTrue(any("超过达人证据" in item for item in violations), violations)

    def test_m1_fabricated_ad_labeled_count_is_reported(self) -> None:
        output = copy.deepcopy(self.archive["module1"]["output"])
        output["competitor_breakdown"]["ad_labeled_count"] = 9
        violations = check_invariants("module1", output, self.req)
        self.assertTrue(any("超过请求竞品证据条数" in item for item in violations), violations)

    def test_m1_paid_metric_without_source_is_reported(self) -> None:
        output = copy.deepcopy(self.archive["module1"]["output"])
        output["paid_landscape"]["cpc_source"] = None
        violations = check_invariants("module1", output, self.req)
        self.assertTrue(any("缺少 cpc_source 来源" in item for item in violations), violations)

    def test_m6_duplicate_keyword_is_reported(self) -> None:
        output = copy.deepcopy(self.archive["module6"]["output"])
        output["keyword_levels"]["blue_ocean"].append(
            {"keyword": "香港伴手礼", "intent": "low", "lane": "feed", "bid_note": "低价试探 0.6–0.8"}
        )
        violations = check_invariants("module6", output, self.req)
        self.assertTrue(any("跨级重复词" in item for item in violations), violations)

    def test_zero_evidence_request_forces_empty_hot_formats(self) -> None:
        """零证据案例的诚实分：无笔记证据却给出 hot_formats 必须报违规。"""
        req = copy.deepcopy(self.req)
        req["category_note_evidence"] = []
        violations = check_invariants("module1", self.archive["module1"]["output"], req)
        self.assertTrue(
            any("hot_formats 必须留空" in item for item in violations), violations
        )

    def test_no_cpc_evidence_forbids_bid_numbers(self) -> None:
        req = copy.deepcopy(self.req)
        req["benchmark_evidence"] = [
            row for row in req["benchmark_evidence"] if "cpc" not in row["metric_name"].lower()
        ]
        violations = check_invariants("module4", self.archive["module4"]["output"], req)
        self.assertTrue(
            any("必须为 null" in item for item in violations), violations
        )

    def test_m4_roi_point_without_band_is_reported(self) -> None:
        """全局不变量：未来类单点值必须成对区间化（01/04 治理规范）。"""
        output = copy.deepcopy(self.archive["module4"]["output"])
        output["forecast"]["roi_band"] = None  # 只剩 roi_point 单点
        violations = check_invariants("module4", output, self.req)
        self.assertTrue(any("roi_point" in item for item in violations), violations)

    def test_m5_half_open_bid_range_is_reported(self) -> None:
        output = copy.deepcopy(self.archive["module5"]["output"])
        output["bid_plan"]["scaling"] = {"low_cny": 0.27}  # 缺 high_cny
        violations = check_invariants("module5", output, self.req)
        self.assertTrue(
            any("缺少配对的区间另一端" in item for item in violations), violations
        )

    def test_paired_ranges_in_reference_outputs_pass(self) -> None:
        for key in MODULE_KEYS:
            with self.subTest(module=key):
                self.assertEqual(
                    invariant_future_values_are_ranged(
                        self.archive[key]["output"], self.req
                    ),
                    [],
                )

    def test_invariants_do_not_crash_on_garbage_output(self) -> None:
        for key in MODULE_KEYS:
            with self.subTest(module=key):
                self.assertIsInstance(check_invariants(key, {}, self.req), list)
                self.assertIsInstance(check_invariants(key, {"x": None}, {}), list)


# ---------------------------------------------------------------------------
# Markdown 报告
# ---------------------------------------------------------------------------
class MarkdownReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.req = load_request()
        self.summary = score_run(load_archive(), self.req)

    def test_markdown_has_table_and_clean_detail_section(self) -> None:
        markdown = self.summary["markdown"]
        self.assertIn("# 六模块回归评分报告", markdown)
        self.assertIn("## 评分表", markdown)
        self.assertIn("## 违规与缺口明细", markdown)
        self.assertIn("全部模块无违规", markdown)
        for golden in GOLDEN_EXPECTATIONS.values():
            self.assertIn(golden["label"], markdown)

    def test_markdown_shows_delta_against_previous_report(self) -> None:
        archive = load_archive()
        archive["module6"]["output"]["level_budget_split"] = {
            "core": 0.6, "long_tail": 0.3, "blue_ocean": 0.2,
        }
        degraded = score_run(archive, self.req)
        markdown = render_markdown(degraded, self.summary)
        self.assertIn("-5.00", markdown)  # module6 掉 5 分
        self.assertIn("较上次", markdown)
        self.assertIn("不变量违规", markdown)


if __name__ == "__main__":
    unittest.main()
