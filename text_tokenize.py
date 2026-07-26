"""Chinese tokenization for keyword recall.

Prefer jieba when installed; otherwise longest-match domain lexicon + CJK n-grams.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_SEP_RE = re.compile(r"[/／|｜,，、;；\s\-－—_·•]+")

# Longest-first domain lexicon for XHS gift / bakery / Hong Kong track.
DOMAIN_LEXICON = tuple(
    sorted(
        {
            "香港伴手礼",
            "伴手礼",
            "蝴蝶酥",
            "曲奇四重奏",
            "珍妮曲奇",
            "港式糕点",
            "香港零食",
            "香港特产",
            "香港曲奇",
            "牛油曲奇",
            "手工曲奇",
            "礼盒",
            "送礼",
            "探店",
            "测评",
            "种草",
            "回购",
            "推荐",
            "必买",
            "必吃",
            "下午茶",
            "手信",
            "糕点",
            "曲奇",
            "饼干",
            "零食",
            "特产",
            "香港",
            "澳门",
            "台北",
            "聚光",
            "信息流",
            "搜索推广",
        },
        key=len,
        reverse=True,
    )
)


@lru_cache(maxsize=1)
def _jieba_cutter():
    try:
        import jieba  # type: ignore

        for word in DOMAIN_LEXICON:
            jieba.add_word(word)
        return jieba
    except Exception:
        return None


def _longest_match_segments(text: str) -> list[str]:
    chars = list(text)
    n = len(chars)
    out: list[str] = []
    i = 0
    while i < n:
        matched = None
        for word in DOMAIN_LEXICON:
            wlen = len(word)
            if i + wlen <= n and "".join(chars[i : i + wlen]) == word:
                matched = word
                break
        if matched:
            out.append(matched)
            i += len(matched)
            continue
        ch = chars[i]
        if _CJK_RE.match(ch):
            # consume contiguous CJK run and emit 2/3-grams later via expand
            j = i + 1
            while j < n and _CJK_RE.match(chars[j]):
                j += 1
            out.append("".join(chars[i:j]))
            i = j
        else:
            j = i + 1
            while j < n and not _CJK_RE.match(chars[j]) and not _SEP_RE.match(chars[j]):
                j += 1
            piece = "".join(chars[i:j]).strip().lower()
            if len(piece) >= 2:
                out.append(piece)
            i = j
    return out


def tokenize_text(text: str) -> list[str]:
    """Tokenize one string into keyword pieces (order preserved, de-duped later)."""
    if not text or not str(text).strip():
        return []
    normalized = str(text).strip().lower()
    pieces = [p for p in _SEP_RE.split(normalized) if p]
    tokens: list[str] = []
    jieba = _jieba_cutter()
    for piece in pieces:
        if jieba is not None and _CJK_RE.search(piece):
            tokens.extend(tok.strip() for tok in jieba.lcut(piece) if len(tok.strip()) >= 2)
        else:
            tokens.extend(_longest_match_segments(piece))
        if _CJK_RE.search(piece) and len(piece) >= 4:
            for size in (4, 3, 2):
                for index in range(0, len(piece) - size + 1):
                    gram = piece[index : index + size]
                    if _CJK_RE.search(gram):
                        tokens.append(gram)
    return [tok for tok in tokens if len(tok) >= 2]


def expand_search_terms(terms: Iterable[str], *, max_terms: int = 80) -> list[str]:
    """Expand campaign phrases into keyword tokens for lexical recall."""
    expanded: list[str] = []
    for raw in terms:
        if not raw or not str(raw).strip():
            continue
        text = str(raw).strip().lower()
        expanded.append(text)
        expanded.extend(tokenize_text(text))
    return list(dict.fromkeys(expanded))[:max_terms]
