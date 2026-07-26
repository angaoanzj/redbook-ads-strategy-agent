"""证据聚合共用工具：供模块1（自然格局）与模块4（投放时段）复用。

只做确定性聚合，不 import engine，不依赖 LLM。发布时段桶的口径两个模块保持一致，
避免模块1 判读高互动时段、模块4 建议投放时段时出现两套时段定义。

时间口径：published_at 先解析为带时区时间，再转到北京时间（UTC+8）取小时。
无时区偏移的时间戳按 UTC 解释（与知识库常见 ISO/Z 存储一致）。
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

BEIJING_TZ = timezone(timedelta(hours=8))
_HOUR_RE = re.compile(r"[T\s](\d{2}):")

# 看板展示分桶（与对标金样 11-14 / 16-20 / 其他 对齐）
PEAK_DISPLAY_BUCKETS = (
    ("11-14点", frozenset(range(11, 14))),
    ("16-20点", frozenset(range(16, 20))),
)


def note_interactions(note: Any) -> int:
    """一条笔记的互动量合计（likes+favorites+comments+shares，缺失记 0）。"""
    return sum(
        int(getattr(note, field) or 0)
        for field in ("likes", "favorites", "comments", "shares")
    )


def parse_published_at(published_at: str | None) -> datetime | None:
    """解析发布时间；失败返回 None。无偏移按 UTC。"""
    if not published_at:
        return None
    text = str(published_at).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def to_beijing(dt: datetime) -> datetime:
    return dt.astimezone(BEIJING_TZ)


def extract_hour(published_at: str | None) -> int | None:
    """从 published_at 抽取北京时间 0-23 小时。"""
    parsed = parse_published_at(published_at)
    if parsed is not None:
        return to_beijing(parsed).hour
    if not published_at:
        return None
    match = _HOUR_RE.search(str(published_at))
    if match:
        hour = int(match.group(1))
        if 0 <= hour <= 23:
            # 回退：无法解析时区时，仍取字面小时并标注由调用方自行声明
            return hour
    return None


def hour_bucket(hour: int) -> str:
    """把北京时间小时映射到模块内时段桶。"""
    if 6 <= hour < 11:
        return "早间(06-11)"
    if 11 <= hour < 14:
        return "午间(11-14)"
    if 14 <= hour < 16:
        return "下午(14-16)"
    if 16 <= hour < 20:
        return "晚间种草(16-20)"
    if 20 <= hour < 23:
        return "夜间(20-23)"
    return "深夜(23-06)"


def peak_display_bucket(hour: int) -> str:
    """看板柱状图分桶：11-14点 / 16-20点 / 其他。"""
    for label, hours in PEAK_DISPLAY_BUCKETS:
        if hour in hours:
            return label
    return "其他"


def aggregate_time_slots(notes: Iterable[Any]) -> list[dict[str, Any]]:
    """按时段桶聚合笔记数与互动量，按互动量降序（次按笔记数降序）。

    返回：[{"slot": str, "count": int, "interaction_sum": int}, ...]
    仅统计能解析出 published_at 小时的笔记；无可用时段返回空列表。
    """
    slot_counts: Counter[str] = Counter()
    slot_interactions: Counter[str] = Counter()
    for note in notes:
        hour = extract_hour(getattr(note, "published_at", None))
        if hour is None:
            continue
        slot = hour_bucket(hour)
        slot_counts[slot] += 1
        slot_interactions[slot] += note_interactions(note)
    rows = [
        {
            "slot": slot,
            "count": count,
            "interaction_sum": slot_interactions[slot],
        }
        for slot, count in slot_counts.items()
    ]
    rows.sort(key=lambda row: (row["interaction_sum"], row["count"]), reverse=True)
    return rows


def aggregate_peak_display_slots(notes: Iterable[Any]) -> list[dict[str, Any]]:
    """按看板三桶聚合（北京时间），固定顺序 11-14 / 16-20 / 其他。"""
    counts: Counter[str] = Counter()
    interactions: Counter[str] = Counter()
    for note in notes:
        hour = extract_hour(getattr(note, "published_at", None))
        if hour is None:
            continue
        slot = peak_display_bucket(hour)
        counts[slot] += 1
        interactions[slot] += note_interactions(note)
    order = ["11-14点", "16-20点", "其他"]
    rows: list[dict[str, Any]] = []
    for slot in order:
        count = int(counts.get(slot) or 0)
        if count <= 0:
            continue
        rows.append(
            {
                "slot": slot,
                "count": count,
                "average_interactions": round(interactions[slot] / count, 1),
            }
        )
    return rows
