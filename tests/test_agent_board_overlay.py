"""模块1 Agent 结论回写对标看板文案。"""
from __future__ import annotations

import unittest

from competitor_benchmark_board import apply_module1_agent_overlay


def _base_board() -> dict:
    return {
        "available": True,
        "pills": ["对标条目 2"],
        "section_organic": {
            "summary": "模板摘要",
            "commonalities": ["高频主题：送礼"],
            "gaps": ["空白卖点：低糖"],
            "peak_caption": "模板高峰",
            "format_note": "模板形式",
            "trend_series": [{"date": "2026-01", "note_count": 3, "interactions": 100}],
        },
        "section_competitor": {
            "commonality_rows": [{"dimension": "主题", "observation": "送礼"}],
            "paid_conclusion": "模板投流结论",
            "targeting_cards": [{"title": "受众信号", "body": "游客"}],
        },
        "counter_actions": [{"priority": "P1", "action": "模板动作", "gap": "模板空白"}],
    }


class AgentBoardOverlayTests(unittest.TestCase):
    def test_overlay_writes_agent_copy_without_touching_trend_series(self):
        board = _base_board()
        modules = {
            "module_1_market_competitor": {
                "agent_decision": {
                    "grounding_check": {"passed": True},
                    "output": {
                        "organic_landscape": {
                            "peak_hour_hypothesis": "假设晚间 19-22 点更活跃（待验证）",
                            "content_form_advice": ["短视频先拍酥脆断面", "图文做伴手礼清单"],
                            "boundary_note": "本样本≠全平台大盘",
                        },
                        "competitor_breakdown": {
                            "common_patterns": [
                                "竞品A 用「伴手礼清单」图文拉收藏，说明决策清单有效"
                            ],
                            "content_gaps": ["低糖健康尚未被对标占坑"],
                            "ad_labeled_count": 1,
                            "targeting_hypotheses": [
                                "假设到港送礼人群对清单型封面更买账，测收藏率"
                            ],
                        },
                        "risk_alerts": [
                            {
                                "risk": "同质化清单",
                                "source": "对标样本",
                                "action": "本周改对比测评角度开测",
                            }
                        ],
                        "human_review_items": ["核验广告标识时长"],
                    },
                }
            }
        }
        apply_module1_agent_overlay(board, modules)
        self.assertTrue(board["agent_insight"]["applied"])
        self.assertIn("伴手礼清单", board["section_organic"]["commonalities"][0])
        self.assertIn("低糖健康", board["section_organic"]["gaps"][0])
        self.assertIn("19-22", board["section_organic"]["peak_caption"])
        self.assertIn("酥脆断面", board["section_organic"]["format_note"])
        self.assertEqual(
            board["section_organic"]["trend_series"][0]["note_count"],
            3,
        )
        self.assertTrue(
            any(
                "假设" in card["body"] or "Agent" in card["title"]
                for card in board["section_competitor"]["targeting_cards"]
            )
        )
        self.assertIn("Agent 人话解读已写入", board["pills"])

    def test_overlay_can_preserve_local_competitor_section(self):
        board = _base_board()
        local_rows = [{
            "dimension": "内容空白",
            "observation": "样本内未覆盖候选：低糖；尚缺需求证据",
            "conclusion_type": "hypothesis",
            "confidence": "low",
        }]
        board["section_competitor"]["commonality_rows"] = local_rows
        board["section_competitor"]["paid_conclusion"] = "本地投流结论"
        modules = {
            "module_1_market_competitor": {
                "agent_decision": {
                    "grounding_check": {"passed": True},
                    "output": {
                        "organic_landscape": {
                            "peak_hour_hypothesis": "假设晚间",
                            "content_form_advice": ["短视频"],
                            "boundary_note": "样本≠大盘",
                        },
                        "competitor_breakdown": {
                            "common_patterns": ["Agent 不该覆盖本地选题"],
                            "content_gaps": ["空白X"],
                            "ad_labeled_count": 0,
                            "targeting_hypotheses": ["假设人群A"],
                        },
                        "risk_alerts": [],
                        "human_review_items": [],
                    },
                }
            }
        }
        board["section_organic"]["commonalities"] = ["图集为主（3/3）"]
        board["section_organic"]["summary"] = "本地心智摘要"
        apply_module1_agent_overlay(
            board,
            modules,
            overlay_competitor_section=False,
            overlay_organic_copy=False,
        )
        self.assertEqual(board["section_competitor"]["commonality_rows"], local_rows)
        self.assertEqual(board["section_competitor"]["paid_conclusion"], "本地投流结论")
        self.assertTrue(any(
            card["title"].startswith("Agent 定向测试假设")
            for card in board["section_competitor"]["targeting_cards"]
        ))
        self.assertTrue(board["agent_insight"]["competitor_section_preserved"])
        self.assertTrue(board["agent_insight"]["organic_copy_preserved"])
        self.assertEqual(board["section_organic"]["summary"], "本地心智摘要")
        self.assertIn("图集为主（3/3）", board["section_organic"]["commonalities"][0])

    def test_enabled_overlay_preserves_authoritative_fact_rows(self):
        board = _base_board()
        local_rows = [{
            "dimension": "内容空白",
            "observation": "样本内未覆盖候选：低糖；尚缺需求证据",
            "conclusion_type": "hypothesis",
            "confidence": "low",
            "coverage": 0.0,
        }]
        board["section_competitor"]["commonality_rows"] = local_rows
        modules = {
            "module_1_market_competitor": {
                "agent_decision": {
                    "grounding_check": {"passed": True},
                    "output": {
                        "organic_landscape": {
                            "peak_hour_hypothesis": "假设晚间",
                            "content_form_advice": ["短视频展示断面"],
                            "boundary_note": "样本≠大盘",
                        },
                        "competitor_breakdown": {
                            "common_patterns": ["竞品A 的清单内容可转成收藏测试"],
                            "content_gaps": ["低糖健康待验证"],
                            "ad_labeled_count": 0,
                            "targeting_hypotheses": ["假设送礼人群关注低糖卖点"],
                        },
                        "risk_alerts": [],
                        "human_review_items": [],
                    },
                }
            }
        }

        apply_module1_agent_overlay(board, modules, overlay_competitor_section=True)

        self.assertEqual(board["section_competitor"]["commonality_rows"], local_rows)
        interpretation = next(
            card["body"]
            for card in board["section_competitor"]["targeting_cards"]
            if card["title"] == "Agent 行动解读"
        )
        self.assertIn("清单内容", interpretation)
        self.assertIn("低糖健康待验证", interpretation)

    def test_failed_grounding_skips_overlay(self):
        board = _base_board()
        modules = {
            "module_1_market_competitor": {
                "agent_decision": {
                    "grounding_check": {"passed": False},
                    "output": {
                        "competitor_breakdown": {
                            "common_patterns": ["不该写入"],
                            "content_gaps": [],
                            "ad_labeled_count": 9,
                            "targeting_hypotheses": ["假设xxx"],
                        }
                    },
                }
            }
        }
        apply_module1_agent_overlay(board, modules)
        self.assertFalse(board["agent_insight"]["applied"])
        self.assertEqual(board["section_organic"]["commonalities"], ["高频主题：送礼"])

    def test_disabled_competitor_overlay_does_not_create_empty_section(self):
        board = {
            "available": True,
            "pills": [],
            "section_organic": {},
        }
        modules = {
            "module_1_market_competitor": {
                "agent_decision": {
                    "grounding_check": {"passed": True},
                    "output": {
                        "organic_landscape": {},
                        "competitor_breakdown": {},
                        "risk_alerts": [],
                        "human_review_items": [],
                    },
                }
            }
        }

        apply_module1_agent_overlay(
            board,
            modules,
            overlay_competitor_section=False,
            overlay_organic_copy=False,
        )

        self.assertNotIn("section_competitor", board)


if __name__ == "__main__":
    unittest.main()
