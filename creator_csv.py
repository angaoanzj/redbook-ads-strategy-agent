from __future__ import annotations

import csv
import io
from typing import Iterable

from models import CreatorEvidence


REQUIRED_COLUMNS = {"name", "profile_url", "source_name", "collected_at"}


def parse_creator_csv(text: str) -> list[CreatorEvidence]:
    """Parse a UTF-8 CSV of creator candidates into CreatorEvidence rows."""
    sample = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(sample))
    if not reader.fieldnames:
        raise ValueError("CSV 缺少表头")
    headers = {name.strip() for name in reader.fieldnames if name}
    missing = REQUIRED_COLUMNS - headers
    if missing:
        raise ValueError(f"CSV 缺少必要列：{', '.join(sorted(missing))}")

    creators: list[CreatorEvidence] = []
    for row in reader:
        name = (row.get("name") or "").strip()
        profile_url = (row.get("profile_url") or "").strip()
        source_name = (row.get("source_name") or "").strip()
        collected_at = (row.get("collected_at") or "").strip()
        if not name or not profile_url:
            continue
        tags_raw = row.get("audience_tags") or ""
        audience_tags = [
            part.strip()
            for part in tags_raw.replace("，", "|").replace(",", "|").split("|")
            if part.strip()
        ]
        is_mock = _optional_bool(row.get("is_mock"))
        creators.append(
            CreatorEvidence(
                name=name,
                profile_url=profile_url,
                followers=_optional_int(row.get("followers")),
                average_interactions=_optional_int(row.get("average_interactions")),
                quote_cny=_optional_float(row.get("quote_cny")),
                audience_tags=audience_tags,
                past_campaign_result=(row.get("past_campaign_result") or None),
                source_name=source_name or "CSV导入",
                collected_at=collected_at or "unknown",
                is_mock=is_mock,
                evidence_grade="M" if is_mock else (row.get("evidence_grade") or "C_user_provided").strip(),
            )
        )
    if not creators:
        raise ValueError("CSV 未解析到有效达人行")
    return creators


def creators_to_dicts(creators: Iterable[CreatorEvidence]) -> list[dict]:
    return [item.model_dump(mode="json") for item in creators]


def _optional_int(value: str | None) -> int | None:
    text = (value or "").strip()
    if not text:
        return None
    return int(float(text))


def _optional_float(value: str | None) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    return float(text)


def _optional_bool(value: str | None) -> bool:
    text = (value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "mock"}
