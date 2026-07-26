"""Normalize competitor links/evidence. Fetch of given URLs is handled in competitor_fetch."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from models import CompetitorEvidence

_NOTE_ID_RE = re.compile(r"/(?:explore|discovery/item)/([0-9a-fA-F]+)")
_MAX_COMPETITORS = 5


def note_id_from_url(url: str) -> str | None:
    match = _NOTE_ID_RE.search(url or "")
    return match.group(1).lower() if match else None


def url_key(url: str) -> str:
    note_id = note_id_from_url(url)
    if note_id:
        return f"note:{note_id}"
    parsed = urlparse((url or "").strip())
    return f"url:{(parsed.netloc + parsed.path).rstrip('/').lower()}"


def stub_from_link(url: str) -> CompetitorEvidence:
    note_id = note_id_from_url(url)
    account = f"对标笔记 {note_id[:8]}" if note_id else "用户提供链接"
    return CompetitorEvidence(
        account_name=account,
        profile_or_note_url=url.strip(),
        note_format=None,
        interactions=None,
        is_ad_labeled=None,
        observed_audience=[],
        content_themes=[],
        title=None,
        notes="给定链接尚未完成抓取或抓取失败，结构化字段待补全。",
        source_name="用户粘贴链接",
        collected_at=None,
        evidence_grade="C_user_provided",
        is_mock=False,
    )


def normalize_competitor_inputs(
    links: list[str] | None,
    evidence: list[CompetitorEvidence] | None,
    *,
    max_items: int = _MAX_COMPETITORS,
) -> list[CompetitorEvidence]:
    """Merge evidence first, then link stubs for URLs not yet covered."""
    merged: list[CompetitorEvidence] = []
    seen: set[str] = set()

    for item in evidence or []:
        key = url_key(item.profile_or_note_url)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= max_items:
            return merged

    for raw in links or []:
        url = (raw or "").strip()
        if not url:
            continue
        key = url_key(url)
        if key in seen:
            continue
        seen.add(key)
        merged.append(stub_from_link(url))
        if len(merged) >= max_items:
            break

    return merged
