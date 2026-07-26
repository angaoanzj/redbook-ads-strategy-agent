"""加分项：内容审核 / A/B / 竞品监控 / 看板。"""
from __future__ import annotations

import unittest

from tools.ab_test import AbTestArgs, build_ab_matrix
from tools.competitor_monitor import CompetitorMonitorArgs, monitor_competitors
from tools.content_audit import ContentAuditArgs, run_content_audit
from tools.dashboard import build_dashboard_payload
from bonus_modules import build_bonus_modules
from engine import run_strategy
from tests.test_engine import sample_request


class BonusModulesTests(unittest.TestCase):
    def test_content_audit_flags_absolute_terms(self):
        result = run_content_audit(
            ContentAuditArgs(
                title="最好吃的曲奇",
                body="全国第一蝴蝶酥",
                selling_points=["牛油香浓"],
            )
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["risk_level"], "high")
        self.assertEqual(result["gate"], "block")
        self.assertTrue(result["publish_gate"]["block_paid_amplification"])
        self.assertGreaterEqual(result["finding_count"], 2)

    def test_content_audit_uses_official_rule_risk_items(self):
        result = run_content_audit(
            ContentAuditArgs(
                title="口感绵密的蝴蝶酥",
                body="本款含特有禁词XYZ可放心冲",
                official_rules=[
                    {
                        "rule_id": "rule-demo-1",
                        "title": "内容审核规则总则",
                        "source_url": "https://example.com/rule",
                        "risk_items": ["特有禁词XYZ", "绝对化用语"],
                        "full_text": "禁止使用「特有禁词XYZ」等不当表述",
                    }
                ],
            )
        )
        self.assertFalse(result["passed"])
        self.assertGreaterEqual(result["kb_rule_term_count"], 1)
        self.assertTrue(
            any(
                row.get("term") == "特有禁词XYZ" and row.get("rule_id") == "rule-demo-1"
                for row in result["findings"]
            )
        )

    def test_content_audit_gates_block_paid_topics(self):
        from tools.content_audit import apply_content_audit_gates

        modules = {
            "module_2_audience_content": {
                "topics": [
                    {
                        "title_template": "最好吃的伴手礼",
                        "suitable_for_paid": True,
                        "suitable_for_spotlight": True,
                        "outline": ["最好"],
                    }
                ],
                "paid_material_gate": {"prototype_thresholds": {"ctr_percent": 10}},
            },
            "module_4_spotlight_decision": {"account_structure": {"plans": []}},
        }
        audit = run_content_audit(
            ContentAuditArgs(title="最好吃的伴手礼", body="绝对好吃")
        )
        trace = apply_content_audit_gates(modules, audit)
        self.assertTrue(trace["block_paid_amplification"])
        topic = modules["module_2_audience_content"]["topics"][0]
        self.assertFalse(topic["suitable_for_paid"])
        self.assertEqual(topic["compliance_gate"]["status"], "blocked")
        self.assertTrue(
            modules["module_4_spotlight_decision"]["content_audit_gate"][
                "block_new_creatives"
            ]
        )

    def test_build_bonus_applies_audit_with_draft_fields(self):
        base = run_strategy(sample_request(), use_model=False, allow_mock=False)
        req = sample_request().model_copy(
            update={
                "draft_title": "全国第一蝴蝶酥",
                "draft_body": "最好的香港伴手礼",
                "draft_image_urls": ["https://example.com/a.jpg"],
                "official_rule_evidence": [],
            }
        )
        core = {
            k: v
            for k, v in base.modules.items()
            if not str(k).startswith("bonus_")
        }
        # deep-ish copy topics list so we don't mutate base fixture unexpectedly
        import copy

        core = copy.deepcopy(core)
        bonus = build_bonus_modules(req, core)
        audit = bonus["bonus_content_audit"]
        self.assertEqual(audit["risk_level"], "high")
        self.assertEqual(audit["multimodal"][0]["status"], "pending_ocr")
        self.assertTrue(audit["gate_application"]["applied"])
        self.assertTrue(
            core["module_4_spotlight_decision"]["content_audit_gate"][
                "block_new_creatives"
            ]
        )

    def test_ab_matrix_cell_count(self):
        from tools.ab_test import TopicVariant

        result = build_ab_matrix(
            AbTestArgs(
                directions=["场景痛点", "产品证据", "对比决策"],
                title_variants_per_direction=2,
                cover_variants_per_direction=2,
                probe_budget_cny=1200,
                topic_variants=[
                    TopicVariant(
                        direction="场景痛点",
                        title="出差只买这一盒",
                        cover="机场柜台近景",
                    ),
                    TopicVariant(
                        direction="场景痛点",
                        title="送长辈不用猜口味",
                        cover="礼盒打开俯拍",
                    ),
                ],
            )
        )
        self.assertEqual(result["cell_count"], 12)
        self.assertEqual(len(result["matrix"]), 12)
        self.assertAlmostEqual(sum(c["scenario_ratio"] for c in result["matrix"]), 1.0, places=2)
        self.assertEqual(result["status"], "plan_only")
        self.assertIn("还没有", result["what_it_is"])
        first = result["matrix"][0]
        self.assertEqual(first["title_text"], "出差只买这一盒")
        self.assertEqual(first["result_status"], "待投放")
        self.assertTrue(str(first["probe_share_label"]).startswith("约"))

    def test_competitor_monitor_diff_alert(self):
        previous = {
            "brand_name": "曲奇四重奏",
            "account_count": 1,
            "ad_labeled_count": 0,
            "sample_note_count": 10,
            "accounts": [{"account": "竞品A"}],
        }
        result = monitor_competitors(
            CompetitorMonitorArgs(
                brand_name="曲奇四重奏",
                current_accounts=[{"account": "竞品A"}, {"account": "竞品B"}],
                current_ad_labeled_count=3,
                current_sample_note_count=12,
                previous_snapshot=previous,
            )
        )
        self.assertEqual(result["status"], "diff")
        types = {row["type"] for row in result["alerts"]}
        self.assertIn("ad_volume_spike", types)

    def test_competitor_monitor_baseline_ready(self):
        result = monitor_competitors(
            CompetitorMonitorArgs(
                brand_name="曲奇四重奏",
                current_accounts=[{"account": "竞品A"}],
                current_ad_labeled_count=0,
                current_sample_note_count=5,
            )
        )
        self.assertEqual(result["status"], "baseline")
        self.assertEqual(result["alerts"][0]["type"], "baseline_ready")

    def test_competitor_monitor_flags_viral_and_large_ads(self):
        result = monitor_competitors(
            CompetitorMonitorArgs(
                brand_name="曲奇四重奏",
                current_accounts=[
                    {"account": "竞品爆款号", "interactions": 12000, "ad_labeled": True},
                ],
                current_ad_labeled_count=4,
                current_sample_note_count=8,
            )
        )
        types = {row["type"] for row in result["alerts"]}
        self.assertIn("baseline_large_scale_ads", types)
        self.assertIn("viral_note_detected", types)
        self.assertTrue(result["viral_candidates"])
        self.assertTrue(result["playbook"])

    def test_run_strategy_includes_bonus_and_dashboard(self):
        result = run_strategy(sample_request(), use_model=False, allow_mock=False)
        self.assertIn("bonus_content_audit", result.modules)
        self.assertIn("bonus_ab_test", result.modules)
        self.assertIn("bonus_competitor_monitor", result.modules)
        self.assertIn("dashboard", result.report_view)
        self.assertIn("addon_tools", result.report_view)
        tools = result.report_view["addon_tools"]
        self.assertEqual(tools["title"], "附加工具")
        self.assertEqual(len(tools["nav"]), 4)
        self.assertIn("content_audit", tools)
        self.assertIn("ab_test", tools)
        self.assertIn("competitor_monitor", tools)
        self.assertTrue(result.report_view["dashboard"]["kpis"])
        self.assertIn("附加工具", result.report_markdown)
        self.assertIn("body_text", (result.modules["bonus_ab_test"].get("matrix") or [{}])[0])

    def test_build_bonus_modules_helper(self):
        base = run_strategy(sample_request(), use_model=False, allow_mock=False)
        core = {
            k: v
            for k, v in base.modules.items()
            if not str(k).startswith("bonus_")
        }
        bonus = build_bonus_modules(sample_request(), core)
        self.assertEqual(set(bonus), {
            "bonus_content_audit",
            "bonus_ab_test",
            "bonus_competitor_monitor",
        })
        dash = build_dashboard_payload(
            base.report_view,
            {**core, **bonus},
            report_id="rep-test",
            generated_at="2026-07-26T00:00:00+00:00",
        )
        self.assertEqual(dash["updated_from"], "report_view+modules")
        self.assertEqual(dash["title"], "全域投放数据看板")
        self.assertTrue(dash["module_panels"])
        self.assertIn("phases", dash["delivery"])
        self.assertIn("core", dash["keyword_tiers"])
        self.assertIn("json", dash["export"]["formats"])
        from tools.dashboard import export_dashboard_csv, export_dashboard_markdown

        md = export_dashboard_markdown(dash)
        self.assertIn("KPI", md)
        csv_text = export_dashboard_csv(dash)
        self.assertIn("section,key,label", csv_text)


if __name__ == "__main__":
    unittest.main()
