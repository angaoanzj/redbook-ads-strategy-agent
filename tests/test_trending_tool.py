"""实时热搜跟进判定工具测试：五条固定决策规则各一条用例 + 计数与参数校验。

不依赖模型 Key / 网络 / 数据库；不 import engine / main。
「候选词不得编造」是 prompt 层约束（module6 铁律 5），工具层不做也无法做该校验，
因此这里不测——工具只对**已提交的候选词**按固定规则判定。
"""
from __future__ import annotations

import unittest

from tools import DEFAULT_REGISTRY
from tools.trending import RECOMMENDATIONS

CATEGORY = "香港蝴蝶酥伴手礼"
BRAND_TERMS = ["曲奇四重奏", "蝴蝶酥礼盒", "香港伴手礼", "牛油香浓"]


def evaluate(candidates: list[dict]) -> dict:
    return DEFAULT_REGISTRY.execute("evaluate_trending_keywords", {
        "candidates": candidates,
        "brand_terms": BRAND_TERMS,
        "category": CATEGORY,
        "rationale": "按数据源快照判定各候选词的趋势方向与是否跟进",
    })


def candidate(
    keyword: str,
    heat: float,
    previous: float | None = None,
    *,
    is_mock: bool = True,
) -> dict:
    return {
        "keyword": keyword,
        "heat_score": heat,
        "previous_heat": previous,
        "source_name": "模拟实时数据源（合规同构接口演示）",
        "is_mock": is_mock,
    }


def by_keyword(result: dict) -> dict[str, dict]:
    return {row["keyword"]: row for row in result["evaluated_keywords"]}


class DecisionRuleTest(unittest.TestCase):
    """五条规则：不相关→不跟进 / rising+相关→跟进 / unknown+相关+高热→观察 /
    cooling→不跟进 / 兜底→观察。"""

    def test_rule_rising_and_relevant_is_followed(self) -> None:
        result = evaluate([candidate("蝴蝶酥礼盒推荐", 80.0, 70.0)])
        row = by_keyword(result)["蝴蝶酥礼盒推荐"]
        self.assertEqual(row["trend"], "rising")
        self.assertGreaterEqual(row["relevance_hits"], 1)
        self.assertEqual(row["recommendation"], "跟进")
        self.assertIn("24h", row["action"])
        self.assertIn("上升", row["reason"])

    def test_rule_irrelevant_is_not_followed(self) -> None:
        # 与品类/品牌毫无词面交集，即便热度暴涨也不跟进
        result = evaluate([candidate("显卡降价", 95.0, 10.0)])
        row = by_keyword(result)["显卡降价"]
        self.assertEqual(row["relevance_hits"], 0)
        self.assertEqual(row["recommendation"], "不跟进")
        self.assertIn("无关", row["reason"])
        self.assertEqual(row["trend"], "rising")  # 趋势仍如实标注，只是不跟进

    def test_rule_cooling_is_not_followed(self) -> None:
        result = evaluate([candidate("香港伴手礼", 60.0, 90.0)])
        row = by_keyword(result)["香港伴手礼"]
        self.assertEqual(row["trend"], "cooling")
        self.assertGreaterEqual(row["relevance_hits"], 1)
        self.assertEqual(row["recommendation"], "不跟进")
        self.assertIn("回落", row["reason"])

    def test_rule_unknown_relevant_and_above_median_is_watched(self) -> None:
        result = evaluate([
            candidate("蝴蝶酥礼盒", 90.0, None),  # 无上批热度且高于中位数
            candidate("牛油香浓曲奇", 40.0, None),
            candidate("香港伴手礼清单", 20.0, None),
        ])
        rows = by_keyword(result)
        high = rows["蝴蝶酥礼盒"]
        self.assertEqual(high["trend"], "unknown")
        self.assertEqual(high["recommendation"], "观察")
        self.assertIn("中位数", high["reason"])
        self.assertIn("监控池", high["action"])
        # 同为 unknown 但低于中位数 → 落到兜底规则，同样是「观察」但理由不同
        low = rows["香港伴手礼清单"]
        self.assertEqual(low["recommendation"], "观察")
        self.assertNotEqual(low["reason"], high["reason"])

    def test_rule_fallback_flat_is_watched(self) -> None:
        result = evaluate([candidate("蝴蝶酥礼盒", 71.0, 70.0)])  # +1.4%，落在 ±5% 噪声带
        row = by_keyword(result)["蝴蝶酥礼盒"]
        self.assertEqual(row["trend"], "flat")
        self.assertEqual(row["recommendation"], "观察")
        self.assertIn("flat", row["reason"])


class OutputShapeTest(unittest.TestCase):
    def test_summary_counts_match_recommendations(self) -> None:
        result = evaluate([
            candidate("蝴蝶酥礼盒推荐", 80.0, 70.0),   # 跟进
            candidate("香港伴手礼", 60.0, 90.0),       # 不跟进（cooling）
            candidate("显卡降价", 95.0, 10.0),         # 不跟进（不相关）
            candidate("牛油香浓测评", 75.0, 74.0),     # 观察（flat）
        ])
        self.assertEqual(result["summary"], {"跟进": 1, "观察": 1, "不跟进": 2})
        self.assertEqual(
            sum(result["summary"].values()), result["candidate_count"]
        )
        self.assertEqual(result["candidate_count"], 4)

    def test_every_row_carries_contract_fields(self) -> None:
        result = evaluate([candidate("蝴蝶酥礼盒推荐", 80.0, 70.0, is_mock=True)])
        row = result["evaluated_keywords"][0]
        for key in (
            "keyword",
            "heat_score",
            "trend",
            "relevance_hits",
            "recommendation",
            "reason",
            "action",
            "is_mock",
        ):
            self.assertIn(key, row)
        self.assertIs(row["is_mock"], True)
        self.assertIn(row["recommendation"], RECOMMENDATIONS)
        self.assertIn("mock 数据仅作演示", result["policy"])
        self.assertIn("人工确认", result["policy"])

    def test_heat_scores_are_transcribed_not_recomputed(self) -> None:
        """热度必须原样回传，模块 6 的溯源检查依赖这一点。"""
        result = evaluate([candidate("蝴蝶酥礼盒推荐", 80.5, 70.25)])
        row = result["evaluated_keywords"][0]
        self.assertEqual(row["heat_score"], 80.5)
        self.assertEqual(row["previous_heat"], 70.25)


class ArgsValidationTest(unittest.TestCase):
    def test_empty_candidates_rejected(self) -> None:
        result = DEFAULT_REGISTRY.execute("evaluate_trending_keywords", {
            "candidates": [],
            "brand_terms": BRAND_TERMS,
            "category": CATEGORY,
            "rationale": "没有候选词也强行调用工具",
        })
        self.assertIn("error", result)
        self.assertTrue(
            any("candidates" in item["field"] for item in result["details"]), result
        )

    def test_more_than_twenty_candidates_rejected(self) -> None:
        result = evaluate([candidate(f"蝴蝶酥礼盒{index}", 50.0) for index in range(21)])
        self.assertIn("error", result)

    def test_short_rationale_and_empty_brand_terms_rejected(self) -> None:
        short = DEFAULT_REGISTRY.execute("evaluate_trending_keywords", {
            "candidates": [candidate("蝴蝶酥礼盒", 50.0)],
            "brand_terms": BRAND_TERMS,
            "category": CATEGORY,
            "rationale": "太短",
        })
        self.assertIn("error", short)
        no_terms = DEFAULT_REGISTRY.execute("evaluate_trending_keywords", {
            "candidates": [candidate("蝴蝶酥礼盒", 50.0)],
            "brand_terms": [],
            "category": CATEGORY,
            "rationale": "缺品牌词时无法做相关性判定",
        })
        self.assertIn("error", no_terms)

    def test_negative_heat_rejected(self) -> None:
        result = evaluate([candidate("蝴蝶酥礼盒", -1.0)])
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
