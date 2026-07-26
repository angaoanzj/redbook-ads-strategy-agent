"""风险预警：限流内容类型 + 拒审原因短条目。"""

from __future__ import annotations

import unittest

from models import CampaignRequest, CompetitorEvidence
from risk_signals import build_risk_signal_pack


class RiskSignalTests(unittest.TestCase):
    def test_builds_short_content_and_rejection_lists(self) -> None:
        req = CampaignRequest(
            brand_name="曲奇四重奏",
            category="香港蝴蝶酥伴手礼",
            product_name="经典－原味蝴蝶酥礼盒",
            selling_points=["牛油香浓", "适合作为香港伴手礼"],
            price_min=228,
            price_max=228,
            currency="HKD",
            initial_audience="到港游客",
            total_budget_cny=100000,
            campaign_days=30,
            goal="conversion",
            competitor_evidence=[
                CompetitorEvidence(
                    account_name="麦芽糖碎碎念",
                    profile_or_note_url="https://www.xiaohongshu.com/explore/1",
                    title="只认这两家 避坑假店",
                    content_themes=["避坑假店", "只收现金", "珍妮曲奇"],
                    notes="评论问代购微信与原料质疑",
                    observed_audience=["避坑攻略党"],
                )
            ],
        )
        risk = {
            "official_rules": {
                "confirmed_types": [
                    {
                        "rule_title": "食品行业广告投放规范",
                        "risk_item": "普通食品宣传不得涉及功效夸大；普通食品不得超出普通食品本身的作用。",
                    },
                    {
                        "rule_title": "专业号合规",
                        "risk_item": "禁止导流微信、手机号、二维码进行站外成交。",
                    },
                ],
                "official_sources": [{"title": "食品规则"}],
            },
            "category_high_frequency_violations": {
                "ranked_reasons": [],
                "decision_conclusion": "无频次证据时不输出赛道高频榜。",
            },
            "frequent_ad_rejection_reasons": {
                "confirmed_reasons": [
                    {
                        "rule_title": "食品行业广告投放规范",
                        "risk_item": "普通食品宣传不得涉及功效夸大。",
                    }
                ],
                "account_ledger_reasons": [],
            },
            "baseline_checks": ["避免绝对化"],
        }
        pack = build_risk_signal_pack(req, risk, req.competitor_evidence)
        self.assertIn("真假店/仿品对抗", pack["content_types"])
        self.assertTrue(any("功效" in item or "导流" in item for item in pack["rejection_reasons"]))
        self.assertTrue(all(len(item) <= 60 for item in pack["content_types"]))
        self.assertTrue(all(len(item) <= 60 for item in pack["rejection_reasons"]))
        self.assertFalse(pack["has_ledger"])
        self.assertIn("台账", pack["rejection_status"])

    def test_ledger_reasons_take_priority(self) -> None:
        req = CampaignRequest(
            brand_name="曲奇四重奏",
            category="香港蝴蝶酥伴手礼",
            product_name="礼盒",
            selling_points=["伴手礼"],
            price_min=1,
            price_max=2,
            currency="HKD",
            initial_audience="游客",
            total_budget_cny=1000,
            campaign_days=30,
            goal="conversion",
        )
        risk = {
            "official_rules": {"confirmed_types": [], "official_sources": []},
            "category_high_frequency_violations": {
                "ranked_reasons": [
                    {"reason": "导流微信", "occurrence_count": 5, "period": "近30天", "source_name": "台账"}
                ],
                "decision_conclusion": "台账显示导流微信最高频",
            },
            "frequent_ad_rejection_reasons": {"confirmed_reasons": [], "account_ledger_reasons": []},
            "baseline_checks": [],
        }
        pack = build_risk_signal_pack(req, risk, [])
        self.assertTrue(pack["has_ledger"])
        self.assertEqual(pack["rejection_reasons"][0], "导流微信（5次）")


if __name__ == "__main__":
    unittest.main()
