"""Deterministic, evidence-backed competitor insight extraction.

This module deliberately reports what the supplied samples support.  It does not
turn a missing competitor mention into a market-wide conclusion.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from models import CompetitorEvidence


# Kept separate so classification boundaries remain reviewable and cannot leak
# a payment condition into trust or an audience tag into interaction.
TOPIC_SIGNALS: Mapping[str, tuple[str, ...]] = {
    "排序测评": ("排序", "测评", "口味"),
    "攻略避坑": ("避坑", "地图", "攻略"),
    "开箱体验": ("开箱", "花费"),
    "伴手礼决策": ("伴手礼", "手信", "必买"),
}
DECISION_INFORMATION_SIGNALS: Mapping[str, tuple[str, ...]] = {
    "门店/地址": ("门店", "店址", "地址"),
    "交通": ("交通", "机场"),
    "营业时段": ("营业时间", "时段"),
    "价格": ("价格", "港币", "花费"),
    "支付": ("支付", "现金", "换汇"),
    "排队/限购": ("排队", "限购"),
    "推荐清单": ("Top", "必买", "推荐"),
    "规格": ("规格", "口味"),
}
TRUST_SIGNALS: Mapping[str, tuple[str, ...]] = {
    "官方/正版门店依据": ("官方", "正版", "正品", "官方门店"),
    "真假辨别依据": ("辨别", "鉴别", "认准", "店招"),
    "实拍/来源说明": ("实拍", "来源", "溯源"),
    "明确价格/规格": ("价格", "规格"),
}
INTERACTION_SIGNALS: Mapping[str, tuple[str, ...]] = {
    "价格": ("价格", "多少钱"),
    "支付": ("现金", "支付", "换汇"),
    "到店/交通": ("机场", "地址", "交通"),
    "代购/寄送": ("代购", "寄送", "快递"),
    "真假/限购": ("真假", "限购"),
}
RISK_SIGNALS: Mapping[str, tuple[str, ...]] = {
    "竞品导流": ("导流",),
    "原料/口感争议": ("质疑", "香精", "人造奶油"),
    "仿品/名誉争议": ("仿品", "无证据指控"),
}
COMMENT_MARKERS = ("评论", "咨询")
COMPARATIVE_RISK_TERMS = ("更好吃",)
DISPUTE_MARKERS = ("争议", "争论", "质疑", "拉踩", "吐槽", "贬低", "引战")
FRAGMENT_SEPARATOR = re.compile(r"[；;。！？!?\n]+")


def _text(item: CompetitorEvidence) -> str:
    return " ".join(
        part
        for part in [
            item.title or "",
            *(item.content_themes or []),
            *(item.observed_audience or []),
            item.notes or "",
        ]
        if part
    )


def _matches(text: str, signal_map: Mapping[str, tuple[str, ...]]) -> list[str]:
    return [label for label, terms in signal_map.items() if any(term in text for term in terms)]


def _source_fragments(item: CompetitorEvidence) -> list[tuple[str, str]]:
    return [
        ("title", item.title or ""),
        *(("content_themes", value) for value in (item.content_themes or [])),
        *(("observed_audience", value) for value in (item.observed_audience or [])),
        ("notes", item.notes or ""),
    ]


def _matched_sources(
    item: CompetitorEvidence,
    signal_map: Mapping[str, tuple[str, ...]],
) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    for label, terms in signal_map.items():
        sources = list(dict.fromkeys(
            source
            for source, text in _source_fragments(item)
            if any(term in text for term in terms)
        ))
        if sources:
            matches.append((label, "/".join(sources)))
    return matches


def _marked_comment_fragments(item: CompetitorEvidence) -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = []
    sources = [
        *(("observed_audience", value) for value in (item.observed_audience or [])),
        ("notes", item.notes or ""),
    ]
    for source, text in sources:
        for fragment in FRAGMENT_SEPARATOR.split(text):
            fragment = fragment.strip()
            if fragment and any(marker in fragment for marker in COMMENT_MARKERS):
                fragments.append((f"{source}:comment_fragment", fragment))
    return fragments


def _all_fragments(item: CompetitorEvidence) -> list[tuple[str, str]]:
    return [
        (source, fragment.strip())
        for source, text in _source_fragments(item)
        for fragment in FRAGMENT_SEPARATOR.split(text)
        if fragment.strip()
    ]


def _canonical_url(raw_url: str) -> str:
    raw_url = str(raw_url or "").strip()
    if not raw_url:
        return ""
    parts = urlsplit(raw_url)
    path = parts.path.rstrip("/") or parts.path
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def _note_identity(url: str) -> str:
    match = re.search(r"/explore/([^/?#]+)", url)
    return f"xhs-note:{match.group(1)}" if match else url


def _ref(item: CompetitorEvidence, signal: str, source: str) -> dict[str, Any]:
    url = _canonical_url(item.profile_or_note_url)
    return {
        "account": item.account_name,
        "title": item.title or "",
        "signal": signal,
        "source": source,
        "url": url,
        "note_id": _note_identity(url),
        "provenance": "raw_note",
    }


def _aggregate_format_ref(
    name: str,
    count: int,
    matched: int,
    normalized_name: str,
) -> dict[str, Any]:
    missing = count - matched
    return {
        "account": "",
        "title": "",
        "signal": f"{name}×{count}",
        "source": "observed_formats",
        "url": "",
        "note_id": f"aggregate:note_format:{normalized_name}",
        "provenance": "aggregate_only",
        "provenance_note": f"聚合计数 {count}；缺少 {missing} 条匹配 note_format 的原始笔记",
    }


def _confidence(total: int, support: int, conclusion_type: str) -> str:
    if conclusion_type == "evidence_insufficient" or not support:
        return "low"
    if total < 5:
        return "low"
    if support == total:
        return "high"
    return "medium"


def _row(
    dimension: str,
    observation: str,
    refs: list[dict[str, Any]],
    total: int,
    *,
    conclusion_type: str | None = None,
    missing_evidence: Sequence[str] = (),
) -> dict[str, Any]:
    support = len({
        str(ref.get("note_id") or ref.get("url"))
        for ref in refs
        if ref.get("provenance") != "aggregate_only"
        and (ref.get("note_id") or ref.get("url"))
    })
    if conclusion_type is None:
        conclusion_type = "inference" if support >= 2 else "sample_observation"
    if not refs:
        conclusion_type = "evidence_insufficient"
    return {
        "dimension": dimension,
        "observation": observation,
        "evidence": refs,
        "sample_count": support,
        "total_samples": total,
        "coverage": round(support / total, 3) if total else 0.0,
        "conclusion_type": conclusion_type,
        "confidence": _confidence(total, support, conclusion_type),
        "missing_evidence": list(missing_evidence),
    }


def _gap_match(point: str, blob: str) -> bool:
    compact = "".join(point.split())
    if compact and compact in blob:
        return True
    # Preserve useful multi-character market phrases without treating generic
    # one-character overlap as coverage of a proprietary selling point.
    phrases = ("香港伴手礼", "香港必买", "伴手礼", "手信", "快递", "寄送")
    return any(phrase in compact and phrase in blob for phrase in phrases)


def assess_content_gaps(
    selling_points: Sequence[str],
    evidence: Sequence[CompetitorEvidence],
    *,
    demand_signals: Sequence[str] = (),
    validated_points: Sequence[str] = (),
) -> dict[str, Any]:
    """Return covered selling points and explicitly staged gap candidates."""
    blob = " ".join(_text(item) for item in evidence)
    demand_blob = " ".join(demand_signals)
    validated = set(validated_points)
    covered_points: list[str] = []
    candidates: list[dict[str, Any]] = []
    for point in selling_points:
        point = str(point).strip()
        if not point:
            continue
        if _gap_match(point, blob):
            covered_points.append(point)
            continue
        if point in validated:
            stage, conclusion_type = "validated_opportunity", "fact"
        elif _gap_match(point, demand_blob):
            stage, conclusion_type = "opportunity_hypothesis", "hypothesis"
        else:
            stage, conclusion_type = "sample_uncovered", "hypothesis"
        evidence_basis = {
            "validated_opportunity": "当前竞品样本未覆盖；已提供用户需求与效果验证",
            "opportunity_hypothesis": "当前竞品样本未覆盖；已有用户需求或搜索信号支持",
            "sample_uncovered": "当前竞品样本未覆盖该卖点",
        }[stage]
        candidates.append({
            "point": point,
            "stage": stage,
            "conclusion_type": conclusion_type,
            "evidence_basis": evidence_basis,
            "validation_required": stage != "validated_opportunity",
        })

    by_stage = {
        stage: [row["point"] for row in candidates if row["stage"] == stage]
        for stage in ("validated_opportunity", "opportunity_hypothesis", "sample_uncovered")
    }
    conclusions: list[str] = []
    if by_stage["validated_opportunity"]:
        conclusions.append("已验证机会：" + "、".join(by_stage["validated_opportunity"]))
    if by_stage["opportunity_hypothesis"]:
        conclusions.append(
            "需求信号支持、效果待验证：" + "、".join(by_stage["opportunity_hypothesis"])
        )
    if by_stage["sample_uncovered"]:
        conclusions.append(
            "样本内未覆盖候选："
            + "、".join(by_stage["sample_uncovered"])
            + "；不等同于市场空白"
        )

    missing: list[str] = []
    if by_stage["sample_uncovered"]:
        missing.append("用户需求或搜索信号")
    if by_stage["sample_uncovered"] or by_stage["opportunity_hypothesis"]:
        missing.append("自然/付费测试效果")
    if not evidence:
        missing.insert(0, "可用竞品样本")
    return {
        "covered_points": covered_points,
        "gap_selling_points": [row["point"] for row in candidates],
        "candidates": candidates,
        "opportunities": [row for row in candidates if row["stage"] != "sample_uncovered"],
        "decision_conclusion": "；".join(conclusions) + ("。" if conclusions else ""),
        "status": (
            "evidence_insufficient"
            if not evidence
            else "validated_opportunity"
            if candidates and all(row["stage"] == "validated_opportunity" for row in candidates)
            else "sample_assessment"
        ),
        "missing_evidence": missing,
    }


def build_competitor_insight_rows(
    evidence: Sequence[CompetitorEvidence],
    *,
    content_gap_analysis: Mapping[str, Any] | None = None,
    observed_formats: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Return the seven compatible rows used by the deep-analysis board."""
    items = list(evidence)
    total = len(items)

    topic_refs: list[dict[str, Any]] = []
    topic_labels: list[str] = []
    decision_refs: list[dict[str, Any]] = []
    decision_labels: list[str] = []
    trust_refs: list[dict[str, Any]] = []
    trust_labels: list[str] = []
    interaction_refs: list[dict[str, Any]] = []
    interaction_labels: list[str] = []
    risk_refs: list[dict[str, Any]] = []
    risk_labels: list[str] = []
    for item in items:
        for label, source in _matched_sources(item, TOPIC_SIGNALS):
            topic_labels.append(label)
            topic_refs.append(_ref(item, label, source))
        for label, source in _matched_sources(item, DECISION_INFORMATION_SIGNALS):
            decision_labels.append(label)
            decision_refs.append(_ref(item, label, source))
        for label, source in _matched_sources(item, TRUST_SIGNALS):
            trust_labels.append(label)
            trust_refs.append(_ref(item, label, source))
        for source, fragment in _marked_comment_fragments(item):
            for label in _matches(fragment, INTERACTION_SIGNALS):
                interaction_labels.append(label)
                interaction_refs.append(_ref(item, f"评论/咨询：{label}", source))
        for label, source in _matched_sources(item, RISK_SIGNALS):
            risk_labels.append(label)
            risk_refs.append(_ref(item, label, source))
        comparison_sources = list(dict.fromkeys(
            source
            for source, fragment in _all_fragments(item)
            if any(term in fragment for term in COMPARATIVE_RISK_TERMS)
            and any(marker in fragment for marker in DISPUTE_MARKERS)
        ))
        if comparison_sources:
            risk_labels.append("原料/口感争议")
            risk_refs.append(_ref(item, "原料/口感争议", "/".join(comparison_sources)))

    def unique(labels: Sequence[str]) -> list[str]:
        return list(dict.fromkeys(labels))

    rows = [
        _row(
            "选题",
            f"样本选题：{'、'.join(unique(topic_labels))}" if topic_labels else "未发现可归类的选题信号。",
            topic_refs,
            total,
            missing_evidence=("需补充更多笔记样本以判断跨样本共性",) if len({r['account'] for r in topic_refs}) < 2 else (),
        ),
        _row(
            "信息密度",
            f"决策信息组合：{'、'.join(unique(decision_labels))}" if decision_labels else "未见可追溯的决策信息组合。",
            decision_refs,
            total,
            missing_evidence=("需补充地址、价格、支付或推荐清单等原始内容",) if not decision_refs else (),
        ),
        _row(
            "信任机制",
            f"购买风险降低依据：{'、'.join(unique(trust_labels))}" if trust_labels else "未见可追溯的购买风险降低依据。",
            trust_refs,
            total,
            missing_evidence=("需补充官方/正版依据、辨别步骤、实拍或来源说明",) if not trust_refs else (),
        ),
        _row(
            "互动引擎",
            f"评论/咨询集中在：{'、'.join(unique(interaction_labels))}" if interaction_labels else "未见可追溯的评论或咨询触发话题。",
            interaction_refs,
            total,
            missing_evidence=("需补充原始评论摘要、咨询问题或互动记录",) if not interaction_refs else (),
        ),
        _row(
            "扩散风险",
            f"已观察到：{'、'.join(unique(risk_labels))}" if risk_labels else "未见可追溯的争议或竞品导流信号。",
            risk_refs,
            total,
            missing_evidence=("需补充争议原文、导流评论或合规证据",) if not risk_refs else (),
        ),
    ]

    format_counts = Counter()
    format_refs: list[dict[str, Any]] = []
    format_missing: list[str] = []
    if observed_formats:
        items_by_format: dict[str, list[CompetitorEvidence]] = defaultdict(list)
        for item in items:
            normalized = str(item.note_format or "").strip().casefold()
            if normalized:
                items_by_format[normalized].append(item)
        consumed: Counter[str] = Counter()
        for row in observed_formats:
            name = str(row.get("format") or "").strip()
            count = int(row.get("sample_count") or 0)
            if not name or count <= 0:
                continue
            format_counts[name] += count
            normalized = name.casefold()
            start = consumed[normalized]
            matched_items = items_by_format.get(normalized, [])[start:start + count]
            consumed[normalized] += len(matched_items)
            for item in matched_items:
                format_refs.append(_ref(item, name, "observed_formats"))
            if len(matched_items) < count:
                missing = count - len(matched_items)
                format_refs.append(
                    _aggregate_format_ref(name, count, len(matched_items), normalized)
                )
                format_missing.append(
                    f"{name}×{count} 缺少 {missing} 条 note_format 匹配的原始笔记"
                )
    else:
        format_counts.update((item.note_format or "未知").strip() or "未知" for item in items)
        format_refs = [
            _ref(item, item.note_format or "未知", "note_format")
            for item in items
        ]
    format_observation = "、".join(f"{name}×{count}" for name, count in format_counts.most_common())
    rows.append(_row(
        "内容形式",
        f"观察到的内容形式：{format_observation}" if format_observation else "未提供内容形式样本。",
        format_refs,
        total,
        conclusion_type=(
            "fact"
            if format_refs and not format_missing
            else "evidence_insufficient"
        ),
        missing_evidence=(
            format_missing
            or (["需补充笔记形式或样本计数"] if not format_refs else [])
        ),
    ))

    gaps = content_gap_analysis or assess_content_gaps((), items)
    candidates = list(gaps.get("candidates") or [])
    gap_refs = [_ref(item, "当前竞品样本", "competitor_evidence") for item in items] if candidates else []
    if candidates:
        gap_text = str(gaps.get("decision_conclusion") or "").strip()
        gap_conclusion_type = (
            "fact"
            if all(row.get("conclusion_type") == "fact" for row in candidates)
            else "hypothesis"
        )
    else:
        gap_text = "未提供待比较的自有卖点；无法判断内容空白。"
        gap_conclusion_type = "evidence_insufficient"
    gap_missing = (
        gaps["missing_evidence"]
        if "missing_evidence" in gaps
        else ["需提供自有卖点、用户需求与效果测试"]
    )
    gap_row = _row(
        "内容空白",
        gap_text,
        gap_refs,
        total,
        conclusion_type=gap_conclusion_type,
        missing_evidence=gap_missing,
    )
    gap_row["candidate_stages"] = candidates
    rows.append(gap_row)
    return rows
