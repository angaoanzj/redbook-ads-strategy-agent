from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from embedding_client import EmbeddingClient, cosine_similarity
from models import CategoryNoteEvidence, MetricEvidence, OfficialRuleEvidence
from text_tokenize import expand_search_terms


ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = ROOT / "data" / "xhs_knowledge.db"
RRF_K = 60


class KnowledgeBase:
    """Small, local SQLite knowledge base for normalized XHS note evidence."""

    def __init__(
        self,
        path: Path = DEFAULT_DB_PATH,
        *,
        embedding_client: EmbeddingClient | None = None,
    ):
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._embedding_client = embedding_client
        self._initialize()

    @property
    def embedding_client(self) -> EmbeddingClient:
        if self._embedding_client is None:
            self._embedding_client = EmbeddingClient()
        return self._embedding_client

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    note_id TEXT PRIMARY KEY,
                    note_url TEXT NOT NULL,
                    search_keyword TEXT NOT NULL,
                    search_sort TEXT,
                    search_rank INTEGER,
                    title TEXT NOT NULL,
                    description TEXT,
                    note_type TEXT,
                    author_nickname TEXT,
                    likes INTEGER,
                    favorites INTEGER,
                    comments INTEGER,
                    shares INTEGER,
                    tags_json TEXT NOT NULL,
                    published_at TEXT,
                    image_count INTEGER,
                    cover_url TEXT,
                    has_video INTEGER,
                    platform TEXT NOT NULL DEFAULT 'xiaohongshu',
                    author_id TEXT,
                    author_followers_snapshot INTEGER,
                    views INTEGER,
                    ad_label_status TEXT,
                    ad_evidence_url TEXT,
                    metric_snapshot_at TEXT,
                    is_mock INTEGER NOT NULL DEFAULT 0,
                    collected_at TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    evidence_grade TEXT NOT NULL,
                    interaction_total INTEGER NOT NULL DEFAULT 0,
                    first_imported_at TEXT NOT NULL,
                    last_imported_at TEXT NOT NULL,
                    import_count INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS import_batches (
                    batch_id TEXT PRIMARY KEY,
                    source_name TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    received_count INTEGER NOT NULL,
                    inserted_count INTEGER NOT NULL,
                    updated_count INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS official_rules (
                    rule_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    category_path_json TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    source_updated_at TEXT,
                    collected_at TEXT NOT NULL,
                    full_text TEXT NOT NULL,
                    risk_items_json TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    evidence_grade TEXT NOT NULL,
                    first_imported_at TEXT NOT NULL,
                    last_imported_at TEXT NOT NULL
                )
                """
            )
            rule_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(official_rules)").fetchall()
            }
            if "full_text" not in rule_columns:
                connection.execute(
                    "ALTER TABLE official_rules ADD COLUMN full_text TEXT NOT NULL DEFAULT ''"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS targeting_catalog (
                    catalog_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    evidence_grade TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    first_imported_at TEXT NOT NULL,
                    last_imported_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                    note_id UNINDEXED,
                    title,
                    description,
                    tags,
                    search_keyword,
                    tokenize='unicode61'
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS note_embeddings (
                    note_id TEXT PRIMARY KEY,
                    model TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    dim INTEGER NOT NULL,
                    vector_json TEXT NOT NULL,
                    embedded_at TEXT NOT NULL,
                    FOREIGN KEY(note_id) REFERENCES notes(note_id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS note_embeddings_model_idx "
                "ON note_embeddings(model)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS notes_interaction_idx "
                "ON notes(interaction_total DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS notes_collected_idx "
                "ON notes(collected_at DESC)"
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(notes)").fetchall()
            }
            if "cover_url" not in columns:
                connection.execute("ALTER TABLE notes ADD COLUMN cover_url TEXT")
            migrations = {
                "platform": "TEXT NOT NULL DEFAULT 'xiaohongshu'",
                "author_id": "TEXT",
                "author_followers_snapshot": "INTEGER",
                "views": "INTEGER",
                "ad_label_status": "TEXT",
                "ad_evidence_url": "TEXT",
                "metric_snapshot_at": "TEXT",
                "is_mock": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, definition in migrations.items():
                if name not in columns:
                    connection.execute(f"ALTER TABLE notes ADD COLUMN {name} {definition}")

    @staticmethod
    def _interaction_total(note: CategoryNoteEvidence) -> int:
        return sum((note.likes or 0, note.favorites or 0, note.comments or 0, note.shares or 0))

    def import_official_rules(
        self,
        rules: Iterable[OfficialRuleEvidence],
    ) -> dict[str, Any]:
        items = list(rules)
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        updated = 0
        with self._connect() as connection:
            for rule in items:
                exists = connection.execute(
                    "SELECT 1 FROM official_rules WHERE rule_id = ?",
                    (rule.rule_id,),
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO official_rules (
                        rule_id, title, category_path_json, source_url,
                        source_updated_at, collected_at, full_text, risk_items_json,
                        source_name, evidence_grade, first_imported_at, last_imported_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(rule_id) DO UPDATE SET
                        title=excluded.title,
                        category_path_json=excluded.category_path_json,
                        source_url=excluded.source_url,
                        source_updated_at=excluded.source_updated_at,
                        collected_at=excluded.collected_at,
                        full_text=excluded.full_text,
                        risk_items_json=excluded.risk_items_json,
                        source_name=excluded.source_name,
                        evidence_grade=excluded.evidence_grade,
                        last_imported_at=excluded.last_imported_at
                    """,
                    (
                        rule.rule_id,
                        rule.title,
                        json.dumps(rule.category_path, ensure_ascii=False),
                        rule.source_url,
                        rule.source_updated_at,
                        rule.collected_at,
                        rule.full_text,
                        json.dumps(rule.risk_items, ensure_ascii=False),
                        rule.source_name,
                        rule.evidence_grade,
                        now,
                        now,
                    ),
                )
                if exists:
                    updated += 1
                else:
                    inserted += 1
        return {
            "received_count": len(items),
            "inserted_count": inserted,
            "updated_count": updated,
            "total_official_rules": self.status()["total_official_rules"],
        }

    def get_official_rules(self, *, limit: int = 20) -> list[OfficialRuleEvidence]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM official_rules
                ORDER BY source_updated_at DESC, collected_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 50)),),
            ).fetchall()
        return [
            OfficialRuleEvidence(
                rule_id=row["rule_id"],
                title=row["title"],
                category_path=json.loads(row["category_path_json"]),
                source_url=row["source_url"],
                source_updated_at=row["source_updated_at"],
                collected_at=row["collected_at"],
                full_text=row["full_text"],
                risk_items=json.loads(row["risk_items_json"]),
                source_name=row["source_name"],
                evidence_grade=row["evidence_grade"],
            )
            for row in rows
        ]

    def import_notes(
        self,
        notes: Iterable[CategoryNoteEvidence],
        *,
        source_name: str = "category_notes.json",
    ) -> dict[str, Any]:
        items = list(notes)
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        updated = 0
        with self._connect() as connection:
            for note in items:
                exists = connection.execute(
                    "SELECT 1 FROM notes WHERE note_id = ?", (note.note_id,)
                ).fetchone()
                inserted += int(exists is None)
                updated += int(exists is not None)
                values = (
                    note.note_id,
                    note.note_url,
                    note.search_keyword,
                    note.search_sort,
                    note.search_rank,
                    note.title,
                    note.description,
                    note.note_type,
                    note.author_nickname,
                    note.likes,
                    note.favorites,
                    note.comments,
                    note.shares,
                    json.dumps(note.tags, ensure_ascii=False),
                    note.published_at,
                    note.image_count,
                    note.cover_url,
                    int(note.has_video) if note.has_video is not None else None,
                    note.platform,
                    note.author_id,
                    note.author_followers_snapshot,
                    note.views,
                    note.ad_label_status,
                    note.ad_evidence_url,
                    note.metric_snapshot_at,
                    int(note.is_mock),
                    note.collected_at,
                    note.source_name,
                    note.evidence_grade,
                    self._interaction_total(note),
                    now,
                    now,
                )
                connection.execute(
                    """
                    INSERT INTO notes (
                        note_id, note_url, search_keyword, search_sort, search_rank,
                        title, description, note_type, author_nickname, likes,
                        favorites, comments, shares, tags_json, published_at,
                        image_count, cover_url, has_video, platform, author_id,
                        author_followers_snapshot, views, ad_label_status,
                        ad_evidence_url, metric_snapshot_at, is_mock,
                        collected_at, source_name,
                        evidence_grade, interaction_total, first_imported_at,
                        last_imported_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    ON CONFLICT(note_id) DO UPDATE SET
                        note_url=excluded.note_url,
                        search_keyword=excluded.search_keyword,
                        search_sort=excluded.search_sort,
                        search_rank=excluded.search_rank,
                        title=excluded.title,
                        description=excluded.description,
                        note_type=excluded.note_type,
                        author_nickname=excluded.author_nickname,
                        likes=excluded.likes,
                        favorites=excluded.favorites,
                        comments=excluded.comments,
                        shares=excluded.shares,
                        tags_json=excluded.tags_json,
                        published_at=excluded.published_at,
                        image_count=excluded.image_count,
                        cover_url=excluded.cover_url,
                        has_video=excluded.has_video,
                        platform=excluded.platform,
                        author_id=excluded.author_id,
                        author_followers_snapshot=excluded.author_followers_snapshot,
                        views=excluded.views,
                        ad_label_status=excluded.ad_label_status,
                        ad_evidence_url=excluded.ad_evidence_url,
                        metric_snapshot_at=excluded.metric_snapshot_at,
                        is_mock=excluded.is_mock,
                        collected_at=excluded.collected_at,
                        source_name=excluded.source_name,
                        evidence_grade=excluded.evidence_grade,
                        interaction_total=excluded.interaction_total,
                        last_imported_at=excluded.last_imported_at,
                        import_count=notes.import_count + 1
                    """,
                    values,
                )
                connection.execute("DELETE FROM notes_fts WHERE note_id = ?", (note.note_id,))
                connection.execute(
                    """
                    INSERT INTO notes_fts(note_id, title, description, tags, search_keyword)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        note.note_id,
                        note.title,
                        note.description or "",
                        " ".join(note.tags),
                        note.search_keyword,
                    ),
                )
                # Content changed → drop stale vector; hybrid search will re-embed lazily.
                connection.execute(
                    "DELETE FROM note_embeddings WHERE note_id = ?",
                    (note.note_id,),
                )
            batch_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO import_batches(
                    batch_id, source_name, imported_at, received_count,
                    inserted_count, updated_count
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (batch_id, source_name, now, len(items), inserted, updated),
            )
        return {
            "batch_id": batch_id,
            "received_count": len(items),
            "inserted_count": inserted,
            "updated_count": updated,
            "total_notes": self.status()["total_notes"],
        }

    def status(self) -> dict[str, Any]:
        with self._connect() as connection:
            summary = connection.execute(
                """
                SELECT COUNT(*) AS total_notes,
                       COALESCE(SUM(interaction_total), 0) AS total_interactions,
                       MAX(last_imported_at) AS last_imported_at
                FROM notes
                """
            ).fetchone()
            batches = connection.execute(
                "SELECT COUNT(*) AS count FROM import_batches"
            ).fetchone()
            official_rules = connection.execute(
                "SELECT COUNT(*) AS count, MAX(last_imported_at) AS last_imported_at "
                "FROM official_rules"
            ).fetchone()
            targeting = connection.execute(
                "SELECT COUNT(*) AS count, MAX(last_imported_at) AS last_imported_at "
                "FROM targeting_catalog"
            ).fetchone()
            try:
                embedding_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM note_embeddings"
                ).fetchone()
                embedding_models = connection.execute(
                    "SELECT model, COUNT(*) AS count FROM note_embeddings GROUP BY model"
                ).fetchall()
            except sqlite3.OperationalError:
                embedding_count = {"count": 0}
                embedding_models = []
        client = self.embedding_client
        return {
            "database": str(self.path),
            "total_notes": int(summary["total_notes"]),
            "total_interactions": int(summary["total_interactions"]),
            "import_batches": int(batches["count"]),
            "last_imported_at": summary["last_imported_at"],
            "total_official_rules": int(official_rules["count"]),
            "official_rules_last_imported_at": official_rules["last_imported_at"],
            "total_targeting_catalogs": int(targeting["count"]),
            "targeting_catalog_last_imported_at": targeting["last_imported_at"],
            "embedded_notes": int(embedding_count["count"] or 0),
            "embedding_backend": client.backend,
            "embedding_model": client.model,
            "embedding_models": {
                row["model"]: int(row["count"]) for row in embedding_models
            },
            "retrieval_mode": "hybrid_keyword_vector",
        }

    def import_targeting_catalog(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Import a Ju Guang targeting taxonomy + vertical playbook catalog."""
        if not isinstance(payload, dict):
            raise ValueError("targeting catalog 根节点必须是对象")
        meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
        catalog_id = str(
            payload.get("catalog_id")
            or meta.get("catalog_id")
            or "juguang_targeting_catalog"
        )
        title = str(meta.get("title") or payload.get("title") or "聚光定向标签知识库")
        evidence_grade = str(
            meta.get("evidence_grade") or "C_public_secondary_synthesis"
        )
        source_name = str(meta.get("source_name") or "公开二级信源整理+品类候选")
        collected_at = str(
            meta.get("collected_at") or datetime.now(timezone.utc).isoformat()
        )
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM targeting_catalog WHERE catalog_id = ?",
                (catalog_id,),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO targeting_catalog (
                    catalog_id, title, payload_json, evidence_grade, source_name,
                    collected_at, first_imported_at, last_imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(catalog_id) DO UPDATE SET
                    title=excluded.title,
                    payload_json=excluded.payload_json,
                    evidence_grade=excluded.evidence_grade,
                    source_name=excluded.source_name,
                    collected_at=excluded.collected_at,
                    last_imported_at=excluded.last_imported_at
                """,
                (
                    catalog_id,
                    title,
                    json.dumps(payload, ensure_ascii=False),
                    evidence_grade,
                    source_name,
                    collected_at,
                    now,
                    now,
                ),
            )
        return {
            "catalog_id": catalog_id,
            "inserted": exists is None,
            "updated": exists is not None,
            "playbook_count": len(payload.get("vertical_playbooks") or []),
            "total_targeting_catalogs": self.status()["total_targeting_catalogs"],
        }

    def get_targeting_catalog(
        self, catalog_id: str = "juguang_targeting_catalog"
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM targeting_catalog WHERE catalog_id = ?",
                (catalog_id,),
            ).fetchone()
        if not row:
            return None
        payload = json.loads(row["payload_json"])
        return payload if isinstance(payload, dict) else None

    def match_targeting_playbooks(
        self,
        *,
        category: str = "",
        product_name: str = "",
        initial_audience: str = "",
        selling_points: Iterable[str] | None = None,
        limit: int = 2,
    ) -> list[dict[str, Any]]:
        catalog = self.get_targeting_catalog()
        if not catalog:
            return []
        haystack = " ".join(
            [
                category or "",
                product_name or "",
                initial_audience or "",
                " ".join(selling_points or ()),
            ]
        ).casefold()
        scored: list[tuple[int, dict[str, Any]]] = []
        for playbook in catalog.get("vertical_playbooks") or []:
            if not isinstance(playbook, dict):
                continue
            keywords = [
                str(item).casefold()
                for item in (playbook.get("match_keywords") or [])
                if str(item).strip()
            ]
            hits = sum(1 for kw in keywords if kw and kw in haystack)
            if hits:
                scored.append((hits, playbook))
        scored.sort(key=lambda item: (-item[0], str(item[1].get("playbook_id") or "")))
        return [item for _, item in scored[: max(1, min(limit, 5))]]

    def targeting_pack_for_campaign(
        self,
        *,
        category: str = "",
        product_name: str = "",
        initial_audience: str = "",
        selling_points: Iterable[str] | None = None,
        limit: int = 2,
    ) -> dict[str, Any] | None:
        """Structured targeting pack from knowledge base for Module 2 UI/engine."""
        catalog = self.get_targeting_catalog()
        if not catalog:
            return None
        playbooks = self.match_targeting_playbooks(
            category=category,
            product_name=product_name,
            initial_audience=initial_audience,
            selling_points=selling_points,
            limit=limit,
        )
        meta = catalog.get("_meta") if isinstance(catalog.get("_meta"), dict) else {}
        taxonomy = catalog.get("platform_taxonomy") if isinstance(catalog.get("platform_taxonomy"), dict) else {}
        primary = playbooks[0] if playbooks else None
        persona = (
            primary.get("persona")
            if isinstance(primary, dict) and isinstance(primary.get("persona"), dict)
            else {}
        )
        tags = (
            primary.get("targeting_tags")
            if isinstance(primary, dict) and isinstance(primary.get("targeting_tags"), dict)
            else {}
        )
        interest = [str(x) for x in (tags.get("interest_tags") or []) if str(x).strip()]
        behavior = [str(x) for x in (tags.get("behavior_tags") or []) if str(x).strip()]
        crowds = [str(x) for x in (tags.get("crowd_packages") or []) if str(x).strip()]
        return {
            "status": "matched_playbook" if primary else "catalog_only_no_playbook",
            "evidence_grade": meta.get("evidence_grade") or "C_public_secondary_synthesis",
            "warning": (
                meta.get("warning")
                or "候选标签须在聚光后台核对可用性；不得写成账户真实定向。"
            ),
            "playbook_id": (primary or {}).get("playbook_id") if primary else None,
            "playbook_title": (primary or {}).get("title") if primary else None,
            "matched_playbooks": [
                {
                    "playbook_id": item.get("playbook_id"),
                    "title": item.get("title"),
                }
                for item in playbooks
                if isinstance(item, dict)
            ],
            "persona": {
                "demographic": list(persona.get("demographic") or []),
                "behavioral": list(persona.get("behavioral") or []),
                "psychological": list(persona.get("psychological") or []),
            },
            "targeting_tags": {
                "interest_tags": interest,
                "behavior_tags": behavior,
                "crowd_packages": crowds,
            },
            "backend_checklist": list((primary or {}).get("backend_checklist") or []) if primary else [],
            "platform_taxonomy": {
                "entry_path": taxonomy.get("entry_path"),
                "basic_targeting": list(taxonomy.get("basic_targeting") or []),
                "advanced_targeting": [
                    item.get("name")
                    for item in (taxonomy.get("advanced_targeting") or [])
                    if isinstance(item, dict) and item.get("name")
                ],
                "interest_l1_categories": list(catalog.get("interest_l1_categories") or [])[:20],
            },
            "persona_dimension_guide": catalog.get("persona_dimension_guide") or {},
        }

    def targeting_brief_for_campaign(
        self,
        *,
        category: str = "",
        product_name: str = "",
        initial_audience: str = "",
        selling_points: Iterable[str] | None = None,
        limit: int = 2,
    ) -> str | None:
        """Render a prompt-ready brief; always marks tags as backend-unverified."""
        catalog = self.get_targeting_catalog()
        if not catalog:
            return None
        playbooks = self.match_targeting_playbooks(
            category=category,
            product_name=product_name,
            initial_audience=initial_audience,
            selling_points=selling_points,
            limit=limit,
        )
        meta = catalog.get("_meta") if isinstance(catalog.get("_meta"), dict) else {}
        lines = [
            "【知识库·聚光定向候选】证据等级="
            + str(meta.get("evidence_grade") or "C_public_secondary_synthesis")
            + "；下列标签须在聚光后台核对可用性，不得写成账户真实定向。",
        ]
        taxonomy = catalog.get("platform_taxonomy")
        if isinstance(taxonomy, dict):
            advanced = taxonomy.get("advanced_targeting") or []
            names = [
                str(item.get("name"))
                for item in advanced
                if isinstance(item, dict) and item.get("name")
            ]
            if names:
                lines.append("平台高级定向入口：" + " / ".join(names))
        l1 = catalog.get("interest_l1_categories") or []
        if isinstance(l1, list) and l1:
            lines.append("行业阅读兴趣一级类目参考：" + "、".join(str(x) for x in l1[:17]))
        cited = catalog.get("named_packages_publicly_cited")
        if isinstance(cited, dict):
            lifestyle = cited.get("lifestyle") or []
            if lifestyle:
                lines.append(
                    "公开文章举例的生活方式包名（需后台确认）："
                    + "、".join(str(x) for x in lifestyle)
                )
        if not playbooks:
            guide = catalog.get("persona_dimension_guide")
            if isinstance(guide, dict):
                lines.append(
                    "无命中品类剧本：请按人口/行为/心理三维撰写画像，"
                    "兴趣标签优先映射一级类目+关键词兴趣，人群包优先平台精选+自定义转化包。"
                )
            return "\n".join(lines)

        for playbook in playbooks:
            lines.append(
                f"命中剧本「{playbook.get('title') or playbook.get('playbook_id')}」："
            )
            persona = playbook.get("persona") if isinstance(playbook.get("persona"), dict) else {}
            for key, label in (
                ("demographic", "人口"),
                ("behavioral", "行为"),
                ("psychological", "心理"),
            ):
                values = persona.get(key) or []
                if values:
                    lines.append(f"  {label}：" + "；".join(str(v) for v in values[:4]))
            tags = (
                playbook.get("targeting_tags")
                if isinstance(playbook.get("targeting_tags"), dict)
                else {}
            )
            for key, label in (
                ("interest_tags", "兴趣标签候选"),
                ("behavior_tags", "行为标签候选"),
                ("crowd_packages", "人群包候选"),
            ):
                values = tags.get(key) or []
                if values:
                    lines.append(f"  {label}：" + "、".join(str(v) for v in values[:8]))
            checklist = playbook.get("backend_checklist") or []
            if checklist:
                lines.append("  后台核对：" + "；".join(str(v) for v in checklist[:3]))
        return "\n".join(lines)

    def metric_evidence_for_campaign(
        self,
        brand_name: str,
        *,
        analysis_days: int = 30,
        as_of: datetime | None = None,
    ) -> list[MetricEvidence]:
        """Convert real paid workbook rows into metric evidence for the engine.

        Mock tables are intentionally not queried here. The workbook importer stores
        raw monthly values, so this method preserves the source and period in notes.
        """
        end = as_of or datetime.now(timezone.utc)
        start_ordinal = end.year * 12 + end.month - max(1, (analysis_days + 29) // 30) + 1
        with self._connect() as connection:
            try:
                rows = connection.execute(
                    """
                    SELECT year, month, data_json, source_file, collected_at
                    FROM paid_metrics
                    WHERE brand_name = ?
                    ORDER BY year DESC, month DESC
                    """,
                    (brand_name,),
                ).fetchall()
            except sqlite3.OperationalError:
                return []

        selected = []
        for row in rows:
            period_ordinal = int(row["year"]) * 12 + int(row["month"])
            if period_ordinal >= start_ordinal and period_ordinal <= end.year * 12 + end.month:
                selected.append(row)
        if not selected:
            selected = rows[:1]

        definitions = {
            "cpc": ("平均点击成本", "CNY/click"),
            "cpm": ("平均千次展现费用", "CNY/1000 impressions"),
            "ctr": ("点击率", "ratio"),
            "cost_per_interaction": ("平均互动成本", "CNY/interaction"),
            "search_component_conversion_rate": ("搜索组件点击转化率", "ratio"),
        }
        output: list[MetricEvidence] = []
        for metric_name, (source_field, unit) in definitions.items():
            values = []
            numerators = []
            denominators = []
            for row in selected:
                payload = json.loads(row["data_json"])
                raw = payload.get(source_field)
                if raw in (None, "", "/"):
                    continue
                try:
                    values.append((float(raw), row))
                    if metric_name == "cpc":
                        numerators.append(float(payload["消费"])); denominators.append(float(payload["点击量"]))
                    elif metric_name == "cpm":
                        numerators.append(float(payload["消费"])); denominators.append(float(payload["曝光量"]) / 1000)
                    elif metric_name == "ctr":
                        numerators.append(float(payload["点击量"])); denominators.append(float(payload["曝光量"]))
                    elif metric_name == "cost_per_interaction":
                        numerators.append(float(payload["消费"])); denominators.append(float(payload["总互动量"]))
                except (TypeError, ValueError):
                    continue
            if not values:
                continue
            value = (
                sum(numerators) / sum(denominators)
                if numerators and denominators and sum(denominators) > 0
                else sum(item[0] for item in values) / len(values)
            )
            periods = ", ".join(f"{item[1]['year']}-{int(item[1]['month']):02d}" for item in values)
            source_files = sorted({item[1]["source_file"] for item in values if item[1]["source_file"]})
            output.append(MetricEvidence(
                source_name=source_files[0] if source_files else "paid_metrics",
                collected_at=max(item[1]["collected_at"] for item in values),
                metric_name=metric_name,
                value=value,
                unit=unit,
                notes=f"真实月度投放数据；期间={periods}；按曝光/点击/互动加权聚合（搜索转化率除外）；样本月数={len(values)}；来源={','.join(source_files)}",
                evidence_grade="C_user_provided",
                is_mock=False,
            ))
        return output

    def paid_monthly_for_campaign(
        self,
        brand_name: str,
        *,
        analysis_days: int | None = 180,
        as_of: datetime | None = None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Return brand paid monthly rows for spotlight monthly_rows (not aggregated)."""
        end = as_of or datetime.now(timezone.utc)
        with self._connect() as connection:
            try:
                rows = connection.execute(
                    """
                    SELECT year, month, data_json, source_file, collected_at
                    FROM paid_metrics
                    WHERE brand_name = ?
                    ORDER BY year ASC, month ASC
                    """,
                    (brand_name,),
                ).fetchall()
            except sqlite3.OperationalError:
                return []
        if analysis_days is None:
            selected = list(rows)
        else:
            start_ordinal = (
                end.year * 12 + end.month - max(1, (analysis_days + 29) // 30) + 1
            )
            selected = [
                row
                for row in rows
                if start_ordinal
                <= int(row["year"]) * 12 + int(row["month"])
                <= end.year * 12 + end.month
            ]
        if not selected:
            selected = list(rows)[-max(1, min(limit, 12)) :]
        else:
            selected = selected[-max(1, min(limit, 12)) :]

        def _fmt_money(value: Any) -> str:
            try:
                return f"{float(value):,.2f}"
            except (TypeError, ValueError):
                return str(value or "—")

        def _fmt_ratio(value: Any) -> str:
            try:
                number = float(value)
                if number <= 1:
                    return f"{number * 100:.2f}%"
                return f"{number:.2f}%"
            except (TypeError, ValueError):
                return str(value or "—")

        output: list[dict[str, Any]] = []
        for row in selected:
            payload = json.loads(row["data_json"])
            output.append({
                "month": f"{int(row['year'])}-{int(row['month']):02d}",
                "spend": _fmt_money(payload.get("消费")),
                "cpc": _fmt_money(payload.get("平均点击成本")),
                "cpm": _fmt_money(payload.get("平均千次展现费用")),
                "ctr": _fmt_ratio(payload.get("点击率")),
                "source_file": row["source_file"],
                "collected_at": row["collected_at"],
                "metrics": payload,
            })
        return output

    def organic_history_for_campaign(
        self, brand_name: str, *, analysis_days: int = 30,
        as_of: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return imported brand-owned organic periods, preserving raw fields."""
        end = as_of or datetime.now(timezone.utc)
        cutoff = end - timedelta(days=analysis_days)
        with self._connect() as connection:
            try:
                rows = connection.execute(
                    "SELECT period, data_json, source_file, collected_at FROM organic_metrics "
                    "WHERE brand_name = ? ORDER BY period DESC", (brand_name,)
                ).fetchall()
            except sqlite3.OperationalError:
                return []
        result = []
        for row in rows:
            period_text = str(row["period"])
            period_has_explicit_year = "-" in period_text[:5]
            try:
                if period_text.endswith("月") and period_text[:-1].isdigit():
                    period_date = datetime(end.year, int(period_text[:-1]), 1, tzinfo=timezone.utc)
                else:
                    period_date = datetime.fromisoformat(period_text + "-01").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if period_has_explicit_year and period_date < cutoff.replace(day=1):
                continue
            result.append({
                "period": row["period"],
                "metrics": json.loads(row["data_json"]),
                "source_file": row["source_file"],
                "collected_at": row["collected_at"],
                "evidence_grade": "C_user_provided",
                "is_mock": False,
                "period_year_inferred": not period_has_explicit_year,
            })
        return result

    @staticmethod
    def _row_to_note(row: sqlite3.Row) -> CategoryNoteEvidence:
        return CategoryNoteEvidence(
            search_keyword=row["search_keyword"],
            search_sort=row["search_sort"],
            search_rank=row["search_rank"],
            note_id=row["note_id"],
            note_url=row["note_url"],
            title=row["title"],
            description=row["description"],
            note_type=row["note_type"],
            author_nickname=row["author_nickname"],
            likes=row["likes"],
            favorites=row["favorites"],
            comments=row["comments"],
            shares=row["shares"],
            tags=json.loads(row["tags_json"]),
            published_at=row["published_at"],
            image_count=row["image_count"],
            cover_url=row["cover_url"],
            has_video=bool(row["has_video"]) if row["has_video"] is not None else None,
            platform=row["platform"] or "xiaohongshu",
            author_id=row["author_id"],
            author_followers_snapshot=row["author_followers_snapshot"],
            views=row["views"],
            ad_label_status=row["ad_label_status"],
            ad_evidence_url=row["ad_evidence_url"],
            metric_snapshot_at=row["metric_snapshot_at"],
            is_mock=bool(row["is_mock"]),
            collected_at=row["collected_at"],
            source_name=row["source_name"],
            evidence_grade=row["evidence_grade"],
        )

    @staticmethod
    def _note_corpus_text(row: sqlite3.Row | dict[str, Any]) -> str:
        tags = row["tags_json"]
        if isinstance(tags, str):
            try:
                tag_text = " ".join(json.loads(tags))
            except json.JSONDecodeError:
                tag_text = tags
        else:
            tag_text = " ".join(tags or [])
        return "\n".join(
            [
                str(row["title"] or ""),
                str(row["description"] or ""),
                tag_text,
                str(row["search_keyword"] or ""),
            ]
        ).strip()

    @staticmethod
    def _content_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _fetch_note_rows(
        self,
        *,
        analysis_days: int | None = None,
        as_of: datetime | None = None,
        source_names: Iterable[str] | None = None,
        evidence_grades: Iterable[str] | None = None,
        allow_mock: bool = False,
        row_limit: int = 5000,
    ) -> list[sqlite3.Row]:
        clauses = ["1=1"]
        params: list[Any] = []
        if not allow_mock:
            clauses.append("is_mock = 0")
        if source_names:
            names = list(dict.fromkeys(source_names))
            clauses.append("source_name IN (" + ",".join("?" for _ in names) + ")")
            params.extend(names)
        if evidence_grades:
            grades = list(dict.fromkeys(evidence_grades))
            clauses.append("evidence_grade IN (" + ",".join("?" for _ in grades) + ")")
            params.extend(grades)
        if analysis_days is not None:
            end = as_of or datetime.now(timezone.utc)
            start = end - timedelta(days=max(1, analysis_days))
            clauses.append(
                "published_at IS NOT NULL AND substr(published_at, 1, 19) >= ? "
                "AND substr(published_at, 1, 19) <= ?"
            )
            params.extend(
                [start.replace(tzinfo=None).isoformat(), end.replace(tzinfo=None).isoformat()]
            )
        with self._connect() as connection:
            return list(
                connection.execute(
                    "SELECT * FROM notes WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY interaction_total DESC, collected_at DESC LIMIT ?",
                    [*params, max(1, min(row_limit, 5000))],
                ).fetchall()
            )

    def _keyword_rank(
        self,
        terms: Iterable[str],
        rows: list[sqlite3.Row],
    ) -> tuple[list[tuple[float, sqlite3.Row]], list[str]]:
        normalized_terms = expand_search_terms(terms)
        if not normalized_terms or not rows:
            return [], normalized_terms
        fts_matches: set[str] = set()
        with self._connect() as connection:
            for term in normalized_terms:
                phrase = f'"{term.replace(chr(34), chr(34) * 2)}"'
                try:
                    matches = connection.execute(
                        "SELECT note_id FROM notes_fts WHERE notes_fts MATCH ? LIMIT 500",
                        (phrase,),
                    ).fetchall()
                    fts_matches.update(row["note_id"] for row in matches)
                except sqlite3.OperationalError:
                    continue
        ranked: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            tags = " ".join(json.loads(row["tags_json"]))
            fields = {
                "title": (row["title"] or "").lower(),
                "description": (row["description"] or "").lower(),
                "tags": tags.lower(),
                "keyword": (row["search_keyword"] or "").lower(),
            }
            relevance = 0.0
            for term in normalized_terms:
                weight = 1.0 if len(term) <= 2 else (1.4 if len(term) == 3 else 1.8)
                relevance += (6.0 * weight) if term in fields["title"] else 0.0
                relevance += (4.0 * weight) if term in fields["tags"] else 0.0
                relevance += (3.0 * weight) if term in fields["keyword"] else 0.0
                relevance += (1.5 * weight) if term in fields["description"] else 0.0
            relevance += 2.0 if row["note_id"] in fts_matches else 0.0
            if relevance <= 0:
                continue
            quality = math.log1p(max(0, row["interaction_total"])) / 10
            ranked.append((relevance + quality, row))
        ranked.sort(key=lambda pair: (-pair[0], -pair[1]["interaction_total"]))
        return ranked, normalized_terms

    @staticmethod
    def _diversify_rows(
        ranked: list[tuple[float, sqlite3.Row]],
        *,
        limit: int,
        diversify_by_author: bool,
    ) -> list[sqlite3.Row]:
        selected: list[sqlite3.Row] = []
        author_counts: dict[str, int] = {}
        for _, row in ranked:
            author = row["author_id"] or row["author_nickname"] or row["note_id"]
            if diversify_by_author and author_counts.get(author, 0) >= 3:
                continue
            selected.append(row)
            author_counts[author] = author_counts.get(author, 0) + 1
            if len(selected) >= max(1, min(limit, 500)):
                break
        return selected

    def ensure_note_embeddings(
        self,
        *,
        note_ids: Iterable[str] | None = None,
        batch_size: int = 32,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Embed missing/stale notes. Uses remote API when configured, else local hash."""
        client = self.embedding_client
        wanted = list(dict.fromkeys(note_ids or []))
        with self._connect() as connection:
            if wanted:
                placeholders = ",".join("?" for _ in wanted)
                rows = connection.execute(
                    f"SELECT * FROM notes WHERE note_id IN ({placeholders})",
                    wanted,
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM notes ORDER BY interaction_total DESC, collected_at DESC"
                ).fetchall()
            existing = {
                row["note_id"]: row
                for row in connection.execute("SELECT * FROM note_embeddings").fetchall()
            }
        pending: list[sqlite3.Row] = []
        for row in rows:
            corpus = self._note_corpus_text(row)
            digest = self._content_hash(corpus)
            current = existing.get(row["note_id"])
            if (
                current
                and current["content_hash"] == digest
                and current["model"] == client.model
            ):
                continue
            pending.append(row)
            if limit is not None and len(pending) >= max(1, limit):
                break
        embedded = 0
        meta: dict[str, Any] = {"backend": client.backend, "model": client.model}
        for start in range(0, len(pending), max(1, batch_size)):
            chunk = pending[start : start + max(1, batch_size)]
            texts = [self._note_corpus_text(row) for row in chunk]
            vectors, embed_meta = client.embed_texts(texts)
            meta = embed_meta
            now = datetime.now(timezone.utc).isoformat()
            with self._connect() as connection:
                for row, vector in zip(chunk, vectors):
                    connection.execute(
                        """
                        INSERT INTO note_embeddings(
                            note_id, model, content_hash, dim, vector_json, embedded_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(note_id) DO UPDATE SET
                            model=excluded.model,
                            content_hash=excluded.content_hash,
                            dim=excluded.dim,
                            vector_json=excluded.vector_json,
                            embedded_at=excluded.embedded_at
                        """,
                        (
                            row["note_id"],
                            embed_meta.get("model") or client.model,
                            self._content_hash(self._note_corpus_text(row)),
                            len(vector),
                            json.dumps(vector),
                            now,
                        ),
                    )
                    embedded += 1
        return {
            "pending": len(pending),
            "embedded": embedded,
            "model": meta.get("model") or client.model,
            "backend": meta.get("backend") or client.backend,
            "error_type": meta.get("error_type"),
        }

    def _vector_rank(
        self,
        query_text: str,
        rows: list[sqlite3.Row],
        *,
        ensure: bool = True,
    ) -> tuple[list[tuple[float, sqlite3.Row]], dict[str, Any]]:
        if not query_text.strip() or not rows:
            return [], {"backend": self.embedding_client.backend, "hit_count": 0}
        if ensure:
            self.ensure_note_embeddings(note_ids=[row["note_id"] for row in rows])
        query_vectors, embed_meta = self.embedding_client.embed_texts([query_text])
        query_vec = query_vectors[0]
        query_dim = len(query_vec)
        with self._connect() as connection:
            stored = connection.execute(
                "SELECT note_id, model, vector_json FROM note_embeddings"
            ).fetchall()
        embeddings: dict[str, list[float]] = {}
        for item in stored:
            vector = json.loads(item["vector_json"])
            if len(vector) != query_dim:
                continue
            embeddings[item["note_id"]] = vector
        ranked: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            vector = embeddings.get(row["note_id"])
            if not vector:
                continue
            score = cosine_similarity(query_vec, vector)
            if score <= 0:
                continue
            ranked.append((score, row))
        ranked.sort(key=lambda pair: (-pair[0], -pair[1]["interaction_total"]))
        embed_meta = {
            **embed_meta,
            "hit_count": len(ranked),
            "query_dim": query_dim,
            "indexed_comparable": len(embeddings),
        }
        return ranked, embed_meta

    def search(
        self,
        terms: Iterable[str],
        *,
        limit: int = 30,
        analysis_days: int | None = None,
        as_of: datetime | None = None,
        source_names: Iterable[str] | None = None,
        evidence_grades: Iterable[str] | None = None,
        allow_mock: bool = False,
        diversify_by_author: bool = True,
    ) -> list[CategoryNoteEvidence]:
        rows = self._fetch_note_rows(
            analysis_days=analysis_days,
            as_of=as_of,
            source_names=source_names,
            evidence_grades=evidence_grades,
            allow_mock=allow_mock,
        )
        ranked, _ = self._keyword_rank(terms, rows)
        selected = self._diversify_rows(
            ranked, limit=limit, diversify_by_author=diversify_by_author
        )
        return [self._row_to_note(row) for row in selected]

    def hybrid_search(
        self,
        terms: Iterable[str],
        *,
        limit: int = 30,
        analysis_days: int | None = None,
        as_of: datetime | None = None,
        source_names: Iterable[str] | None = None,
        evidence_grades: Iterable[str] | None = None,
        allow_mock: bool = False,
        diversify_by_author: bool = True,
        use_vector: bool = True,
        keyword_weight: float = 0.55,
        vector_weight: float = 0.45,
        ensure_embeddings: bool = True,
        query_text: str | None = None,
    ) -> list[CategoryNoteEvidence]:
        notes, _ = self.hybrid_search_with_meta(
            terms,
            limit=limit,
            analysis_days=analysis_days,
            as_of=as_of,
            source_names=source_names,
            evidence_grades=evidence_grades,
            allow_mock=allow_mock,
            diversify_by_author=diversify_by_author,
            use_vector=use_vector,
            keyword_weight=keyword_weight,
            vector_weight=vector_weight,
            ensure_embeddings=ensure_embeddings,
            query_text=query_text,
        )
        return notes

    def hybrid_search_with_meta(
        self,
        terms: Iterable[str],
        *,
        limit: int = 30,
        analysis_days: int | None = None,
        as_of: datetime | None = None,
        source_names: Iterable[str] | None = None,
        evidence_grades: Iterable[str] | None = None,
        allow_mock: bool = False,
        diversify_by_author: bool = True,
        use_vector: bool = True,
        keyword_weight: float = 0.55,
        vector_weight: float = 0.45,
        ensure_embeddings: bool = True,
        query_text: str | None = None,
    ) -> tuple[list[CategoryNoteEvidence], dict[str, Any]]:
        """Keyword tokenization recall + vector RAG recall, fused by weighted RRF."""
        term_list = [str(t).strip() for t in terms if t and str(t).strip()]
        rows = self._fetch_note_rows(
            analysis_days=analysis_days,
            as_of=as_of,
            source_names=source_names,
            evidence_grades=evidence_grades,
            allow_mock=allow_mock,
        )
        keyword_ranked, normalized_terms = self._keyword_rank(term_list, rows)
        query_blob = (query_text or " ".join(term_list)).strip()
        vector_ranked: list[tuple[float, sqlite3.Row]] = []
        vector_meta: dict[str, Any] = {"enabled": False}
        if use_vector and query_blob:
            vector_ranked, vector_meta = self._vector_rank(
                query_blob, rows, ensure=ensure_embeddings
            )
            vector_meta["enabled"] = True

        keyword_rank_map = {
            row["note_id"]: index + 1 for index, (_, row) in enumerate(keyword_ranked)
        }
        vector_rank_map = {
            row["note_id"]: index + 1 for index, (_, row) in enumerate(vector_ranked)
        }
        row_by_id = {row["note_id"]: row for row in rows}
        fused: list[tuple[float, sqlite3.Row]] = []
        for note_id, row in row_by_id.items():
            kw_rank = keyword_rank_map.get(note_id)
            vec_rank = vector_rank_map.get(note_id)
            if kw_rank is None and vec_rank is None:
                continue
            kw_rrf = (keyword_weight / (RRF_K + kw_rank)) if kw_rank else 0.0
            vec_rrf = (vector_weight / (RRF_K + vec_rank)) if vec_rank else 0.0
            quality = math.log1p(max(0, row["interaction_total"])) / 1000
            fused.append((kw_rrf + vec_rrf + quality, row))
        fused.sort(key=lambda pair: (-pair[0], -pair[1]["interaction_total"]))
        selected = self._diversify_rows(
            fused, limit=limit, diversify_by_author=diversify_by_author
        )
        meta = {
            "mode": "hybrid" if use_vector else "keyword",
            "query_terms": term_list,
            "expanded_terms": normalized_terms[:40],
            "keyword_hits": len(keyword_ranked),
            "vector_hits": len(vector_ranked),
            "fused_candidates": len(fused),
            "returned": len(selected),
            "keyword_weight": keyword_weight,
            "vector_weight": vector_weight,
            "vector": vector_meta,
            "tokenizer": "jieba_or_lexicon_ngram",
        }
        return [self._row_to_note(row) for row in selected], meta

    @staticmethod
    def aggregate_keyword_stats(
        notes: Iterable[CategoryNoteEvidence],
        *,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        """Aggregate search_keyword + tags from KB notes into ranked keyword stats.

        Used as the seed pool for core / long_tail / blue_ocean tiering.
        """
        occurrences: Counter[str] = Counter()
        interactions: Counter[str] = Counter()
        sources: dict[str, set[str]] = defaultdict(set)
        display: dict[str, str] = {}

        def _accept(raw: Any, *, source: str) -> None:
            text = str(raw or "").strip().lstrip("#＃").strip()
            if not (2 <= len(text) <= 24):
                return
            key = text.casefold()
            display.setdefault(key, text)
            sources[key].add(source)

        note_list = list(notes or [])
        for note in note_list:
            local_keys: list[str] = []
            sk = str(getattr(note, "search_keyword", None) or "").strip()
            if sk:
                key = sk.casefold()
                _accept(sk, source="search_keyword")
                if 2 <= len(sk) <= 24:
                    local_keys.append(key)
            for tag in (getattr(note, "tags", None) or [])[:8]:
                text = str(tag or "").strip().lstrip("#＃").strip()
                if not (2 <= len(text) <= 24):
                    continue
                key = text.casefold()
                _accept(text, source="tag")
                local_keys.append(key)
            note_inter = KnowledgeBase._interaction_total(note)
            for key in dict.fromkeys(local_keys):
                occurrences[key] += 1
                interactions[key] += note_inter

        ranked = occurrences.most_common(max(1, int(limit)))
        return [
            {
                "keyword": display[key],
                "note_count": count,
                "total_interactions": interactions[key],
                "sources": sorted(sources.get(key) or []),
                "from_evidence": True,
            }
            for key, count in ranked
        ]

    def keyword_candidates_for_campaign(
        self,
        terms: Iterable[str],
        *,
        limit_notes: int = 300,
        limit_keywords: int = 40,
        allow_mock: bool = False,
        use_vector: bool = True,
    ) -> list[dict[str, Any]]:
        """Hybrid-retrieve notes from this KB, then aggregate keyword stats."""
        term_list = [str(t).strip() for t in terms if t and str(t).strip()]
        notes = self.hybrid_search(
            term_list or ["伴手礼"],
            limit=limit_notes,
            analysis_days=None,
            allow_mock=allow_mock,
            diversify_by_author=True,
            use_vector=use_vector,
            query_text=" ".join(term_list),
        )
        return self.aggregate_keyword_stats(notes, limit=limit_keywords)

    # 场景 / 人群识别词表（从知识库标签、搜索词、标题正文中匹配）
    SCENE_MARKERS = (
        "送礼", "伴手礼", "下午茶", "探店", "开箱", "办公室", "聚会", "过年", "春节",
        "中秋", "情人节", "生日", "婚礼", "出差", "旅行", "打卡", "囤货", "解馋",
        "早餐", "宵夜", "野餐", "约会", "年货", "手信", "场景", "宅家", "周末",
        "节日", "礼盒", "走亲访友", "回礼", "乔迁", "升学", "过节", "犒劳",
        "下午茶点", "茶歇", "伴手", "探店打卡", "居家", "通勤",
    )
    AUDIENCE_MARKERS = (
        "岁", "女性", "男性", "宝妈", "妈妈", "妈咪", "学生", "上班族", "打工人",
        "女孩", "男生", "女生", "情侣", "母女", "亲子", "职场", "白领", "人群",
        "都市女性", "男士", "女士", "年轻人", "中年", "老人", "儿童", "大学生",
        "留学生", "港漂", "游客", "精致妈妈", "职场女性", "新手妈妈", "宝爸",
        "阿姨", "婆婆", "闺蜜", "男友", "女友", "同事",
    )

    @classmethod
    def _keyword_role(cls, keyword: str) -> str | None:
        """Return 'audience' | 'scene' | None for a candidate keyword."""
        text = (keyword or "").strip()
        if not text:
            return None
        # 人群优先：避免「女生送礼」同时命中时被场景抢走
        if any(marker in text for marker in cls.AUDIENCE_MARKERS):
            return "audience"
        if any(marker in text for marker in cls.SCENE_MARKERS):
            return "scene"
        return None

    @classmethod
    def extract_scene_audience_keywords(
        cls,
        notes: Iterable[CategoryNoteEvidence],
        *,
        scene_limit: int = 8,
        audience_limit: int = 6,
        exclude: Iterable[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Identify scene / audience keywords from KB notes (tags, search, title)."""
        exclude_keys = {
            str(item).casefold().strip()
            for item in (exclude or [])
            if item and str(item).strip()
        }
        weights: dict[str, dict[str, Any]] = {}

        def _bump(raw: Any, *, source: str, score: int, interactions: int) -> None:
            text = str(raw or "").strip().lstrip("#＃").strip()
            if not (2 <= len(text) <= 24):
                return
            role = cls._keyword_role(text)
            if role is None:
                return
            key = text.casefold()
            if key in exclude_keys:
                return
            row = weights.get(key)
            if row is None:
                weights[key] = {
                    "keyword": text,
                    "role": role,
                    "note_count": 1,
                    "total_interactions": max(0, interactions),
                    "score": score,
                    "sources": {source},
                    "from_evidence": True,
                }
                return
            row["note_count"] += 1
            row["total_interactions"] += max(0, interactions)
            row["score"] += score
            row["sources"].add(source)
            # 若后续命中更明确的人群标记，升级角色
            if role == "audience":
                row["role"] = "audience"

        note_list = list(notes or [])
        for note in note_list:
            inter = cls._interaction_total(note)
            sk = getattr(note, "search_keyword", None)
            _bump(sk, source="search_keyword", score=3, interactions=inter)
            for tag in (getattr(note, "tags", None) or [])[:10]:
                _bump(tag, source="tag", score=4, interactions=inter)
            # 标题/正文：命中词表中的 marker 本身也作为候选
            blob = " ".join(
                str(part or "")
                for part in (
                    getattr(note, "title", None),
                    getattr(note, "description", None),
                )
            )
            if blob.strip():
                for marker in cls.AUDIENCE_MARKERS:
                    if marker in blob:
                        _bump(marker, source="title_body", score=2, interactions=inter)
                for marker in cls.SCENE_MARKERS:
                    if marker in blob:
                        _bump(marker, source="title_body", score=2, interactions=inter)

        scene_rows = [
            {
                **row,
                "sources": sorted(row["sources"]),
            }
            for row in weights.values()
            if row["role"] == "scene"
        ]
        audience_rows = [
            {
                **row,
                "sources": sorted(row["sources"]),
            }
            for row in weights.values()
            if row["role"] == "audience"
        ]
        scene_rows.sort(
            key=lambda r: (-r["score"], -r["note_count"], -r["total_interactions"], r["keyword"])
        )
        audience_rows.sort(
            key=lambda r: (-r["score"], -r["note_count"], -r["total_interactions"], r["keyword"])
        )
        return {
            "scene_keywords": scene_rows[: max(0, int(scene_limit))],
            "audience_keywords": audience_rows[: max(0, int(audience_limit))],
        }

    def identify_competitors(
        self,
        *,
        own_brand: str,
        candidate_names: Iterable[str],
        category_terms: Iterable[str],
    ) -> list[dict[str, Any]]:
        own_brand_key = own_brand.strip().casefold()
        candidates = list(
            dict.fromkeys(
                name.strip()
                for name in candidate_names
                if name and name.strip() and name.strip().casefold() != own_brand_key
            )
        )[:20]
        category_tokens: list[str] = []
        for term in category_terms:
            category_tokens.extend(
                part.casefold()
                for part in re.split(r"[/／|｜,，、;；\s\-－—]+", term or "")
                if len(part) >= 2
            )
        category_tokens = list(dict.fromkeys(category_tokens))
        comparison_markers = ("对比", "实测", "测评", "排雷", "横评", "vs", "哪个好", "三强")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM notes ORDER BY interaction_total DESC"
            ).fetchall()

        results: list[dict[str, Any]] = []
        for candidate in candidates:
            key = candidate.casefold()
            mentions: list[sqlite3.Row] = []
            category_relevant = 0
            comparison_mentions = 0
            authors: set[str] = set()
            for row in rows:
                tags = " ".join(json.loads(row["tags_json"]))
                text = " ".join((
                    row["title"] or "",
                    row["description"] or "",
                    tags,
                    row["search_keyword"] or "",
                )).casefold()
                if key not in text:
                    continue
                mentions.append(row)
                if row["author_nickname"]:
                    authors.add(row["author_nickname"])
                if any(token in text for token in category_tokens):
                    category_relevant += 1
                if any(marker in text for marker in comparison_markers):
                    comparison_mentions += 1
            mention_count = len(mentions)
            if mention_count >= 2 and category_relevant >= 1:
                classification = "可能竞品"
            elif mention_count == 1:
                classification = "待人工复核"
            else:
                classification = "证据不足"
            confidence = min(
                95,
                mention_count * 18
                + min(len(authors), 3) * 8
                + min(category_relevant, 3) * 8
                + min(comparison_mentions, 2) * 7,
            )
            results.append({
                "candidate_name": candidate,
                "classification": classification,
                "confidence_score": confidence,
                "mention_note_count": mention_count,
                "independent_author_count": len(authors),
                "category_relevant_note_count": category_relevant,
                "comparison_context_count": comparison_mentions,
                "total_interactions": sum(row["interaction_total"] for row in mentions),
                "ad_label_status": "待打开原笔记人工核验",
                "evidence_notes": [
                    {
                        "title": row["title"],
                        "url": row["note_url"],
                        "note_type": row["note_type"],
                        "interactions": row["interaction_total"],
                    }
                    for row in mentions[:3]
                ],
                "decision_rule": "至少2条独立笔记提及，且至少1条与当前品类相关",
            })
        return sorted(
            results,
            key=lambda item: (
                item["classification"] != "可能竞品",
                -item["confidence_score"],
                -item["mention_note_count"],
            ),
        )


def _load_notes(path: Path) -> list[CategoryNoteEvidence]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("category_notes.json 根节点必须是数组")
    return [CategoryNoteEvidence.model_validate(item) for item in payload]


def _load_official_rules(path: Path) -> list[OfficialRuleEvidence]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("official_rule_evidence") or payload.get("rules")
        if not isinstance(items, list):
            raise ValueError(
                "official_rules.json 根节点必须是数组，或含 official_rule_evidence 数组"
            )
    else:
        raise ValueError("official_rules.json 根节点类型无效")
    return [OfficialRuleEvidence.model_validate(item) for item in items]


def main() -> int:
    parser = argparse.ArgumentParser(description="小红书本地知识库管理")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    import_parser = subparsers.add_parser("import", help="导入 category_notes.json")
    import_parser.add_argument("json_file", type=Path)
    import_parser.add_argument("--source-name")
    rules_parser = subparsers.add_parser("import-rules", help="导入官方规则 JSON")
    rules_parser.add_argument("json_file", type=Path)
    targeting_parser = subparsers.add_parser(
        "import-targeting",
        help="导入聚光定向标签知识库 JSON",
    )
    targeting_parser.add_argument(
        "json_file",
        type=Path,
        nargs="?",
        default=ROOT / "examples" / "knowledge" / "juguang_targeting_catalog.json",
    )
    export_rules_parser = subparsers.add_parser(
        "export-rules",
        help="导出官方规则到 JSON（可供 mock 生成或二次 import-rules）",
    )
    export_rules_parser.add_argument(
        "json_file",
        type=Path,
        nargs="?",
        default=ROOT / "examples" / "mock" / "official_rules_demo.json",
        help="输出路径，默认 examples/mock/official_rules_demo.json",
    )
    export_rules_parser.add_argument("--limit", type=int, default=50)
    export_rules_parser.add_argument(
        "--array-only",
        action="store_true",
        help="仅输出规则数组（兼容旧 import-rules）",
    )
    search_parser = subparsers.add_parser("search", help="搜索本地知识库")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)
    subparsers.add_parser("status", help="查看知识库状态")
    args = parser.parse_args()

    knowledge = KnowledgeBase(args.db)
    if args.command == "import":
        result = knowledge.import_notes(
            _load_notes(args.json_file),
            source_name=args.source_name or args.json_file.name,
        )
    elif args.command == "import-rules":
        result = knowledge.import_official_rules(_load_official_rules(args.json_file))
    elif args.command == "import-targeting":
        payload = json.loads(args.json_file.read_text(encoding="utf-8"))
        result = knowledge.import_targeting_catalog(payload)
    elif args.command == "export-rules":
        from official_rules_loader import (
            build_demo_rules_envelope,
            order_official_rules,
        )

        rules = order_official_rules(knowledge.get_official_rules(limit=args.limit))
        out_path = args.json_file.expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if args.array_only:
            payload: Any = [rule.model_dump(mode="json") for rule in rules]
        else:
            payload = build_demo_rules_envelope(
                rules,
                source_label=f"knowledge_base:{knowledge.path}",
            )
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        result = {
            "exported_count": len(rules),
            "output": str(out_path),
            "array_only": bool(args.array_only),
        }
    elif args.command == "search":
        result = [
            item.model_dump(mode="json")
            for item in knowledge.search([args.query], limit=args.limit)
        ]
    else:
        result = knowledge.status()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
