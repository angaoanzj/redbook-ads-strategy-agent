#!/usr/bin/env python3
"""一键重生 examples/mock/ 下的演示 Mock 数据文件。

这些文件明确标注 is_mock=true / source_name 含 Mock，仅供方案演示，
不代表实时平台抓取结果。生成后可用：

  curl -X POST 'http://127.0.0.1:8010/analyze?use_model=false&allow_mock=false' \\
    -H 'Content-Type: application/json' \\
    --data @examples/mock/cookie_quartet_demo_full_case.json

或在页面上传 creators_demo.csv / 粘贴全案 JSON。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mock_scenarios import (  # noqa: E402
    MOCK_SOURCE,
    MOCK_WARNING,
    apply_demo_mock_evidence,
    build_mock_benchmarks,
    build_mock_creators,
    build_mock_notes,
    build_mock_paid_risk_scenarios,
    build_mock_trending,
    build_mock_violations,
)
from models import CampaignRequest  # noqa: E402
from official_rules_loader import (  # noqa: E402
    DEFAULT_DEMO_RULES_PATH,
    load_demo_official_rule_evidence,
    sync_official_rules_demo,
)

OUT_DIR = ROOT / "examples" / "mock"
AS_OF = "2026-07-24"
MOCK_SOURCE_FILE = "演示 Mock 数据包（scripts/generate_mock_data.py）"
# 全案嵌入时截断 risk_items 前缀（仍为已采集原文），控制 JSON 体积。
OFFICIAL_RULE_RISK_ITEM_LIMIT = 24


def _demo_request() -> CampaignRequest:
    return CampaignRequest(
        brand_name="曲奇四重奏",
        category="香港曲奇伴手礼",
        product_name="曲奇礼盒",
        selling_points=["香港伴手礼", "多口味", "礼盒送礼"],
        price_min=120,
        price_max=320,
        currency="CNY",
        initial_audience="25-40岁、关注香港旅行与节日送礼的女性消费者",
        total_budget_cny=100000,
        spotlight_budget_cny=70000,
        campaign_days=30,
        goal="conversion",
        analysis_days=30,
        constraints=["不得虚构实时平台数据", "本包全部为 Mock/演示样本"],
    )


def _stamp_mock(obj: dict, *, include_notes: bool = True) -> dict:
    """统一补齐演示标注字段。"""
    obj = dict(obj)
    obj["is_mock"] = True
    obj["evidence_grade"] = "M"
    if "source_name" in obj:
        obj["source_name"] = MOCK_SOURCE_FILE
    if "collected_at" in obj:
        collected = str(obj["collected_at"])
        obj["collected_at"] = AS_OF if "T" not in collected else f"{AS_OF}T12:00:00+00:00"
    if include_notes:
        notes = obj.get("notes") or ""
        if "Mock" not in notes and "演示" not in notes:
            prefix = "Mock/演示样本；"
            obj["notes"] = f"{prefix}{notes}".rstrip("；") if notes else "Mock/演示样本，非平台实时数据"
    return obj


def write_creators_csv(path: Path, req: CampaignRequest) -> int:
    creators = build_mock_creators(req, as_of=AS_OF)
    fieldnames = [
        "name",
        "profile_url",
        "followers",
        "average_interactions",
        "quote_cny",
        "audience_tags",
        "past_campaign_result",
        "source_name",
        "collected_at",
        "is_mock",
        "evidence_grade",
    ]
    rows = []
    for item in creators:
        data = _stamp_mock(item.model_dump(mode="json"), include_notes=False)
        data["audience_tags"] = "|".join(data.get("audience_tags") or [])
        data["is_mock"] = "true"
        # past_campaign_result 已含 Mock 说明；CSV 仅保留解析器认识的列
        rows.append({key: data.get(key, "") for key in fieldnames})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ensure_official_rules_demo() -> tuple[Path, int, str]:
    """保证 examples/mock/official_rules_demo.json 存在（优先用已采集快照）。"""
    if DEFAULT_DEMO_RULES_PATH.is_file():
        rules = load_demo_official_rule_evidence(
            demo_path=DEFAULT_DEMO_RULES_PATH,
            risk_item_limit=None,
        )
        return DEFAULT_DEMO_RULES_PATH, len(rules), str(DEFAULT_DEMO_RULES_PATH)
    path, rules, source = sync_official_rules_demo(demo_path=DEFAULT_DEMO_RULES_PATH)
    return path, len(rules), source


def build_fragment_files(req: CampaignRequest) -> dict[str, Path]:
    # 保留 build_mock_notes 的多日/多高峰 published_at，不再强制压成同一天
    notes = [_stamp_mock(n.model_dump(mode="json")) for n in build_mock_notes(req, as_of=AS_OF)]
    for note in notes:
        desc = (note.get("description") or "").strip()
        if not desc.startswith("Mock"):
            note["description"] = f"Mock/演示正文（非平台抓取）：{desc}" if desc else "Mock/演示正文（非平台抓取）"
        note["author_nickname"] = note.get("author_nickname") or "演示作者"

    trending = [_stamp_mock(t.model_dump(mode="json")) for t in build_mock_trending(req, as_of=AS_OF)]
    violations = [_stamp_mock(v.model_dump(mode="json")) for v in build_mock_violations(as_of=AS_OF)]
    benchmarks = [
        _stamp_mock(b.model_dump(mode="json")) for b in build_mock_benchmarks(req, as_of=AS_OF)
    ]
    paid_risk = [
        _stamp_mock(s.model_dump(mode="json"))
        for s in build_mock_paid_risk_scenarios(req, as_of=AS_OF)
    ]
    rules_path, _count, _source = ensure_official_rules_demo()

    paths = {
        "notes": OUT_DIR / "category_notes_demo.json",
        "trending": OUT_DIR / "trending_keywords_demo.json",
        "violations": OUT_DIR / "account_violations_demo.json",
        "benchmarks": OUT_DIR / "benchmarks_demo.json",
        "paid_risk": OUT_DIR / "paid_risk_scenarios_demo.json",
        "official_rules": rules_path,
    }
    write_json(
        paths["notes"],
        {
            "data_type": "模拟数据（Mock）",
            "is_mock": True,
            "source_name": MOCK_SOURCE_FILE,
            "as_of": AS_OF,
            "warning": MOCK_WARNING,
            "notes": "品类笔记演示样本，供聚类/共性管线使用，不代表平台大盘",
            "category_note_evidence": notes,
        },
    )
    write_json(
        paths["trending"],
        {
            "data_type": "模拟数据（Mock）",
            "is_mock": True,
            "source_name": MOCK_SOURCE_FILE,
            "as_of": AS_OF,
            "warning": MOCK_WARNING,
            "notes": "演示热搜情景，非平台实时热搜榜",
            "trending_keyword_evidence": trending,
        },
    )
    write_json(
        paths["violations"],
        {
            "data_type": "模拟数据（Mock）",
            "is_mock": True,
            "source_name": MOCK_SOURCE_FILE,
            "as_of": AS_OF,
            "warning": MOCK_WARNING,
            "notes": "Mock 拒审台账，需替换为真实聚光导出",
            "account_violation_evidence": violations,
        },
    )
    write_json(
        paths["benchmarks"],
        {
            "data_type": "模拟数据（Mock）",
            "is_mock": True,
            "source_name": MOCK_SOURCE_FILE,
            "as_of": AS_OF,
            "warning": MOCK_WARNING,
            "notes": "演示投放指标情景，非账户真实报表",
            "benchmark_evidence": benchmarks,
        },
    )
    write_json(
        paths["paid_risk"],
        {
            "data_type": "模拟数据（Mock）",
            "is_mock": True,
            "source_name": MOCK_SOURCE_FILE,
            "as_of": AS_OF,
            "warning": MOCK_WARNING,
            "notes": "五类投流问题 Mock 诊断情景，挂到模块4 risk_playbook.demo_scenario",
            "paid_risk_demo_scenarios": paid_risk,
        },
    )
    return paths


def build_full_case(req: CampaignRequest) -> Path:
    """组装可直接 POST /analyze 的一键全案 Mock JSON。"""
    creators = [_stamp_mock(c.model_dump(mode="json")) for c in build_mock_creators(req, as_of=AS_OF)]
    notes_pack = json.loads((OUT_DIR / "category_notes_demo.json").read_text(encoding="utf-8"))
    trending_pack = json.loads((OUT_DIR / "trending_keywords_demo.json").read_text(encoding="utf-8"))
    violations_pack = json.loads((OUT_DIR / "account_violations_demo.json").read_text(encoding="utf-8"))
    benchmarks_pack = json.loads((OUT_DIR / "benchmarks_demo.json").read_text(encoding="utf-8"))
    paid_risk_pack = json.loads((OUT_DIR / "paid_risk_scenarios_demo.json").read_text(encoding="utf-8"))
    # 官方规则是 A 级公开证据，禁止走 _stamp_mock
    official_rules = [
        rule.model_dump(mode="json")
        for rule in load_demo_official_rule_evidence(
            risk_item_limit=OFFICIAL_RULE_RISK_ITEM_LIMIT,
        )
    ]

    payload = req.model_dump(mode="json")
    payload.update(
        {
            "competitor_links": [],
            "competitor_candidates": [],
            "competitor_evidence": [
                {
                    "account_name": "演示竞品A（Mock）",
                    "profile_or_note_url": "https://example.com/mock-competitor/a",
                    "note_format": "图集",
                    "interactions": None,
                    "is_ad_labeled": None,
                    "observed_audience": ["伴手礼", "送礼"],
                    "notes": "Mock/演示竞品占位，非真实账号观察",
                }
            ],
            "benchmark_evidence": benchmarks_pack["benchmark_evidence"],
            "creator_evidence": creators,
            "category_note_evidence": notes_pack["category_note_evidence"],
            "official_rule_evidence": official_rules,
            "trending_keyword_evidence": trending_pack["trending_keyword_evidence"],
            "account_violation_evidence": violations_pack["account_violation_evidence"],
            "paid_risk_demo_scenarios": paid_risk_pack["paid_risk_demo_scenarios"],
            "owned_history_summary": "Mock/演示：无真实历史投放摘要",
            "constraints": [
                "本文件 Mock 字段为演示样本；official_rule_evidence 为已采集官方公开规则",
                MOCK_WARNING,
                "不得当作实时平台抓取结果；不得伪造官方规则正文",
            ],
        }
    )
    # 校验可被 CampaignRequest 接受；并确认 apply_demo 不会覆盖已填 Mock
    validated = CampaignRequest(**payload)
    filled, injected = apply_demo_mock_evidence(validated)
    assert filled.creator_evidence, "full case 应含演示达人"
    assert all(c.is_mock for c in filled.creator_evidence)
    assert len(filled.paid_risk_demo_scenarios) == 5, "full case 应含5条投流问题演示情景"
    assert filled.official_rule_evidence, "full case 应含已采集官方规则"
    assert all(
        rule.evidence_grade == "A_official_public_rule" for rule in filled.official_rule_evidence
    )
    assert all(rule.source_url for rule in filled.official_rule_evidence)
    assert all(rule.collected_at for rule in filled.official_rule_evidence)
    assert not any(f["field"] == "creator_evidence" for f in injected["fields"]), (
        "已提供 Mock 达人时不应再注入 creator_evidence"
    )
    assert not any(f["field"] == "paid_risk_demo_scenarios" for f in injected["fields"]), (
        "已提供投流情景时不应再注入 paid_risk_demo_scenarios"
    )

    out = OUT_DIR / "cookie_quartet_demo_full_case.json"
    envelope = {
        "_meta": {
            "data_type": "模拟数据（Mock）+ 官方规则快照",
            "is_mock": True,
            "source_name": MOCK_SOURCE_FILE,
            "as_of": AS_OF,
            "warning": MOCK_WARNING,
            "notes": (
                "一键全案演示包；official_rule_evidence 来自官方帮助中心已采集快照"
                "（见 official_rules_demo.json），非 Mock 伪造条文"
            ),
            "usage": (
                "POST /analyze?use_model=false&allow_mock=false "
                "with this file (strip _meta) or use allow_mock=true on empty cookie_quartet.json"
            ),
            "official_rules_source": str(
                DEFAULT_DEMO_RULES_PATH.relative_to(ROOT)
            ),
            "legacy_source_constant": MOCK_SOURCE,
        },
        **payload,
    }
    write_json(out, envelope)
    return out


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="重生 examples/mock 演示数据")
    parser.add_argument(
        "--sync-official-rules",
        action="store_true",
        help="强制从 research-data 或本地 KB 刷新 official_rules_demo.json",
    )
    args = parser.parse_args()

    req = _demo_request()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.sync_official_rules or not DEFAULT_DEMO_RULES_PATH.is_file():
        rules_path, rules, source = sync_official_rules_demo(demo_path=DEFAULT_DEMO_RULES_PATH)
        print(
            f"Synced {len(rules)} official rules from {source} "
            f"-> {rules_path.relative_to(ROOT)}"
        )

    creators_path = OUT_DIR / "creators_demo.csv"
    n_creators = write_creators_csv(creators_path, req)
    fragments = build_fragment_files(req)
    full_case = build_full_case(req)

    # 供页面「仅笔记」导入时也可直接用数组文件
    notes_only = OUT_DIR / "category_notes_demo.array.json"
    pack = json.loads(fragments["notes"].read_text(encoding="utf-8"))
    write_json(notes_only, pack["category_note_evidence"])

    print(f"Wrote {n_creators} mock creators -> {creators_path.relative_to(ROOT)}")
    for key, path in fragments.items():
        print(f"Wrote {key} -> {path.relative_to(ROOT)}")
    print(f"Wrote notes array -> {notes_only.relative_to(ROOT)}")
    print(f"Wrote full case -> {full_case.relative_to(ROOT)}")
    official_count = len(
        json.loads(full_case.read_text(encoding="utf-8")).get("official_rule_evidence") or []
    )
    print(f"Full case official_rule_evidence count: {official_count}")
    print(MOCK_WARNING)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
