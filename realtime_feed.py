"""合规实时数据源接入层（当前实现：模拟实时数据源，接口与真实源同构）。

设计原则（对齐 docs/OPTIMIZATION_ROADMAP.md 第 1 节）：

1. **接口先行**：`FeedAdapter` 协议只有一个方法 `pull(since_ts) -> FeedBatch`。
   未来接官方开放数据 / 品牌授权第三方 API 时，只需要新写一个实现该协议的
   adapter（如 `OfficialTrendFeedAdapter`），`FeedStore` / `merge_feed_into_request`
   与 main.py 的接线一行都不用改。
2. **红线**：mock 数据一律带 `is_mock=True` 与「模拟实时数据源」source 前缀，
   证据等级固定 `M`，绝不混进 A/B/C 真实证据等级；报告与模块 prompt 因此可以
   如实区分「实时热搜（模拟源）」与真实合规源。
3. **可复现**：同一 seed 的批次序列可复现，热度值随批次单调演化（模拟热搜升温），
   便于演示与回归。

本文件只依赖 pydantic / mock_scenarios（复用 normalize_mock_seed、rng_for），
绝不 import engine / main / report_view。
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from mock_scenarios import normalize_mock_seed, rng_for

# ---------------------------------------------------------------------------
# 常量：mock 源标识（真实源接入后换成官方源名，前缀判断也随之失效 → 自然降级）
# ---------------------------------------------------------------------------
MOCK_SOURCE_PREFIX = "模拟实时数据源"
MOCK_FEED_SOURCE_NAME = "模拟实时数据源（合规同构接口演示）"
MOCK_EVIDENCE_GRADE = "M"

DEFAULT_FEED_DB_PATH = str(Path(__file__).resolve().parent / "data" / "realtime_feed.db")

# 热度演化参数：base 由 seed×关键词派生，每批 +3，封顶 99（保证单调不降）
_BASE_HEAT_RANGE = (40.0, 75.0)
_HEAT_STEP = 3.0
_HEAT_CAP = 99.0

# 竞品事件与基准漂移
_COMPETITOR_POOL = ("模拟竞品 A", "模拟竞品 B", "模拟竞品 C")
_NOTE_FORMATS = ("图集测评", "短视频开箱", "场景种草", "横向对比")
_DRIFT_PROBABILITY = 0.4
_DRIFT_BAND = (0.90, 1.10)  # cpc ±10% 以内
_DEFAULT_BASELINE_CPC_CNY = 0.30


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 批次数据契约
# ---------------------------------------------------------------------------
class FeedTrendingItem(BaseModel):
    """与 models.TrendKeywordEvidence 字段兼容（可直接 model_validate）。"""

    keyword: str
    source_name: str = MOCK_FEED_SOURCE_NAME
    collected_at: str
    heat_score: float | None = Field(default=None, ge=0)
    notes: str | None = None
    is_mock: bool = True
    evidence_grade: str = MOCK_EVIDENCE_GRADE
    mock_seed: str | None = None


class FeedCompetitorEvent(BaseModel):
    """竞品变动事件；字段是 models.CompetitorEvidence 的超集，便于无损转换。"""

    account_name: str
    event_type: Literal["new_ad_note", "volume_spike"]
    note_format: str
    observed_at: str
    note: str
    profile_or_note_url: str
    interactions: int | None = Field(default=None, ge=0)
    is_ad_labeled: bool | None = None
    source_name: str = MOCK_FEED_SOURCE_NAME
    is_mock: bool = True
    evidence_grade: str = MOCK_EVIDENCE_GRADE
    mock_seed: str | None = None


class FeedBenchmarkDrift(BaseModel):
    """基准指标漂移；字段与 models.MetricEvidence 兼容。"""

    metric_name: str
    value: float
    unit: str
    collected_at: str
    source_name: str = MOCK_FEED_SOURCE_NAME
    notes: str | None = None
    is_mock: bool = True
    evidence_grade: str = MOCK_EVIDENCE_GRADE
    mock_seed: str | None = None


class FeedBatch(BaseModel):
    batch_id: str
    batch_index: int = Field(ge=1, description="同一 seed 下的批次序号，从 1 开始")
    seed: str | None = None
    generated_at: str
    source_name: str = MOCK_FEED_SOURCE_NAME
    is_mock: bool = True
    since_ts: float | None = None
    trending: list[FeedTrendingItem] = Field(default_factory=list)
    competitor_events: list[FeedCompetitorEvent] = Field(default_factory=list)
    benchmark_drift: list[FeedBenchmarkDrift] = Field(default_factory=list)

    def item_counts(self) -> dict[str, int]:
        return {
            "trending": len(self.trending),
            "competitor_event": len(self.competitor_events),
            "benchmark_drift": len(self.benchmark_drift),
        }

    def summary(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "batch_index": self.batch_index,
            "seed": self.seed,
            "generated_at": self.generated_at,
            "source_name": self.source_name,
            "is_mock": self.is_mock,
            "counts": self.item_counts(),
            "trending_keywords": [item.keyword for item in self.trending],
            "competitor_accounts": [event.account_name for event in self.competitor_events],
        }


@runtime_checkable
class FeedAdapter(Protocol):
    """实时数据源适配器协议：换真实源只换实现，不动下游。"""

    def pull(self, since_ts: float | None = None) -> FeedBatch:
        """拉取自 since_ts（UTC epoch 秒）以来的增量批次；None 表示全量最新窗口。"""


# ---------------------------------------------------------------------------
# Mock adapter
# ---------------------------------------------------------------------------
def _keyword_pool(category: str, brand: str, product_name: str) -> list[str]:
    """候选上升词池：风格对齐 mock_scenarios.build_mock_trending。"""
    category = (category or "品类").strip() or "品类"
    brand = (brand or "").strip()
    product = (product_name or "").strip() or category
    pool = [
        f"{category}推荐",
        f"{category}测评",
        f"{category}怎么选",
        f"{category}送长辈",
        f"{product}平替",
        f"{product}回购",
        "节日礼盒推荐",
        "伴手礼清单",
    ]
    if brand:
        pool.append(f"{brand}好吃吗")
    # 去重保序
    return list(dict.fromkeys(pool))


def _base_heat(seed: str, keyword: str) -> float:
    rng = rng_for(f"{seed}|{keyword}", "realtime_feed_base")
    return round(rng.uniform(*_BASE_HEAT_RANGE), 1)


def _heat_for_batch(seed: str, keyword: str, batch_index: int) -> float:
    """热度随批次单调演化（同 seed 同关键词，后批不低于前批）。"""
    raw = _base_heat(seed, keyword) + _HEAT_STEP * (batch_index - 1)
    return round(min(_HEAT_CAP, raw), 1)


class MockRealtimeFeedAdapter:
    """模拟实时数据源：同 seed 可复现批次序列，热度随批次单调升温。

    与真实源的差别只有「数据从哪来」：本 adapter 用 seed 派生的可复现随机数生成，
    所有条目强制 is_mock=True / evidence_grade="M" / source_name 带
    「模拟实时数据源」前缀，禁止被当作真实证据使用。
    """

    def __init__(
        self,
        seed: str | None = None,
        category: str = "",
        brand: str = "",
        *,
        product_name: str = "",
        baseline_cpc_cny: float = _DEFAULT_BASELINE_CPC_CNY,
        source_name: str = MOCK_FEED_SOURCE_NAME,
        start_index: int = 0,
    ) -> None:
        self.seed = normalize_mock_seed(seed)
        self.category = category
        self.brand = brand
        self.product_name = product_name
        self.baseline_cpc_cny = baseline_cpc_cny
        self.source_name = source_name
        self._batch_index = max(0, int(start_index))
        self._pool = _keyword_pool(category, brand, product_name)

    def resume_from(self, store: "FeedStore") -> int:
        """从 store 里已有的同 seed 批次续号。

        无状态调用方（如 HTTP 的 /feeds/pull 每次都新建 adapter）必须先调它，
        否则同一个 seed 会永远停在第 1 批、互相覆盖。返回续号后的当前批次号。
        """
        self._batch_index = max(self._batch_index, store.last_batch_index(self.seed))
        return self._batch_index

    # -- 内部：单批生成 ----------------------------------------------------
    def _build_trending(self, batch_index: int, collected_at: str) -> list[FeedTrendingItem]:
        rng = rng_for(f"{self.seed}#{batch_index}", "realtime_feed_trending")
        count = rng.randint(2, min(4, len(self._pool)))
        keywords = rng.sample(self._pool, k=count)
        return [
            FeedTrendingItem(
                keyword=keyword,
                source_name=self.source_name,
                collected_at=collected_at,
                heat_score=_heat_for_batch(self.seed, keyword, batch_index),
                notes=(
                    f"模拟实时热搜第 {batch_index} 批：热度为可复现演化值，"
                    "非平台真实热搜榜，禁止当作真实趋势结论"
                ),
                is_mock=True,
                evidence_grade=MOCK_EVIDENCE_GRADE,
                mock_seed=self.seed,
            )
            for keyword in keywords
        ]

    def _build_competitor_events(
        self, batch_index: int, observed_at: str
    ) -> list[FeedCompetitorEvent]:
        rng = rng_for(f"{self.seed}#{batch_index}", "realtime_feed_competitor")
        count = rng.randint(0, 2)
        # 同一批次内账号不重复（真实源同一账号的多条变动会先聚合再下发）
        accounts = rng.sample(_COMPETITOR_POOL, k=count) if count else []
        events: list[FeedCompetitorEvent] = []
        for index, account in enumerate(accounts):
            event_type: Literal["new_ad_note", "volume_spike"] = rng.choice(
                ["new_ad_note", "volume_spike"]
            )
            note_format = rng.choice(_NOTE_FORMATS)
            interactions = rng.randint(500, 30_000)
            events.append(FeedCompetitorEvent(
                account_name=account,
                event_type=event_type,
                note_format=note_format,
                observed_at=observed_at,
                note=(
                    "模拟实时竞品事件："
                    + ("新增带广告标识笔记" if event_type == "new_ad_note" else "互动量异动上扬")
                    + "；广告标识与投放时长仍需人工打开原笔记核验"
                ),
                profile_or_note_url=(
                    f"https://example.com/mock-feed/{self.seed}/{batch_index}/{index + 1}"
                ),
                interactions=interactions,
                is_ad_labeled=True if event_type == "new_ad_note" else None,
                source_name=self.source_name,
                is_mock=True,
                evidence_grade=MOCK_EVIDENCE_GRADE,
                mock_seed=self.seed,
            ))
        return events

    def _build_benchmark_drift(
        self, batch_index: int, collected_at: str
    ) -> list[FeedBenchmarkDrift]:
        rng = rng_for(f"{self.seed}#{batch_index}", "realtime_feed_drift")
        if rng.random() >= _DRIFT_PROBABILITY:
            return []
        factor = rng.uniform(*_DRIFT_BAND)
        return [FeedBenchmarkDrift(
            metric_name="cpc",
            value=round(self.baseline_cpc_cny * factor, 4),
            unit="CNY/click",
            collected_at=collected_at,
            source_name=self.source_name,
            notes=(
                f"模拟实时基准漂移：相对演示基准 {self.baseline_cpc_cny:g} 的 "
                f"×{factor:.3f}（±10% 以内），仅用于演示，不可替代账户真实数据"
            ),
            is_mock=True,
            evidence_grade=MOCK_EVIDENCE_GRADE,
            mock_seed=self.seed,
        )]

    # -- FeedAdapter 协议 --------------------------------------------------
    def pull(self, since_ts: float | None = None) -> FeedBatch:
        self._batch_index += 1
        index = self._batch_index
        now = utc_now_iso()
        return FeedBatch(
            batch_id=f"feed-{self.seed}-{index:04d}",
            batch_index=index,
            seed=self.seed,
            generated_at=now,
            source_name=self.source_name,
            is_mock=True,
            since_ts=since_ts,
            trending=self._build_trending(index, now),
            competitor_events=self._build_competitor_events(index, now),
            benchmark_drift=self._build_benchmark_drift(index, now),
        )


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------
_KINDS = ("trending", "competitor_event", "benchmark_drift")


class FeedStore:
    """SQLite 持久化批次与条目（每次操作一个短连接，FastAPI 线程池安全）。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        path = str(db_path or os.getenv("XHS_FEED_DB") or DEFAULT_FEED_DB_PATH)
        self.db_path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feed_batches (
                    batch_id TEXT PRIMARY KEY,
                    batch_index INTEGER NOT NULL,
                    seed TEXT,
                    generated_at TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    is_mock INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    stored_at TEXT NOT NULL
                )
                """
            )
            # 轻量迁移：早期库没有 seed 列时补上（本表在本次接入中新建，无历史数据风险）
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(feed_batches)").fetchall()
            }
            if "seed" not in columns:
                conn.execute("ALTER TABLE feed_batches ADD COLUMN seed TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feed_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    source_name TEXT NOT NULL,
                    is_mock INTEGER NOT NULL,
                    collected_at TEXT,
                    payload TEXT NOT NULL,
                    stored_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_feed_items_kind ON feed_items(kind, id DESC)"
            )

    # -- 写 ---------------------------------------------------------------
    def save_batch(self, batch: FeedBatch) -> dict[str, Any]:
        stored_at = utc_now_iso()
        rows: list[tuple[Any, ...]] = []
        groups: Iterable[tuple[str, list[Any]]] = (
            ("trending", list(batch.trending)),
            ("competitor_event", list(batch.competitor_events)),
            ("benchmark_drift", list(batch.benchmark_drift)),
        )
        for kind, items in groups:
            for ordinal, item in enumerate(items, start=1):
                payload = item.model_dump(mode="json")
                rows.append((
                    batch.batch_id,
                    kind,
                    ordinal,
                    payload.get("source_name") or batch.source_name,
                    1 if payload.get("is_mock", True) else 0,
                    payload.get("collected_at") or payload.get("observed_at"),
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    stored_at,
                ))
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO feed_batches"
                " (batch_id, batch_index, seed, generated_at, source_name, is_mock, payload,"
                "  stored_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch.batch_id,
                    batch.batch_index,
                    batch.seed,
                    batch.generated_at,
                    batch.source_name,
                    1 if batch.is_mock else 0,
                    json.dumps(batch.model_dump(mode="json"), ensure_ascii=False, sort_keys=True),
                    stored_at,
                ),
            )
            conn.execute("DELETE FROM feed_items WHERE batch_id = ?", (batch.batch_id,))
            conn.executemany(
                "INSERT INTO feed_items"
                " (batch_id, kind, ordinal, source_name, is_mock, collected_at, payload, stored_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        summary = batch.summary()
        summary["stored_at"] = stored_at
        return summary

    # -- 读 ---------------------------------------------------------------
    def last_batch_index(self, seed: str | None) -> int:
        """某 seed 已落库的最大批次号（无记录返回 0），供无状态调用方续号。"""
        if not seed:
            return 0
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT MAX(batch_index) AS m FROM feed_batches WHERE seed = ?", (seed,)
            ).fetchone()
        return int(row["m"] or 0)

    def latest_batches(self, limit: int = 5) -> list[dict[str, Any]]:
        limit = max(1, int(limit))
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "SELECT payload FROM feed_batches ORDER BY generated_at DESC, rowid DESC LIMIT ?",
                (limit,),
            )
            return [json.loads(row["payload"]) for row in cursor.fetchall()]

    def latest_evidence(self, kind: str, limit: int = 10) -> list[dict[str, Any]]:
        """按写入倒序返回某类条目的原始 payload（最新批次在前）。"""
        if kind not in _KINDS:
            raise ValueError(f"未知条目类型 {kind!r}，允许：{'、'.join(_KINDS)}")
        limit = max(0, int(limit))
        if limit == 0:
            return []
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "SELECT payload FROM feed_items WHERE kind = ? ORDER BY id DESC LIMIT ?",
                (kind, limit),
            )
            return [json.loads(row["payload"]) for row in cursor.fetchall()]

    def latest_trending_with_previous(self, limit: int = 8) -> list[dict[str, Any]]:
        """最近出现的热搜词 + 同词上一批热度（供下游算 rising/cooling 趋势）。

        实现方式是**纯查询**（feed_items × feed_batches 左连接后在内存里按词分组），
        不改表结构、不需要迁移：老库直接可用；孤儿条目（批次行缺失）也能返回，
        只是 batch_index 记 0。

        返回按「最近一次出现」倒序的至多 limit 个**不同词**：
        `{keyword, heat_score, previous_heat|None, source_name, is_mock, batch_index}`。
        previous_heat 取该词上一次出现（不同批次）的热度，只出现过一批时为 None。
        """
        limit = max(0, int(limit))
        if limit == 0:
            return []
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT i.payload AS payload, i.id AS item_id,"
                "       COALESCE(b.batch_index, 0) AS batch_index,"
                "       COALESCE(b.generated_at, '') AS generated_at"
                " FROM feed_items AS i"
                " LEFT JOIN feed_batches AS b ON b.batch_id = i.batch_id"
                " WHERE i.kind = 'trending'"
                " ORDER BY generated_at DESC, batch_index DESC, i.id DESC"
            ).fetchall()

        grouped: dict[str, list[tuple[dict[str, Any], int]]] = {}
        order: list[str] = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, ValueError):
                continue
            keyword = str(payload.get("keyword") or "").strip()
            if not keyword:
                continue
            key = keyword.casefold()
            bucket = grouped.get(key)
            if bucket is None:
                bucket = grouped[key] = []
                order.append(key)
            if len(bucket) >= 2:
                continue
            batch_index = int(row["batch_index"] or 0)
            # 同一批次内的重复词不算「上一批」，跳过
            if bucket and bucket[0][1] == batch_index:
                continue
            bucket.append((payload, batch_index))

        results: list[dict[str, Any]] = []
        for key in order[:limit]:
            bucket = grouped[key]
            latest, batch_index = bucket[0]
            previous_heat = bucket[1][0].get("heat_score") if len(bucket) > 1 else None
            results.append({
                "keyword": latest.get("keyword", ""),
                "heat_score": latest.get("heat_score"),
                "previous_heat": previous_heat,
                "source_name": latest.get("source_name") or MOCK_FEED_SOURCE_NAME,
                "is_mock": bool(latest.get("is_mock", True)),
                "batch_index": batch_index,
            })
        return results

    def status(self) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            batch_count = conn.execute("SELECT COUNT(*) AS c FROM feed_batches").fetchone()["c"]
            latest = conn.execute(
                "SELECT generated_at FROM feed_batches ORDER BY generated_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
            item_rows = conn.execute(
                "SELECT kind, COUNT(*) AS c FROM feed_items GROUP BY kind"
            ).fetchall()
        counts = {kind: 0 for kind in _KINDS}
        for row in item_rows:
            counts[row["kind"]] = row["c"]
        return {
            "db_path": self.db_path,
            "batch_count": batch_count,
            "item_counts": counts,
            "item_total": sum(counts.values()),
            "latest_generated_at": latest["generated_at"] if latest else None,
            "source_policy": (
                "当前仅接入模拟实时数据源；全部条目 is_mock=true、evidence_grade=M，"
                "不参与真实证据等级判定"
            ),
        }


# ---------------------------------------------------------------------------
# 合并进请求（纯函数：dict 进 dict 出，便于沙盒测试）
# ---------------------------------------------------------------------------
def _competitor_event_to_evidence(event: dict[str, Any]) -> dict[str, Any]:
    """把竞品事件转成 models.CompetitorEvidence 兼容 dict。"""
    return {
        "account_name": event.get("account_name", ""),
        "profile_or_note_url": event.get("profile_or_note_url", ""),
        "note_format": event.get("note_format"),
        "interactions": event.get("interactions"),
        "is_ad_labeled": event.get("is_ad_labeled"),
        "observed_audience": [],
        "notes": event.get("note"),
        "source_name": event.get("source_name") or MOCK_FEED_SOURCE_NAME,
        "collected_at": event.get("observed_at"),
        "is_mock": True,
        "evidence_grade": MOCK_EVIDENCE_GRADE,
        "mock_seed": event.get("mock_seed"),
    }


def _trending_to_evidence(item: dict[str, Any]) -> dict[str, Any]:
    """把热搜条目转成 models.TrendKeywordEvidence 兼容 dict。"""
    return {
        "keyword": item.get("keyword", ""),
        "source_name": item.get("source_name") or MOCK_FEED_SOURCE_NAME,
        "collected_at": item.get("collected_at", ""),
        "heat_score": item.get("heat_score"),
        "notes": item.get("notes"),
        "is_mock": True,
        "evidence_grade": MOCK_EVIDENCE_GRADE,
        "mock_seed": item.get("mock_seed"),
    }


def merge_feed_into_request(
    req_dict: dict[str, Any],
    store: FeedStore,
    *,
    trending_limit: int = 6,
    competitor_limit: int = 4,
) -> dict[str, Any]:
    """把 store 里最新的 feed 条目合并进请求 dict（不修改入参，返回新 dict）。

    去重规则：已有同名热搜词 / 同名竞品一律不覆盖（真实证据优先）；
    新增条目全部带 is_mock=True 与 evidence_grade="M"。
    store 为空或全部重复时返回与入参等价的 dict（no-op）。
    """
    merged = dict(req_dict)

    # -- 热搜词 --
    existing_trending = list(merged.get("trending_keyword_evidence") or [])
    seen_keywords = {
        str((row or {}).get("keyword", "")).casefold().strip()
        for row in existing_trending
        if isinstance(row, dict)
    }
    seen_keywords.discard("")
    added_trending: list[dict[str, Any]] = []
    if trending_limit > 0:
        for item in store.latest_evidence("trending", limit=max(trending_limit * 4, trending_limit)):
            keyword = str(item.get("keyword", "")).casefold().strip()
            if not keyword or keyword in seen_keywords:
                continue
            seen_keywords.add(keyword)
            added_trending.append(_trending_to_evidence(item))
            if len(added_trending) >= trending_limit:
                break
    if added_trending:
        merged["trending_keyword_evidence"] = [*existing_trending, *added_trending]

    # -- 竞品事件 --
    existing_competitors = list(merged.get("competitor_evidence") or [])
    seen_accounts = {
        str((row or {}).get("account_name", "")).casefold().strip()
        for row in existing_competitors
        if isinstance(row, dict)
    }
    seen_accounts.discard("")
    added_competitors: list[dict[str, Any]] = []
    if competitor_limit > 0:
        for event in store.latest_evidence(
            "competitor_event", limit=max(competitor_limit * 4, competitor_limit)
        ):
            account = str(event.get("account_name", "")).casefold().strip()
            if not account or account in seen_accounts:
                continue
            seen_accounts.add(account)
            added_competitors.append(_competitor_event_to_evidence(event))
            if len(added_competitors) >= competitor_limit:
                break
    if added_competitors:
        merged["competitor_evidence"] = [*existing_competitors, *added_competitors]

    return merged


def feed_merge_counts(before: dict[str, Any], after: dict[str, Any]) -> dict[str, int]:
    """合并前后的条目增量（供调用方写 trace）。"""
    def _len(payload: dict[str, Any], key: str) -> int:
        return len(payload.get(key) or [])

    return {
        "merged_trending": _len(after, "trending_keyword_evidence")
        - _len(before, "trending_keyword_evidence"),
        "merged_competitors": _len(after, "competitor_evidence")
        - _len(before, "competitor_evidence"),
    }
