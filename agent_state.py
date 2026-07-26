"""Persistent runtime state for the local Xiaohongshu strategy Agent."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


ROOT = Path(__file__).resolve().parent
DEFAULT_STATE_DB_PATH = ROOT / "data" / "agent_state.db"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_report_id() -> str:
    return f"rpt_{uuid4().hex}"


_SENSITIVE_KEY_PARTS = (
    "cookie",
    "authorization",
    "apikey",
    "token",
    "secret",
    "proxy",
    "traceback",
)


def sanitize_state_payload(value: Any) -> Any:
    """Remove secret-bearing keys recursively before state is serialized."""

    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                continue
            safe[str(key)] = sanitize_state_payload(item)
        return safe
    if isinstance(value, list):
        return [sanitize_state_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_state_payload(item) for item in value]
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(
        sanitize_state_payload(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


class AgentStateStore:
    """Owns SQLite persistence for sessions and Agent runtime state."""

    def __init__(self, path: str | Path = DEFAULT_STATE_DB_PATH):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    session_id TEXT PRIMARY KEY,
                    analysis_count INTEGER NOT NULL DEFAULT 0,
                    last_report_id TEXT,
                    last_brand_name TEXT,
                    last_product_name TEXT,
                    last_category TEXT,
                    last_goal TEXT,
                    last_mock_seed TEXT,
                    last_summary_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS session_memory (
                    session_id TEXT NOT NULL,
                    memory_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(session_id, memory_key),
                    FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS session_memory_expiry_idx
                    ON session_memory(expires_at);

                CREATE TABLE IF NOT EXISTS analysis_runs (
                    report_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    brand_name TEXT,
                    product_name TEXT,
                    category TEXT,
                    goal TEXT,
                    mock_seed TEXT,
                    data_confidence TEXT,
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    source_counts_json TEXT NOT NULL DEFAULT '{}',
                    response_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS analysis_runs_session_idx
                    ON analysis_runs(session_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS feedback_records (
                    feedback_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    report_id TEXT NOT NULL,
                    rating TEXT NOT NULL,
                    comment TEXT,
                    sections_json TEXT NOT NULL DEFAULT '[]',
                    field_corrections_json TEXT NOT NULL DEFAULT '[]',
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS backfilled_cases (
                    case_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    report_id TEXT NOT NULL,
                    brand_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    problem_summary TEXT NOT NULL,
                    strategy_summary TEXT NOT NULL,
                    evidence_grade TEXT NOT NULL,
                    case_type TEXT NOT NULL,
                    is_mock INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS common_hit_cache (
                    cache_key TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    source_version TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS common_hit_cache_expiry_idx
                    ON common_hit_cache(expires_at);

                CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                    session_id TEXT NOT NULL,
                    report_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    context_json TEXT NOT NULL DEFAULT '{}',
                    error_summary TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(session_id, report_id, stage)
                );

                CREATE TABLE IF NOT EXISTS submitted_actions (
                    idempotency_key TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    report_id TEXT,
                    status TEXT NOT NULL,
                    response_summary_json TEXT NOT NULL DEFAULT '{}',
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS submitted_actions_expiry_idx
                    ON submitted_actions(expires_at);

                CREATE TABLE IF NOT EXISTS alert_events (
                    alert_id TEXT PRIMARY KEY,
                    brand_name TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    response TEXT,
                    source TEXT NOT NULL DEFAULT 'competitor_monitor',
                    report_id TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS alert_events_brand_idx
                    ON alert_events(brand_name, created_at DESC);
                CREATE INDEX IF NOT EXISTS alert_events_severity_idx
                    ON alert_events(severity, created_at DESC);
                """
            )
            # 兼容旧库：补反馈可计算字段
            cols = {
                row[1]
                for row in connection.execute("PRAGMA table_info(feedback_records)").fetchall()
            }
            if "field_corrections_json" not in cols:
                connection.execute(
                    "ALTER TABLE feedback_records "
                    "ADD COLUMN field_corrections_json TEXT NOT NULL DEFAULT '[]'"
                )
            connection.commit()

    @staticmethod
    def _session_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["last_summary"] = _json_loads(result.pop("last_summary_json"), {})
        return result

    def get_or_create_session(self, session_id: str | None) -> dict[str, Any]:
        normalized = (session_id or "").strip() or str(uuid4())
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_sessions (session_id, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO NOTHING
                """,
                (normalized, now, now),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM agent_sessions WHERE session_id = ?", (normalized,)
            ).fetchone()
        return self._session_row(row)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._session_row(row) if row else None

    def set_session_memory(
        self,
        session_id: str,
        values: dict[str, Any],
        *,
        ttl_seconds: int,
        max_items: int,
        now: datetime | None = None,
    ) -> None:
        current = now or datetime.now(timezone.utc)
        created_at = current.isoformat()
        expires_at = (current + timedelta(seconds=max(1, ttl_seconds))).isoformat()
        self.get_or_create_session(session_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for key, value in values.items():
                connection.execute(
                    """INSERT INTO session_memory(session_id, memory_key, value_json, expires_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id, memory_key) DO UPDATE SET
                      value_json=excluded.value_json, expires_at=excluded.expires_at, updated_at=excluded.updated_at""",
                    (session_id, key, _json_dumps(value), expires_at, created_at, created_at),
                )
            connection.execute("DELETE FROM session_memory WHERE expires_at <= ?", (created_at,))
            connection.execute(
                """DELETE FROM session_memory WHERE session_id = ? AND memory_key IN (
                    SELECT memory_key FROM session_memory WHERE session_id = ?
                    ORDER BY updated_at DESC LIMIT -1 OFFSET ?
                )""", (session_id, session_id, max(1, max_items)),
            )
            connection.commit()

    def get_session_memory(self, session_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        current = (now or datetime.now(timezone.utc)).isoformat()
        with self._connect() as connection:
            connection.execute("DELETE FROM session_memory WHERE expires_at <= ?", (current,))
            rows = connection.execute(
                "SELECT memory_key, value_json FROM session_memory WHERE session_id = ? AND expires_at > ?",
                (session_id, current),
            ).fetchall()
            connection.commit()
        return {row["memory_key"]: _json_loads(row["value_json"], None) for row in rows}

    def complete_analysis(
        self,
        session_id: str,
        report_id: str,
        summary: dict[str, Any],
        metadata: dict[str, Any],
        *,
        response: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        self.get_or_create_session(session_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO analysis_runs (
                    report_id, session_id, brand_name, product_name, category, goal,
                    mock_seed, data_confidence, summary_json, source_counts_json,
                    response_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    session_id,
                    metadata.get("brand_name"),
                    metadata.get("product_name"),
                    metadata.get("category"),
                    metadata.get("goal"),
                    metadata.get("mock_seed"),
                    metadata.get("data_confidence"),
                    _json_dumps(summary),
                    _json_dumps(metadata.get("source_counts") or {}),
                    _json_dumps(response) if response is not None else None,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE agent_sessions SET
                    analysis_count = analysis_count + 1,
                    last_report_id = ?,
                    last_brand_name = ?,
                    last_product_name = ?,
                    last_category = ?,
                    last_goal = ?,
                    last_mock_seed = ?,
                    last_summary_json = ?,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (
                    report_id,
                    metadata.get("brand_name"),
                    metadata.get("product_name"),
                    metadata.get("category"),
                    metadata.get("goal"),
                    metadata.get("mock_seed"),
                    _json_dumps(summary),
                    now,
                    session_id,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._session_row(row)

    def list_runs(self, session_id: str, limit: int = 10) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT report_id, session_id, brand_name, product_name, category,
                       goal, mock_seed, data_confidence, summary_json,
                       source_counts_json, created_at
                FROM analysis_runs
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, safe_limit),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["summary"] = _json_loads(item.pop("summary_json"), {})
            item["source_counts"] = _json_loads(item.pop("source_counts_json"), {})
            results.append(item)
        return results

    def get_run(self, report_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT report_id, session_id, brand_name, product_name, category,
                       goal, mock_seed, data_confidence, summary_json,
                       source_counts_json, created_at
                FROM analysis_runs WHERE report_id = ?
                """,
                (report_id,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["summary"] = _json_loads(result.pop("summary_json"), {})
        result["source_counts"] = _json_loads(result.pop("source_counts_json"), {})
        return result

    def save_run_response(self, report_id: str, response: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE analysis_runs SET response_json = ? WHERE report_id = ?",
                (_json_dumps(response), report_id),
            )
            connection.commit()

    def get_run_response(self, report_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM analysis_runs WHERE report_id = ?",
                (report_id,),
            ).fetchone()
        return _json_loads(row["response_json"], {}) if row and row["response_json"] else None

    def save_checkpoint(
        self,
        session_id: str,
        report_id: str,
        stage: str,
        *,
        status: str,
        context: dict[str, Any],
        error_summary: str | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflow_checkpoints (
                    session_id, report_id, stage, status, context_json,
                    error_summary, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, report_id, stage) DO UPDATE SET
                    status = excluded.status,
                    context_json = excluded.context_json,
                    error_summary = excluded.error_summary,
                    updated_at = excluded.updated_at
                """,
                (
                    session_id,
                    report_id,
                    stage,
                    status,
                    _json_dumps(context),
                    error_summary,
                    now,
                    now,
                ),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT * FROM workflow_checkpoints
                WHERE session_id = ? AND report_id = ? AND stage = ?
                """,
                (session_id, report_id, stage),
            ).fetchone()
        result = dict(row)
        result["context"] = _json_loads(result.pop("context_json"), {})
        return result

    def list_checkpoints(self, session_id: str, report_id: str) -> list[dict[str, Any]]:
        stage_order = (
            "CASE stage "
            "WHEN 'received' THEN 1 WHEN 'evidence_ready' THEN 2 "
            "WHEN 'strategy_generated' THEN 3 WHEN 'report_generated' THEN 4 "
            "WHEN 'completed' THEN 5 WHEN 'failed' THEN 6 ELSE 99 END"
        )
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM workflow_checkpoints
                WHERE session_id = ? AND report_id = ?
                ORDER BY {stage_order}, created_at
                """,
                (session_id, report_id),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["context"] = _json_loads(item.pop("context_json"), {})
            results.append(item)
        return results

    @staticmethod
    def _cache_storage_key(namespace: str, cache_key: str) -> str:
        return f"{namespace}:{cache_key}"

    def set_cache(
        self,
        namespace: str,
        cache_key: str,
        payload: dict[str, Any],
        *,
        ttl_seconds: int,
        source_version: str = "v1",
        now: datetime | None = None,
    ) -> None:
        current = now or datetime.now(timezone.utc)
        created_at = current.isoformat()
        expires_at = (current + timedelta(seconds=max(1, ttl_seconds))).isoformat()
        storage_key = self._cache_storage_key(namespace, cache_key)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO common_hit_cache (
                    cache_key, namespace, payload_json, source_version,
                    expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    namespace = excluded.namespace,
                    payload_json = excluded.payload_json,
                    source_version = excluded.source_version,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    storage_key,
                    namespace,
                    _json_dumps(payload),
                    source_version,
                    expires_at,
                    created_at,
                    created_at,
                ),
            )
            connection.commit()

    def get_cache(
        self,
        namespace: str,
        cache_key: str,
        *,
        source_version: str = "v1",
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        current = (now or datetime.now(timezone.utc)).isoformat()
        storage_key = self._cache_storage_key(namespace, cache_key)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM common_hit_cache
                WHERE cache_key = ? AND namespace = ? AND source_version = ?
                  AND expires_at > ?
                """,
                (storage_key, namespace, source_version, current),
            ).fetchone()
        return _json_loads(row["payload_json"], {}) if row else None

    def begin_action(
        self,
        idempotency_key: str,
        action_type: str,
        request_hash: str,
        session_id: str,
        *,
        report_id: str | None = None,
        ttl_seconds: int = 86400,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        now_text = current.isoformat()
        expires_at = (current + timedelta(seconds=max(1, ttl_seconds))).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM submitted_actions WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row and row["expires_at"] <= now_text:
                connection.execute(
                    "DELETE FROM submitted_actions WHERE idempotency_key = ?",
                    (idempotency_key,),
                )
                row = None
            if not row:
                connection.execute(
                    """
                    INSERT INTO submitted_actions (
                        idempotency_key, action_type, request_hash, session_id,
                        report_id, status, expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'processing', ?, ?, ?)
                    """,
                    (
                        idempotency_key,
                        action_type,
                        request_hash,
                        session_id,
                        report_id,
                        expires_at,
                        now_text,
                        now_text,
                    ),
                )
                connection.commit()
                return {"result": "started"}
            if (
                row["action_type"] != action_type
                or row["request_hash"] != request_hash
                or row["session_id"] != session_id
            ):
                connection.commit()
                return {"result": "conflict"}
            if row["status"] == "completed":
                connection.commit()
                return {
                    "result": "replayed",
                    "report_id": row["report_id"],
                    "response_summary": _json_loads(row["response_summary_json"], {}),
                }
            if row["status"] == "failed":
                connection.execute(
                    """
                    UPDATE submitted_actions SET status='processing', report_id=?,
                        response_summary_json='{}', expires_at=?, updated_at=?
                    WHERE idempotency_key=?
                    """,
                    (report_id, expires_at, now_text, idempotency_key),
                )
                connection.commit()
                return {"result": "started"}
            connection.commit()
            return {"result": "processing"}

    def complete_action(
        self,
        idempotency_key: str,
        report_id: str,
        response_summary: dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE submitted_actions
                SET status='completed', report_id=?, response_summary_json=?, updated_at=?
                WHERE idempotency_key=?
                """,
                (report_id, _json_dumps(response_summary), _utc_now(), idempotency_key),
            )
            connection.commit()

    def fail_action(self, idempotency_key: str, response_summary: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE submitted_actions
                SET status='failed', response_summary_json=?, updated_at=?
                WHERE idempotency_key=?
                """,
                (_json_dumps(response_summary), _utc_now(), idempotency_key),
            )
            connection.commit()

    def get_action(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM submitted_actions WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["response_summary"] = _json_loads(result.pop("response_summary_json"), {})
        return result

    def save_feedback(
        self,
        *,
        session_id: str,
        report_id: str,
        rating: str,
        comment: str | None,
        sections: list[str],
        idempotency_key: str,
        field_corrections: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        feedback_id = f"fb_{uuid4().hex}"
        corrections = list(field_corrections or [])
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO feedback_records (
                    feedback_id, session_id, report_id, rating, comment,
                    sections_json, field_corrections_json, idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    feedback_id,
                    session_id,
                    report_id,
                    rating,
                    comment,
                    _json_dumps(sections),
                    _json_dumps(corrections),
                    idempotency_key,
                    _utc_now(),
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM feedback_records WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        result = dict(row)
        result["sections"] = _json_loads(result.pop("sections_json"), [])
        raw_corrections = result.pop("field_corrections_json", "[]")
        result["field_corrections"] = _json_loads(raw_corrections, [])
        return result

    def list_feedback_for_brand(
        self, brand_name: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """按品牌关联 analysis_runs，取近期反馈（含 field_corrections）。"""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT f.*
                FROM feedback_records f
                JOIN analysis_runs r ON r.report_id = f.report_id
                WHERE r.brand_name = ?
                ORDER BY f.created_at DESC
                LIMIT ?
                """,
                (brand_name, max(1, limit)),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["sections"] = _json_loads(item.pop("sections_json"), [])
            item["field_corrections"] = _json_loads(
                item.pop("field_corrections_json", "[]"), []
            )
            results.append(item)
        return results

    def list_backfilled_cases_for_brand(
        self, brand_name: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM backfilled_cases
                WHERE brand_name = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (brand_name, max(1, limit)),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["is_mock"] = bool(item["is_mock"])
            results.append(item)
        return results

    def get_latest_run_by_brand(self, brand_name: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT report_id, session_id, brand_name, product_name, category,
                       goal, mock_seed, data_confidence, summary_json,
                       source_counts_json, response_json, created_at
                FROM analysis_runs
                WHERE brand_name = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (brand_name,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["summary"] = _json_loads(result.pop("summary_json"), {})
        result["source_counts"] = _json_loads(result.pop("source_counts_json"), {})
        raw = result.pop("response_json", None)
        result["response"] = _json_loads(raw, {}) if raw else None
        return result

    def save_alert(
        self,
        *,
        brand_name: str,
        severity: str,
        alert_type: str,
        message: str,
        response: str | None = None,
        source: str = "competitor_monitor",
        report_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        alert_id = f"alert_{uuid4().hex}"
        created_at = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO alert_events (
                    alert_id, brand_name, severity, alert_type, message,
                    response, source, report_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_id,
                    brand_name,
                    severity,
                    alert_type,
                    message,
                    response,
                    source,
                    report_id,
                    _json_dumps(payload or {}),
                    created_at,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM alert_events WHERE alert_id = ?", (alert_id,)
            ).fetchone()
        result = dict(row)
        result["payload"] = _json_loads(result.pop("payload_json"), {})
        return result

    def list_alerts(
        self,
        *,
        brand_name: str | None = None,
        severity: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if brand_name:
            clauses.append("brand_name = ?")
            params.append(brand_name)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(max(1, limit))
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM alert_events
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["payload"] = _json_loads(item.pop("payload_json"), {})
            results.append(item)
        return results

    def save_backfilled_case(
        self,
        *,
        session_id: str,
        report_id: str,
        brand_name: str,
        category: str,
        problem_summary: str,
        strategy_summary: str,
        evidence_grade: str,
        requested_case_type: str,
        is_mock: bool,
    ) -> dict[str, Any]:
        now = _utc_now()
        case_type = "demo_case" if is_mock else requested_case_type
        case_id = f"case_{uuid4().hex}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO backfilled_cases (
                    case_id, session_id, report_id, brand_name, category,
                    problem_summary, strategy_summary, evidence_grade,
                    case_type, is_mock, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    session_id,
                    report_id,
                    brand_name,
                    category,
                    problem_summary,
                    strategy_summary,
                    evidence_grade,
                    case_type,
                    int(is_mock),
                    now,
                    now,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM backfilled_cases WHERE case_id = ?", (case_id,)
            ).fetchone()
        result = dict(row)
        result["is_mock"] = bool(result["is_mock"])
        return result

    def state_status(self, *, now: datetime | None = None) -> dict[str, int]:
        current = (now or datetime.now(timezone.utc)).isoformat()
        tables = (
            "agent_sessions",
            "analysis_runs",
            "feedback_records",
            "backfilled_cases",
            "workflow_checkpoints",
            "submitted_actions",
            "alert_events",
        )
        with self._connect() as connection:
            result = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            }
            result["active_cache"] = connection.execute(
                "SELECT COUNT(*) FROM common_hit_cache WHERE expires_at > ?", (current,)
            ).fetchone()[0]
            result["expired_cache"] = connection.execute(
                "SELECT COUNT(*) FROM common_hit_cache WHERE expires_at <= ?", (current,)
            ).fetchone()[0]
        return result

    def reset_session(self, session_id: str) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute(
                "SELECT 1 FROM agent_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if not exists:
                connection.commit()
                return False
            for table in (
                "session_memory",
                "feedback_records",
                "backfilled_cases",
                "workflow_checkpoints",
                "submitted_actions",
                "analysis_runs",
            ):
                connection.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
            connection.execute(
                "DELETE FROM agent_sessions WHERE session_id = ?", (session_id,)
            )
            connection.commit()
        return True
