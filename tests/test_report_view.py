import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import run_strategy
from tests.test_engine import sample_request


class ReportViewTests(unittest.TestCase):
    def test_report_contains_four_human_readable_sections(self):
        result = run_strategy(
            sample_request(), use_model=False, allow_mock=True, mock_seed="report-ui-a"
        )
        view = result.report_view

        self.assertEqual(
            [row["key"] for row in view["report_sections"]],
            [
                "market_competitor",
                "audience",
                "keyword_strategy",
                "creator_keyword",
                "spotlight_decision",
                "budget",
            ],
        )
        kw_strategy = next(row for row in view["report_sections"] if row["key"] == "keyword_strategy")
        self.assertEqual(kw_strategy["title"], "关键词策略")
        self.assertTrue(kw_strategy["visuals"].get("core_keywords"))
        self.assertIn("level_budget_split", kw_strategy["visuals"])
        spotlight_decision = next(
            row for row in view["report_sections"] if row["key"] == "spotlight_decision"
        )
        self.assertEqual(spotlight_decision["title"], "聚光投流前置决策")
        self.assertGreaterEqual(len(spotlight_decision["visuals"].get("account_plans") or []), 2)
        self.assertEqual(len(spotlight_decision["visuals"].get("targeting_packages") or []), 3)
        self.assertEqual(len(spotlight_decision["visuals"].get("risk_playbook") or []), 5)
        self.assertGreaterEqual(len(spotlight_decision["visuals"].get("operator_playbook") or []), 3)
        self.assertIn("投手执行", spotlight_decision["decision"])
        market = view["report_sections"][0]
        self.assertEqual(market["title"], "赛道与竞品深度分析")
        self.assertEqual(
            [row["key"] for row in market.get("subsections") or []],
            ["organic", "spotlight", "competitor", "risk"],
        )
        for section in view["report_sections"]:
            for field in (
                "decision",
                "data_explanation",
                "analysis",
                "actions",
                "success_metrics",
                "evidence_boundary",
            ):
                self.assertTrue(section[field], f"{section['key']} 缺少 {field}")

    def test_executive_summary_is_decision_oriented(self):
        result = run_strategy(
            sample_request(), use_model=False, allow_mock=True, mock_seed="report-ui-a"
        )
        summary = result.report_view["executive_summary"]

        self.assertTrue(summary["strategic_thesis"])
        self.assertGreaterEqual(len(summary["key_findings"]), 3)
        self.assertEqual(len(summary["priority_actions"]), 3)
        self.assertEqual(summary["mock_seed"], "report-ui-a")

    def test_action_plan_has_operator_fields(self):
        result = run_strategy(
            sample_request(), use_model=False, allow_mock=True, mock_seed="report-ui-a"
        )
        actions = result.report_view["action_plan"]

        self.assertGreaterEqual(len(actions), 3)
        self.assertEqual({row["priority"] for row in actions[:3]}, {"P1", "P2", "P3"})
        for action in actions:
            for field in (
                "title",
                "why",
                "steps",
                "owner",
                "timeline",
                "success_metrics",
                "stop_condition",
                "evidence_dependency",
            ):
                self.assertTrue(action[field], f"{action['priority']} 缺少 {field}")

    def test_markdown_uses_human_readable_report_sections(self):
        result = run_strategy(
            sample_request(), use_model=False, allow_mock=True, mock_seed="report-ui-a"
        )

        self.assertIn("## 管理层决策摘要", result.report_markdown)
        self.assertIn("## 第一章｜赛道与竞品深度分析", result.report_markdown)
        self.assertIn("### 自然流量大盘分析", result.report_markdown)
        self.assertIn("### 聚光投放大盘分析", result.report_markdown)
        self.assertIn("### 竞品全域投放分析", result.report_markdown)
        self.assertIn("### 风险预警", result.report_markdown)
        self.assertIn("## 第二章｜目标用户精准画像", result.report_markdown)
        self.assertIn("## 第三章｜关键词策略", result.report_markdown)
        self.assertIn("## 第四章｜关键词与达人匹配", result.report_markdown)
        self.assertIn("## 第五章｜聚光投流前置决策", result.report_markdown)
        self.assertIn("### 投手执行方案", result.report_markdown)
        self.assertNotIn("## 执行方案", result.report_markdown)
        self.assertIn("## 第六章｜全域预算与节奏规划", result.report_markdown)
        self.assertIn("## 附加工具：数据看板 / 内容审核 / A/B / 竞品监控", result.report_markdown)
        self.assertEqual(len(result.report_view["executive_summary"]["key_findings"]), 3)
        self.assertTrue(result.report_view["executive_summary"].get("this_week_action"))
        self.assertIn("bonus_content_audit", result.modules)
        self.assertIn("dashboard", result.report_view)
        self.assertIn("### 决策结论", result.report_markdown)
        self.assertIn("### 建议动作", result.report_markdown)
        self.assertIn("## 证据附录说明", result.report_markdown)

    def test_report_preserves_creator_boundary_and_paid_risk_playbook(self):
        result = run_strategy(
            sample_request(), use_model=False, allow_mock=True, mock_seed="report-ui-a"
        )

        self.assertIn("Mock 演示达人", result.report_markdown)
        self.assertEqual(len(result.report_view["operational_risk_playbook"]), 5)
        self.assertIn("冷启动无量", result.report_markdown)

    def test_mock_sections_explain_mock_evidence_boundary(self):
        result = run_strategy(
            sample_request(), use_model=False, allow_mock=True, mock_seed="report-ui-a"
        )

        for section in result.report_view["report_sections"]:
            if section["is_mock"]:
                self.assertEqual(section["mock_seed"], "report-ui-a")
                self.assertIn("模拟", section["evidence_boundary"])

    def test_executive_summary_exposes_gap_count(self):
        result = run_strategy(
            sample_request(), use_model=False, allow_mock=False
        )
        summary = result.report_view["executive_summary"]
        self.assertIn("gap_count", summary)
        self.assertEqual(summary["gap_count"], len(summary["evidence_gaps"]))
        self.assertIn("证据缺口数", result.report_markdown)

    def test_agent_decision_surfaces_in_report_view_after_attach(self):
        """P0：modules 上先挂 agent_decision，再 build_report_view，章节应出现 Agent 卡片。"""
        from report_view import build_report_view, render_report_markdown

        result = run_strategy(
            sample_request(), use_model=False, allow_mock=False, use_agent_modules=False
        )
        modules = result.modules
        modules["module_5_budget_pacing"]["agent_decision"] = {
            "output": {
                "budget_split": {
                    "organic_budget_cny": 30000,
                    "paid_budget_cny": 70000,
                    "organic_ratio": 0.3,
                    "needs_review": False,
                },
                "human_review_items": ["核对预算比例"],
            },
            "grounding_check": {
                "passed": False,
                "mismatches": [{"path": "budget_split.organic_budget_cny", "value": 30000}],
            },
            "steps_used": 2,
        }
        modules["module_5_budget_pacing"]["decision_source"] = "llm_agent"
        view = build_report_view(
            sample_request(),
            modules,
            result.evidence_gaps,
            result.data_confidence,
        )
        budget_section = next(s for s in view["report_sections"] if s["key"] == "budget")
        views = budget_section.get("agent_decision_views") or []
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0]["decision_source"], "llm_agent_ungrounded")
        self.assertFalse(views[0]["grounding"]["passed"])
        self.assertEqual(view["executive_summary"]["agent_ungrounded_count"], 1)
        md = render_report_markdown(sample_request(), view)
        self.assertIn("decision_source: llm_agent_ungrounded", md)
        self.assertIn("数字未溯源模块", md)
        self.assertEqual(budget_section.get("execution_badge"), "需复核")

    def test_p1_module4_and_specific_actions_surface_in_report(self):
        """P1：模块4日程/账户进正文；Ch5–7 动作具名；探测预算标注；执行徽章。"""
        import json
        from models import CampaignRequest

        payload = json.loads(
            Path(__file__).resolve().parents[1]
            .joinpath("examples/cookie_quartet_full_case.json")
            .read_text(encoding="utf-8")
        )
        result = run_strategy(
            CampaignRequest(**payload), use_model=False, allow_mock=False
        )
        sections = {s["key"]: s for s in result.report_view["report_sections"]}

        market = sections["market_competitor"]
        self.assertEqual(market["title"], "赛道与竞品深度分析")
        subs = {s["key"]: s for s in market.get("subsections") or []}
        organic = subs["organic"]
        self.assertTrue(
            any("导入全量" in line or "窗口" in line for line in organic["data_explanation"])
        )
        self.assertIn(market["execution_badge"], {"可执行", "需复核"})

        spotlight = subs["spotlight"]
        self.assertTrue(
            any("08:00" in a or "探测预算" in a for a in spotlight["actions"])
            or "探测预算" in spotlight["decision"]
        )
        self.assertTrue(spotlight["visuals"].get("daily_slots") or spotlight["visuals"].get("account_plans"))
        self.assertIn("探测预算", result.report_markdown)

        audience = sections["audience"]
        self.assertTrue(any("选题" in a or "「" in a for a in audience["actions"]))

        spotlight_decision = sections["spotlight_decision"]
        self.assertEqual(len(spotlight_decision["visuals"].get("targeting_packages") or []), 3)
        self.assertEqual(len(spotlight_decision["visuals"].get("risk_playbook") or []), 5)

        creator = sections["creator_keyword"]
        self.assertTrue(
            any("达人" in a or "词包" in a or "出价" in a or "搜索" in a for a in creator["actions"])
        )
        visuals = creator["visuals"]
        self.assertTrue(visuals.get("organic_traffic"))
        self.assertTrue(visuals.get("search_keywords"))
        self.assertTrue(visuals.get("feed_keywords"))
        self.assertTrue((visuals.get("layout_plan") or {}).get("title_keywords") is not None)

        budget = sections["budget"]
        self.assertTrue(any("探测" in a or "聚光" in a for a in budget["actions"]))

        p1 = result.report_view["action_plan"][0]
        self.assertEqual(p1.get("budget_kind"), "probe")
        self.assertIn("探测", p1.get("budget_label") or "")
        self.assertIn("探测预算", result.report_markdown)
        self.assertIn("执行状态", result.report_markdown)
        # P2 黄金锚点：预算守恒 + 四章 + 探测预算标注
        self.assertIn("¥30,000", result.report_markdown.replace(" ", ""))
        self.assertIn("¥70,000", result.report_markdown.replace(" ", ""))
        self.assertIn("## 第一章｜赛道与竞品深度分析", result.report_markdown)
        self.assertIn("## 第四章｜", result.report_markdown)
        self.assertIn("探测预算（非全案投放预算）", result.report_markdown)
        self.assertEqual(len(result.report_view["executive_summary"]["key_findings"]), 3)

    def test_p1_grounded_agent_annotates_chapter_decision(self):
        from report_view import build_report_view

        result = run_strategy(
            sample_request(), use_model=False, allow_mock=False, use_agent_modules=False
        )
        modules = result.modules
        modules["module_5_budget_pacing"]["agent_decision"] = {
            "output": {
                "budget_split": {
                    "organic_budget_cny": 30000,
                    "paid_budget_cny": 70000,
                    "organic_ratio": 0.3,
                    "needs_review": False,
                },
                "human_review_items": ["核对预算比例"],
            },
            "grounding_check": {"passed": True, "mismatches": []},
            "steps_used": 2,
        }
        modules["module_5_budget_pacing"]["decision_source"] = "llm_agent"
        view = build_report_view(
            sample_request(),
            modules,
            result.evidence_gaps,
            result.data_confidence,
        )
        budget_section = next(s for s in view["report_sections"] if s["key"] == "budget")
        self.assertIn("【Agent 已溯源", budget_section["decision"])
        self.assertIn("规则基线", budget_section["decision"])
        self.assertTrue(budget_section.get("decision_baseline"))
        self.assertTrue(
            any("人工复核：核对预算比例" == a for a in budget_section["actions"])
        )
        self.assertEqual(budget_section["execution_badge"], "可执行")


if __name__ == "__main__":
    unittest.main()
