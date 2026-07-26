from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from competitor_fetch import enrich_links_to_evidence
from competitor_input import normalize_competitor_inputs
from creator_csv import parse_creator_csv
from agent_state import AgentStateStore, DEFAULT_STATE_DB_PATH, new_report_id
from engine import run_strategy
from knowledge_base import KnowledgeBase
from memory.session_memory import SessionMemoryStore
from models import (
    BackfilledCaseRequest,
    CampaignRequest,
    CategoryNoteEvidence,
    CompetitorEvidence,
    FeedbackRequest,
    OfficialRuleEvidence,
    StrategyResponse,
)
from realtime_feed import (
    FeedStore,
    MockRealtimeFeedAdapter,
    feed_merge_counts,
    merge_feed_into_request,
)

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
HISTORY_EXAMPLE = ROOT / "examples" / "cookie_quartet_with_workbook_data.json"
FULL_CASE_EXAMPLE = ROOT / "examples" / "cookie_quartet_full_case.json"
COMPETITOR_BENCHMARK_EXAMPLE = ROOT / "examples" / "jenny_benchmark_competitor_evidence.json"
CREATOR_CSV_EXAMPLE = ROOT / "examples" / "creators_cookie_quartet.csv"
KNOWLEDGE = KnowledgeBase()
STATE = AgentStateStore(Path(os.getenv("XHS_AGENT_STATE_DB", DEFAULT_STATE_DB_PATH)))
# 实时数据源接入层：当前只挂模拟源（is_mock=true / evidence_grade=M），
# 换真实合规源时只替换 adapter，store 与 /analyze 的合并逻辑不动。
FEED_STORE = FeedStore()
SESSION_MEMORY = SessionMemoryStore(
    STATE,
    ttl_seconds=max(300, int(os.getenv("XHS_SESSION_MEMORY_TTL_SECONDS", "86400"))),
    max_items=max(4, int(os.getenv("XHS_SESSION_MEMORY_MAX_ITEMS", "32"))),
)

# 竞品快照 TTL：默认 14 天，与周扫描周期匹配；可用 XHS_COMPETITOR_CACHE_TTL_DAYS 覆盖
def competitor_cache_ttl_seconds() -> int:
    raw = (os.getenv("XHS_COMPETITOR_CACHE_TTL_DAYS") or "14").strip()
    try:
        days = float(raw.split()[0])
    except (TypeError, ValueError):
        days = 14.0
    days = max(1.0, min(days, 90.0))
    return int(days * 24 * 3600)


def _persist_monitor_alerts(
    brand_name: str,
    monitor: dict[str, Any],
    *,
    report_id: str | None = None,
) -> list[dict[str, Any]]:
    """把 high/medium 竞品预警落入 alert_events，供 GET /alerts 订阅。"""
    saved: list[dict[str, Any]] = []
    for alert in monitor.get("alerts") or []:
        if not isinstance(alert, dict):
            continue
        severity = str(alert.get("severity") or "")
        if severity not in {"high", "medium"}:
            continue
        saved.append(
            STATE.save_alert(
                brand_name=brand_name,
                severity=severity,
                alert_type=str(alert.get("type") or "competitor"),
                message=str(alert.get("message") or ""),
                response=str(alert.get("response") or "") or None,
                source="competitor_monitor",
                report_id=report_id,
                payload=alert,
            )
        )
    return saved


app = FastAPI(
    title="小红书投放策略决策 AI Agent",
    version="0.2.0",
    description="基于受控证据生成自然内容 + 聚光投流全案的可运行原型。",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/assets", StaticFiles(directory=WEB_ROOT), name="assets")


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(
        WEB_ROOT / "index.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "xiaohongshu-strategy"}


@app.get("/example/history", include_in_schema=False)
def history_example() -> dict:
    return json.loads(HISTORY_EXAMPLE.read_text(encoding="utf-8"))


@app.get("/example/full-case", include_in_schema=False)
def full_case_example() -> dict:
    return json.loads(FULL_CASE_EXAMPLE.read_text(encoding="utf-8"))


@app.get("/example/competitor-benchmark", include_in_schema=False)
def competitor_benchmark_example() -> dict:
    """User-provided Jenny Bakery benchmark notes — not scraped at runtime."""
    return json.loads(COMPETITOR_BENCHMARK_EXAMPLE.read_text(encoding="utf-8"))


@app.post("/creators/parse-csv")
async def creators_parse_csv(file: UploadFile = File(...)) -> dict:
    raw = (await file.read()).decode("utf-8-sig")
    creators = parse_creator_csv(raw)
    return {
        "count": len(creators),
        "creators": [item.model_dump(mode="json") for item in creators],
        "policy": "仅返回 CSV 中的真实候选；不会补造推荐名单",
    }


@app.get("/knowledge/status")
def knowledge_status() -> dict:
    return KNOWLEDGE.status()


@app.post("/knowledge/import")
def knowledge_import(notes: list[CategoryNoteEvidence]) -> dict:
    return KNOWLEDGE.import_notes(notes, source_name="网页导入 category_notes.json")


@app.get("/knowledge/search")
def knowledge_search(
    q: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=100),
    mode: str = Query(default="hybrid", pattern="^(hybrid|keyword)$"),
) -> dict:
    if mode == "keyword":
        notes = KNOWLEDGE.search([q], limit=limit)
        meta = {"mode": "keyword"}
    else:
        notes, meta = KNOWLEDGE.hybrid_search_with_meta([q], limit=limit)
    return {
        "query": q,
        "count": len(notes),
        "retrieval": meta,
        "notes": [note.model_dump(mode="json") for note in notes],
    }


@app.post("/knowledge/embeddings/ensure")
def knowledge_ensure_embeddings(
    limit: int | None = Query(default=None, ge=1, le=5000),
) -> dict:
    return KNOWLEDGE.ensure_note_embeddings(limit=limit)


@app.get("/knowledge/competitors")
def knowledge_competitors(
    own_brand: str = Query(min_length=1),
    candidates: str = Query(min_length=1, description="逗号分隔的候选品牌"),
    category: str = Query(default=""),
) -> dict:
    results = KNOWLEDGE.identify_competitors(
        own_brand=own_brand,
        candidate_names=re.split(r"[,，、;；\n]+", candidates),
        category_terms=[category],
    )
    return {"count": len(results), "candidates": results}


@app.get("/knowledge/rules")
def knowledge_rules(limit: int = Query(default=20, ge=1, le=50)) -> dict:
    rules = KNOWLEDGE.get_official_rules(limit=limit)
    return {
        "count": len(rules),
        "rules": [rule.model_dump(mode="json") for rule in rules],
    }


@app.get("/knowledge/targeting")
def knowledge_targeting(
    category: str = Query(default="", max_length=200),
    product_name: str = Query(default="", max_length=200),
    audience: str = Query(default="", max_length=500),
    selling_points: str = Query(
        default="",
        max_length=500,
        description="逗号分隔卖点，用于匹配品类剧本",
    ),
) -> dict[str, Any]:
    points = [p.strip() for p in re.split(r"[,，、;；\n]+", selling_points) if p.strip()]
    playbooks = KNOWLEDGE.match_targeting_playbooks(
        category=category,
        product_name=product_name,
        initial_audience=audience,
        selling_points=points,
        limit=3,
    )
    brief = KNOWLEDGE.targeting_brief_for_campaign(
        category=category,
        product_name=product_name,
        initial_audience=audience,
        selling_points=points,
        limit=3,
    )
    pack = KNOWLEDGE.targeting_pack_for_campaign(
        category=category,
        product_name=product_name,
        initial_audience=audience,
        selling_points=points,
        limit=3,
    )
    catalog = KNOWLEDGE.get_targeting_catalog()
    return {
        "has_catalog": catalog is not None,
        "matched_playbook_count": len(playbooks),
        "playbooks": playbooks,
        "brief": brief,
        "pack": pack,
        "targeting_tags": (pack or {}).get("targeting_tags"),
        "warning": (
            "候选标签须在聚光后台核对可用性；公开来源无法保证叶子标签在账户中真实存在。"
        ),
    }


@app.post("/feeds/pull")
def feeds_pull(
    seed: str | None = Query(
        default=None, max_length=128, description="Mock 可复现种子；同种子生成同一批次序列"
    ),
    category: str = Query(default="", max_length=200, description="品类，用于生成上升词"),
    brand: str = Query(default="", max_length=200, description="品牌，用于生成上升词"),
    product_name: str = Query(default="", max_length=200, description="商品名，用于生成上升词"),
) -> dict[str, Any]:
    """拉取一批「模拟实时数据源」并落库；返回批次摘要。

    真实源接入后只需把 MockRealtimeFeedAdapter 换成对应 adapter（同为 FeedAdapter 协议）。
    """
    adapter = MockRealtimeFeedAdapter(
        seed, category, brand, product_name=product_name
    )
    # HTTP 无状态：每次请求都是新 adapter，必须从库里已有的同 seed 批次续号，
    # 否则固定 seed 会永远停在第 1 批并互相覆盖。
    adapter.resume_from(FEED_STORE)
    batch = adapter.pull()
    return FEED_STORE.save_batch(batch)


@app.get("/feeds/status")
def feeds_status() -> dict[str, Any]:
    return FEED_STORE.status()


@app.get("/feeds/latest")
def feeds_latest(limit: int = Query(default=5, ge=1, le=50)) -> dict[str, Any]:
    batches = FEED_STORE.latest_batches(limit)
    return {"count": len(batches), "batches": batches}


@app.get("/sessions/{session_id}")
def session_status(session_id: str) -> dict[str, Any]:
    session = STATE.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@app.get("/sessions/{session_id}/memory")
def session_memory_status(session_id: str) -> dict[str, Any]:
    if not STATE.get_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "memory": SESSION_MEMORY.load(session_id)}


@app.get("/sessions/{session_id}/runs")
def session_runs(
    session_id: str,
    limit: int = Query(default=10, ge=1, le=100),
) -> dict[str, Any]:
    if not STATE.get_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    runs = STATE.list_runs(session_id, limit=limit)
    return {"session_id": session_id, "count": len(runs), "runs": runs}


@app.get("/workflows/{session_id}/{report_id}")
def workflow_status(session_id: str, report_id: str) -> dict[str, Any]:
    checkpoints = STATE.list_checkpoints(session_id, report_id)
    if not checkpoints:
        raise HTTPException(status_code=404, detail="工作流记录不存在")
    return {
        "session_id": session_id,
        "report_id": report_id,
        "checkpoints": checkpoints,
    }


@app.get("/state/status")
def agent_state_status() -> dict[str, int]:
    return STATE.state_status()


@app.post("/feedback")
def submit_feedback(
    request: FeedbackRequest,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", max_length=128
    ),
) -> dict[str, Any]:
    run = STATE.get_run(request.report_id)
    if not run or run["session_id"] != request.session_id:
        raise HTTPException(status_code=404, detail="报告或会话不存在")
    key = idempotency_key or f"feedback_{uuid4().hex}"
    encoded = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    request_hash = hashlib.sha256(encoded).hexdigest()
    action = STATE.begin_action(key, "feedback", request_hash, request.session_id)
    if action["result"] == "conflict":
        raise HTTPException(
            status_code=409,
            detail="同一 Idempotency-Key 不能用于不同的反馈请求",
        )
    if action["result"] == "processing":
        raise HTTPException(status_code=409, detail="该反馈仍在处理中")
    if action["result"] == "replayed":
        return action["response_summary"]["feedback"]
    feedback = STATE.save_feedback(
        session_id=request.session_id,
        report_id=request.report_id,
        rating=request.rating,
        comment=request.comment,
        sections=request.sections,
        idempotency_key=key,
        field_corrections=[item.model_dump(mode="json") for item in request.field_corrections],
    )
    STATE.complete_action(key, request.report_id, {"feedback": feedback})
    return feedback


@app.get("/alerts")
def list_alerts(
    brand_name: str | None = Query(default=None, max_length=200),
    severity: str | None = Query(default=None, pattern="^(high|medium|low)$"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """可订阅的预警出口：竞品监控 high/medium 事件落库后在此查询。"""
    items = STATE.list_alerts(brand_name=brand_name, severity=severity, limit=limit)
    return {"count": len(items), "alerts": items}


@app.get("/calibration/{brand_name}")
def get_brand_calibration(brand_name: str) -> dict[str, Any]:
    """按品牌读取反馈回流校准档（样本不足时 status=insufficient）。"""
    from calibration import load_brand_calibration

    return load_brand_calibration(STATE, brand_name)


@app.post("/competitors/scan")
def competitors_scan(
    brand_name: str = Query(..., min_length=1, max_length=200),
) -> dict[str, Any]:
    """独立于 /analyze 的竞品快照扫描：供定时守护脚本调用，刷新缓存并落预警。"""
    from tools.competitor_monitor import CompetitorMonitorArgs, monitor_competitors

    previous = STATE.get_cache(
        "competitor_monitor",
        f"brand:{brand_name}",
        source_version="v1",
    )
    accounts: list[dict[str, Any]] = []
    ad_labeled = 0
    sample_notes = 0
    report_id: str | None = None
    last = STATE.get_latest_run_by_brand(brand_name)
    if last and isinstance(last.get("response"), dict):
        report_id = last.get("report_id")
        modules = (last["response"] or {}).get("modules") or {}
        bonus = modules.get("bonus_competitor_monitor") or {}
        snap = bonus.get("snapshot") if isinstance(bonus, dict) else None
        if isinstance(snap, dict):
            accounts = list(snap.get("accounts") or [])
            ad_labeled = int(snap.get("ad_labeled_count") or 0)
            sample_notes = int(snap.get("sample_note_count") or 0)
        else:
            module1 = modules.get("module_1_market_competitor") or {}
            competitor = module1.get("competitor_full_funnel") or {}
            accounts = list(competitor.get("accounts") or [])
            ad_labeled = int(
                (competitor.get("paid_notes") or {}).get("confirmed_count") or 0
            )
            sample_notes = int(
                (competitor.get("organic_hits_commonalities") or {}).get(
                    "sample_note_count"
                )
                or 0
            )

    # 无历史分析时，用上一快照作为 current，触发一次 TTL 续期式扫描
    if not accounts and isinstance(previous, dict):
        accounts = list(previous.get("accounts") or [])
        ad_labeled = int(previous.get("ad_labeled_count") or 0)
        sample_notes = int(previous.get("sample_note_count") or 0)

    monitor = monitor_competitors(
        CompetitorMonitorArgs(
            brand_name=brand_name,
            current_accounts=accounts,
            current_ad_labeled_count=ad_labeled,
            current_sample_note_count=sample_notes,
            previous_snapshot=previous,
        )
    )
    snapshot = monitor.get("snapshot")
    if isinstance(snapshot, dict):
        STATE.set_cache(
            "competitor_monitor",
            f"brand:{brand_name}",
            snapshot,
            source_version="v1",
            ttl_seconds=competitor_cache_ttl_seconds(),
        )
    alerts = _persist_monitor_alerts(brand_name, monitor, report_id=report_id)
    return {
        "brand_name": brand_name,
        "status": monitor.get("status"),
        "monitor": monitor,
        "alerts_saved": len(alerts),
        "cache_ttl_seconds": competitor_cache_ttl_seconds(),
        "had_previous_snapshot": previous is not None,
    }


@app.post("/backfilled-cases")
def submit_backfilled_case(request: BackfilledCaseRequest) -> dict[str, Any]:
    run = STATE.get_run(request.report_id)
    if not run or run["session_id"] != request.session_id:
        raise HTTPException(status_code=404, detail="报告或会话不存在")
    response = STATE.get_run_response(request.report_id) or {}
    report_sections = (response.get("report_view") or {}).get("report_sections") or []
    is_mock = bool(run.get("mock_seed")) or any(
        row.get("is_mock") is True for row in report_sections
    )
    return STATE.save_backfilled_case(
        session_id=request.session_id,
        report_id=request.report_id,
        brand_name=request.brand_name,
        category=request.category,
        problem_summary=request.problem_summary,
        strategy_summary=request.strategy_summary,
        evidence_grade=request.evidence_grade,
        requested_case_type=request.requested_case_type,
        is_mock=is_mock,
    )


@app.post("/sessions/{session_id}/reset")
def reset_session(session_id: str) -> dict[str, Any]:
    if not STATE.reset_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "status": "reset"}


def _analyze_core(
    request: CampaignRequest,
    *,
    use_model: bool,
    use_knowledge: bool,
    allow_mock: bool,
    mock_seed: str | None,
    use_agent_modules: bool = False,
    use_realtime_feed: bool = False,
    fetch_competitors: bool = True,
    checkpoint: Callable[[str, dict[str, Any]], None] | None = None,
) -> StrategyResponse:
    # 实时数据源合并：在本地知识库证据合并之前完成，后续流程看到的就是合并后的请求。
    # 合并进来的条目一律 is_mock=true / evidence_grade=M，不会抬高证据等级。
    feed_merge_trace: dict[str, Any] | None = None
    if use_realtime_feed:
        try:
            before_payload = request.model_dump(mode="json")
            after_payload = merge_feed_into_request(before_payload, FEED_STORE)
            counts = feed_merge_counts(before_payload, after_payload)
            request = CampaignRequest.model_validate(after_payload)
            feed_merge_trace = {
                "step": "realtime_feed_merge",
                "merged_trending": counts["merged_trending"],
                "merged_competitors": counts["merged_competitors"],
                "is_mock": True,
            }
        except Exception as exc:  # 数据源故障不应拖垮分析：退回「不合并」并如实记 trace
            feed_merge_trace = {
                "step": "realtime_feed_merge",
                "merged_trending": 0,
                "merged_competitors": 0,
                "is_mock": True,
                "status": "failed",
                "error_type": exc.__class__.__name__,
            }

    retrieved: list[CategoryNoteEvidence] = []
    retrieval_meta: dict[str, Any] = {"mode": "disabled"}
    official_rules: list[OfficialRuleEvidence] = []
    retrieved_metrics = []
    organic_history = []
    paid_monthly_history: list[dict[str, Any]] = []
    targeting_brief: str | None = None
    targeting_pack: dict[str, Any] | None = None
    retrieval_terms = [request.category, request.product_name, *request.selling_points]
    if use_knowledge:
        # 品类优先检索：不在此处按 analysis_days 截断（由引擎做近窗高峰/决策），
        # 以便发布量／互动量趋势能用上知识库全量命中笔记。
        retrieval_terms = [request.category]
        if request.product_name:
            retrieval_terms.append(request.product_name)
        for point in request.selling_points or []:
            text = (point or "").strip()
            if 2 <= len(text) <= 16:
                retrieval_terms.append(text)
        retrieved, retrieval_meta = KNOWLEDGE.hybrid_search_with_meta(
            retrieval_terms,
            limit=300,
            analysis_days=None,
            allow_mock=False,
            diversify_by_author=True,
            use_vector=True,
            query_text=" ".join(retrieval_terms),
        )
        official_rules = KNOWLEDGE.get_official_rules(limit=20)
        retrieved_metrics = KNOWLEDGE.metric_evidence_for_campaign(
            request.brand_name,
            analysis_days=request.analysis_days,
        )
        organic_history = KNOWLEDGE.organic_history_for_campaign(
            request.brand_name, analysis_days=request.analysis_days,
        )
        # 月度表明细与卡片加权窗口解耦：优先展示知识库已导入的全部月份（最多12行）
        paid_monthly_history = KNOWLEDGE.paid_monthly_for_campaign(
            request.brand_name,
            analysis_days=None,
            limit=12,
        )
        targeting_brief = KNOWLEDGE.targeting_brief_for_campaign(
            category=request.category,
            product_name=request.product_name,
            initial_audience=request.initial_audience,
            selling_points=request.selling_points,
            limit=2,
        )
        targeting_pack = KNOWLEDGE.targeting_pack_for_campaign(
            category=request.category,
            product_name=request.product_name,
            initial_audience=request.initial_audience,
            selling_points=request.selling_points,
            limit=2,
        )
    supplied_ids = {note.note_id for note in request.category_note_evidence}
    merged_notes = [
        *request.category_note_evidence,
        *(note for note in retrieved if note.note_id not in supplied_ids),
    ]
    competitor_assessment = KNOWLEDGE.identify_competitors(
        own_brand=request.brand_name,
        candidate_names=request.competitor_candidates,
        category_terms=[request.category, request.product_name, *request.selling_points],
    ) if use_knowledge and request.competitor_candidates else []
    # 仅抓取用户给定的少量链接，抽出结构化字段；不做全站/千条爬取
    user_competitors, competitor_fetch_trace = enrich_links_to_evidence(
        request.competitor_links,
        existing=list(request.competitor_evidence),
        fetch_enabled=fetch_competitors,
    )
    if checkpoint:
        checkpoint(
            "competitor_fetch",
            {
                "fetch_enabled": fetch_competitors,
                "link_count": len(request.competitor_links or []),
                "fetched": sum(1 for row in competitor_fetch_trace if row.get("status") == "fetched"),
                "trace": competitor_fetch_trace,
            },
        )
    inferred_competitors: list[CompetitorEvidence] = []
    # 用户已粘贴对标链接时，以实时抓取为准，禁止掺入知识库候选空账号（如「帝苑」占位行）
    if not request.competitor_links:
        supplied_competitor_names = {
            item.account_name.casefold() for item in user_competitors
        }
        for candidate in competitor_assessment:
            if candidate["classification"] != "可能竞品":
                continue
            if candidate["candidate_name"].casefold() in supplied_competitor_names:
                continue
            top_note = candidate["evidence_notes"][0]
            inferred_competitors.append(CompetitorEvidence(
                account_name=candidate["candidate_name"],
                profile_or_note_url=top_note["url"],
                note_format=top_note["note_type"],
                interactions=candidate["total_interactions"],
                is_ad_labeled=None,
                observed_audience=[request.category],
                notes=(
                    f"知识库候选：{candidate['mention_note_count']}条笔记提及，"
                    f"{candidate['independent_author_count']}位作者，"
                    f"置信度{candidate['confidence_score']}；广告标识待打开原笔记核验"
                ),
                source_name="本地知识库候选",
                evidence_grade="C_user_provided",
            ))
    merged_competitors = normalize_competitor_inputs(
        [],
        [*user_competitors, *inferred_competitors],
    )
    supplied_metric_names = {
        item.metric_name.casefold() for item in request.benchmark_evidence
    }
    merged_metrics = [
        *request.benchmark_evidence,
        *(item for item in retrieved_metrics if item.metric_name.casefold() not in supplied_metric_names),
    ]
    supplied_rule_ids = {rule.rule_id for rule in request.official_rule_evidence}
    merged_rules = [
        *request.official_rule_evidence,
        *(rule for rule in official_rules if rule.rule_id not in supplied_rule_ids),
    ]
    # 用户粘贴了竞品链接时：丢掉示例 brief，强制按本次抓取结果重合成对标看板
    refresh_brief = bool(request.competitor_links) and any(
        row.get("status") in {"fetched", "fetch_failed", "stub_only"}
        for row in competitor_fetch_trace
    )
    effective_request = request.model_copy(update={
        "category_note_evidence": merged_notes,
        "competitor_evidence": merged_competitors,
        "official_rule_evidence": merged_rules,
        "benchmark_evidence": merged_metrics,
        "owned_content_history": organic_history,
        "paid_monthly_history": paid_monthly_history or request.paid_monthly_history,
        "targeting_knowledge_brief": targeting_brief or request.targeting_knowledge_brief,
        "targeting_knowledge_pack": targeting_pack or request.targeting_knowledge_pack,
        **(
            {"competitor_benchmark_brief": None}
            if refresh_brief
            else {}
        ),
    })
    if checkpoint:
        checkpoint(
            "evidence_ready",
            {
                "retrieved_notes": len(retrieved),
                "merged_notes": len(merged_notes),
                "official_rules": len(merged_rules),
                "paid_metrics": len(merged_metrics),
                "targeting_knowledge": bool(
                    targeting_brief
                    or targeting_pack
                    or request.targeting_knowledge_brief
                    or request.targeting_knowledge_pack
                ),
            },
        )
    previous_snapshot = STATE.get_cache(
        "competitor_monitor",
        f"brand:{request.brand_name}",
        source_version="v1",
    )
    from calibration import load_brand_calibration

    brand_calibration = load_brand_calibration(STATE, request.brand_name)
    response = run_strategy(
        effective_request,
        use_model=use_model,
        allow_mock=allow_mock,
        mock_seed=mock_seed,
        use_agent_modules=use_agent_modules,
        previous_competitor_snapshot=previous_snapshot,
        brand_calibration=brand_calibration if brand_calibration.get("status") == "ready" else None,
    )
    monitor = response.modules.get("bonus_competitor_monitor") or {}
    snapshot = monitor.get("snapshot")
    if isinstance(snapshot, dict):
        STATE.set_cache(
            "competitor_monitor",
            f"brand:{request.brand_name}",
            snapshot,
            source_version="v1",
            ttl_seconds=competitor_cache_ttl_seconds(),
        )
    _persist_monitor_alerts(
        request.brand_name, monitor, report_id=response.report_id or None
    )
    if brand_calibration.get("status") == "ready":
        response.trace.append({
            "step": "brand_calibration",
            "status": "ready",
            "sample_count": brand_calibration.get("sample_count"),
            "defaults": brand_calibration.get("defaults") or {},
        })
    elif brand_calibration.get("status") == "insufficient":
        response.trace.append({
            "step": "brand_calibration",
            "status": "insufficient",
            "sample_count": brand_calibration.get("sample_count"),
            "reason": brand_calibration.get("reason"),
        })
    if checkpoint:
        checkpoint(
            "strategy_generated",
            {"module_count": 6, "data_confidence": response.data_confidence},
        )
    if feed_merge_trace:
        response.trace.append(feed_merge_trace)
    response.trace.append({
        "step": "local_knowledge_retrieval",
        "enabled": use_knowledge,
        "query_terms": retrieval_terms,
        "retrieved_count": len(retrieved),
        "retrieval_filters": {
            "analysis_days": None,
            "allow_mock": False,
            "diversify_by_author": True,
            "limit": 300,
            "mode": "hybrid_keyword_vector",
            "window_applied_in": "engine_peak_hours",
        },
        "retrieval_meta": retrieval_meta,
        "request_supplied_count": len(request.category_note_evidence),
        "evidence_count_after_merge": len(merged_notes),
        "database_total_notes": KNOWLEDGE.status()["total_notes"],
        "official_rule_count": len(official_rules),
        "paid_metric_count": len(retrieved_metrics),
        "organic_period_count": len(organic_history),
        "targeting_knowledge": bool(targeting_brief),
        "metric_sources": sorted({item.source_name for item in retrieved_metrics}),
        "analysis_window_days": request.analysis_days,
        "allow_mock": allow_mock,
        "mock_seed": mock_seed,
    })
    response.trace.append({
        "step": "competitor_identification",
        "candidate_count": len(competitor_assessment),
        "likely_competitor_count": len(inferred_competitors),
        "rules": "至少2条独立笔记提及，且至少1条与当前品类相关；广告标识人工核验",
        "assessment": competitor_assessment,
    })
    response.trace.append({
        "step": "competitor_fetch",
        "fetch_enabled": fetch_competitors,
        "link_count": len(request.competitor_links or []),
        "evidence_count": len(merged_competitors),
        "fetched": sum(1 for row in competitor_fetch_trace if row.get("status") == "fetched"),
        "brief_refreshed": refresh_brief,
        "trace": competitor_fetch_trace,
    })
    return response


def _analysis_request_hash(
    request: CampaignRequest,
    *,
    use_model: bool,
    use_knowledge: bool,
    allow_mock: bool,
    mock_seed: str | None,
    use_agent_modules: bool = False,
    use_realtime_feed: bool = False,
    fetch_competitors: bool = True,
) -> str:
    payload = {
        "request": request.model_dump(mode="json"),
        "options": {
            "use_model": use_model,
            "use_knowledge": use_knowledge,
            "allow_mock": allow_mock,
            "mock_seed": mock_seed,
            "use_agent_modules": use_agent_modules,
            "use_realtime_feed": use_realtime_feed,
            "fetch_competitors": fetch_competitors,
        },
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@app.post("/analyze", response_model=StrategyResponse)
def analyze(
    request: CampaignRequest,
    use_model: bool = Query(default=True, description="是否调用聊天模型润色最终报告"),
    use_knowledge: bool = Query(default=True, description="是否自动检索本地品类知识库"),
    allow_mock: bool = Query(
        default=False,
        description="是否启用多子Agent用明确标识的模拟数据补足缺失字段（生产默认关闭）",
    ),
    mock_seed: str | None = Query(
        default=None,
        max_length=128,
        description="Mock 可复现种子；相同种子生成相同模拟数据",
    ),
    use_agent_modules: bool = Query(
        default=False,
        description="是否启用六模块 LLM Agent 决策（成功则挂 agent_decision；失败回退确定性模块）",
    ),
    use_realtime_feed: bool = Query(
        default=False,
        description=(
            "是否把 /feeds/pull 落库的实时数据源条目合并进本次请求的证据"
            "（当前为模拟源：全部 is_mock=true、evidence_grade=M，同名词/同竞品不覆盖）"
        ),
    ),
    fetch_competitors: bool = Query(
        default=True,
        description="是否抓取用户给定的竞品笔记/账号链接以抽取结构化字段（仅给定链接，非全站爬取）",
    ),
    x_session_id: str | None = Header(
        default=None, alias="X-Session-ID", max_length=128
    ),
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", max_length=128
    ),
) -> StrategyResponse:
    session = STATE.get_or_create_session(x_session_id)
    session_id = session["session_id"]
    previous_memory = SESSION_MEMORY.load(session_id)
    report_id = new_report_id()
    request_hash = _analysis_request_hash(
        request,
        use_model=use_model,
        use_knowledge=use_knowledge,
        allow_mock=allow_mock,
        mock_seed=mock_seed,
        use_agent_modules=use_agent_modules,
        use_realtime_feed=use_realtime_feed,
        fetch_competitors=fetch_competitors,
    )
    if idempotency_key:
        action = STATE.begin_action(
            idempotency_key,
            "analyze",
            request_hash,
            session_id,
            report_id=report_id,
        )
        if action["result"] == "conflict":
            raise HTTPException(
                status_code=409,
                detail="同一 Idempotency-Key 不能用于不同的分析请求",
            )
        if action["result"] == "processing":
            raise HTTPException(status_code=409, detail="该分析请求仍在处理中")
        if action["result"] == "replayed":
            saved = STATE.get_run_response(action["report_id"])
            if not saved:
                raise HTTPException(status_code=409, detail="幂等记录存在但报告结果不可用")
            return StrategyResponse.model_validate(saved)

    STATE.save_checkpoint(
        session_id,
        report_id,
        "received",
        status="success",
        context={
            "brand_name": request.brand_name,
            "product_name": request.product_name,
            "session_memory_used": bool(previous_memory),
            "session_memory_keys": sorted(previous_memory),
        },
    )

    def checkpoint(stage: str, context: dict[str, Any]) -> None:
        STATE.save_checkpoint(
            session_id, report_id, stage, status="success", context=context
        )

    try:
        response = _analyze_core(
            request,
            use_model=use_model,
            use_knowledge=use_knowledge,
            allow_mock=allow_mock,
            mock_seed=mock_seed,
            use_agent_modules=use_agent_modules,
            use_realtime_feed=use_realtime_feed,
            fetch_competitors=fetch_competitors,
            checkpoint=checkpoint,
        )
        checkpoint(
            "report_generated",
            {"report_sections": len(response.report_view.get("report_sections") or [])},
        )
        retrieval_trace = next(
            (
                row
                for row in response.trace
                if row.get("step") == "local_knowledge_retrieval"
            ),
            {},
        )
        metadata = {
            "brand_name": request.brand_name,
            "product_name": request.product_name,
            "category": request.category,
            "goal": request.goal,
            "mock_seed": mock_seed if allow_mock else None,
            "data_confidence": response.data_confidence,
            "source_counts": {
                "notes": retrieval_trace.get("evidence_count_after_merge", 0),
                "official_rules": retrieval_trace.get("official_rule_count", 0),
                "paid_metrics": retrieval_trace.get("paid_metric_count", 0),
            },
        }
        session_state = STATE.complete_analysis(
            session_id,
            report_id,
            response.report_view.get("executive_summary") or {},
            metadata,
        )
        response.trace.append(
            {
                "stage": "session_state",
                "status": "success",
                "session_id": session_id,
                "report_id": report_id,
                "analysis_count": session_state["analysis_count"],
            }
        )
        response = response.model_copy(
            update={
                "report_id": report_id,
                "session_state": session_state,
                "session_memory": {
                    "used": bool(previous_memory),
                    "keys": sorted(previous_memory),
                    "source": "session_memory" if previous_memory else "explicit_input",
                    "note": "仅用于当前会话上下文提示，不构成新的事实证据。",
                },
            }
        )
        # 看板补齐 report_id / 生成时间，便于前端刷新与导出
        try:
            from tools.dashboard import build_dashboard_payload

            view = dict(response.report_view or {})
            view["dashboard"] = build_dashboard_payload(
                view,
                response.modules,
                report_id=report_id,
                generated_at=response.generated_at,
                feed_status=FEED_STORE.status(),
            )
            response = response.model_copy(update={"report_view": view})
        except Exception:
            pass
        SESSION_MEMORY.remember(
            session_id,
            {
                "recent_brand": request.brand_name,
                "recent_product": request.product_name,
                "recent_category": request.category,
                "recent_goal": request.goal,
                "recent_report_id": report_id,
                "recent_intent": "strategy_analysis",
                "low_risk_preferences": {"currency": request.currency},
            },
        )
        checkpoint("completed", {"analysis_count": session_state["analysis_count"]})
        STATE.save_run_response(report_id, response.model_dump(mode="json"))
        if idempotency_key:
            STATE.complete_action(
                idempotency_key,
                report_id,
                {"session_id": session_id, "analysis_count": session_state["analysis_count"]},
            )
        return response
    except Exception as exc:
        STATE.save_checkpoint(
            session_id,
            report_id,
            "failed",
            status="failed",
            context={},
            error_summary=exc.__class__.__name__,
        )
        if idempotency_key:
            STATE.fail_action(
                idempotency_key, {"error_type": exc.__class__.__name__}
            )
        raise


def _build_board_for_report(report_id: str, *, refresh: bool = True) -> dict[str, Any]:
    """从已保存报告组装看板；默认每次刷新重投影并叠加实时源状态。"""
    saved = STATE.get_run_response(report_id)
    if not saved:
        raise HTTPException(status_code=404, detail="报告不存在")
    view = saved.get("report_view") or {}
    from tools.dashboard import build_dashboard_payload

    feed_status: dict[str, Any] = {}
    try:
        feed_status = FEED_STORE.status()
    except Exception:
        feed_status = {}

    cached = view.get("dashboard") if not refresh else None
    if cached and not refresh:
        return cached

    dashboard = build_dashboard_payload(
        view,
        saved.get("modules") or {},
        report_id=report_id,
        generated_at=saved.get("generated_at"),
        feed_status=feed_status,
    )
    # 回写缓存，便于下次快速读取；导出与刷新均走最新投影
    try:
        view["dashboard"] = dashboard
        saved["report_view"] = view
        STATE.save_run_response(report_id, saved)
    except Exception:
        pass
    return dashboard


@app.get("/board/{report_id}")
def get_board(
    report_id: str,
    refresh: bool = Query(default=True, description="是否从报告重投影看板（默认是）"),
) -> dict[str, Any]:
    """返回已保存报告的可视化看板；支持刷新以叠加最新实时源状态。"""
    return _build_board_for_report(report_id, refresh=refresh)


@app.get("/board/{report_id}/export")
def export_board(
    report_id: str,
    format: str = Query(default="json", pattern="^(json|markdown|csv)$"),
) -> Any:
    """导出看板：json / markdown / csv。"""
    from fastapi.responses import PlainTextResponse, Response

    from tools.dashboard import export_dashboard_csv, export_dashboard_markdown

    dashboard = _build_board_for_report(report_id, refresh=True)
    stamp = (dashboard.get("refreshed_at") or "export").replace(":", "").replace("+", "")
    if format == "markdown":
        body = export_dashboard_markdown(dashboard)
        return PlainTextResponse(
            body,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="dashboard-{report_id[:12]}-{stamp}.md"'
            },
        )
    if format == "csv":
        body = export_dashboard_csv(dashboard)
        return Response(
            body,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="dashboard-{report_id[:12]}-{stamp}.csv"'
            },
        )
    import json

    payload = json.dumps(dashboard, ensure_ascii=False, indent=2)
    return Response(
        payload,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="dashboard-{report_id[:12]}-{stamp}.json"'
        },
    )


@app.post("/bonus/content-audit")
def bonus_content_audit(payload: dict[str, Any]) -> dict[str, Any]:
    from tools.content_audit import ContentAuditArgs, run_content_audit

    return run_content_audit(ContentAuditArgs(**payload))


@app.post("/bonus/ab-test")
def bonus_ab_test(payload: dict[str, Any]) -> dict[str, Any]:
    from tools.ab_test import AbTestArgs, build_ab_matrix

    return build_ab_matrix(AbTestArgs(**payload))


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=True)
