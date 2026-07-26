"""从对标证据 + 品类笔记拼装「对标内容共性 / 空白点」人话（对齐珍妮金样结构）。

不调用 LLM；只做确定性抽取与模板句，供自动合成 brief 与看板 section_organic 使用。
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from models import CampaignRequest, CompetitorEvidence

_TITLE_HOOKS = (
    ("排序", "排序"),
    ("好吃程度", "排序"),
    ("只认", "只认这两家"),
    ("避坑", "避坑地图"),
    ("地图", "避坑地图"),
    ("开箱", "开箱花费"),
    ("花费", "开箱花费"),
    ("必买", "必买Top"),
    ("Top", "必买Top"),
)

_BODY_BITS = (
    ("门店地址", "门店地址"),
    ("地址", "门店地址"),
    ("营业时间", "营业时间"),
    ("时段", "营业时间"),
    ("现金", "现金/限购信息"),
    ("限购", "现金/限购信息"),
    ("只收现金", "现金/限购信息"),
    ("交通", "交通指引"),
    ("Top3", "必买TopN"),
    ("必买", "必买TopN"),
)

_COVER_BITS = ("铁盒", "小熊", "店招", "品牌", "聪明小熊", "Jenny")

_TAG_HINTS = (
    "香港必买",
    "香港伴手礼",
    "珍妮曲奇",
    "珍妮",
    "探店",
    "伴手礼",
    "手信",
    "曲奇",
)

_COMMENT_HINTS = (
    "价格",
    "现金",
    "机场",
    "代购",
    "限购",
    "真假",
    "寄送",
    "快递",
    "换汇",
)

_MINDSHARE_HINTS = ("珍妮", "聪明小熊", "Jenny", "香港伴手礼", "伴手礼", "手信")


def _blob(evidence: list[CompetitorEvidence]) -> str:
    parts: list[str] = []
    for item in evidence:
        parts.append(item.title or "")
        parts.extend(item.content_themes or [])
        parts.extend(item.observed_audience or [])
        parts.append(item.notes or "")
    return " ".join(parts)


def _unique_keep(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = (item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _pick_hooks(blob: str, pairs: tuple[tuple[str, str], ...]) -> list[str]:
    hits: list[str] = []
    seen: set[str] = set()
    for needle, label in pairs:
        if needle in blob and label not in seen:
            seen.add(label)
            hits.append(label)
    return hits


def _format_line(evidence: list[CompetitorEvidence]) -> str | None:
    if not evidence:
        return None
    counts = Counter((item.note_format or "未知").strip() or "未知" for item in evidence)
    top_fmt, top_cnt = counts.most_common(1)[0]
    total = len(evidence)
    cover = "，封面强品牌符号（铁盒小熊/店招）" if any(
        bit in _blob(evidence) for bit in _COVER_BITS
    ) else ""
    return f"{top_fmt}为主（{top_cnt}/{total}）{cover}"


def _title_line(evidence: list[CompetitorEvidence]) -> str | None:
    titles = " ".join(item.title or "" for item in evidence)
    themes = " ".join(
        theme for item in evidence for theme in (item.content_themes or [])
    )
    hooks = _pick_hooks(f"{titles} {themes}", _TITLE_HOOKS)
    if not hooks:
        return None
    return f"标题模板：{' / '.join(hooks[:4])}"


def _body_line(evidence: list[CompetitorEvidence]) -> str | None:
    blob = _blob(evidence)
    bits = _pick_hooks(blob, _BODY_BITS)
    if not bits:
        return None
    return f"正文标配：{' + '.join(bits[:5])}"


def _tag_line(
    evidence: list[CompetitorEvidence],
    competitor: dict[str, Any],
) -> str | None:
    theme_names = [
        str(row.get("theme") or "")
        for row in ((competitor.get("organic_hits_commonalities") or {}).get("top_themes") or [])
        if row.get("theme")
    ]
    if not theme_names:
        theme_names = [
            theme
            for item in evidence
            for theme in (item.content_themes or [])
        ]
    tags = [name for name in _unique_keep(theme_names) if any(h in name for h in _TAG_HINTS)]
    if not tags:
        tags = [name for name in _unique_keep(theme_names)[:4]]
    if not tags:
        return None
    return f"标签簇：{'、'.join(tags[:6])}"


def _comment_line(evidence: list[CompetitorEvidence]) -> str | None:
    audience = _unique_keep(
        [signal for item in evidence for signal in (item.observed_audience or [])]
    )
    blob = _blob(evidence)
    comment_bits = [hint for hint in _COMMENT_HINTS if hint in blob]
    merged = _unique_keep(comment_bits + audience)[:7]
    if not merged:
        return None
    return f"评论场：{'、'.join(merged)}"


def _summary_line(
    req: CampaignRequest,
    evidence: list[CompetitorEvidence],
) -> str:
    if not evidence:
        return "对标样本不足，暂无法归纳心智与互动分层。"
    blob = _blob(evidence)
    mind = [hint for hint in _MINDSHARE_HINTS if hint in blob]
    mind = _unique_keep(mind)[:3] or [req.category]
    ranked = sorted(
        evidence,
        key=lambda item: item.interactions if isinstance(item.interactions, int) else -1,
        reverse=True,
    )
    high = [
        item for item in ranked
        if isinstance(item.interactions, int) and item.interactions >= 1000
    ]
    low = [
        item for item in ranked
        if isinstance(item.interactions, int) and item.interactions < 100
    ]
    high_angles = []
    for item in high[:2]:
        title = item.title or ""
        if any(k in title for k in ("排序", "地图", "避坑", "只认")):
            high_angles.append("攻略地图与口味排序" if "排序" in title or "地图" in title or "避坑" in title else title[:12])
    if not high_angles and high:
        high_angles = ["高互动攻略/测评"]
    low_note = (
        "纯开箱打卡若不带决策信息则几乎沉底"
        if low and any("开箱" in ((item.title or "") + " ".join(item.content_themes or [])) for item in low)
        else ("低互动样本多为信息密度不足的打卡" if low else "其余样本互动分化明显")
    )
    brand_mind = "、".join(mind)
    high_text = "、".join(_unique_keep(high_angles)) or "高信息密度攻略"
    return (
        f"{len(evidence)}条对标都打「{brand_mind}」心智："
        f"{high_text}能冲到千级赞藏，{low_note}。"
    )


def _gaps_lines(
    req: CampaignRequest,
    evidence: list[CompetitorEvidence],
    competitor: dict[str, Any],
    organic: dict[str, Any],
) -> list[str]:
    blob = _blob(evidence)
    gaps_mod = competitor.get("content_gaps") or {}
    gap_points = list(gaps_mod.get("gap_selling_points") or [])
    covered = list(gaps_mod.get("covered_selling_points") or [])
    lines: list[str] = []

    # 卖点空白 → 人话
    for point in gap_points[:4]:
        key = point.casefold()
        if any(token in key for token in ("牛油", "原料", "日麦", "新西兰", "麦")):
            lines.append(f"几乎不讲原料溯源（{point}）")
        elif any(token in key for token in ("手工", "大厨", "酒店", "品质")):
            lines.append(f"很少做「酒店大厨/手工」品质对比叙事（相对卖点：{point}）")
        elif any(token in key for token in ("快递", "寄送", "履约", "内地")):
            lines.append(f"缺少可快递/内地履约方案（相对卖点：{point}）")
        else:
            lines.append(f"对标很少展开卖点「{point}」，可作为差异化切口")

    if "寄送" in blob or "快递" in blob or "代购" in blob:
        if not any("履约" in line or "寄送" in line or "快递" in line for line in lines):
            lines.append("缺少可快递/内地履约方案（评论大量问寄送）")

    if any(token in blob for token in ("香精", "人造奶油", "原料质疑", "质疑", "更好吃")):
        lines.append("负面口感/原料质疑已出现（香精/人造奶油或竞品导流评论）")

    # 视频占比：品类笔记
    video = 0
    image = 0
    for note in req.category_note_evidence or []:
        note_type = (note.note_type or "").casefold()
        if "视频" in note_type or "video" in note_type:
            video += 1
        else:
            image += 1
    total_kb = video + image
    if total_kb >= 20 and video / total_kb < 0.2:
        lines.append(
            f"视频占比低：KB 相关约 {total_kb} 条中视频仅 {video} 条"
        )

    # 若卖点已被覆盖但仍无差异化句，补形式空白
    if not lines and covered:
        lines.append(
            f"卖点「{'、'.join(covered[:3])}」已被对标主题覆盖，空白更多在表达形式与证据强度"
        )
    if not lines:
        for point in req.selling_points[:3]:
            lines.append(f"可强化卖点「{point}」的对比/体验内容")
    return _unique_keep(lines)[:6]


def build_organic_benchmark_insights(
    req: CampaignRequest,
    *,
    competitor: dict[str, Any],
    organic: dict[str, Any],
    evidence: list[CompetitorEvidence] | None = None,
) -> dict[str, Any]:
    """返回 summary / commonalities / gaps / format_note。"""
    items = list(evidence if evidence is not None else (req.competitor_evidence or []))
    # competitor module dict may nest organic_hits under competitor_full_funnel
    if "organic_hits_commonalities" not in competitor and "competitor_full_funnel" in (
        competitor or {}
    ):
        # allow passing module1 block by mistake
        pass

    commonalities = [
        line
        for line in (
            _format_line(items),
            _title_line(items),
            _body_line(items),
            _tag_line(items, competitor),
            _comment_line(items),
        )
        if line
    ]
    if not commonalities:
        themes = (competitor.get("organic_hits_commonalities") or {}).get("top_themes") or []
        commonalities = [
            f"高频主题：{row.get('theme')}"
            for row in themes[:5]
            if row.get("theme")
        ] or ["对标主题字段不足，请补全 content_themes / 标题后再看共性"]

    gaps = _gaps_lines(req, items, competitor, organic)
    formats = (competitor.get("organic_hits_commonalities") or {}).get("observed_formats") or []
    if formats:
        top = "、".join(
            f"{row.get('format')}×{row.get('sample_count')}"
            for row in formats[:3]
            if row.get("format")
        )
        format_note = (
            f"热门形式：对标样本以{top}为主。"
            "高互动仍多依赖信息密度高的图文攻略，不是纯短视频打卡。"
        )
    else:
        format_note = organic.get("popular_content_format_conclusion") or (
            "热门形式待更多对标样本确认。"
        )

    return {
        "summary": _summary_line(req, items),
        "commonalities": commonalities[:6],
        "gaps": gaps,
        "format_note": format_note,
        "source": "local_organic_insights",
    }
