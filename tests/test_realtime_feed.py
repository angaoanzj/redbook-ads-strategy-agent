"""合规实时数据源接入层测试：不依赖网络与模型 Key，不 import engine/main。

覆盖：
- 同 seed 的批次序列可复现、批次内容随批次单调演化（热度只升不降）；
- 条目与 models 的证据契约兼容（TrendKeywordEvidence / CompetitorEvidence / MetricEvidence）；
- FeedStore 用 tmp 路径存取与 status()；
- merge_feed_into_request 的去重、is_mock/evidence_grade 标记、limit 生效、空 store no-op。
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from models import CompetitorEvidence, MetricEvidence, TrendKeywordEvidence
from realtime_feed import (
    MOCK_EVIDENCE_GRADE,
    MOCK_FEED_SOURCE_NAME,
    MOCK_SOURCE_PREFIX,
    FeedAdapter,
    FeedBatch,
    FeedStore,
    MockRealtimeFeedAdapter,
    _competitor_event_to_evidence,
    feed_merge_counts,
    merge_feed_into_request,
)

CATEGORY = "香港蝴蝶酥伴手礼"
BRAND = "曲奇四重奏"
PRODUCT = "经典－原味蝴蝶酥礼盒"


def make_adapter(seed: str = "bench-seed") -> MockRealtimeFeedAdapter:
    return MockRealtimeFeedAdapter(seed, CATEGORY, BRAND, product_name=PRODUCT)


def strip_timestamps(batch: FeedBatch) -> dict:
    """去掉墙钟时间字段，只比较可复现内容。"""
    payload = batch.model_dump(mode="json")
    payload.pop("generated_at", None)
    for item in payload["trending"]:
        item.pop("collected_at", None)
    for item in payload["competitor_events"]:
        item.pop("observed_at", None)
    for item in payload["benchmark_drift"]:
        item.pop("collected_at", None)
    return payload


class TempStoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "realtime_feed.db"
        self.store = FeedStore(self.db_path)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
class MockAdapterTest(unittest.TestCase):
    def test_satisfies_feed_adapter_protocol(self) -> None:
        self.assertIsInstance(make_adapter(), FeedAdapter)

    def test_same_seed_reproduces_batch_sequence(self) -> None:
        left, right = make_adapter("seed-a"), make_adapter("seed-a")
        first = [strip_timestamps(left.pull()) for _ in range(3)]
        second = [strip_timestamps(right.pull()) for _ in range(3)]
        self.assertEqual(first, second)

    def test_different_seed_diverges(self) -> None:
        left = strip_timestamps(make_adapter("seed-a").pull())
        right = strip_timestamps(make_adapter("seed-b").pull())
        self.assertNotEqual(left, right)

    def test_batch_index_increments_and_is_encoded_in_id(self) -> None:
        adapter = make_adapter()
        batches = [adapter.pull() for _ in range(3)]
        self.assertEqual([batch.batch_index for batch in batches], [1, 2, 3])
        self.assertEqual(batches[0].batch_id, "feed-bench-seed-0001")
        self.assertEqual(batches[2].batch_id, "feed-bench-seed-0003")

    def test_batch_shape_within_declared_bounds(self) -> None:
        adapter = make_adapter()
        for _ in range(8):
            batch = adapter.pull()
            with self.subTest(batch=batch.batch_id):
                self.assertTrue(2 <= len(batch.trending) <= 4)
                self.assertTrue(0 <= len(batch.competitor_events) <= 2)
                self.assertTrue(0 <= len(batch.benchmark_drift) <= 1)
                accounts = [event.account_name for event in batch.competitor_events]
                self.assertEqual(len(accounts), len(set(accounts)), "同批次竞品账号不应重复")

    def test_heat_score_evolves_monotonically_per_keyword(self) -> None:
        adapter = make_adapter()
        seen: dict[str, float] = {}
        compared = 0
        for _ in range(10):
            batch = adapter.pull()
            for item in batch.trending:
                if item.keyword in seen:
                    compared += 1
                    self.assertGreaterEqual(item.heat_score, seen[item.keyword])
                seen[item.keyword] = item.heat_score
        self.assertGreater(compared, 0, "十批之内应至少出现一次同词复现以验证单调性")

    def test_all_items_carry_mock_flags_and_source_prefix(self) -> None:
        adapter = make_adapter()
        for _ in range(5):
            batch = adapter.pull()
            self.assertTrue(batch.is_mock)
            self.assertEqual(batch.source_name, MOCK_FEED_SOURCE_NAME)
            self.assertTrue(batch.source_name.startswith(MOCK_SOURCE_PREFIX))
            rows = [*batch.trending, *batch.competitor_events, *batch.benchmark_drift]
            for row in rows:
                self.assertTrue(row.is_mock)
                self.assertEqual(row.evidence_grade, MOCK_EVIDENCE_GRADE)
                self.assertTrue(row.source_name.startswith(MOCK_SOURCE_PREFIX))
                self.assertEqual(row.mock_seed, adapter.seed)

    def test_benchmark_drift_within_ten_percent(self) -> None:
        adapter = MockRealtimeFeedAdapter(
            "drift-seed", CATEGORY, BRAND, baseline_cpc_cny=0.30
        )
        seen = 0
        for _ in range(20):
            for row in adapter.pull().benchmark_drift:
                seen += 1
                self.assertEqual(row.metric_name, "cpc")
                self.assertTrue(0.30 * 0.9 <= row.value <= 0.30 * 1.1, row.value)
        self.assertGreater(seen, 0, "20 批之内应至少出现一次基准漂移")

    def test_items_are_compatible_with_evidence_contracts(self) -> None:
        adapter = make_adapter()
        for _ in range(6):
            batch = adapter.pull()
            for item in batch.trending:
                TrendKeywordEvidence.model_validate(item.model_dump(mode="json"))
            for event in batch.competitor_events:
                CompetitorEvidence.model_validate(
                    _competitor_event_to_evidence(event.model_dump(mode="json"))
                )
            for row in batch.benchmark_drift:
                MetricEvidence.model_validate(row.model_dump(mode="json"))

    def test_since_ts_is_recorded_on_batch(self) -> None:
        batch = make_adapter().pull(since_ts=1_700_000_000.0)
        self.assertEqual(batch.since_ts, 1_700_000_000.0)


# ---------------------------------------------------------------------------
# FeedStore
# ---------------------------------------------------------------------------
class FeedStoreTest(TempStoreCase):
    def test_empty_status(self) -> None:
        status = self.store.status()
        self.assertEqual(status["batch_count"], 0)
        self.assertEqual(status["item_total"], 0)
        self.assertIsNone(status["latest_generated_at"])
        self.assertEqual(status["db_path"], str(self.db_path))

    def test_save_and_read_back(self) -> None:
        adapter = make_adapter()
        batches = [adapter.pull() for _ in range(3)]
        summaries = [self.store.save_batch(batch) for batch in batches]
        self.assertEqual([row["batch_index"] for row in summaries], [1, 2, 3])

        status = self.store.status()
        self.assertEqual(status["batch_count"], 3)
        expected_items = sum(sum(batch.item_counts().values()) for batch in batches)
        self.assertEqual(status["item_total"], expected_items)
        self.assertEqual(
            status["item_counts"]["trending"],
            sum(len(batch.trending) for batch in batches),
        )
        self.assertEqual(status["latest_generated_at"], batches[-1].generated_at)

        latest = self.store.latest_batches(2)
        self.assertEqual(len(latest), 2)
        self.assertEqual(latest[0]["batch_id"], batches[-1].batch_id)

    def test_latest_evidence_returns_newest_first_and_respects_limit(self) -> None:
        adapter = make_adapter()
        for _ in range(4):
            self.store.save_batch(adapter.pull())
        rows = self.store.latest_evidence("trending", limit=3)
        self.assertEqual(len(rows), 3)
        newest_batch = self.store.latest_batches(1)[0]
        self.assertIn(rows[0]["keyword"], [item["keyword"] for item in newest_batch["trending"]])
        self.assertEqual(self.store.latest_evidence("trending", limit=0), [])

    def test_latest_evidence_rejects_unknown_kind(self) -> None:
        with self.assertRaises(ValueError):
            self.store.latest_evidence("unknown_kind", limit=1)

    def test_last_batch_index_and_resume_from_store(self) -> None:
        """无状态调用方（/feeds/pull 每次新建 adapter）必须能续号，否则批次互相覆盖。"""
        self.assertEqual(self.store.last_batch_index("resume-seed"), 0)
        self.assertEqual(self.store.last_batch_index(None), 0)

        ids: list[str] = []
        for _ in range(3):
            adapter = MockRealtimeFeedAdapter("resume-seed", CATEGORY, BRAND)
            adapter.resume_from(self.store)
            batch = adapter.pull()
            self.store.save_batch(batch)
            ids.append(batch.batch_id)

        self.assertEqual(len(set(ids)), 3, "同 seed 的连续拉取必须落成三个不同批次")
        self.assertEqual(self.store.last_batch_index("resume-seed"), 3)
        self.assertEqual(self.store.status()["batch_count"], 3)

    def test_start_index_offsets_batch_numbering(self) -> None:
        adapter = MockRealtimeFeedAdapter("offset-seed", CATEGORY, BRAND, start_index=5)
        batch = adapter.pull()
        self.assertEqual(batch.batch_index, 6)
        self.assertEqual(batch.batch_id, "feed-offset-seed-0006")
        self.assertEqual(batch.seed, "offset-seed")

    def test_resaving_same_batch_is_idempotent(self) -> None:
        batch = make_adapter().pull()
        self.store.save_batch(batch)
        self.store.save_batch(batch)
        status = self.store.status()
        self.assertEqual(status["batch_count"], 1)
        self.assertEqual(status["item_total"], sum(batch.item_counts().values()))

    def test_env_override_is_used_when_no_path_given(self) -> None:
        import os

        target = Path(self._tmp.name) / "from_env.db"
        original = os.environ.get("XHS_FEED_DB")
        os.environ["XHS_FEED_DB"] = str(target)
        try:
            store = FeedStore()
            self.assertEqual(store.db_path, str(target))
            self.assertTrue(target.exists())
        finally:
            if original is None:
                os.environ.pop("XHS_FEED_DB", None)
            else:
                os.environ["XHS_FEED_DB"] = original


class LatestTrendingWithPreviousTest(TempStoreCase):
    """跨批对比查询：同词取最近两批热度，供模块 6 算 rising/cooling 趋势。"""

    def test_empty_store_returns_empty_list(self) -> None:
        self.assertEqual(self.store.latest_trending_with_previous(limit=5), [])

    def test_previous_heat_is_none_on_single_batch(self) -> None:
        adapter = make_adapter("single-batch")
        batch = adapter.pull()
        self.store.save_batch(batch)
        rows = self.store.latest_trending_with_previous(limit=10)
        self.assertEqual(len(rows), len(batch.trending))
        for row in rows:
            with self.subTest(keyword=row["keyword"]):
                self.assertIsNone(row["previous_heat"], "只有一批时不存在上批热度")
                self.assertEqual(row["batch_index"], 1)
                self.assertIs(row["is_mock"], True)
                self.assertTrue(row["source_name"].startswith(MOCK_SOURCE_PREFIX))

    def test_previous_heat_comes_from_earlier_batch(self) -> None:
        adapter = make_adapter("cross-batch")
        batches = [adapter.pull() for _ in range(6)]
        for batch in batches:
            self.store.save_batch(batch)

        # 期望值：按批次倒序，每个词最近两次出现的热度
        seen: dict[str, list[float]] = {}
        for batch in reversed(batches):
            for item in batch.trending:
                seen.setdefault(item.keyword, []).append(item.heat_score)

        rows = self.store.latest_trending_with_previous(limit=20)
        self.assertTrue(rows)
        compared = 0
        for row in rows:
            history = seen[row["keyword"]]
            with self.subTest(keyword=row["keyword"]):
                self.assertEqual(row["heat_score"], history[0])
                if len(history) > 1:
                    compared += 1
                    self.assertEqual(row["previous_heat"], history[1])
                    # mock 源热度随批次单调升温，跨批对比必须体现为不降
                    self.assertGreaterEqual(row["heat_score"], row["previous_heat"])
                else:
                    self.assertIsNone(row["previous_heat"])
        self.assertGreater(compared, 0, "六批之内应至少有一个词出现两次以供跨批对比")

    def test_keywords_are_deduplicated_and_limit_applies(self) -> None:
        adapter = make_adapter("limit-seed")
        for _ in range(8):
            self.store.save_batch(adapter.pull())
        rows = self.store.latest_trending_with_previous(limit=3)
        self.assertEqual(len(rows), 3)
        keywords = [row["keyword"] for row in rows]
        self.assertEqual(len(keywords), len(set(keywords)), "同词只返回一行")
        self.assertEqual(self.store.latest_trending_with_previous(limit=0), [])

    def test_rows_carry_full_contract(self) -> None:
        adapter = make_adapter("contract-seed")
        for _ in range(3):
            self.store.save_batch(adapter.pull())
        for row in self.store.latest_trending_with_previous(limit=5):
            self.assertEqual(
                set(row),
                {"keyword", "heat_score", "previous_heat", "source_name", "is_mock", "batch_index"},
            )


# ---------------------------------------------------------------------------
# merge_feed_into_request
# ---------------------------------------------------------------------------
class MergeFeedTest(TempStoreCase):
    def fill(self, batches: int = 4, seed: str = "merge-seed") -> None:
        adapter = MockRealtimeFeedAdapter(seed, CATEGORY, BRAND, product_name=PRODUCT)
        for _ in range(batches):
            self.store.save_batch(adapter.pull())

    def test_empty_store_is_noop(self) -> None:
        req = {
            "brand_name": BRAND,
            "trending_keyword_evidence": [{"keyword": "香港伴手礼", "source_name": "人工粘贴热搜词"}],
            "competitor_evidence": [],
        }
        merged = merge_feed_into_request(copy.deepcopy(req), self.store)
        self.assertEqual(merged, req)
        self.assertEqual(
            feed_merge_counts(req, merged), {"merged_trending": 0, "merged_competitors": 0}
        )

    def test_does_not_mutate_input(self) -> None:
        self.fill()
        req = {"trending_keyword_evidence": [], "competitor_evidence": []}
        snapshot = copy.deepcopy(req)
        merge_feed_into_request(req, self.store)
        self.assertEqual(req, snapshot)

    def test_merged_items_are_marked_mock_and_graded_m(self) -> None:
        self.fill()
        merged = merge_feed_into_request({}, self.store)
        trending = merged["trending_keyword_evidence"]
        self.assertTrue(trending)
        for row in trending:
            self.assertIs(row["is_mock"], True)
            self.assertEqual(row["evidence_grade"], MOCK_EVIDENCE_GRADE)
            self.assertTrue(row["source_name"].startswith(MOCK_SOURCE_PREFIX))
            TrendKeywordEvidence.model_validate(row)
        for row in merged.get("competitor_evidence", []):
            self.assertIs(row["is_mock"], True)
            self.assertEqual(row["evidence_grade"], MOCK_EVIDENCE_GRADE)
            CompetitorEvidence.model_validate(row)

    def test_trending_limit_is_respected(self) -> None:
        self.fill(batches=6)
        merged = merge_feed_into_request({}, self.store, trending_limit=2)
        self.assertEqual(len(merged["trending_keyword_evidence"]), 2)
        merged_zero = merge_feed_into_request({}, self.store, trending_limit=0)
        self.assertNotIn("trending_keyword_evidence", merged_zero)

    def test_competitor_limit_is_respected(self) -> None:
        self.fill(batches=8)
        merged = merge_feed_into_request({}, self.store, competitor_limit=1)
        self.assertEqual(len(merged["competitor_evidence"]), 1)
        merged_zero = merge_feed_into_request({}, self.store, competitor_limit=0)
        self.assertNotIn("competitor_evidence", merged_zero)

    def test_existing_keyword_is_not_overwritten(self) -> None:
        self.fill()
        existing_keyword = self.store.latest_evidence("trending", 1)[0]["keyword"]
        req = {
            "trending_keyword_evidence": [{
                "keyword": existing_keyword,
                "source_name": "人工粘贴热搜词",
                "collected_at": "2026-07-24",
                "is_mock": False,
                "evidence_grade": "C_manual_paste",
            }]
        }
        merged = merge_feed_into_request(req, self.store)
        rows = merged["trending_keyword_evidence"]
        same_keyword = [row for row in rows if row["keyword"] == existing_keyword]
        self.assertEqual(len(same_keyword), 1, "同名词不得重复写入")
        self.assertEqual(same_keyword[0]["source_name"], "人工粘贴热搜词")
        self.assertIs(same_keyword[0]["is_mock"], False, "真实证据不得被 mock 覆盖")

    def test_existing_competitor_is_not_overwritten(self) -> None:
        self.fill(batches=8)
        account = self.store.latest_evidence("competitor_event", 1)[0]["account_name"]
        req = {
            "competitor_evidence": [{
                "account_name": account,
                "profile_or_note_url": "https://www.xiaohongshu.com/real",
                "is_mock": False,
                "evidence_grade": "B_public_observation",
            }]
        }
        merged = merge_feed_into_request(req, self.store)
        matches = [
            row for row in merged["competitor_evidence"] if row["account_name"] == account
        ]
        self.assertEqual(len(matches), 1)
        self.assertIs(matches[0]["is_mock"], False)

    def test_merged_output_is_deduplicated_within_feed(self) -> None:
        self.fill(batches=10)
        merged = merge_feed_into_request({}, self.store, trending_limit=6, competitor_limit=4)
        keywords = [row["keyword"] for row in merged["trending_keyword_evidence"]]
        self.assertEqual(len(keywords), len(set(keywords)))
        accounts = [row["account_name"] for row in merged.get("competitor_evidence", [])]
        self.assertEqual(len(accounts), len(set(accounts)))

    def test_merge_counts_helper(self) -> None:
        self.fill(batches=6)
        req = {"trending_keyword_evidence": [], "competitor_evidence": []}
        merged = merge_feed_into_request(req, self.store, trending_limit=3, competitor_limit=2)
        counts = feed_merge_counts(req, merged)
        self.assertEqual(counts["merged_trending"], 3)
        self.assertEqual(counts["merged_competitors"], 2)


if __name__ == "__main__":
    unittest.main()
