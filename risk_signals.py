"""Build short, homework-ready risk signals for module-1 / benchmark board."""

from __future__ import annotations

from typing import Any

from models import CampaignRequest, CompetitorEvidence

# 食品/伴手礼赛道常见限流与争议内容类型（规则映射，非台账频次）
_CATEGORY_CONTENT_PLAYBOOK = (
    ("绝对化/最高级表述", ("最强", "只认", "第一", "全网", "本地人盖章", "必买榜首")),
    ("真假店/仿品对抗", ("假店", "仿品", "正版", "避坑", "认准")),
    ("原料/添加剂质疑", ("香精", "人造奶油", "原料", "防腐", "添加剂")),
    ("食品功效/治疗暗示", ("功效", "治疗", "改善", "养生", "瘦身", "降糖")),
    ("导流私域/站外成交", ("微信", "二维码", "私域", "代购", "留资", "手机号")),
    ("跨境宣传不一致", ("跨境", "境外", "港币", "只收现金", "资质")),
    ("虚假稀缺/低差营销", ("仅此一家", "最后一天", "清仓", "假货")),
)

_REJECTION_SHORT_LABELS = (
    ("食品功效夸大", ("功效", "特殊化妆品", "普通食品不得", "治疗", "改善")),
    ("虚假或夸大宣传", ("虚假", "夸大", "误导")),
    ("导流联系方式", ("微信", "二维码", "电话", "联系方式", "私信成交")),
    ("资质与证照不符", ("资质", "证照", "许可证", "备案")),
    ("跨境广告规范", ("跨境", "境外", "禁投")),
    ("低俗或不当营销", ("低俗", "低差", "擦边")),
    ("绝对化承诺", ("最", "第一", "绝对", "保证")),
)


def _shorten(text: str, limit: int = 42) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    for sep in ("。", "；", ";", "\n", "："):
        if sep in cleaned:
            head = cleaned.split(sep, 1)[0].strip()
            if 6 <= len(head) <= limit:
                return head
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _match_labels(blob: str, catalog: tuple[tuple[str, tuple[str, ...]], ...]) -> list[str]:
    text = (blob or "").casefold()
    hits: list[str] = []
    for label, keys in catalog:
        if any(key.casefold() in text for key in keys):
            hits.append(label)
    return hits


def _official_items(risk: dict[str, Any]) -> list[dict[str, Any]]:
    items = (risk.get("official_rules") or {}).get("confirmed_types") or []
    return [item for item in items if isinstance(item, dict)]


def _ledger_rows(risk: dict[str, Any]) -> list[dict[str, Any]]:
    rows = (risk.get("category_high_frequency_violations") or {}).get("ranked_reasons") or []
    if rows:
        return [row for row in rows if isinstance(row, dict)]
    return [
        row
        for row in ((risk.get("frequent_ad_rejection_reasons") or {}).get("account_ledger_reasons") or [])
        if isinstance(row, dict)
    ]


def build_risk_signal_pack(
    req: CampaignRequest,
    risk: dict[str, Any],
    evidence: list[CompetitorEvidence] | None = None,
) -> dict[str, Any]:
    """Return structured risk pack for report chapter + benchmark board."""
    evidence = list(evidence or req.competitor_evidence or [])
    official = _official_items(risk)
    ledger = _ledger_rows(risk)
    review_items = (risk.get("frequent_ad_rejection_reasons") or {}).get("confirmed_reasons") or []
    if not isinstance(review_items, list):
        review_items = []

    evidence_blob = " ".join(
        f"{item.title or ''} {' '.join(item.content_themes or [])} {item.notes or ''} "
        f"{' '.join(item.observed_audience or [])}"
        for item in evidence
    )
    category_blob = f"{req.category} {req.product_name} {' '.join(req.selling_points)}"
    official_blob = " ".join(
        f"{item.get('rule_title', '')} {item.get('risk_item', '')}" for item in official
    )

    content_types: list[str] = []
    for label in _match_labels(evidence_blob, _CATEGORY_CONTENT_PLAYBOOK):
        if label not in content_types:
            content_types.append(label)
    for label in _match_labels(f"{category_blob} {official_blob}", _CATEGORY_CONTENT_PLAYBOOK):
        if label not in content_types:
            content_types.append(label)
    # 官方风险项压缩成可读短句，补足到至少 4 条
    for item in official:
        short = _shorten(str(item.get("risk_item") or item.get("rule_title") or ""))
        if short and short not in content_types and len(content_types) < 8:
            # 跳过纯说明性残句
            if short.startswith(("以下规则", "1.", "2.", "3.", "违规案例", "常见违规词汇")):
                continue
            content_types.append(short)

    if not content_types:
        content_types = [
            "绝对化/最高级表述",
            "食品功效/治疗暗示",
            "导流私域/站外成交",
            "虚假稀缺/低差营销",
        ]

    rejection_reasons: list[str] = []
    rejection_status = ""
    if ledger:
        rejection_status = "已接入拒审/违规台账，可按频次排序"
        for row in ledger[:8]:
            reason = str(row.get("reason") or "").strip()
            count = row.get("occurrence_count")
            if not reason:
                continue
            label = f"{reason}（{count}次）" if count not in (None, "") else reason
            if label not in rejection_reasons:
                rejection_reasons.append(label)
    else:
        rejection_status = "暂无拒审频次台账；以下为官方规则预审清单，不得称为赛道高频排名"
        for item in review_items:
            if isinstance(item, dict):
                blob = f"{item.get('rule_title', '')} {item.get('risk_item', '')}"
                short_source = str(item.get("risk_item") or item.get("rule_title") or "")
            else:
                blob = str(item)
                short_source = blob
            for label in _match_labels(blob, _REJECTION_SHORT_LABELS):
                if label not in rejection_reasons:
                    rejection_reasons.append(label)
            short = _shorten(short_source)
            if (
                short
                and short not in rejection_reasons
                and 8 <= len(short) <= 28
                and not short.startswith(("以下规则", "1.", "2.", "3.", "违规案例", "常见违规词汇", "食品行业"))
                and len(rejection_reasons) < 8
            ):
                rejection_reasons.append(short)
        for label in _match_labels(official_blob, _REJECTION_SHORT_LABELS):
            if label not in rejection_reasons:
                rejection_reasons.append(label)

    if not rejection_reasons:
        rejection_reasons = [
            "食品功效夸大",
            "虚假或夸大宣传",
            "导流联系方式",
            "资质与证照不符",
        ]

    content_status = (
        "结合对标笔记争议信号 + 官方规则映射的赛道风险内容类型（非平台处罚频次榜）"
        if evidence
        else "基于官方规则与品类常识的限流/违规内容类型映射（待对标样本补强）"
    )
    ledger_conclusion = (risk.get("category_high_frequency_violations") or {}).get("decision_conclusion")
    risk_note = ledger_conclusion or (
        "官方规则是合规底线；无拒审台账时不输出「赛道近 30 天 Top 拒审榜」。"
    )

    return {
        "content_status": content_status,
        "content_types": content_types[:8],
        "rejection_status": rejection_status,
        "rejection_reasons": rejection_reasons[:8],
        "has_ledger": bool(ledger),
        "ledger_rows": ledger[:12],
        "risk_note": risk_note,
        "baseline_checks": list(risk.get("baseline_checks") or []),
        "official_source_count": len((risk.get("official_rules") or {}).get("official_sources") or []),
    }
