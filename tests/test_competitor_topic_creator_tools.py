"""competitor / topic / creator_match 三个新工具单测：不依赖真实模型 Key，不 import engine。

沿用 tests/test_agent_tools.py 的 DEFAULT_REGISTRY.execute 范式：校验失败以 error dict
返回而非抛异常，成功则返回工具算术结果。
"""
from __future__ import annotations

import unittest

from tools import DEFAULT_REGISTRY


# ---------------------------------------------------------------------------
# summarize_competitor_landscape
# ---------------------------------------------------------------------------
class CompetitorToolTest(unittest.TestCase):
    def _base_competitors(self) -> list[dict]:
        return [
            {"name": "竞品A", "note_format": "图文", "interactions": 1000, "is_ad_labeled": True, "evidence_status": "用户提供"},
            {"name": "竞品B", "note_format": "图文", "interactions": 2000, "is_ad_labeled": False, "evidence_status": "用户提供"},
            {"name": "竞品C", "note_format": "短视频", "interactions": 5000, "is_ad_labeled": None, "evidence_status": "知识库识别"},
        ]

    def test_hot_format_ranking_and_gaps(self) -> None:
        result = DEFAULT_REGISTRY.execute("summarize_competitor_landscape", {
            "competitors": self._base_competitors(),
            "own_selling_points": ["牛油香浓", "低糖健康", "送礼体面"],
            "covered_themes": ["牛油香浓层次酥脆"],
            "rationale": "基于三条竞品证据判读格局",
        })
        self.assertNotIn("error", result)
        ranking = result["hot_format_ranking"]
        # 短视频均值 5000 > 图文均值 1500，短视频排第一
        self.assertEqual(ranking[0]["note_format"], "短视频")
        self.assertEqual(ranking[1]["note_format"], "图文")
        self.assertEqual(ranking[1]["avg_interactions"], 1500.0)
        # 牛油香浓被覆盖，低糖健康/送礼体面为缺口
        self.assertEqual(result["content_gaps"], ["低糖健康", "送礼体面"])
        self.assertEqual(result["content_gap_stage"], "sample_uncovered")
        self.assertIn("样本内未覆盖", result["content_gap_policy"])
        self.assertNotIn("市场空白", result["content_gap_policy"])
        self.assertEqual(result["ad_labeled_count"], 1)

    def test_no_ad_label_forbids_budget_inference(self) -> None:
        comps = self._base_competitors()
        for c in comps:
            c["is_ad_labeled"] = None  # 没有任何广告标识证据
        result = DEFAULT_REGISTRY.execute("summarize_competitor_landscape", {
            "competitors": comps,
            "own_selling_points": ["招牌经典"],
            "covered_themes": [],
            "rationale": "无广告标识证据，预算禁止推测",
        })
        self.assertEqual(result["ad_labeled_count"], 0)
        self.assertEqual(result["budget_inference_policy"], "无广告标识证据：禁止推测竞品预算")
        self.assertIn("定向测试假设", result["targeting_hypothesis_policy"])

    def test_ad_labeled_only_gives_manual_review_text_no_numbers(self) -> None:
        result = DEFAULT_REGISTRY.execute("summarize_competitor_landscape", {
            "competitors": self._base_competitors(),
            "own_selling_points": ["招牌经典"],
            "covered_themes": [],
            "rationale": "有广告标识仅给粗估口径，绝不给数字",
        })
        self.assertEqual(result["budget_inference_policy"], "可按投放时长×档位区间粗估，需人工核验")
        # 政策文本里不含任何数字
        self.assertFalse(any(ch.isdigit() for ch in result["budget_inference_policy"]))

    def test_empty_competitors_returns_honest_result(self) -> None:
        # 零竞品证据：返回诚实结论而非报错（不逼模型编造竞品条目）
        result = DEFAULT_REGISTRY.execute("summarize_competitor_landscape", {
            "competitors": [],
            "own_selling_points": ["牛油香浓", "低糖健康", "送礼体面"],
            "covered_themes": [],
            "rationale": "证据区无竞品，如实返回无竞品结论",
        })
        self.assertNotIn("error", result)
        self.assertEqual(result["competitor_count"], 0)
        self.assertEqual(result["common_patterns"], [])
        self.assertEqual(result["hot_format_ranking"], [])
        # content_gaps = 全部卖点
        self.assertEqual(result["content_gaps"], ["牛油香浓", "低糖健康", "送礼体面"])
        self.assertEqual(result["content_gap_stage"], "evidence_insufficient")
        self.assertIn("样本覆盖本身未知", result["content_gap_policy"])
        self.assertEqual(result["ad_labeled_count"], 0)
        self.assertEqual(result["budget_inference_policy"], "无竞品证据：禁止推测竞品预算")
        self.assertEqual(result["evidence_status"], "无竞品证据，需补采")


# ---------------------------------------------------------------------------
# score_content_topics
# ---------------------------------------------------------------------------
def _directions() -> list[dict]:
    return [
        {"direction": "方向一", "organic_score": 8, "paid_score": 6, "rationale": "方向一自然与付费评分理由"},
        {"direction": "方向二", "organic_score": 7, "paid_score": 7, "rationale": "方向二自然与付费评分理由"},
        {"direction": "方向三", "organic_score": 6, "paid_score": 8, "rationale": "方向三自然与付费评分理由"},
    ]


def _topic(direction: str, index: int, paid: bool = False) -> dict:
    return {
        "title_template": f"选题标题模板{direction}{index}",
        "cover_suggestion": "封面建议文案",
        "outline": ["大纲要点一", "大纲要点二"],
        "direction": direction,
        "suitable_for_paid": paid,
        "paid_objective": "种草" if paid else None,
    }


def _fifteen_topics() -> list[dict]:
    topics = []
    for name in ("方向一", "方向二", "方向三"):
        for i in range(5):
            topics.append(_topic(name, i, paid=(i == 0)))
    return topics


class TopicToolTest(unittest.TestCase):
    def test_happy_grouping_and_thresholds(self) -> None:
        result = DEFAULT_REGISTRY.execute("score_content_topics", {
            "directions": _directions(),
            "topics": _fifteen_topics(),
            "rationale": "三方向均衡分布，各 5 个选题",
        })
        self.assertNotIn("error", result)
        self.assertEqual(result["counts_by_direction"], {"方向一": 5, "方向二": 5, "方向三": 5})
        self.assertEqual(result["material_screening"]["ctr_threshold"], 0.10)
        self.assertEqual(result["material_screening"]["engagement_threshold"], 0.07)
        self.assertEqual(result["paid_fit"]["paid_topic_count"], 3)
        self.assertEqual(result["paid_fit"]["paid_objective_breakdown"], {"种草": 3})

    def test_topic_direction_miss_named_and_rejected(self) -> None:
        topics = _fifteen_topics()
        topics[0]["direction"] = "未知方向X"  # 不在三方向内
        result = DEFAULT_REGISTRY.execute("score_content_topics", {
            "directions": _directions(),
            "topics": topics,
            "rationale": "含未命中方向的选题应被点名拒绝",
        })
        self.assertIn("error", result)
        joined = str(result.get("details"))
        self.assertIn(topics[0]["title_template"], joined)

    def test_direction_topic_shortfall_rejected(self) -> None:
        # 方向三只留 2 个选题（<3），把三个方向三改成方向一
        topics = _fifteen_topics()
        topics[-1]["direction"] = "方向一"
        topics[-2]["direction"] = "方向一"
        topics[-3]["direction"] = "方向一"
        result = DEFAULT_REGISTRY.execute("score_content_topics", {
            "directions": _directions(),
            "topics": topics,
            "rationale": "方向三选题不足 3 个应被拒",
        })
        self.assertIn("error", result)

    def test_paid_topic_without_objective_rejected(self) -> None:
        topics = _fifteen_topics()
        topics[1]["suitable_for_paid"] = True
        topics[1]["paid_objective"] = None
        result = DEFAULT_REGISTRY.execute("score_content_topics", {
            "directions": _directions(),
            "topics": topics,
            "rationale": "付费选题缺投放目标应被拒",
        })
        self.assertIn("error", result)


# ---------------------------------------------------------------------------
# match_creators
# ---------------------------------------------------------------------------
class CreatorMatchToolTest(unittest.TestCase):
    def test_scoring_tiers_and_budget(self) -> None:
        result = DEFAULT_REGISTRY.execute("match_creators", {
            "creators": [
                {"name": "小美", "followers": 8000, "average_interactions": 400, "quote_cny": 300,
                 "audience_tags": ["美食", "送礼", "伴手礼"], "source_name": "蒲公英"},
                {"name": "大V", "followers": 600000, "average_interactions": 9000, "quote_cny": None,
                 "audience_tags": ["美食"], "source_name": "CSV"},
            ],
            "audience_keywords": ["美食", "送礼", "伴手礼", "下午茶"],
            "tier_budgets": {"素人": 500, "达人": 2000, "KOL": 8000},
            "per_note_cap_ratio": 0.5,
            "rationale": "基于受众关键词做匹配与单篇预算",
        })
        self.assertNotIn("error", result)
        by_name = {m["name"]: m for m in result["matched_creators"]}
        # 小美：3 个标签交集 → 55 + 30 = 85；素人层 → 500×0.5=250
        self.assertEqual(by_name["小美"]["match_score"], 85)
        self.assertEqual(by_name["小美"]["tier"], "素人")
        self.assertEqual(by_name["小美"]["suggested_note_budget_cny"], 250)
        # 大V：1 个交集 → 65；KOL 层 → 8000×0.5=4000
        self.assertEqual(by_name["大V"]["match_score"], 65)
        self.assertEqual(by_name["大V"]["tier"], "KOL")
        self.assertEqual(by_name["大V"]["suggested_note_budget_cny"], 4000)
        # 匹配分高者排前
        self.assertEqual(result["matched_creators"][0]["name"], "小美")

    def test_match_score_capped_at_95(self) -> None:
        result = DEFAULT_REGISTRY.execute("match_creators", {
            "creators": [
                {"name": "全命中", "followers": 5000, "average_interactions": 100, "quote_cny": None,
                 "audience_tags": ["a", "b", "c", "d", "e", "f"], "source_name": "CSV"},
            ],
            "audience_keywords": ["a", "b", "c", "d", "e", "f"],
            "tier_budgets": {"素人": 500, "达人": 2000, "KOL": 8000},
            "rationale": "6 个交集应封顶 95 而非 115",
        })
        self.assertEqual(result["matched_creators"][0]["match_score"], 95)

    def test_shortfall_yields_open_slots(self) -> None:
        result = DEFAULT_REGISTRY.execute("match_creators", {
            "creators": [
                {"name": "小美", "followers": 8000, "average_interactions": 400, "quote_cny": 300,
                 "audience_tags": ["美食"], "source_name": "蒲公英"},
            ],
            "audience_keywords": ["美食", "送礼"],
            "tier_budgets": {"素人": 500, "达人": 2000, "KOL": 8000},
            "rationale": "达人不足 20，应按层给 open_slots",
        })
        self.assertLess(result["candidate_count"], 20)
        self.assertTrue(result["open_slots"])  # 有缺口
        self.assertLessEqual(len(result["open_slots"]), 3)
        self.assertEqual(result["policy"], "不足名额不编造，导入 CSV/蒲公英后补齐")
        for slot in result["open_slots"]:
            self.assertGreaterEqual(slot["slots_needed"], 1)

    def test_no_creators_empty_matched(self) -> None:
        result = DEFAULT_REGISTRY.execute("match_creators", {
            "creators": [],
            "audience_keywords": ["美食", "送礼"],
            "tier_budgets": {"素人": 500, "达人": 2000, "KOL": 8000},
            "rationale": "无达人证据，matched 为空但仍给 open_slots",
        })
        self.assertEqual(result["matched_creators"], [])
        self.assertTrue(result["open_slots"])


if __name__ == "__main__":
    unittest.main()
