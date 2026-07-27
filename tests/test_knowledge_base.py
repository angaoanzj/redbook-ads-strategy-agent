import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from knowledge_base import KnowledgeBase
from models import CategoryNoteEvidence, OfficialRuleEvidence


def sample_note(
    *,
    note_id: str = "note-1",
    title: str = "香港蝴蝶酥伴手礼推荐",
    description: str = "送礼场景实测",
    author: str = "作者甲",
    likes: int = 100,
) -> CategoryNoteEvidence:
    return CategoryNoteEvidence(
        search_keyword="香港伴手礼",
        search_sort="综合",
        search_rank=1,
        note_id=note_id,
        note_url=f"https://example.com/{note_id}",
        title=title,
        description=description,
        note_type="图集",
        author_nickname=author,
        likes=likes,
        favorites=20,
        comments=5,
        shares=2,
        tags=["蝴蝶酥", "香港伴手礼"],
        collected_at="2026-07-24T00:00:00Z",
        source_name="个人研究公开样本",
    )


class KnowledgeBaseTests(unittest.TestCase):
    def test_extract_scene_audience_keywords_from_notes(self):
        notes = [
            sample_note(note_id="a", title="女生送礼清单", description="下午茶场景"),
            CategoryNoteEvidence(
                search_keyword="职场女性",
                search_sort="综合",
                search_rank=2,
                note_id="b",
                note_url="https://example.com/b",
                title="宝妈囤货",
                description="办公室也用得上",
                note_type="图文",
                likes=40,
                favorites=5,
                comments=1,
                shares=0,
                tags=["宝妈", "办公室", "送礼"],
                collected_at="2026-07-24T00:00:00Z",
                source_name="个人研究公开样本",
            ),
        ]
        pack = KnowledgeBase.extract_scene_audience_keywords(notes)
        scene = {row["keyword"] for row in pack["scene_keywords"]}
        audience = {row["keyword"] for row in pack["audience_keywords"]}
        self.assertTrue(scene & {"送礼", "下午茶", "办公室", "伴手礼"})
        self.assertTrue(audience & {"宝妈", "职场女性", "女生"})

    def test_aggregate_keyword_stats_from_notes(self):
        notes = [
            sample_note(note_id="a", likes=100),
            sample_note(
                note_id="b",
                title="蝴蝶酥测评",
                author="作者乙",
                likes=40,
            ),
            CategoryNoteEvidence(
                search_keyword="送礼推荐",
                search_sort="综合",
                search_rank=2,
                note_id="c",
                note_url="https://example.com/c",
                title="送礼推荐",
                note_type="图文",
                likes=10,
                favorites=1,
                comments=0,
                shares=0,
                tags=["送礼", "蝴蝶酥"],
                collected_at="2026-07-24T00:00:00Z",
                source_name="个人研究公开样本",
            ),
        ]
        stats = KnowledgeBase.aggregate_keyword_stats(notes, limit=10)
        keywords = [row["keyword"] for row in stats]
        self.assertIn("香港伴手礼", keywords)
        self.assertIn("蝴蝶酥", keywords)
        top = stats[0]
        self.assertGreaterEqual(top["note_count"], 1)
        self.assertTrue(top["from_evidence"])
        self.assertTrue(set(top["sources"]) <= {"search_keyword", "tag"})

    def test_brand_metrics_are_normalized_from_workbook_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            knowledge = KnowledgeBase(Path(directory) / "knowledge.db")
            with sqlite3.connect(knowledge.path) as connection:
                connection.execute("CREATE TABLE paid_metrics (brand_name TEXT, year INTEGER, month INTEGER, data_json TEXT, source_file TEXT, collected_at TEXT)")
                connection.execute("INSERT INTO paid_metrics VALUES (?,?,?,?,?,?)", ("曲奇四重奏", 2026, 1, '{"消费":"100","曝光量":"1000","点击量":"100","点击率":"0.1","平均点击成本":"1","平均千次展现费用":"100","总互动量":"10"}', "数据需求.xlsx", "2026-07-24"))
            evidence = knowledge.metric_evidence_for_campaign("曲奇四重奏", analysis_days=180)
            names = {item.metric_name for item in evidence}
            self.assertIn("cpc", names)
            self.assertIn("cpm", names)
            self.assertTrue(all(item.notes and "数据需求.xlsx" in item.notes for item in evidence))
            monthly = knowledge.paid_monthly_for_campaign("曲奇四重奏", analysis_days=None)
            self.assertEqual(len(monthly), 1)
            self.assertEqual(monthly[0]["month"], "2026-01")
            self.assertEqual(monthly[0]["cpc"], "1.00")

    def test_paid_metrics_30day_window_keeps_ctr_when_current_month_missing(self):
        """近30天若严格只取当月，7月无导出会让 CTR 空白；应回看/回退有数月。"""
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as directory:
            knowledge = KnowledgeBase(Path(directory) / "knowledge.db")
            with sqlite3.connect(knowledge.path) as connection:
                connection.execute(
                    "CREATE TABLE paid_metrics "
                    "(brand_name TEXT, year INTEGER, month INTEGER, data_json TEXT, "
                    "source_file TEXT, collected_at TEXT)"
                )
                connection.execute(
                    "INSERT INTO paid_metrics VALUES (?,?,?,?,?,?)",
                    (
                        "曲奇四重奏",
                        2026,
                        5,
                        json.dumps(
                            {
                                "消费": "351596",
                                "曝光量": "7418361",
                                "点击量": "1439061",
                                "点击率": "0.193986",
                                "平均点击成本": "0.244",
                                "平均千次展现费用": "47.4",
                                "总互动量": "60600",
                            },
                            ensure_ascii=False,
                        ),
                        "数据需求.xlsx",
                        "2026-07-24",
                    ),
                )
            evidence = knowledge.metric_evidence_for_campaign(
                "曲奇四重奏",
                analysis_days=30,
                as_of=datetime(2026, 7, 26, tzinfo=timezone.utc),
            )
            by_name = {item.metric_name: item for item in evidence}
            self.assertIn("ctr", by_name)
            self.assertAlmostEqual(by_name["ctr"].value, 0.193986, places=5)
            self.assertIn("期间=2026-05", by_name["ctr"].notes)

    def test_imports_and_reads_official_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            knowledge = KnowledgeBase(Path(directory) / "knowledge.db")
            result = knowledge.import_official_rules([
                OfficialRuleEvidence(
                    rule_id="food-rule",
                    title="食品行业规则&投放规则",
                    category_path=["新手必看", "物料审核规范"],
                    source_url="https://ad.xiaohongshu.com/next_help/docs/food-rule",
                    source_updated_at="2026-06-01T00:00:00Z",
                    collected_at="2026-07-24T00:00:00Z",
                    full_text="食品广告不得虚假夸大。",
                    risk_items=["食品广告不得虚假夸大。"],
                )
            ])
            self.assertEqual(result["inserted_count"], 1)
            self.assertEqual(knowledge.status()["total_official_rules"], 1)
            self.assertEqual(
                knowledge.get_official_rules()[0].risk_items,
                ["食品广告不得虚假夸大。"],
            )

    def test_import_rules_accepts_envelope_and_export_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            knowledge = KnowledgeBase(Path(directory) / "knowledge.db")
            envelope_path = Path(directory) / "rules_envelope.json"
            envelope_path.write_text(
                json.dumps(
                    {
                        "_meta": {"is_mock": False},
                        "official_rule_evidence": [
                            {
                                "rule_id": "cross-rule",
                                "title": "跨境广告内容规范",
                                "category_path": ["新手必看"],
                                "source_url": "https://ad.xiaohongshu.com/next_help/docs/cross-rule",
                                "collected_at": "2026-07-24T00:00:00Z",
                                "full_text": "跨境广告禁止推广目录",
                                "risk_items": ["跨境广告禁止推广目录"],
                                "source_name": "小红书聚光官方帮助中心",
                                "evidence_grade": "A_official_public_rule",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            from knowledge_base import _load_official_rules

            imported = knowledge.import_official_rules(_load_official_rules(envelope_path))
            self.assertEqual(imported["inserted_count"], 1)
            export_path = Path(directory) / "exported.json"
            rules = knowledge.get_official_rules()
            from official_rules_loader import build_demo_rules_envelope

            export_path.write_text(
                json.dumps(
                    build_demo_rules_envelope(rules, source_label="test"),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            reloaded = _load_official_rules(export_path)
            self.assertEqual(reloaded[0].title, "跨境广告内容规范")
            self.assertEqual(reloaded[0].risk_items, ["跨境广告禁止推广目录"])

    def test_import_deduplicates_and_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            knowledge = KnowledgeBase(Path(directory) / "knowledge.db")
            first = knowledge.import_notes([sample_note()])
            second = knowledge.import_notes([sample_note(likes=250)])
            self.assertEqual(first["inserted_count"], 1)
            self.assertEqual(second["updated_count"], 1)
            self.assertEqual(knowledge.status()["total_notes"], 1)
            self.assertEqual(knowledge.search(["蝴蝶酥"])[0].likes, 250)

    def test_search_filters_window_mock_rows_and_repeats(self):
        with tempfile.TemporaryDirectory() as directory:
            knowledge = KnowledgeBase(Path(directory) / "knowledge.db")
            notes = [
                sample_note(note_id="old", title="蝴蝶酥旧样本", author="作者甲"),
                sample_note(note_id="new-1", title="蝴蝶酥新样本1", author="作者甲"),
                sample_note(note_id="new-2", title="蝴蝶酥新样本2", author="作者甲"),
                sample_note(note_id="new-3", title="蝴蝶酥新样本3", author="作者甲"),
                sample_note(note_id="new-4", title="蝴蝶酥新样本4", author="作者甲"),
                sample_note(note_id="other", title="蝴蝶酥另一作者", author="作者乙"),
            ]
            for index, note in enumerate(notes):
                note.published_at = "2026-07-24T00:00:00Z" if index else "2025-01-01T00:00:00Z"
                note.is_mock = index == 5
            knowledge.import_notes(notes)
            results = knowledge.search(
                ["蝴蝶酥"],
                analysis_days=30,
                as_of=__import__("datetime").datetime(2026, 7, 24, tzinfo=__import__("datetime").timezone.utc),
                limit=20,
            )
            self.assertEqual({item.note_id for item in results}, {"new-1", "new-2", "new-3"})
            self.assertLessEqual(sum(item.author_nickname == "作者甲" for item in results), 3)

    def test_search_returns_only_relevant_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            knowledge = KnowledgeBase(Path(directory) / "knowledge.db")
            knowledge.import_notes([sample_note()])
            self.assertEqual(len(knowledge.search(["香港伴手礼"])), 1)
            self.assertEqual(
                len(knowledge.search(["食品饮料 / 休闲零食 / 香港伴手礼"])),
                1,
            )
            self.assertEqual(knowledge.search(["护肤精华"]), [])

    def test_search_expands_compound_category_phrases(self):
        from knowledge_base import expand_search_terms

        terms = expand_search_terms(["香港蝴蝶酥伴手礼"])
        self.assertIn("蝴蝶酥", terms)
        self.assertIn("伴手礼", terms)
        with tempfile.TemporaryDirectory() as directory:
            knowledge = KnowledgeBase(Path(directory) / "knowledge.db")
            knowledge.import_notes([
                sample_note(
                    note_id="hit",
                    title="香港必买蝴蝶酥伴手礼清单",
                )
            ])
            hits = knowledge.search(["香港蝴蝶酥伴手礼"], analysis_days=None, limit=20)
            self.assertEqual([item.note_id for item in hits], ["hit"])

    def test_competitor_identification_requires_two_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            knowledge = KnowledgeBase(Path(directory) / "knowledge.db")
            knowledge.import_notes([
                sample_note(
                    note_id="note-1",
                    title="蝴蝶酥三强实测",
                    description="奇华与自有品牌横评",
                    author="作者甲",
                ),
                sample_note(
                    note_id="note-2",
                    title="香港伴手礼推荐",
                    description="奇华适合送长辈",
                    author="作者乙",
                ),
            ])
            result = knowledge.identify_competitors(
                own_brand="自有品牌",
                candidate_names=["奇华", "帝苑"],
                category_terms=["香港伴手礼", "蝴蝶酥"],
            )
            by_name = {item["candidate_name"]: item for item in result}
            self.assertEqual(by_name["奇华"]["classification"], "可能竞品")
            self.assertEqual(by_name["奇华"]["mention_note_count"], 2)
            self.assertEqual(by_name["帝苑"]["classification"], "证据不足")

    def test_import_and_match_targeting_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            knowledge = KnowledgeBase(Path(directory) / "knowledge.db")
            catalog_path = (
                Path(__file__).resolve().parents[1]
                / "examples"
                / "knowledge"
                / "juguang_targeting_catalog.json"
            )
            payload = json.loads(catalog_path.read_text(encoding="utf-8"))
            result = knowledge.import_targeting_catalog(payload)
            self.assertEqual(result["catalog_id"], "juguang_targeting_catalog")
            self.assertGreaterEqual(result["playbook_count"], 1)
            self.assertEqual(knowledge.status()["total_targeting_catalogs"], 1)

            matched = knowledge.match_targeting_playbooks(
                category="香港蝴蝶酥伴手礼",
                product_name="经典－原味蝴蝶酥礼盒",
                initial_audience="到港游客送礼",
                selling_points=["适合作为香港伴手礼"],
            )
            self.assertTrue(matched)
            self.assertEqual(matched[0]["playbook_id"], "hk_bakery_souvenir")

            brief = knowledge.targeting_brief_for_campaign(
                category="香港蝴蝶酥伴手礼",
                product_name="经典－原味蝴蝶酥礼盒",
                initial_audience="到港游客送礼",
                selling_points=["牛油香浓"],
            )
            self.assertIsNotNone(brief)
            assert brief is not None
            self.assertIn("须在聚光后台核对可用性", brief)
            self.assertIn("食品饮料", brief)
            self.assertIn("兴趣标签候选", brief)

            pack = knowledge.targeting_pack_for_campaign(
                category="香港蝴蝶酥伴手礼",
                product_name="经典－原味蝴蝶酥礼盒",
                initial_audience="到港游客送礼",
                selling_points=["牛油香浓"],
            )
            self.assertIsNotNone(pack)
            assert pack is not None
            self.assertEqual(pack["playbook_id"], "hk_bakery_souvenir")
            tags = pack["targeting_tags"]
            self.assertTrue(tags["interest_tags"])
            self.assertTrue(tags["behavior_tags"])
            self.assertTrue(tags["crowd_packages"])
            self.assertTrue(pack["persona"]["demographic"])


if __name__ == "__main__":
    unittest.main()
