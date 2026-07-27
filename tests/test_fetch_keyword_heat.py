"""fetch_keyword_heat 纯函数单测（不打真实 5118）。"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "fetch_keyword_heat.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("fetch_keyword_heat", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FetchKeywordHeatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_module()

    def test_heat_score_from_index(self) -> None:
        score = self.mod.heat_score_from_metrics(
            index=1000, mobile_index=800, pc_pv=None, mobile_pv=None
        )
        self.assertGreater(score, 50)
        self.assertLessEqual(score, 99)

    def test_heat_score_from_pv_when_index_missing(self) -> None:
        score = self.mod.heat_score_from_metrics(
            index=None, mobile_index=None, pc_pv=100, mobile_pv=400
        )
        self.assertGreater(score, 0)

    def test_row_to_evidence(self) -> None:
        row = {
            "keyword": "香港伴手礼",
            "index": 500,
            "mobile_index": 400,
            "bidword_pcpv": 120,
            "bidword_wisepv": 800,
        }
        item = self.mod.row_to_evidence(
            row, source_name="test", mode="lookup"
        )
        self.assertEqual(item["keyword"], "香港伴手礼")
        self.assertEqual(item["evidence_grade"], "B_5118_live")
        self.assertFalse(item["is_proxy"])
        self.assertIn("流量指数=500", item["notes"])

    def test_build_output_paste(self) -> None:
        items = [
            {
                "keyword": "B",
                "source_name": "t",
                "collected_at": "2026-07-26",
                "heat_score": 70,
                "notes": "",
                "is_mock": False,
                "evidence_grade": "B_5118_live",
            },
            {
                "keyword": "A",
                "source_name": "t",
                "collected_at": "2026-07-26",
                "heat_score": 90,
                "notes": "",
                "is_mock": False,
                "evidence_grade": "B_5118_live",
            },
        ]
        out = self.mod.build_output(items, mode="lookup", seed=None, keywords=["A", "B"])
        self.assertEqual(out["count"], 2)
        self.assertTrue(out["paste_for_ui"].startswith("A|90"))


if __name__ == "__main__":
    unittest.main()
