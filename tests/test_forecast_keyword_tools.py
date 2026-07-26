"""forecast / keyword 工具单测：不依赖真实模型 Key，不 import engine。

沿用 tests/test_agent_tools.py 的 DEFAULT_REGISTRY.execute 范式：校验失败以
error dict 返回而非抛异常，成功则返回工具算术结果。
"""
from __future__ import annotations

import unittest

from tools import DEFAULT_REGISTRY


def _find_keyword(result: dict, keyword: str) -> dict | None:
    for rows in result["keyword_tiers"].values():
        for row in rows:
            if row["keyword"] == keyword:
                return row
    return None


# 8 个覆盖各意向×版位组合的候选词（core≥2/long_tail≥4/blue_ocean≥2）
_KEYWORDS = [
    {"keyword": "招牌蝴蝶酥", "level": "core", "intent": "high", "lane": "search", "from_evidence": True},
    {"keyword": "蝴蝶酥礼盒", "level": "core", "intent": "mid", "lane": "search", "from_evidence": True},
    {"keyword": "手工蝴蝶酥推荐", "level": "long_tail", "intent": "high", "lane": "search", "from_evidence": True},
    {"keyword": "蝴蝶酥怎么选", "level": "long_tail", "intent": "mid", "lane": "search", "from_evidence": False},
    {"keyword": "送礼伴手礼", "level": "long_tail", "intent": "mid", "lane": "feed", "from_evidence": False},
    {"keyword": "香港伴手礼", "level": "long_tail", "intent": "high", "lane": "both", "from_evidence": False},
    {"keyword": "低糖蝴蝶酥", "level": "blue_ocean", "intent": "low", "lane": "search", "from_evidence": False},
    {"keyword": "办公室下午茶", "level": "blue_ocean", "intent": "mid", "lane": "feed", "from_evidence": False},
]
_SPLIT = {"core": 0.5, "long_tail": 0.3, "blue_ocean": 0.2}


class ForecastToolTest(unittest.TestCase):
    def test_accepts_baseline_source_alias_for_cpc(self) -> None:
        """LLM 常把 calc_bid_range 的 baseline_source 误传到 forecast，应兼容。"""
        result = DEFAULT_REGISTRY.execute("estimate_paid_performance", {
            "paid_budget_cny": 70000,
            "baseline_cpc_cny": 1.6,
            "baseline_source": "数据需求.xlsx",  # 别名
            "aov_cny": 200,
            "rationale": "兼容 baseline_source 别名，避免工具循环烧步数",
        })
        self.assertNotIn("error", result)
        self.assertEqual(result["stop_loss"]["cpc_stop_cny"], 2.4)

    def test_test_budget_takes_sample_branch(self) -> None:
        # by_ratio=100000*0.15=15000，by_sample=40*20*1.5=1200 → min=样本分支=1200，
        # 但 1200 < 聚光×5%=5000，触发最低带宽下限 → 5000
        result = DEFAULT_REGISTRY.execute("estimate_paid_performance", {
            "paid_budget_cny": 100000,
            "baseline_cpc_cny": 1.6,
            "baseline_cpc_source": "数据需求.xlsx",
            "baseline_cvr": 0.04,
            "baseline_cvr_source": "数据需求.xlsx",
            "aov_cny": 200,
            "rationale": "有CPC与CVR证据，按目标CPA估算测试带宽",
        })
        self.assertEqual(result["target_cpa_cny"], 40.0)
        self.assertEqual(result["test_budget_cny"], 5000)  # 样本分支 1200 被下限抬到 5000
        self.assertIn("最低测试带宽下限", result["test_budget_basis"])
        self.assertEqual(result["stop_loss"]["cpc_stop_cny"], 2.4)
        self.assertEqual(result["stop_loss"]["cpa_stop_cny"], 48.0)
        self.assertIsNone(result["roi_point"])  # 缺 CTR 不给 ROI

    def test_test_budget_takes_ratio_branch(self) -> None:
        # by_ratio=5000*0.15=750，by_sample=200*20*1.5=6000 → min=比例分支
        result = DEFAULT_REGISTRY.execute("estimate_paid_performance", {
            "paid_budget_cny": 5000,
            "baseline_cpc_cny": 2.0,
            "baseline_cpc_source": "数据需求.xlsx",
            "baseline_cvr": 0.01,
            "baseline_cvr_source": "数据需求.xlsx",
            "aov_cny": 200,
            "rationale": "小预算下 15% 比例低于样本估算，取比例分支",
        })
        self.assertEqual(result["target_cpa_cny"], 200.0)
        self.assertEqual(result["test_budget_cny"], 750)

    def test_no_cvr_uses_conservative_placeholder(self) -> None:
        result = DEFAULT_REGISTRY.execute("estimate_paid_performance", {
            "paid_budget_cny": 100000,
            "baseline_cpc_cny": 1.6,
            "baseline_cpc_source": "数据需求.xlsx",
            "aov_cny": 200,
            "rationale": "只有CPC证据，CVR用保守占位仅用于测试带宽",
        })
        self.assertEqual(result["target_cpa_cny"], 40.0)  # 1.6 × 25
        self.assertIn("占位", result["target_cpa_basis"])
        # by_sample=1200 < 聚光×5%=5000，触发最低带宽下限
        self.assertEqual(result["test_budget_cny"], 5000)
        self.assertIn("最低测试带宽下限", result["test_budget_basis"])
        self.assertIsNone(result["roi_point"])

    def test_full_evidence_gives_roi_band(self) -> None:
        result = DEFAULT_REGISTRY.execute("estimate_paid_performance", {
            "paid_budget_cny": 70000,
            "baseline_cpc_cny": 1.6,
            "baseline_cpc_source": "数据需求.xlsx",
            "baseline_ctr": 0.05,
            "baseline_ctr_source": "数据需求.xlsx",
            "baseline_cvr": 0.04,
            "baseline_cvr_source": "数据需求.xlsx",
            "aov_cny": 209.76,
            "rationale": "CPC/CTR/CVR 齐全且客单价已换汇，给 ROI 粗算",
        })
        self.assertIsNotNone(result["roi_point"])
        self.assertEqual(len(result["roi_band"]), 2)
        self.assertLess(result["roi_band"][0], result["roi_point"])
        self.assertGreater(result["roi_band"][1], result["roi_point"])
        self.assertIn("退货", result["roi_warning"])

    def test_test_budget_floor_triggered(self) -> None:
        # 低CPC无CVR：target_cpa=0.30×25=7.5，by_sample=7.5×20×1.5=225，by_ratio=10500
        # → min=225（占聚光0.3%不可执行），触发最低带宽下限 聚光×5%=3500
        result = DEFAULT_REGISTRY.execute("estimate_paid_performance", {
            "paid_budget_cny": 70000,
            "baseline_cpc_cny": 0.30,
            "baseline_cpc_source": "数据需求.xlsx",
            "aov_cny": 200,
            "rationale": "低CPC无CVR，公式算出极小带宽，应被最低带宽下限抬升",
        })
        self.assertEqual(result["test_budget_cny"], 3500)
        self.assertIn("最低测试带宽下限", result["test_budget_basis"])

    def test_missing_source_rejected(self) -> None:
        result = DEFAULT_REGISTRY.execute("estimate_paid_performance", {
            "paid_budget_cny": 100000,
            "baseline_cpc_cny": 1.6,  # 未附 baseline_cpc_source
            "aov_cny": 200,
            "rationale": "提供CPC但漏了来源，应被拒",
        })
        self.assertIn("error", result)


class KeywordToolTest(unittest.TestCase):
    def test_duplicate_keyword_rejected(self) -> None:
        dup = [dict(item) for item in _KEYWORDS]
        dup.append({
            "keyword": "招牌蝴蝶酥",  # 与首词重复（casefold 后相同）
            "level": "long_tail", "intent": "mid", "lane": "search", "from_evidence": False,
        })
        result = DEFAULT_REGISTRY.execute("build_keyword_tiers", {
            "keywords": dup,
            "level_budget_split": _SPLIT,
            "rationale": "含重复词，应整体拒绝",
        })
        self.assertIn("error", result)

    def test_budget_split_sum_not_one_rejected(self) -> None:
        result = DEFAULT_REGISTRY.execute("build_keyword_tiers", {
            "keywords": _KEYWORDS,
            "level_budget_split": {"core": 0.5, "long_tail": 0.3, "blue_ocean": 0.3},
            "rationale": "预算比例合计 1.1，应被拒",
        })
        self.assertIn("error", result)

    def test_level_count_shortfall_rejected(self) -> None:
        # 只有 1 个 core，低于下限 2
        few = [item for item in _KEYWORDS if item["level"] != "core"]
        few.append({"keyword": "唯一核心词", "level": "core", "intent": "high", "lane": "search", "from_evidence": True})
        result = DEFAULT_REGISTRY.execute("build_keyword_tiers", {
            "keywords": few,
            "level_budget_split": _SPLIT,
            "rationale": "core 不足 2 个，应被拒",
        })
        self.assertIn("error", result)

    def test_no_baseline_yields_null_bid_range(self) -> None:
        result = DEFAULT_REGISTRY.execute("build_keyword_tiers", {
            "keywords": _KEYWORDS,
            "level_budget_split": _SPLIT,
            "rationale": "无基准CPC，出价区间应留空待补",
        })
        self.assertNotIn("error", result)
        for rows in result["keyword_tiers"].values():
            for row in rows:
                self.assertIsNone(row["bid_range_cny"])
        self.assertEqual(result["bid_status"], "待补基准CPC")
        # evidence_coverage = 3/8
        self.assertEqual(result["evidence_coverage"], 0.375)

    def test_multiplier_bands_correct_with_baseline(self) -> None:
        result = DEFAULT_REGISTRY.execute("build_keyword_tiers", {
            "keywords": _KEYWORDS,
            "level_budget_split": _SPLIT,
            "baseline_cpc_cny": 2.0,
            "baseline_source": "数据需求.xlsx",
            "rationale": "有基准CPC，按固定倍率带算出价区间",
        })
        self.assertNotIn("error", result)
        # search+high → 1.0–1.3
        self.assertEqual(_find_keyword(result, "招牌蝴蝶酥")["bid_range_cny"], [2.0, 2.6])
        # search+mid → 0.9–1.1
        self.assertEqual(_find_keyword(result, "蝴蝶酥礼盒")["bid_range_cny"], [1.8, 2.2])
        # feed 一律 → 0.7–1.0
        self.assertEqual(_find_keyword(result, "送礼伴手礼")["bid_range_cny"], [1.4, 2.0])
        # both 视同 search+high → 1.0–1.3
        self.assertEqual(_find_keyword(result, "香港伴手礼")["bid_range_cny"], [2.0, 2.6])
        # blue_ocean 覆盖版位/意向 → 0.6–0.8 低价试探
        blue = _find_keyword(result, "低糖蝴蝶酥")
        self.assertEqual(blue["bid_range_cny"], [1.2, 1.6])
        self.assertIn("低价试探", blue["bid_note"])


if __name__ == "__main__":
    unittest.main()
