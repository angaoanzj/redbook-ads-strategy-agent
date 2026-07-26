"""Fetch structured fields from user-given Xiaohongshu note URLs only.

Scope: at most a handful of explore/discovery links provided by the user.
Does not crawl search result pages or bulk category datasets.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from competitor_input import note_id_from_url
from models import CompetitorEvidence

_FIXTURE_PATH = Path(__file__).resolve().parent / "examples" / "jenny_benchmark_competitor_evidence.json"

_META_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']*)["\']',
    re.I,
)
_META_RE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']([^"\']+)["\']',
    re.I,
)
_TAG_RE = re.compile(r"#([^\s#]+)")
_AUTHOR_RE = re.compile(
    r'class="[^"]*username[^"]*"[^>]*>\s*([^<]+)|'
    r'"nickname"\s*:\s*"([^"\\]+)"|'
    r'<a[^>]+class="[^"]*name[^"]*"[^>]*>([^<]+)',
    re.I,
)
_AD_NEAR_NOTE_RE = re.compile(
    r'(?:class|aria-label)=["\'][^"\']*(?:advertise|ad-tag|note-ad)[^"\']*["\']|'
    r'>\s*广告\s*<|'
    r'"adType"\s*:\s*"[^"]+"|'
    r'"isAds?"\s*:\s*true',
    re.I,
)
_AUDIENCE_HINTS = (
    ("到港游客", ("香港", "到港", "尖沙咀", "上环", "手信", "伴手礼")),
    ("价格敏感", ("多少钱", "价格", "港币", "¥", "元")),
    ("现金支付咨询", ("现金", "只收现金", "换汇", "支付宝", "微信")),
    ("机场与行李", ("机场", "行李", "托运")),
    ("代购寄送", ("代购", "快递", "寄", "运输")),
    ("避坑攻略党", ("避坑", "假店", "正版", "只认")),
)
_THEME_HINTS = (
    ("口味排序测评", ("排序", "好吃", "第一名", "测评")),
    ("正版门店地图", ("门店", "地址", "地铁", "地图", "只认")),
    ("避坑假店", ("避坑", "假", "认准")),
    ("只收现金", ("现金",)),
    ("花费开箱", ("港币", "排队", "开箱", "买了")),
    ("必买Top3", ("必买", "top", "推荐")),
    ("香港伴手礼", ("伴手礼", "手信")),
    ("珍妮曲奇", ("珍妮", "jenny", "聪明小熊")),
)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _parse_meta(html: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for match in _META_RE.finditer(html or ""):
        meta[match.group(1)] = unescape(match.group(2))
    for match in _META_RE_ALT.finditer(html or ""):
        meta.setdefault(match.group(2), unescape(match.group(1)))
    return meta


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    text = str(value).strip().replace(",", "")
    try:
        if text.endswith(("万", "w", "W")):
            return int(float(text[:-1]) * 10000)
        return int(float(text))
    except ValueError:
        return None


def _extract_author(html: str, meta: dict[str, str]) -> str:
    for match in _AUTHOR_RE.finditer(html or ""):
        for group in match.groups():
            if group and group.strip() and group.strip() not in {"关注", "登录"}:
                return group.strip()[:40]
    title = meta.get("og:title") or meta.get("title") or ""
    return title.split("-")[0].strip()[:40] or "未知作者"


def _detect_ad_label(html: str) -> bool | None:
    # Footer links like「推广合作」must not count as note-level 广告.
    head = (html or "")[:120000]
    if _AD_NEAR_NOTE_RE.search(head):
        return True
    # Explicit note JSON flags sometimes appear in SSR payload.
    if re.search(r'"ads?"\s*:\s*true', head, re.I):
        return True
    if "og:title" in head or "og:xhs:note_like" in head:
        return False
    return None


def _themes_from_text(title: str, description: str, keywords: str) -> list[str]:
    blob = f"{title} {description} {keywords}".casefold()
    themes: list[str] = []
    for theme, keys in _THEME_HINTS:
        if any(key.casefold() in blob for key in keys):
            themes.append(theme)
    for tag in _TAG_RE.findall(description or ""):
        cleaned = tag.strip()
        if cleaned and cleaned not in themes:
            themes.append(cleaned)
    for part in re.split(r"[,，、\s]+", keywords or ""):
        cleaned = part.strip()
        if cleaned and cleaned not in themes:
            themes.append(cleaned)
    return themes[:10]


def _audience_from_text(description: str, body: str) -> list[str]:
    blob = f"{description} {body}".casefold()
    hits = []
    for label, keys in _AUDIENCE_HINTS:
        if any(key.casefold() in blob for key in keys):
            hits.append(label)
    return hits[:8]


def _note_format(description: str, html: str) -> str:
    if '"type":"video"' in html or "video" in (description or "").casefold():
        # Prefer image-set when SSR shows image carousel marker.
        if re.search(r"\b1/\d+\b", html):
            return "图集"
        return "视频"
    if re.search(r"\b1/\d+\b", html):
        return "图集"
    return "图集"


def parse_note_html(url: str, html: str) -> CompetitorEvidence:
    meta = _parse_meta(html)
    title = (meta.get("og:title") or "").replace(" - 小红书", "").strip()
    description = meta.get("og:description") or meta.get("description") or ""
    keywords = meta.get("keywords") or ""
    likes = _to_int(meta.get("og:xhs:note_like"))
    collects = _to_int(meta.get("og:xhs:note_collect"))
    comments = _to_int(meta.get("og:xhs:note_comment"))
    # OG 缺评论数时，尝试从页面 JSON 回退
    if comments is None:
        for pattern in (
            r'"commentCount"\s*:\s*(\d+)',
            r'"comments?"\s*:\s*(\d+)',
            r'"comment_count"\s*:\s*(\d+)',
        ):
            match = re.search(pattern, html or "", re.I)
            if match:
                comments = _to_int(match.group(1))
                if comments is not None:
                    break
    interactions = None
    if likes is not None or collects is not None or comments is not None:
        interactions = (likes or 0) + (collects or 0) + (comments or 0)
    author = _extract_author(html, meta)
    ad_labeled = _detect_ad_label(html)
    # 已拿到公开互动元数据且无广告标识信号时，按「未见广告标识」处理
    if ad_labeled is None and interactions is not None:
        ad_labeled = False
    themes = _themes_from_text(title, description, keywords)
    audience = _audience_from_text(description, html)
    collected_at = datetime.now(timezone.utc).date().isoformat()
    note_id = note_id_from_url(url)
    notes_bits = [
        f"脚本抓取给定链接（note_id={note_id or 'n/a'}）",
        f"赞{likes if likes is not None else '—'} / 藏{collects if collects is not None else '—'} / 评{comments if comments is not None else '—'}",
    ]
    if ad_labeled is True:
        notes_bits.append("检测到广告标识相关信号")
    elif ad_labeled is False:
        notes_bits.append("公开页未见广告标识")
    else:
        notes_bits.append("广告标识未能从公开页判定")
    return CompetitorEvidence(
        account_name=author,
        profile_or_note_url=url.strip(),
        title=title or None,
        note_format=_note_format(description, html),
        interactions=interactions,
        likes=likes,
        favorites=collects,
        comments=comments,
        is_ad_labeled=ad_labeled,
        observed_audience=audience,
        content_themes=themes,
        notes="；".join(notes_bits),
        source_name="给定链接公开页抓取",
        collected_at=collected_at,
        evidence_grade="B_public_page_fetch",
        is_mock=False,
    )


def fetch_note_html(url: str, *, timeout: float = 12.0) -> str:
    host = urlparse(url).netloc
    if "xiaohongshu.com" not in host:
        raise ValueError(f"仅支持小红书链接: {url}")
    with httpx.Client(headers=_DEFAULT_HEADERS, follow_redirects=True, timeout=timeout) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _fixture_evidence(note_id: str, url: str) -> CompetitorEvidence | None:
    if not _FIXTURE_PATH.exists():
        return None
    try:
        payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for row in payload.get("competitor_evidence") or []:
        if note_id_from_url(str(row.get("profile_or_note_url") or "")) == note_id:
            item = CompetitorEvidence.model_validate(row)
            return item.model_copy(update={
                "profile_or_note_url": url.strip(),
                "source_name": "给定链接抓取失败·本地示例缓存回退",
                "notes": (item.notes or "") + "；直播抓取失败时使用同 note_id 本地缓存",
            })
    return None


def fetch_competitor_from_url(
    url: str,
    *,
    timeout: float = 12.0,
    allow_fixture_fallback: bool = True,
) -> CompetitorEvidence:
    note_id = note_id_from_url(url)
    try:
        html = fetch_note_html(url, timeout=timeout)
        evidence = parse_note_html(url, html)
        thin_page = (
            evidence.interactions is None
            and evidence.likes is None
            and not evidence.title
            and not evidence.content_themes
        )
        if thin_page:
            raise RuntimeError("公开页未返回可用笔记元数据（可能被登录墙拦截）")
        return evidence
    except Exception as exc:
        if allow_fixture_fallback and note_id:
            cached = _fixture_evidence(note_id, url)
            if cached is not None:
                return cached
        raise RuntimeError(str(exc)) from exc


def _is_stub_account(name: str | None) -> bool:
    text = (name or "").strip()
    return (not text) or text.startswith("对标笔记") or text in {"未知作者", "用户提供链接"}


def _richness_score(item: CompetitorEvidence) -> int:
    score = 0
    if item.interactions is not None:
        score += 4
    if item.likes is not None:
        score += 3
    if item.favorites is not None:
        score += 2
    if item.comments is not None:
        score += 2
    if item.title:
        score += 2
    if item.content_themes:
        score += 2
    if item.is_ad_labeled is not None:
        score += 1
    if item.observed_audience:
        score += 1
    if not _is_stub_account(item.account_name):
        score += 2
    else:
        score -= 3
    return score


def _merge_competitor_evidence(
    primary: CompetitorEvidence,
    secondary: CompetitorEvidence | None,
) -> CompetitorEvidence:
    """Keep the richer structured fields when live fetch returns a thin page."""
    if secondary is None:
        return primary
    if _richness_score(secondary) > _richness_score(primary):
        base, overlay = secondary, primary
    else:
        base, overlay = primary, secondary
    data = base.model_dump()
    overlay_data = overlay.model_dump()
    for key, value in overlay_data.items():
        current = data.get(key)
        empty = current in (None, "", [])
        if empty and value not in (None, "", []):
            data[key] = value
    if _is_stub_account(data.get("account_name")) and not _is_stub_account(
        overlay_data.get("account_name")
    ):
        data["account_name"] = overlay_data["account_name"]
    # Prefer explicit like/fav/comment split; recompute interactions when possible.
    likes = data.get("likes")
    favorites = data.get("favorites")
    comments = data.get("comments")
    if likes is not None or favorites is not None or comments is not None:
        data["interactions"] = (likes or 0) + (favorites or 0) + (comments or 0)
    elif data.get("interactions") is None and secondary.interactions is not None:
        data["interactions"] = secondary.interactions
    notes = [part for part in [base.notes, overlay.notes] if part]
    if notes:
        # Keep unique note fragments, prefer longer/base first.
        seen: set[str] = set()
        merged_notes: list[str] = []
        for part in notes:
            for frag in str(part).split("；"):
                cleaned = frag.strip()
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    merged_notes.append(cleaned)
        data["notes"] = "；".join(merged_notes)[:500]
    return CompetitorEvidence.model_validate(data)


def _is_structured(item: CompetitorEvidence) -> bool:
    return _richness_score(item) >= 3


def enrich_links_to_evidence(
    links: list[str],
    *,
    existing: list[CompetitorEvidence] | None = None,
    max_items: int = 5,
    fetch_enabled: bool = True,
    timeout: float = 12.0,
) -> tuple[list[CompetitorEvidence], list[dict[str, Any]]]:
    """Fetch user-given note URLs in real time.

    When the user pastes competitor links, those links are the sole source —
    older full-case evidence is only used to enrich the *same* note URL, never
    to append unrelated accounts (e.g. 帝苑 stub rows).
    Live fetch must not wipe richer imported/fixture fields when the public page
    is a login shell without og:xhs engagement meta.
    """
    from competitor_input import stub_from_link, url_key

    existing_items = list(existing or [])
    link_urls = [(raw or "").strip() for raw in (links or []) if (raw or "").strip()]
    existing_by_key = {
        url_key(item.profile_or_note_url): item
        for item in existing_items
        if item.profile_or_note_url
    }

    # 有粘贴链接：只处理这些链接；无链接时才回退到已有证据列表
    ordered_urls: list[str] = []
    seen_order: set[str] = set()
    source_urls = link_urls or [
        (item.profile_or_note_url or "").strip()
        for item in existing_items
        if (item.profile_or_note_url or "").strip()
    ]
    for url in source_urls:
        key = url_key(url)
        if key in seen_order:
            continue
        seen_order.add(key)
        ordered_urls.append(url)

    link_keys = {url_key(url) for url in link_urls}
    merged: list[CompetitorEvidence] = []
    seen: set[str] = set()
    trace: list[dict[str, Any]] = []

    for url in ordered_urls:
        if len(merged) >= max_items:
            break
        key = url_key(url)
        if key in seen:
            continue
        seen.add(key)
        is_user_link = key in link_keys if link_keys else True
        existing_item = existing_by_key.get(key)
        should_fetch = bool(fetch_enabled and note_id_from_url(url) and is_user_link)

        if existing_item is not None and _is_structured(existing_item) and not should_fetch:
            merged.append(existing_item)
            trace.append({
                "url": url,
                "status": "reused_existing",
                "account_name": existing_item.account_name,
            })
            continue

        if not should_fetch:
            if existing_item is not None and _is_structured(existing_item):
                merged.append(existing_item)
                trace.append({"url": url, "status": "reused_existing", "reason": "fetch_disabled"})
            elif existing_item is not None:
                merged.append(existing_item)
                trace.append({"url": url, "status": "reused_thin_existing", "reason": "fetch_disabled"})
            else:
                merged.append(stub_from_link(url))
                trace.append({"url": url, "status": "stub_only", "reason": "fetch_disabled_or_not_note"})
            continue

        try:
            item = fetch_competitor_from_url(url, timeout=timeout)
            item = _merge_competitor_evidence(item, existing_item)
            # Live shell pages often return author/themes without engagement.
            # Prefer structured import/fixture when fetch is still thin.
            if existing_item is not None and _richness_score(existing_item) > _richness_score(item):
                item = _merge_competitor_evidence(existing_item, item)
                status = "fetch_merged_existing_richer"
            else:
                status = "fetched" if existing_item is None else "fetch_merged_existing"
            merged.append(item)
            trace.append({
                "url": url,
                "status": status,
                "account_name": item.account_name,
                "interactions": item.interactions,
                "likes": item.likes,
                "favorites": item.favorites,
                "comments": item.comments,
                "is_ad_labeled": item.is_ad_labeled,
                "richness": _richness_score(item),
            })
        except Exception as exc:  # noqa: BLE001 - surface per-link failure, keep pipeline
            if existing_item is not None and _is_structured(existing_item):
                merged.append(existing_item)
                trace.append({
                    "url": url,
                    "status": "fetch_failed_reused_existing",
                    "error": str(exc)[:240],
                })
            else:
                stub = stub_from_link(url)
                stub.notes = f"给定链接抓取失败：{exc}；已降级为链接占位"
                stub.source_name = "给定链接抓取失败占位"
                merged.append(stub)
                trace.append({"url": url, "status": "fetch_failed", "error": str(exc)[:240]})
    return merged[:max_items], trace
