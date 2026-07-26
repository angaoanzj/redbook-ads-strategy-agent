"""多子 Agent：数据缺失时分工模拟，并显式标记来源与职责。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from mock_scenarios import (
    MOCK_WARNING,
    build_mock_benchmarks,
    build_mock_competitors,
    build_mock_creators,
    build_mock_notes,
    build_mock_paid_risk_scenarios,
    build_mock_platform_market,
    build_mock_trending,
    build_mock_violations,
    normalize_mock_seed,
)
from models import CampaignRequest


@dataclass
class MockSubAgent:
    agent_id: str
    name: str
    specialty: str
    fills: list[str]
    status: str = "idle"
    injected_count: int = 0
    notes: str = ""
    details: dict[str, Any] = field(default_factory=dict)


AGENT_SPECS: list[dict[str, Any]] = [
    {
        "agent_id": "organic_market_agent",
        "name": "自然大盘模拟 Agent",
        "specialty": "品类笔记样本、发布时段与内容形式分布",
        "field": "category_note_evidence",
        "always_try": False,
        "builder": lambda req, seed: build_mock_notes(req, mock_seed=seed),
        "note": "演示笔记样本，不代表平台大盘",
    },
    {
        "agent_id": "spotlight_benchmark_agent",
        "name": "聚光指标模拟 Agent",
        "specialty": "CPC/CPM/CTR/CVR 冷启动情景",
        "field": "benchmark_evidence",
        "always_try": True,
        "builder": lambda req, seed: build_mock_benchmarks(req, mock_seed=seed),
        "note": "只补缺失指标，不覆盖真实账户值",
    },
    {
        "agent_id": "competitor_agent",
        "name": "竞品投放模拟 Agent",
        "specialty": "匿名竞品笔记、广告标识与预算假设",
        "field": "competitor_evidence",
        "always_try": False,
        "builder": lambda req, seed: build_mock_competitors(req, mock_seed=seed),
        "note": "匿名模拟竞品，非真实品牌投放证据",
    },
    {
        "agent_id": "creator_agent",
        "name": "达人分层模拟 Agent",
        "specialty": "素人/达人/KOL 分层预算演示名单",
        "field": "creator_evidence",
        "always_try": False,
        "builder": lambda req, seed: build_mock_creators(req, mock_seed=seed),
        "note": "演示候选，非真实推荐名单",
    },
    {
        "agent_id": "trending_agent",
        "name": "热搜趋势模拟 Agent",
        "specialty": "品类相关热搜词与热度情景",
        "field": "trending_keyword_evidence",
        "always_try": False,
        "builder": lambda req, seed: build_mock_trending(req, mock_seed=seed),
        "note": "演示热搜情景，非实时热搜",
    },
    {
        "agent_id": "compliance_agent",
        "name": "合规拒审模拟 Agent",
        "specialty": "赛道拒审/限流台账演示",
        "field": "account_violation_evidence",
        "always_try": False,
        "builder": lambda req, seed: build_mock_violations(mock_seed=seed),
        "note": "模拟台账，不可当作正式合规结论",
    },
    {
        "agent_id": "paid_risk_agent",
        "name": "投流风控模拟 Agent",
        "specialty": "冷启动无量/高CPC/低转化等五类诊断情景",
        "field": "paid_risk_demo_scenarios",
        "always_try": False,
        "builder": lambda req, seed: build_mock_paid_risk_scenarios(req, mock_seed=seed),
        "note": "五类投流问题 Mock 诊断情景",
    },
]


def run_mock_subagents(
    req: CampaignRequest,
    *,
    mock_seed: str | None = None,
) -> tuple[CampaignRequest, dict[str, Any]]:
    """按缺口启动多个专职子 Agent，各自只填充缺失字段。"""
    seed = normalize_mock_seed(mock_seed)
    agents: list[MockSubAgent] = []
    updates: dict[str, Any] = {}
    injected_fields: list[dict[str, Any]] = []

    for spec in AGENT_SPECS:
        field_name = spec["field"]
        agent = MockSubAgent(
            agent_id=spec["agent_id"],
            name=spec["name"],
            specialty=spec["specialty"],
            fills=[field_name],
        )
        current = getattr(req, field_name, None) or []
        if current and not spec["always_try"]:
            agent.status = "skipped_real_evidence_present"
            agent.notes = "已有用户/知识库证据，本 Agent 不覆盖"
            agents.append(agent)
            continue

        builder: Callable[[CampaignRequest, str], Any] = spec["builder"]
        working = req.model_copy(update=updates) if updates else req
        payload = builder(working, seed)
        if not payload:
            agent.status = "skipped_no_missing_metrics"
            agent.notes = "目标字段已齐全，无需补足"
            agents.append(agent)
            continue

        if field_name == "benchmark_evidence":
            updates[field_name] = [*working.benchmark_evidence, *payload]
        else:
            updates[field_name] = payload

        count = len(payload)
        agent.status = "injected_mock"
        agent.injected_count = count
        agent.notes = spec["note"]
        agent.details = {"is_mock": True, "mock_seed": seed}
        injected_fields.append({
            "field": field_name,
            "count": count,
            "is_mock": True,
            "note": spec["note"],
            "agent_id": spec["agent_id"],
            "agent_name": spec["name"],
        })
        agents.append(agent)

    agents.append(MockSubAgent(
        agent_id="platform_trend_agent",
        name="平台趋势情景 Agent",
        specialty="30日自然流量大盘情景曲线（对照用）",
        fills=["simulated_platform_market"],
        status="ready_for_module_attach",
        notes="不写入请求体；引擎在 allow_mock 时挂到 module1",
        details={"mock_seed": seed},
    ))

    effective = req.model_copy(update=updates) if updates else req
    return effective, {
        "fields": injected_fields,
        "policy": MOCK_WARNING,
        "mock_seed": seed,
        "subagents": [
            {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "specialty": agent.specialty,
                "fills": agent.fills,
                "status": agent.status,
                "injected_count": agent.injected_count,
                "notes": agent.notes,
                "details": agent.details,
            }
            for agent in agents
        ],
        "agent_count_activated": sum(1 for agent in agents if agent.status == "injected_mock"),
        "platform_market_preview": build_mock_platform_market(effective, mock_seed=seed)["status"],
    }
