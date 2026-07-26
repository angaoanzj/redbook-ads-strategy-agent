"""Load Xiaohongshu official public rules for mock/demo cases.

Prefer already-collected help-center snapshots. Never invent rule body text.
Source priority for sync/regeneration:
1. examples/mock/official_rules_demo.json (vendored, git-tracked)
2. research-data/xhs-official-rules/*/official_rules.json (collector output)
3. local SQLite knowledge base (import-rules / collector auto-import)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from models import OfficialRuleEvidence

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
MOCK_DIR = ROOT / "examples" / "mock"
DEFAULT_DEMO_RULES_PATH = MOCK_DIR / "official_rules_demo.json"
RESEARCH_RULES_ROOT = REPO_ROOT / "research-data" / "xhs-official-rules"
DEFAULT_DB_PATH = ROOT / "data" / "xhs_knowledge.db"

# Align with engine.py preferred_rule_order; food / review / cross-border first.
PREFERRED_OFFICIAL_RULE_TITLES = (
    "食品行业规则&投放规则",
    "内容审核规则总则",
    "跨境广告内容规范",
    "专业号合规经营指南：自查与规范手册",
    "治理公告&违规公示",
    "商业化风险积分管理规则",
)


def find_latest_research_rules_json(
    research_root: Path = RESEARCH_RULES_ROOT,
) -> Path | None:
    if not research_root.is_dir():
        return None
    candidates = sorted(
        research_root.glob("*/official_rules.json"),
        key=lambda path: path.parent.name,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _payload_to_rules(payload: Any) -> list[OfficialRuleEvidence]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("official_rule_evidence") or payload.get("rules")
        if not isinstance(items, list):
            raise ValueError("官方规则 JSON 需为数组，或含 official_rule_evidence 数组")
    else:
        raise ValueError("官方规则 JSON 根节点类型无效")
    return [OfficialRuleEvidence.model_validate(item) for item in items]


def load_official_rules_from_path(path: Path) -> list[OfficialRuleEvidence]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _payload_to_rules(payload)


def load_official_rules_from_kb(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    limit: int = 50,
) -> list[OfficialRuleEvidence]:
    from knowledge_base import KnowledgeBase

    if not db_path.is_file():
        return []
    return KnowledgeBase(db_path).get_official_rules(limit=limit)


def order_official_rules(
    rules: list[OfficialRuleEvidence],
    *,
    preferred_titles: tuple[str, ...] = PREFERRED_OFFICIAL_RULE_TITLES,
) -> list[OfficialRuleEvidence]:
    by_title = {rule.title: rule for rule in rules}
    ordered: list[OfficialRuleEvidence] = []
    seen: set[str] = set()
    for title in preferred_titles:
        rule = by_title.get(title)
        if rule is None or rule.rule_id in seen:
            continue
        ordered.append(rule)
        seen.add(rule.rule_id)
    for rule in rules:
        if rule.rule_id in seen:
            continue
        ordered.append(rule)
        seen.add(rule.rule_id)
    return ordered


def trim_risk_items(
    rules: list[OfficialRuleEvidence],
    *,
    risk_item_limit: int | None = 24,
) -> list[OfficialRuleEvidence]:
    """Keep a prefix of collected risk_items only; never rewrite wording."""
    if risk_item_limit is None:
        return list(rules)
    limit = max(1, risk_item_limit)
    return [
        rule.model_copy(update={"risk_items": list(rule.risk_items[:limit])})
        for rule in rules
    ]


def resolve_official_rules(
    *,
    demo_path: Path = DEFAULT_DEMO_RULES_PATH,
    research_root: Path = RESEARCH_RULES_ROOT,
    db_path: Path = DEFAULT_DB_PATH,
    allow_kb: bool = True,
) -> tuple[list[OfficialRuleEvidence], str]:
    """Return rules and a human-readable source label."""
    if demo_path.is_file():
        return load_official_rules_from_path(demo_path), str(demo_path)
    research_path = find_latest_research_rules_json(research_root)
    if research_path is not None:
        return load_official_rules_from_path(research_path), str(research_path)
    if allow_kb:
        kb_rules = load_official_rules_from_kb(db_path)
        if kb_rules:
            return kb_rules, f"knowledge_base:{db_path}"
    raise FileNotFoundError(
        "未找到官方规则：请先运行 research-tools/xhs_official_rules_collector.py，"
        "或 python knowledge_base.py import-rules <official_rules.json>，"
        f"或放置 {demo_path}"
    )


def _relativize_source_label(source_label: str) -> str:
    try:
        path = Path(source_label)
        if path.is_absolute():
            return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except Exception:
        pass
    return source_label


def build_demo_rules_envelope(
    rules: list[OfficialRuleEvidence],
    *,
    source_label: str,
) -> dict[str, Any]:
    collected_values = [rule.collected_at for rule in rules if rule.collected_at]
    return {
        "_meta": {
            "data_type": "官方公开规则快照",
            "is_mock": False,
            "evidence_grade": "A_official_public_rule",
            "source_name": "小红书聚光官方帮助中心",
            "source_snapshot": _relativize_source_label(source_label),
            "collected_at": collected_values[0] if collected_values else None,
            "warning": (
                "正文来自已采集的官方帮助中心公开规则；"
                "不得伪造条文；更新请重新采集后 sync 进本文件。"
            ),
            "usage": (
                "供 examples/mock 全案挂载；也可用 "
                "python knowledge_base.py import-rules "
                "examples/mock/official_rules_demo.json "
                "（需先导出为纯数组，见 export-rules）"
            ),
        },
        "official_rule_evidence": [
            rule.model_dump(mode="json") for rule in rules
        ],
    }


def sync_official_rules_demo(
    *,
    demo_path: Path = DEFAULT_DEMO_RULES_PATH,
    research_root: Path = RESEARCH_RULES_ROOT,
    db_path: Path = DEFAULT_DB_PATH,
) -> tuple[Path, list[OfficialRuleEvidence], str]:
    """Refresh vendored demo snapshot from research-data or KB."""
    research_path = find_latest_research_rules_json(research_root)
    if research_path is not None:
        rules = load_official_rules_from_path(research_path)
        source_label = str(research_path)
    else:
        rules = load_official_rules_from_kb(db_path)
        if not rules:
            raise FileNotFoundError(
                "无法 sync：research-data 与本地知识库均无官方规则"
            )
        source_label = f"knowledge_base:{db_path}"
    ordered = order_official_rules(rules)
    demo_path.parent.mkdir(parents=True, exist_ok=True)
    envelope = build_demo_rules_envelope(ordered, source_label=source_label)
    demo_path.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return demo_path, ordered, source_label


def load_demo_official_rule_evidence(
    *,
    demo_path: Path = DEFAULT_DEMO_RULES_PATH,
    research_root: Path = RESEARCH_RULES_ROOT,
    db_path: Path = DEFAULT_DB_PATH,
    risk_item_limit: int | None = 24,
    titles: tuple[str, ...] | None = None,
) -> list[OfficialRuleEvidence]:
    """Rules for CampaignRequest.official_rule_evidence (not Mock-stamped)."""
    rules, _source = resolve_official_rules(
        demo_path=demo_path,
        research_root=research_root,
        db_path=db_path,
    )
    preferred = titles or PREFERRED_OFFICIAL_RULE_TITLES
    ordered = order_official_rules(rules, preferred_titles=preferred)
    if titles is not None:
        wanted = set(titles)
        ordered = [rule for rule in ordered if rule.title in wanted]
    return trim_risk_items(ordered, risk_item_limit=risk_item_limit)
