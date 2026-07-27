"""竞品证据：链接归一化 + 给定链接抓取拆解 + 稳定四章报告。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from competitor_fetch import enrich_links_to_evidence, parse_note_html
from competitor_input import normalize_competitor_inputs, note_id_from_url, stub_from_link
from engine import run_strategy
from models import CampaignRequest, CompetitorEvidence

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "examples" / "jenny_benchmark_competitor_evidence.json"

_SAMPLE_HTML = """
<html><head>
<meta property="og:title" content="香港珍妮曲奇 好吃程度排序 - 小红书">
<meta property="og:description" content="尖沙咀门店避坑，只收现金 #珍妮曲奇 #香港伴手礼">
<meta name="keywords" content="珍妮曲奇,香港必买,口味排序测评">
<meta property="og:xhs:note_like" content="1396">
<meta property="og:xhs:note_collect" content="972">
<meta property="og:xhs:note_comment" content="73">
</head><body><div class="username">詹詹的市井日记</div><div>1/3</div></body></html>
"""


def _base_request(**overrides) -> CampaignRequest:
    payload = {
        "brand_name": "曲奇四重奏",
        "category": "香港蝴蝶酥伴手礼",
        "product_name": "经典－原味蝴蝶酥礼盒",
        "selling_points": [
            "招牌经典款",
            "采用日本小麦粉与新西兰牛油",
            "牛油香浓、层次酥脆",
            "适合作为香港伴手礼",
        ],
        "price_min": 228,
        "price_max": 228,
        "currency": "HKD",
        "initial_audience": "到港游客",
        "total_budget_cny": 100000,
        "spotlight_budget_cny": 70000,
        "campaign_days": 30,
        "goal": "conversion",
        "analysis_days": 30,
        "competitor_links": [],
        "competitor_evidence": [],
        "constraints": ["竞品仅抓取用户给定链接，禁止全站爬取"],
    }
    payload.update(overrides)
    return CampaignRequest(**payload)


class CompetitorInputTests(unittest.TestCase):
    def test_note_id_from_explore_url(self) -> None:
        url = "https://www.xiaohongshu.com/explore/69a81ab6000000002602f416?xsec_token=abc"
        self.assertEqual(note_id_from_url(url), "69a81ab6000000002602f416")

    def test_links_only_become_stubs_without_fetch(self) -> None:
        url = "https://www.xiaohongshu.com/explore/68b11f08000000001c009d99"
        rows = normalize_competitor_inputs([url], [])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].interactions)
        self.assertIsNone(rows[0].is_ad_labeled)
        self.assertIn("尚未完成抓取", rows[0].notes or "")

    def test_parse_note_html_extracts_structured_fields(self) -> None:
        url = "https://www.xiaohongshu.com/explore/69a81ab6000000002602f416"
        item = parse_note_html(url, _SAMPLE_HTML)
        self.assertEqual(item.account_name, "詹詹的市井日记")
        self.assertIn("好吃程度排序", item.title or "")
        self.assertEqual(item.likes, 1396)
        self.assertEqual(item.favorites, 972)
        self.assertEqual(item.comments, 73)
        self.assertEqual(item.interactions, 1396 + 972 + 73)
        self.assertIs(item.is_ad_labeled, False)
        self.assertTrue(any("珍妮" in t or "伴手礼" in t or "排序" in t for t in item.content_themes))

    def test_enrich_fetches_given_links_only(self) -> None:
        url = "https://www.xiaohongshu.com/explore/69a81ab6000000002602f416"
        with patch(
            "competitor_fetch.fetch_note_html",
            return_value=_SAMPLE_HTML,
        ):
            rows, trace = enrich_links_to_evidence([url], existing=[], fetch_enabled=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].likes, 1396)
        self.assertEqual(trace[0]["status"], "fetched")

    def test_enrich_uses_only_pasted_links_when_present(self) -> None:
        """有粘贴链接时只实时抓取这些链接，不掺入全案旧账号。"""
        existing = [
            CompetitorEvidence(
                account_name=f"旧账号{i}",
                profile_or_note_url=f"https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaa{i}",
                interactions=100 + i,
                title=f"旧笔记{i}",
                content_themes=["旧主题"],
            )
            for i in range(5)
        ]
        new_links = [
            "https://www.xiaohongshu.com/explore/69a81ab6000000002602f416",
            "https://www.xiaohongshu.com/explore/6a321138000000001702f5cd",
        ]
        with patch(
            "competitor_fetch.fetch_note_html",
            return_value=_SAMPLE_HTML,
        ):
            rows, trace = enrich_links_to_evidence(
                new_links, existing=existing, fetch_enabled=True, max_items=5
            )
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(t["status"].startswith("fetch") for t in trace))
        self.assertTrue(rows[0].profile_or_note_url.startswith(new_links[0].split("?")[0]))
        self.assertTrue(rows[1].profile_or_note_url.startswith(new_links[1].split("?")[0]))
        self.assertFalse(any(r.account_name.startswith("旧账号") for r in rows))

    def test_enrich_thin_live_page_keeps_rich_existing(self) -> None:
        """登录墙/薄公开页不得冲掉已导入的赞藏评。"""
        url = "https://www.xiaohongshu.com/explore/69a81ab6000000002602f416"
        existing = [
            CompetitorEvidence(
                account_name="詹詹的市井日记",
                profile_or_note_url=url,
                title="香港珍妮曲奇 好吃程度排序",
                note_format="图集",
                interactions=2441,
                likes=1396,
                favorites=972,
                comments=73,
                is_ad_labeled=False,
                content_themes=["口味排序测评", "门店地址", "珍妮曲奇"],
                collected_at="2026-07-26",
            )
        ]
        thin_html = """
        <html><body><div class="username">詹詹的市井日记</div>
        <p>香港珍妮曲奇排序 门店地址</p><div>1/3</div></body></html>
        """
        with patch("competitor_fetch.fetch_note_html", return_value=thin_html):
            rows, trace = enrich_links_to_evidence(
                [url], existing=existing, fetch_enabled=True
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].likes, 1396)
        self.assertEqual(rows[0].favorites, 972)
        self.assertEqual(rows[0].comments, 73)
        self.assertEqual(rows[0].interactions, 2441)
        self.assertIn(trace[0]["status"], {"fetch_merged_existing", "fetch_merged_existing_richer"})

    def test_sample_notes_board_exposes_like_collect_comment(self) -> None:
        bench = json.loads(BENCH.read_text(encoding="utf-8"))
        req = _base_request(
            competitor_links=bench["competitor_links"],
            competitor_evidence=bench["competitor_evidence"],
            competitor_benchmark_brief=None,
        )
        result = run_strategy(req, use_model=False, allow_mock=False)
        samples = result.report_view["competitor_benchmark_board"]["sample_notes"]
        self.assertEqual(len(samples), 3)
        by_account = {row["account"]: row for row in samples}
        self.assertEqual(by_account["詹詹的市井日记"]["likes"], 1396)
        self.assertEqual(by_account["詹詹的市井日记"]["collects"], 972)
        self.assertEqual(by_account["詹詹的市井日记"]["comments"], 73)
        self.assertEqual(by_account["麦芽糖碎碎念"]["likes"], 3795)
        self.assertNotEqual(by_account["詹詹的市井日记"].get("angle"), "待接入")

    def test_auto_board_uses_local_engine_competitor_section(self) -> None:
        """无手写 brief 时，第03章应对齐本地引擎拆解，而不是主题/形式薄模板。"""
        bench = json.loads(BENCH.read_text(encoding="utf-8"))
        req = _base_request(
            competitor_links=bench["competitor_links"],
            competitor_evidence=bench["competitor_evidence"],
            competitor_benchmark_brief=None,
        )
        result = run_strategy(req, use_model=False, allow_mock=False)
        board = result.report_view["competitor_benchmark_board"]
        comp = board["section_competitor"]
        dims = [row["dimension"] for row in comp["commonality_rows"]]
        self.assertIn("选题", dims)
        self.assertIn("互动引擎", dims)
        rows = {row["dimension"]: row for row in comp["commonality_rows"]}
        self.assertEqual(
            set(rows),
            {"选题", "信息密度", "信任机制", "互动引擎", "扩散风险", "内容形式", "内容空白"},
        )
        required_evidence_metadata = {
            "sample_count",
            "total_samples",
            "coverage",
            "conclusion_type",
            "confidence",
            "evidence",
            "missing_evidence",
        }
        self.assertTrue(
            all(required_evidence_metadata.issubset(row) for row in rows.values())
        )
        self.assertTrue(
            all(
                isinstance(row["sample_count"], int)
                and isinstance(row["total_samples"], int)
                and isinstance(row["coverage"], (int, float))
                and row["conclusion_type"] in {"fact", "inference", "hypothesis"}
                and isinstance(row["evidence"], list)
                and isinstance(row["missing_evidence"], list)
                for row in rows.values()
            )
        )
        self.assertIn("门店", rows["信息密度"]["observation"])
        self.assertIn("支付", rows["信息密度"]["observation"])
        self.assertIn("正版", rows["信任机制"]["observation"])
        self.assertIn("价格", rows["互动引擎"]["observation"])
        self.assertIn("导流", rows["扩散风险"]["observation"])
        self.assertIn("样本内未覆盖", rows["内容空白"]["observation"])
        self.assertTrue(all(row["confidence"] == "low" for row in rows.values()))
        self.assertEqual(rows["选题"]["total_samples"], 3)
        self.assertEqual(rows["选题"]["confidence"], "low")
        self.assertTrue(rows["选题"]["evidence"])
        self.assertNotIn("现金", rows["信任机制"]["observation"])
        self.assertIn("样本内未覆盖", rows["内容空白"]["observation"])
        self.assertEqual(comp.get("source"), "local_engine")
        self.assertTrue(comp["paid_note_rows"])
        self.assertEqual(comp["paid_note_rows"][0]["ad_label"], "否")
        self.assertTrue(
            any(
                token in comp["paid_note_rows"][0]["content_type"]
                for token in ("自然", "攻略")
            ),
            comp["paid_note_rows"][0]["content_type"],
        )
        self.assertNotIn("需多日快照", comp["paid_note_rows"][0]["duration_judgment"])
        self.assertIn("自然流量内容武器", comp["paid_conclusion"])
        titles = [card["title"] for card in comp["targeting_cards"]]
        self.assertIn("地域/场景", titles)
        self.assertIn("兴趣词包", titles)
        self.assertIn("到港游客", comp["targeting_cards"][0]["body"])
        gaps = result.modules["module_1_market_competitor"]["competitor_full_funnel"]["content_gaps"]
        self.assertIn("样本内未覆盖候选", gaps["decision_conclusion"])
        self.assertNotIn("可规模化空白机会", gaps["decision_conclusion"])
        self.assertTrue(all(row["stage"] == "sample_uncovered" for row in gaps["candidates"]))
        self.assertIn("用户需求", " ".join(gaps["missing_evidence"]))
        self.assertTrue(gaps["opportunities"])
        reason0 = gaps["opportunities"][0]["reason"]
        self.assertIn("空白：缺", reason0)
        self.assertNotEqual(reason0, "当前对标样本未覆盖；尚缺用户需求与效果证据")

    def test_evidence_wins_over_duplicate_link(self) -> None:
        url = "https://www.xiaohongshu.com/explore/69a81ab6000000002602f416"
        evidence = [
            CompetitorEvidence(
                account_name="詹詹的市井日记",
                profile_or_note_url=url,
                interactions=2441,
                is_ad_labeled=False,
                content_themes=["口味排序测评"],
            )
        ]
        rows = normalize_competitor_inputs([url + "?xsec_token=1"], evidence)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].account_name, "詹詹的市井日记")
        self.assertEqual(rows[0].interactions, 2441)

    def test_jenny_benchmark_report_is_stable(self) -> None:
        bench = json.loads(BENCH.read_text(encoding="utf-8"))
        req = _base_request(
            competitor_links=bench["competitor_links"],
            competitor_evidence=bench["competitor_evidence"],
            competitor_benchmark_brief=bench["competitor_benchmark_brief"],
        )
        first = run_strategy(req, use_model=False, allow_mock=False)
        second = run_strategy(req, use_model=False, allow_mock=False)
        c1 = first.modules["module_1_market_competitor"]["competitor_full_funnel"]
        c2 = second.modules["module_1_market_competitor"]["competitor_full_funnel"]
        self.assertEqual(c1["input_policy"], "fetch_user_given_links_only_no_bulk_crawl")
        self.assertEqual(len(c1["accounts"]), 3)
        self.assertEqual(c1["paid_notes"]["confirmed_count"], 0)
        self.assertIn("结构化证据", c1["status"])
        self.assertIn("给定链接抓取", c1["organic_hits_commonalities"]["status"])
        themes = [row["theme"] for row in c1["organic_hits_commonalities"]["top_themes"]]
        self.assertTrue(any("珍妮" in t or "伴手礼" in t or "避坑" in t for t in themes))
        self.assertEqual(
            c1["targeting_inference"]["status"],
            "基于给定链接正文/评论画像信号的定向测试假设",
        )
        self.assertIn("到港游客", c1["targeting_inference"]["audience_signals"])
        self.assertEqual(
            c1["organic_hits_commonalities"]["decision_conclusion"],
            c2["organic_hits_commonalities"]["decision_conclusion"],
        )
        market = first.report_view["report_sections"][0]
        self.assertEqual(market["key"], "market_competitor")
        self.assertEqual(market["title"], "赛道与竞品深度分析")
        competitor = next(
            s for s in (market.get("subsections") or []) if s["key"] == "competitor"
        )
        self.assertTrue(
            any("给定链接" in line or "抓取" in line for line in competitor["data_explanation"])
            or "给定链接" in (competitor.get("decision") or "")
        )
        board = first.report_view["competitor_benchmark_board"]
        self.assertTrue(board["available"])
        self.assertEqual(board["headline"], "赛道与竞品深度分析")
        self.assertEqual(len(board["sample_notes"]), 3)
        self.assertEqual(board["counter_actions"][0]["priority"], "P1")
        self.assertEqual(
            board["headline"],
            second.report_view["competitor_benchmark_board"]["headline"],
        )
        self.assertIn("section_organic", board)
        self.assertIn("section_spotlight", board)
        self.assertIn("section_competitor", board)
        self.assertIn("section_risk", board)

    def test_links_only_auto_synthesize_board_with_fixture_fallback(self) -> None:
        bench = json.loads(BENCH.read_text(encoding="utf-8"))
        links = bench["competitor_links"]
        with patch(
            "competitor_fetch.fetch_note_html",
            side_effect=RuntimeError("login wall"),
        ):
            rows, trace = enrich_links_to_evidence(links, existing=[], fetch_enabled=True)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(item.interactions is not None for item in rows))
        self.assertTrue(any(row["status"] == "fetched" for row in trace))
        req = _base_request(competitor_links=links, competitor_evidence=rows)
        result = run_strategy(req, use_model=False, allow_mock=False)
        board = result.report_view["competitor_benchmark_board"]
        self.assertTrue(board["available"])
        self.assertEqual(len(board["sample_notes"]), 3)
        self.assertTrue(board["section_organic"]["commonalities"] or board["section_organic"]["summary"])

    def test_stub_helper_marks_pending_fields(self) -> None:
        stub = stub_from_link("https://www.xiaohongshu.com/explore/aaaabbbbccccdddd")
        self.assertTrue(stub.account_name.startswith("对标笔记"))
        self.assertEqual(stub.evidence_grade, "C_user_provided")


if __name__ == "__main__":
    unittest.main()
