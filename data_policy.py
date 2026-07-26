"""真实数据优先；只有目标字段无真实记录时才返回模拟记录。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


REAL_TO_MOCK = {
    "business_metrics": ("business_metrics", "mock_business_metrics"),
    "paid_details": ("paid_details", "mock_paid_details"),
}


def metric_with_fallback(db: Path, kind: str, brand_name: str, period: str) -> dict[str, Any] | None:
    """按字段和期间选择数据；返回结果中带 is_mock，便于前端展示标签。"""
    if kind not in REAL_TO_MOCK:
        raise ValueError(f"unsupported kind: {kind}")
    real_table, mock_table = REAL_TO_MOCK[kind]
    with sqlite3.connect(db) as conn:
        # 真实经营/投放明细需要由品牌后台导入后写入 real 表。
        for table, is_mock in ((real_table, 0), (mock_table, 1)):
            try:
                exists = conn.execute(
                    f"SELECT data_json, source_name, evidence_grade FROM {table} WHERE brand_name=? AND period=? LIMIT 1",
                    (brand_name, period),
                ).fetchone()
            except sqlite3.OperationalError:
                exists = None
            if exists:
                return {**json.loads(exists[0]), "source_name": exists[1], "evidence_grade": exists[2], "is_mock": is_mock}
    return None


def notes_with_fallback(db: Path, *, limit: int = 30) -> list[dict[str, Any]]:
    """有真实笔记时只返回真实笔记；没有真实笔记时才返回模拟笔记。"""
    with sqlite3.connect(db) as conn:
        real = conn.execute("SELECT note_id, title, note_url, source_name, evidence_grade FROM notes LIMIT ?", (limit,)).fetchall()
        if real:
            return [{"note_id": r[0], "title": r[1], "note_url": r[2], "source_name": r[3], "evidence_grade": r[4], "is_mock": 0} for r in real]
        mock = conn.execute("SELECT data_json FROM mock_content_notes ORDER BY note_id LIMIT ?", (limit,)).fetchall()
    return [{**json.loads(r[0]), "is_mock": 1} for r in mock]
