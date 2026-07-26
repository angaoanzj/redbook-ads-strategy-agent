"""多模态内容审核工具（加分项）：知识库规则驱动文本预审 + 图片/视频占位。

文本：优先用 official_rule_evidence.risk_items / 条文关键词，再叠加内置兜底词表。
图片与视频：返回 pending_ocr / pending_frame_scan，不伪造视觉识别结果。
高风险结果可供模块2/4 做选题与聚光创意门禁。
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from tools.registry import ToolSpec

# 兜底词表：知识库无 risk_items 时仍可预审
DEFAULT_ABSOLUTE_TERMS = (
    "最好",
    "第一",
    "顶级",
    "全国首家",
    "全国第一",
    "绝对",
    "100%",
    "根治",
    "疗效",
    "最强",
    "唯一",
    "无敌",
)
DEFAULT_CLAIM_TERMS = ("减肥", "降脂", "治疗", "药用", "抗癌", "速效", "药到病除")
DEFAULT_COMPETITOR_HINTS = ("奇华", "帝苑", "珍妮", "皇玥", "恒香", "竞品logo")

# 从官方规则条文里捞检查词的粗筛模式
_RULE_TERM_PATTERNS = (
    re.compile(r"[「『\"“]([^」』\"”]{1,12})[」』\"”]"),
    re.compile(r"(最好|第一|顶级|绝对|100%|根治|疗效|唯一|最强|速效|药用|治疗)"),
)


class ContentAuditArgs(BaseModel):
    title: str = Field(default="", description="笔记标题或草稿标题")
    body: str = Field(default="", description="笔记正文或草稿正文")
    selling_points: list[str] = Field(default_factory=list, description="卖点列表")
    tags: list[str] = Field(default_factory=list, description="标签/话题")
    image_urls: list[str] = Field(default_factory=list, description="图片 URL（可选）")
    video_urls: list[str] = Field(default_factory=list, description="视频 URL（可选）")
    competitor_names: list[str] = Field(
        default_factory=list, description="已知竞品名，用于提及检测"
    )
    category: str = Field(default="", description="品类，用于规则路由提示")
    placement: str = Field(
        default="organic_note",
        description="投放场景：organic_note / spotlight_creative",
    )
    official_rules: list[dict[str, Any]] = Field(
        default_factory=list,
        description="官方规则证据（OfficialRuleEvidence 字典），用于条款化校验",
    )
    violation_ledger: list[dict[str, Any]] = Field(
        default_factory=list,
        description="账户/赛道拒审台账，用于加权本品牌雷区",
    )


def _norm_term(raw: Any) -> str | None:
    text = str(raw or "").strip().lstrip("#＃").strip()
    if not (1 <= len(text) <= 24):
        return None
    return text


def _terms_from_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从知识库规则抽出可检查词，并挂 rule_id。"""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rule_id = str(rule.get("rule_id") or "")
        title = str(rule.get("title") or "")
        source_url = str(rule.get("source_url") or "")
        risk_items = rule.get("risk_items") or []
        candidates: list[str] = []
        for item in risk_items:
            term = _norm_term(item)
            if term:
                candidates.append(term)
            # risk_item 可能是短句，再抽引号内词
            for match in _RULE_TERM_PATTERNS[0].findall(str(item or "")):
                term = _norm_term(match)
                if term:
                    candidates.append(term)
        full_text = str(rule.get("full_text") or "")[:2000]
        for pattern in _RULE_TERM_PATTERNS:
            for match in pattern.findall(full_text):
                term = _norm_term(match if isinstance(match, str) else match)
                if term:
                    candidates.append(term)
        for term in candidates:
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            category = "rule_risk_item"
            if any(x in term for x in DEFAULT_ABSOLUTE_TERMS):
                category = "absolute_claim"
            elif any(x in term for x in DEFAULT_CLAIM_TERMS):
                category = "efficacy_claim"
            rows.append(
                {
                    "term": term,
                    "category": category,
                    "severity": "high"
                    if category in {"absolute_claim", "efficacy_claim"}
                    else "medium",
                    "rule_id": rule_id,
                    "rule_title": title,
                    "source_url": source_url,
                    "source": "official_rule_evidence",
                }
            )
    return rows


def _terms_from_violations(ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in ledger:
        if not isinstance(row, dict):
            continue
        reason = _norm_term(row.get("reason"))
        if not reason:
            continue
        rows.append(
            {
                "term": reason if len(reason) <= 16 else reason[:16],
                "category": "account_violation_pattern",
                "severity": "high" if int(row.get("occurrence_count") or 1) >= 3 else "medium",
                "rule_id": "",
                "rule_title": f"拒审台账·{row.get('period') or ''}",
                "source_url": "",
                "source": "account_violation_evidence",
                "message_hint": f"本品牌/赛道台账高频原因「{reason}」",
            }
        )
        # 台账原因里若含绝对化词，额外挂上
        for abs_term in DEFAULT_ABSOLUTE_TERMS:
            if abs_term in reason:
                rows.append(
                    {
                        "term": abs_term,
                        "category": "absolute_claim",
                        "severity": "high",
                        "rule_id": "",
                        "rule_title": "拒审台账加权",
                        "source_url": "",
                        "source": "account_violation_evidence",
                    }
                )
    return rows


def _build_check_lexicon(args: ContentAuditArgs) -> list[dict[str, Any]]:
    lexicon = _terms_from_rules(list(args.official_rules or []))
    lexicon.extend(_terms_from_violations(list(args.violation_ledger or [])))
    seen = {str(row["term"]).casefold() for row in lexicon}

    def _add_defaults(terms: tuple[str, ...], category: str, severity: str) -> None:
        for term in terms:
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            lexicon.append(
                {
                    "term": term,
                    "category": category,
                    "severity": severity,
                    "rule_id": "",
                    "rule_title": "内置兜底词表",
                    "source_url": "",
                    "source": "builtin_fallback",
                }
            )

    _add_defaults(DEFAULT_ABSOLUTE_TERMS, "absolute_claim", "high")
    _add_defaults(DEFAULT_CLAIM_TERMS, "efficacy_claim", "high")
    competitors = list(DEFAULT_COMPETITOR_HINTS) + list(args.competitor_names or [])
    for name in competitors:
        term = _norm_term(name)
        if not term:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        lexicon.append(
            {
                "term": term,
                "category": "competitor_mention",
                "severity": "medium",
                "rule_id": "",
                "rule_title": "竞品名/商标提及",
                "source_url": "",
                "source": "competitor_candidates",
            }
        )
    return lexicon


def _scan_text(
    field: str,
    text: str,
    lexicon: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not text:
        return findings
    for row in lexicon:
        term = row["term"]
        if term and term in text:
            findings.append(
                {
                    "field": field,
                    "modality": "text",
                    "severity": row["severity"],
                    "category": row["category"],
                    "term": term,
                    "evidence": f"{field}含「{term}」",
                    "rule_id": row.get("rule_id") or None,
                    "rule_title": row.get("rule_title") or None,
                    "source_url": row.get("source_url") or None,
                    "source": row.get("source"),
                    "message": row.get("message_hint")
                    or (
                        f"{field}命中「{term}」（{row['category']}）"
                        + (
                            f"；规则：{row['rule_title']}"
                            if row.get("rule_title")
                            else ""
                        )
                        + "，发布前改写或删除"
                    ),
                    "rewrite_suggestion": _rewrite_hint(row["category"], term),
                }
            )
    return findings


def _rewrite_hint(category: str, term: str) -> str:
    if category == "absolute_claim":
        return f"避免「{term}」等绝对化用语，改为可验证的体验描述（如口感/场景/对比维度）"
    if category == "efficacy_claim":
        return f"删除「{term}」等功效/医疗暗示，食品赛道只保留风味与食用场景"
    if category == "competitor_mention":
        return f"弱化或删除对「{term}」的直接点名，改用品类共性对比"
    return f"按对应官方规则改写含「{term}」的表述"


def run_content_audit(args: ContentAuditArgs) -> dict[str, Any]:
    lexicon = _build_check_lexicon(args)
    findings: list[dict[str, Any]] = []
    findings.extend(_scan_text("标题", args.title, lexicon))
    findings.extend(_scan_text("正文", args.body, lexicon))
    for index, point in enumerate(args.selling_points, start=1):
        findings.extend(_scan_text(f"卖点{index}", point, lexicon))
    for index, tag in enumerate(args.tags, start=1):
        findings.extend(_scan_text(f"标签{index}", tag, lexicon))

    multimodal: list[dict[str, Any]] = []
    if args.image_urls:
        multimodal.append(
            {
                "modality": "image",
                "count": len(args.image_urls),
                "status": "pending_ocr",
                "message": (
                    "已收到图片链接，OCR/Logo 识别待接入合规视觉服务；"
                    "当前不伪造识别结果，不计入自动拦截"
                ),
            }
        )
    if args.video_urls:
        multimodal.append(
            {
                "modality": "video",
                "count": len(args.video_urls),
                "status": "pending_frame_scan",
                "message": (
                    "已收到视频链接，关键帧/语音审核待接入；"
                    "当前不伪造识别结果，不计入自动拦截"
                ),
            }
        )

    high = sum(1 for row in findings if row["severity"] == "high")
    medium = sum(1 for row in findings if row["severity"] == "medium")
    if high:
        risk_level = "high"
        passed = False
        gate = "block"
    elif medium:
        risk_level = "medium"
        passed = False
        gate = "review"
    else:
        risk_level = "low"
        passed = True
        gate = "pass"

    rules_used = [
        {
            "rule_id": rule.get("rule_id"),
            "title": rule.get("title"),
            "source_url": rule.get("source_url"),
        }
        for rule in (args.official_rules or [])[:12]
        if isinstance(rule, dict)
    ]
    kb_term_count = sum(1 for row in lexicon if row.get("source") == "official_rule_evidence")

    return {
        "passed": passed,
        "risk_level": risk_level,
        "gate": gate,
        "finding_count": len(findings),
        "findings": findings,
        "multimodal": multimodal,
        "placement": args.placement,
        "category": args.category,
        "lexicon_size": len(lexicon),
        "kb_rule_term_count": kb_term_count,
        "rules_considered": rules_used,
        "human_review_items": [
            row["message"] for row in findings if row["severity"] == "high"
        ][:5],
        "publish_gate": {
            "block_paid_amplification": gate == "block",
            "require_human_review": gate in {"block", "review"},
            "reason": (
                "文本预审发现高风险绝对化/功效表述，禁止进入聚光创意池"
                if gate == "block"
                else (
                    "存在中风险命中，发布前需人工复核"
                    if gate == "review"
                    else "文本预审通过（视觉模态仍可能 pending）"
                )
            ),
        },
        "evidence_boundary": (
            "文本规则预审优先使用知识库官方规则 risk_items/条文关键词，不足时用内置兜底词表；"
            "图片/视频未接入视觉模型前不得宣称已完成多模态审核。"
            + (f" 本案品类「{args.category}」。" if args.category else "")
        ),
    }


def apply_content_audit_gates(
    modules: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    """把审核结果回写模块2选题与模块4创意门禁。"""
    gate = (audit or {}).get("publish_gate") or {}
    block_paid = bool(gate.get("block_paid_amplification"))
    require_review = bool(gate.get("require_human_review"))
    reason = gate.get("reason") or "内容预审门禁"
    high_terms = [
        str(row.get("term"))
        for row in (audit.get("findings") or [])
        if row.get("severity") == "high" and row.get("term")
    ][:8]

    module2 = modules.get("module_2_audience_content")
    if isinstance(module2, dict):
        topics = module2.get("topics") or []
        blocked = 0
        for topic in topics:
            if not isinstance(topic, dict):
                continue
            blob = " ".join(
                [
                    str(topic.get("title_template") or ""),
                    str(topic.get("cover") or ""),
                    " ".join(str(x) for x in (topic.get("outline") or [])),
                    str(topic.get("selling_point_focus") or ""),
                ]
            )
            hit = [term for term in high_terms if term and term in blob]
            if block_paid or hit:
                if topic.get("suitable_for_paid") or topic.get("suitable_for_spotlight"):
                    blocked += 1
                topic["suitable_for_paid"] = False
                topic["suitable_for_spotlight"] = False
                topic["compliance_gate"] = {
                    "status": "blocked" if (block_paid or hit) else "review",
                    "reason": reason,
                    "hit_terms": hit,
                }
            elif require_review:
                topic.setdefault(
                    "compliance_gate",
                    {"status": "review", "reason": reason, "hit_terms": []},
                )
        paid_gate = module2.get("paid_material_gate") or {}
        paid_gate = dict(paid_gate)
        paid_gate["content_audit"] = {
            "gate": audit.get("gate"),
            "risk_level": audit.get("risk_level"),
            "block_paid_amplification": block_paid,
            "blocked_topic_count": blocked,
            "reason": reason,
        }
        module2["paid_material_gate"] = paid_gate
        screening = dict(module2.get("material_screening") or {})
        screening["content_audit_gate"] = paid_gate["content_audit"]
        module2["material_screening"] = screening

    module4 = modules.get("module_4_spotlight_decision")
    if isinstance(module4, dict):
        creative = module4.get("account_structure") or {}
        creative = dict(creative)
        creative["compliance_gate"] = {
            "gate": audit.get("gate"),
            "risk_level": audit.get("risk_level"),
            "block_new_creatives": block_paid,
            "require_human_review": require_review,
            "reason": reason,
            "action": (
                "高风险文案未改写前，禁止把对应素材复制进聚光创意池"
                if block_paid
                else "中风险素材仅小预算探测，人工复核后再放量"
                if require_review
                else "文本预审通过，仍需关注视觉模态 pending 状态"
            ),
        }
        module4["account_structure"] = creative
        module4["content_audit_gate"] = creative["compliance_gate"]

    return {
        "applied": True,
        "block_paid_amplification": block_paid,
        "require_human_review": require_review,
        "high_term_count": len(high_terms),
    }


CONTENT_AUDIT_TOOLS = [
    ToolSpec(
        name="audit_note_content",
        description=(
            "对笔记标题/正文/卖点/标签做合规预审（优先知识库官方规则），"
            "并声明图片视频 OCR 状态；高风险可阻断聚光放大"
        ),
        args_model=ContentAuditArgs,
        fn=run_content_audit,
    )
]
