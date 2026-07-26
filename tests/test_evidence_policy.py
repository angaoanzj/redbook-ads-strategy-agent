"""证据治理策略测试（只 import evidence_policy，沙盒 3.10 可跑）。

覆盖四项治理规范的代码化：
- 等级梯子排序与等级归一化（03 文档冲突优先级 + models.py 实际取值域）；
- SSOT 三段仲裁：最高等级组 → 同级口径一致取最新 → 同级分歧升级人工裁决；
- Mock 永不当选；
- value_kind 纪律（04 文档：历史事实精确、未来建议区间）；
- module_state 判定（02 文档：completed / completed_with_gaps + unresolved_gaps）。
"""

import unittest

import evidence_policy as ep


def _cand(value, *, level=None, source="来源", collected="2026-01-01", is_mock=False):
    row = {
        "value": value,
        "source_name": source,
        "collected_at": collected,
        "is_mock": is_mock,
    }
    if level is not None:
        row["evidence_grade"] = level
    return row


class EvidenceLadderTest(unittest.TestCase):
    def test_priority_order_matches_governance_doc(self) -> None:
        self.assertEqual(
            ep.EVIDENCE_PRIORITY,
            ["A_官方或授权", "C_用户导入", "B_公开观察", "D_行业基准", "E_策略假设", "M"],
        )

    def test_rank_is_monotonic_along_the_ladder(self) -> None:
        ranks = [ep.evidence_level_rank(level) for level in ep.EVIDENCE_PRIORITY]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(len(set(ranks)), len(ranks))

    def test_unknown_level_ranks_below_assumption_but_above_mock(self) -> None:
        unknown = ep.evidence_level_rank("说不清的等级")
        self.assertGreater(unknown, ep.evidence_level_rank("E_策略假设"))
        self.assertLess(unknown, ep.evidence_level_rank("M"))


class NormalizeLevelTest(unittest.TestCase):
    def test_code_side_grades_are_normalized(self) -> None:
        cases = {
            "A_official_public_rule": "A_官方或授权",
            "B_public_observation": "B_公开观察",
            "C_user_provided": "C_用户导入",
            "C_manual_paste": "C_用户导入",
            "C_user_provided_workbook": "C_用户导入",
            "M": "M",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(ep.normalize_evidence_level(raw), expected)

    def test_short_forms_and_no_code_labels(self) -> None:
        self.assertEqual(ep.normalize_evidence_level("A"), "A_官方或授权")
        self.assertEqual(ep.normalize_evidence_level("c"), "C_用户导入")
        self.assertEqual(ep.normalize_evidence_level("A_官方或授权"), "A_官方或授权")
        self.assertEqual(ep.normalize_evidence_level("mock"), "M")
        self.assertIsNone(ep.normalize_evidence_level(""))
        self.assertIsNone(ep.normalize_evidence_level(None))

    def test_candidate_level_falls_back_to_is_mock_then_source(self) -> None:
        self.assertEqual(ep.candidate_evidence_level({"is_mock": True}), "M")
        self.assertEqual(
            ep.candidate_evidence_level({"source_name": "《数据需求.xlsx》账户实测"}),
            "C_用户导入",
        )
        self.assertEqual(
            ep.candidate_evidence_level({"source_name": "某行业报告"}), "D_行业基准"
        )
        self.assertIsNone(ep.candidate_evidence_level({"source_name": "???"}))
        self.assertIsNone(ep.candidate_evidence_level("not a dict"))


class ResolveSsotSelectionTest(unittest.TestCase):
    def test_empty_returns_no_selection(self) -> None:
        decision = ep.resolve_ssot_selection([])
        self.assertIsNone(decision["selected"])
        self.assertIsNone(decision["escalation"])
        self.assertEqual(decision["conflict_candidates"], [])

    def test_highest_level_group_wins_over_latest_collection(self) -> None:
        decision = ep.resolve_ssot_selection(
            [
                _cand(0.30, level="D_行业基准", collected="2026-06-01"),
                _cand(1.60, level="C_用户导入", collected="2026-01-01"),
            ]
        )
        self.assertEqual(decision["selected"]["value"], 1.60)
        self.assertEqual(decision["evidence_level"], "C_用户导入")
        self.assertIsNone(decision["escalation"])

    def test_same_level_consistent_values_take_latest(self) -> None:
        decision = ep.resolve_ssot_selection(
            [
                _cand(2.00, level="A_官方或授权", collected="2026-01-01"),
                _cand(2.01, level="A_官方或授权", collected="2026-06-01"),  # 相差 0.5%
            ]
        )
        self.assertEqual(decision["selected"]["collected_at"], "2026-06-01")
        self.assertEqual(decision["selected"]["value"], 2.01)

    def test_same_level_divergent_values_escalate_without_selection(self) -> None:
        decision = ep.resolve_ssot_selection(
            [
                _cand(10, level="D_行业基准", source="行业A", collected="2026-01-01"),
                _cand(20, level="D_行业基准", source="行业B", collected="2026-06-01"),
            ]
        )
        self.assertIsNone(decision["selected"])
        self.assertEqual(decision["escalation"], ep.CONFLICT_ESCALATION)
        self.assertIn("需人工裁决", decision["escalation"])
        self.assertEqual(len(decision["conflict_candidates"]), 2)

    def test_lower_level_conflict_does_not_block_higher_level_selection(self) -> None:
        decision = ep.resolve_ssot_selection(
            [
                _cand(10, level="D_行业基准"),
                _cand(20, level="D_行业基准"),
                _cand(3.0, level="A_官方或授权"),
            ]
        )
        self.assertEqual(decision["selected"]["value"], 3.0)
        self.assertIsNone(decision["escalation"])

    def test_mock_never_selected_even_when_latest(self) -> None:
        decision = ep.resolve_ssot_selection(
            [
                _cand(0.012, level="M", collected="2026-06-30"),
                _cand(0.030, level="E_策略假设", collected="2026-01-01"),
            ]
        )
        self.assertEqual(decision["selected"]["value"], 0.030)
        self.assertEqual(decision["evidence_level"], "E_策略假设")

    def test_mock_only_group_returns_none_with_note(self) -> None:
        decision = ep.resolve_ssot_selection(
            [_cand(0.012, level="M"), _cand(0.013, level="M")]
        )
        self.assertIsNone(decision["selected"])
        self.assertEqual(decision["note"], ep.MOCK_ONLY_NOTE)
        self.assertEqual(decision["evidence_level"], "M")

    def test_non_dict_rows_are_ignored(self) -> None:
        decision = ep.resolve_ssot_selection([None, "junk", _cand(1.0, level="A")])
        self.assertEqual(decision["selected"]["value"], 1.0)


class ValuesWithinToleranceTest(unittest.TestCase):
    def test_one_percent_boundary(self) -> None:
        self.assertTrue(ep.values_within_tolerance([100.0, 100.9]))
        self.assertFalse(ep.values_within_tolerance([100.0, 102.0]))
        self.assertTrue(ep.values_within_tolerance([5.0]))
        self.assertTrue(ep.values_within_tolerance([]))

    def test_non_numeric_only_equal_values_pass(self) -> None:
        self.assertTrue(ep.values_within_tolerance(["高", "高"]))
        self.assertFalse(ep.values_within_tolerance(["高", "低"]))
        self.assertFalse(ep.values_within_tolerance([1.0, None]))


class ValueKindDisciplineTest(unittest.TestCase):
    def test_historical_fact_must_be_exact_scalar(self) -> None:
        violations = ep.check_value_kind_discipline(
            [{"metric_name": "CPC", "value": None, "value_kind": "historical_fact"}]
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("标量精确值", violations[0])

    def test_historical_fact_scalar_passes(self) -> None:
        self.assertEqual(
            ep.check_value_kind_discipline(
                [{"metric_name": "CPC", "value": 0.3, "value_kind": "historical_fact"}]
            ),
            [],
        )

    def test_historical_fact_cannot_be_rewritten_as_band(self) -> None:
        violations = ep.check_value_kind_discipline(
            [
                {
                    "metric_name": "CPC",
                    "value": 0.3,
                    "value_kind": "historical_fact",
                    "band": [0.2, 0.4],
                }
            ]
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("不得改写成区间", violations[0])

    def test_forward_estimate_single_scalar_is_violation(self) -> None:
        violations = ep.check_value_kind_discipline(
            [{"metric_name": "建议出价", "value": 1.2, "value_kind": "forward_estimate"}]
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("未来建议必须表达为范围", violations[0])

    def test_forward_estimate_with_range_passes(self) -> None:
        self.assertEqual(
            ep.check_value_kind_discipline(
                [
                    {
                        "metric_name": "建议出价",
                        "value": None,
                        "value_kind": "forward_estimate",
                        "low": 1.0,
                        "high": 1.4,
                    },
                    {
                        "metric_name": "ROI 预估",
                        "value": [5.16, 8.85],
                        "value_kind": "forward_estimate",
                    },
                ]
            ),
            [],
        )

    def test_unlabeled_metrics_are_out_of_scope(self) -> None:
        self.assertEqual(
            ep.check_value_kind_discipline(
                [{"metric_name": "CPC", "value": 0.3}, None, "junk"]
            ),
            [],
        )


class DeriveModuleStatusTest(unittest.TestCase):
    def test_clean_output_is_completed(self) -> None:
        state = ep.derive_module_status(
            {"budget_split": {"paid_budget_cny": 100}, "human_review_items": ["名单需核对"]},
            {"passed": True, "mismatches": []},
        )
        self.assertEqual(state["module_status"], ep.STATUS_COMPLETED)
        self.assertEqual(state["unresolved_gaps"], [])

    def test_grounding_failure_becomes_completed_with_gaps(self) -> None:
        state = ep.derive_module_status(
            {"budget_split": {"paid_budget_cny": 88888}},
            {"passed": False, "mismatches": [{"path": "budget_split.paid_budget_cny", "value": 88888}]},
        )
        self.assertEqual(state["module_status"], ep.STATUS_COMPLETED_WITH_GAPS)
        self.assertEqual(len(state["unresolved_gaps"]), 1)
        self.assertIn("budget_split.paid_budget_cny", state["unresolved_gaps"][0])

    def test_gap_marker_pulls_human_review_items(self) -> None:
        state = ep.derive_module_status(
            {
                "forecast": {"status": "演示补全 CVR，待投手确认"},
                "human_review_items": ["确认真实 CVR", "确认预算上限"],
            },
            {"passed": True, "mismatches": []},
        )
        self.assertEqual(state["module_status"], ep.STATUS_COMPLETED_WITH_GAPS)
        self.assertEqual(state["unresolved_gaps"], ["确认真实 CVR", "确认预算上限"])

    def test_gap_marker_without_review_items_still_records_marker(self) -> None:
        state = ep.derive_module_status(
            {"trending_monitor": {"data_source_status": "待接入数据源"}},
            {"passed": True, "mismatches": []},
        )
        self.assertEqual(state["module_status"], ep.STATUS_COMPLETED_WITH_GAPS)
        self.assertTrue(state["unresolved_gaps"])
        self.assertIn("待接入", state["unresolved_gaps"][0])

    def test_missing_grounding_check_is_tolerated(self) -> None:
        state = ep.derive_module_status({"a": 1}, None)
        self.assertEqual(state["module_status"], ep.STATUS_COMPLETED)
        self.assertEqual(ep.find_gap_markers({"a": 1}), [])

    def test_blocked_is_not_produced_here(self) -> None:
        # blocked 只由编排层按硬前序判定，base 层永不产生
        state = ep.derive_module_status({"x": "待补"}, {"passed": False, "mismatches": []})
        self.assertNotEqual(state["module_status"], ep.STATUS_BLOCKED)


class ModuleStatusBadgeTest(unittest.TestCase):
    def test_three_tone_mapping(self) -> None:
        self.assertEqual(ep.module_status_badge("completed")["tone"], "green")
        self.assertEqual(ep.module_status_badge("completed_with_gaps", 2)["tone"], "orange")
        self.assertEqual(ep.module_status_badge("blocked")["tone"], "red")

    def test_gap_count_shows_in_label_and_unknown_degrades(self) -> None:
        badge = ep.module_status_badge("completed_with_gaps", 3)
        self.assertIn("3", badge["label"])
        self.assertEqual(ep.module_status_badge("胡说")["status"], "completed")


if __name__ == "__main__":
    unittest.main()
