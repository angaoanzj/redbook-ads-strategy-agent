"""官方规则加载/排序：只使用已采集公开规则，不伪造正文。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import OfficialRuleEvidence
from official_rules_loader import (
    load_demo_official_rule_evidence,
    load_official_rules_from_path,
    order_official_rules,
    sync_official_rules_demo,
    trim_risk_items,
)


ROOT = Path(__file__).resolve().parents[1]
DEMO_PATH = ROOT / "examples" / "mock" / "official_rules_demo.json"


class OfficialRulesLoaderTests(unittest.TestCase):
    def test_demo_file_loads_preferred_order(self):
        rules = load_demo_official_rule_evidence(demo_path=DEMO_PATH, risk_item_limit=24)
        self.assertGreaterEqual(len(rules), 3)
        self.assertEqual(rules[0].title, "食品行业规则&投放规则")
        self.assertEqual(rules[1].title, "内容审核规则总则")
        self.assertEqual(rules[2].title, "跨境广告内容规范")
        self.assertTrue(all(rule.source_url for rule in rules))
        self.assertTrue(all(rule.collected_at for rule in rules))
        self.assertTrue(all(len(rule.risk_items) <= 24 for rule in rules))

    def test_trim_risk_items_keeps_collected_prefix(self):
        rule = OfficialRuleEvidence(
            rule_id="r1",
            title="食品行业规则&投放规则",
            source_url="https://ad.xiaohongshu.com/next_help/docs/r1",
            collected_at="2026-07-24T18:07:21+00:00",
            risk_items=["甲", "乙", "丙"],
        )
        trimmed = trim_risk_items([rule], risk_item_limit=2)[0]
        self.assertEqual(trimmed.risk_items, ["甲", "乙"])

    def test_order_official_rules_prefers_food_review_crossborder(self):
        rules = [
            OfficialRuleEvidence(
                rule_id="a",
                title="治理公告&违规公示",
                source_url="https://example.com/a",
                collected_at="2026-07-24T00:00:00+00:00",
            ),
            OfficialRuleEvidence(
                rule_id="b",
                title="食品行业规则&投放规则",
                source_url="https://example.com/b",
                collected_at="2026-07-24T00:00:00+00:00",
            ),
            OfficialRuleEvidence(
                rule_id="c",
                title="跨境广告内容规范",
                source_url="https://example.com/c",
                collected_at="2026-07-24T00:00:00+00:00",
            ),
        ]
        ordered = order_official_rules(rules)
        self.assertEqual(
            [item.title for item in ordered],
            ["食品行业规则&投放规则", "跨境广告内容规范", "治理公告&违规公示"],
        )

    def test_sync_from_demo_source_roundtrip(self):
        source_rules = load_official_rules_from_path(DEMO_PATH)
        with tempfile.TemporaryDirectory() as directory:
            research_root = Path(directory) / "xhs-official-rules"
            run_dir = research_root / "20260724T180721Z"
            run_dir.mkdir(parents=True)
            array_path = run_dir / "official_rules.json"
            array_path.write_text(
                json.dumps(
                    [rule.model_dump(mode="json") for rule in source_rules],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            out = Path(directory) / "official_rules_demo.json"
            path, rules, source = sync_official_rules_demo(
                demo_path=out,
                research_root=research_root,
                db_path=Path(directory) / "missing.db",
            )
            self.assertEqual(path, out)
            self.assertGreaterEqual(len(rules), 3)
            self.assertIn("official_rules.json", source)
            reloaded = load_official_rules_from_path(out)
            self.assertEqual(len(reloaded), len(rules))


if __name__ == "__main__":
    unittest.main()
