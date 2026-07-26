"""最小 Agent Loop 演示：模块5（预算与节奏）决策场景。

用法：
    # 完整演示（需要本项目 .env / course.env 中的模型 Key，模型必须支持 function calling）
    python demo_agent_loop.py

    # 离线模式：不调用 LLM，直接演示工具层的校验与自我修正数据流
    python demo_agent_loop.py --offline

    # 模块 Agent 化端到端演示（需要模型 Key）：用真实 example 构造 CampaignRequest，
    # 跑对应 run_moduleN 并打印 trace 摘要 + 溯源检查 + 最终 JSON
    python demo_agent_loop.py --module1
    python demo_agent_loop.py --module2
    python demo_agent_loop.py --module3
    python demo_agent_loop.py --module4
    python demo_agent_loop.py --module5
    python demo_agent_loop.py --module6
    # --module6 会先检查实时数据源库：为空时用 MockRealtimeFeedAdapter(seed="demo-live")
    # 连拉 2 批落库，演示「mock API 接口 → 数据库 → 模块运行时实时取值」完整链路，
    # 并在输出里高亮 trending_monitor.rising_keywords（跟进/观察/不跟进）。

    # 叠加强模型 Critic 二审（只审策略文本质量，不审数字）：
    python demo_agent_loop.py --module4 --critic

    # 依赖传递编排：按 M1→M2→M6→M3→M4→M5 顺序跑全流程，上游结论摘要注入下游 prompt
    python demo_agent_loop.py --pipeline
    python demo_agent_loop.py --pipeline --critic
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from tools import DEFAULT_REGISTRY

# 模块 demo（_print_module_demo）默认用满证据案例：40 条品类笔记 / 2 竞品 / 8 达人 /
# 4 热搜词 / 3 违规台账，模块 1/2/3 才有笔记/竞品/达人证据可判读，不再输出空壳。
# 如需演示零证据降级路径，把下方文件名手改回 cookie_quartet_with_workbook_data.json。
EXAMPLE_FILE = (
    Path(__file__).resolve().parent
    / "examples"
    / "cookie_quartet_full_case.json"
)

SYSTEM_PROMPT = """你是小红书投放策略 Agent 的预算决策模块。

规则：
1. 所有金额、比例、出价数字必须通过工具计算，禁止自己心算。
2. 每次工具调用的 rationale 必须引用用户输入中的证据。
3. 没有证据支撑的数据（如基准CPC）必须如实传 null，禁止编造。
4. 工具返回参数校验错误时，按 details 修正后重新调用。
5. 全部工具调用完成后，输出一份中文 Markdown 决策摘要：
   预算拆分表、达人分层表、出价建议，并附「需人工拍板事项」。
"""

USER_PROMPT = """品牌：曲奇四重奏（香港伴手礼/蝴蝶酥）
总预算：50000 元，周期 30 天，核心目标：商品成交(conversion)
证据：
- 品牌 2026 年 1-5 月聚光账户加权 CPC 为 1.60 元（来源：品牌《数据需求.xlsx》）
- 达人合作历史：以腰部美食达人为主，KOL 合作经验少
请完成：总预算拆分（自然 vs 聚光 + 三阶段）、达人分层预算、冷启动出价区间。
"""


def run_offline() -> None:
    """不依赖 LLM：按脚本模拟 LLM 的决策序列，验证工具层数据流。

    第 2 步故意提交一个非法参数（比例合计 ≠ 1），演示校验错误如何
    作为 tool result 返回——真实循环中 LLM 会据此自我修正（第 3 步）。
    """
    scripted_calls = [
        (
            "compute_budget_split",
            {
                "total_budget_cny": 50000,
                "goal": "conversion",
                "rationale": "转化目标采用默认档 3:7，符合作业基准配比",
            },
        ),
        (
            "plan_creator_tiers",  # 故意出错：比例合计 0.9
            {
                "organic_budget_cny": 15000,
                "paid_budget_cny": 35000,
                "allocations": [
                    {"tier": "素人", "count": 12, "budget_ratio": 0.5},
                    {"tier": "达人", "count": 6, "budget_ratio": 0.4},
                ],
                "rationale": "品牌KOL合作经验少，预算集中在素人与腰部达人",
            },
        ),
        (
            "plan_creator_tiers",  # 模拟 LLM 收到校验错误后的自我修正
            {
                "organic_budget_cny": 15000,
                "paid_budget_cny": 35000,
                "allocations": [
                    {"tier": "素人", "count": 12, "budget_ratio": 0.5},
                    {"tier": "达人", "count": 6, "budget_ratio": 0.5},
                ],
                "rationale": "品牌KOL合作经验少，取消KOL层，预算集中在素人与腰部达人",
            },
        ),
        (
            "calc_bid_range",
            {
                "stage": "cold_start",
                "baseline_cpc_cny": 1.60,
                "baseline_source": "品牌《数据需求.xlsx》2026年1-5月加权CPC",
                "low_multiplier": 0.9,
                "high_multiplier": 1.1,
                "rationale": "冷启动稳定成本出价，围绕历史加权CPC小幅试探",
            },
        ),
    ]
    print("=== 离线模式：脚本化决策序列（含一次故意的参数错误与修正） ===\n")
    for index, (tool, arguments) in enumerate(scripted_calls, start=1):
        result = DEFAULT_REGISTRY.execute(tool, arguments)
        status = "OK" if "error" not in result else "REJECTED"
        print(f"[{index}] {tool} -> {status}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print()


def run_live() -> None:
    from agent_core import AgentLoop

    agent = AgentLoop(SYSTEM_PROMPT, DEFAULT_REGISTRY)
    outcome = agent.run(USER_PROMPT)
    print("=== 工具调用轨迹 ===")
    for row in outcome["trace"]:
        if row["action"] == "tool_call":
            status = "OK" if row["ok"] else "REJECTED->待LLM修正"
            print(f"step {row['step']}: {row['tool']} [{status}]")
    print(f"\n=== 最终决策摘要（共 {outcome['steps_used']} 步收敛） ===\n")
    print(outcome["final"])


def _critic_requested() -> bool:
    """`--critic` 是可叠加 flag：如 `python demo_agent_loop.py --module4 --critic`。"""
    return "--critic" in sys.argv


def _load_demo_request():
    from models import CampaignRequest

    payload = json.loads(EXAMPLE_FILE.read_text(encoding="utf-8"))
    return CampaignRequest.model_validate(payload)


def _build_evidence_digest(req, upstream_context: str = "") -> str:
    """给 Critic 的证据摘要：输入关键字段 + 上游结论（与 engine 侧口径一致）。"""
    parts = [
        f"品牌：{req.brand_name}（{req.category}）",
        f"商品：{req.product_name}｜卖点：" + "、".join(req.selling_points),
        f"目标：{req.goal}｜总预算：{req.total_budget_cny:g} 元"
        f"｜周期：{req.campaign_days} 天｜初始人群：{req.initial_audience}",
    ]
    if req.constraints:
        parts.append("约束：" + "；".join(req.constraints))
    if upstream_context:
        parts.append("上游模块结论摘要：\n" + upstream_context)
    return "\n".join(parts)


def _print_critic_review(module_name: str, module_title: str, req, output: dict) -> None:
    """跑一次 Critic 二审并打印 verdict/四维分/issues（失败只打印降级原因）。"""
    from module_agents.critic import run_critic

    review = run_critic(
        module_name, module_title, output, _build_evidence_digest(req)
    )
    print("\n--- Critic 二审（强模型，只审策略文本质量） ---")
    if review.get("status") != "ok":
        print(f"status: degraded；原因：{review.get('reason')}")
        return
    report = review["report"]
    print(f"verdict: {report['verdict']}")
    scores = report["dimension_scores"]
    print(
        "四维评分："
        f"证据引用 {scores['evidence_citation']}／可执行性 {scores['executability']}"
        f"／合规措辞 {scores['compliance_wording']}／一致性 {scores['consistency']}"
    )
    issues = report.get("issues") or []
    print(f"issues: {len(issues)} 条")
    for item in issues:
        print(f"  [{item['severity']}] {item['path']}：{item['problem']}")
        print(f"        建议：{item['suggestion']}")
    print(f"总评：{report['summary']}")


def _print_module_demo(
    label: str, run_fn, contract_name: str, module_name: str = ""
) -> None:
    """通用模块 Agent 演示打印：真实 example → run_fn → trace/溯源/JSON。"""
    req = _load_demo_request()
    print(f"=== {label} Agent 化演示：{req.brand_name} / 总预算 {req.total_budget_cny:g} 元 ===\n")

    result = run_fn(req)

    print("--- 工具调用轨迹摘要 ---")
    for row in result["trace"]:
        if row.get("action") == "tool_call":
            status = "OK" if row.get("ok") else "REJECTED->待LLM修正"
            print(f"step {row['step']}: {row['tool']} [{status}]")
    print(
        f"\n共 {result['steps_used']} 步，JSON 修复轮数 {result['repair_rounds_used']}"
    )

    grounding = result["grounding_check"]
    print("\n--- 数字溯源检查 ---")
    print(f"passed: {grounding['passed']}")
    if grounding["mismatches"]:
        for item in grounding["mismatches"]:
            print(f"  未溯源: {item['path']} = {item['value']}")

    output = result["output"]
    # 模块4 契约字段是 bidding（不是 bid_plan）；单独高亮，避免误读为 null
    if "bidding" in output:
        print("\n--- bidding（出价计划，契约字段名 bidding） ---")
        print(json.dumps(output.get("bidding"), ensure_ascii=False, indent=2))
    if "forecast" in output:
        print("\n--- forecast（效果预估） ---")
        print(json.dumps(output.get("forecast"), ensure_ascii=False, indent=2))
    # 模块6 的实时热搜跟进结论：来自 mock API→DB→实时取值→evaluate_trending_keywords
    monitor = output.get("trending_monitor")
    if isinstance(monitor, dict):
        rising = monitor.get("rising_keywords") or []
        print(f"\n--- trending_monitor.rising_keywords（实时热搜跟进建议，{len(rising)} 条） ---")
        print(f"数据源状态：{monitor.get('data_source_status')}")
        if not rising:
            print("（无热搜数据或无候选词：rising_keywords 留空，符合诚实性要求）")
        for row in rising:
            if not isinstance(row, dict):
                continue
            print(
                f"  [{row.get('recommendation')}] {row.get('keyword')}"
                f"（热度 {row.get('heat_score')}，趋势 {row.get('trend')}）：{row.get('reason')}"
            )

    print(f"\n--- {label} 最终 JSON（已通过 {contract_name} 契约校验） ---")
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if _critic_requested() and module_name:
        _print_critic_review(module_name, label, req, output)


def run_module5_demo() -> None:
    """端到端演示模块5 Agent：真实 example → run_module5 → trace/溯源/JSON。"""
    from module_agents.module5 import run_module5

    _print_module_demo("模块5", run_module5, "Module5Output", "module5")


def run_module4_demo() -> None:
    """端到端演示模块4 Agent：真实 example → run_module4 → trace/溯源/JSON。"""
    from module_agents.module4 import run_module4

    _print_module_demo("模块4", run_module4, "Module4Output", "module4")


def _seed_realtime_feed_if_empty(req, *, batches: int = 2, seed: str = "demo-live") -> None:
    """模块6 演示前置：数据源库为空时用 mock adapter 连拉 N 批写入，打通完整链路。

    链路：MockRealtimeFeedAdapter（mock API 接口，与真实源同构）→ FeedStore（SQLite）
    → module6._load_live_trending 在模块运行时实时取值 → evaluate_trending_keywords 判定跟进。
    库里已有热搜条目时不重复注入（保留 /feeds/pull 已经拉到的真实批次序列）。
    """
    from realtime_feed import FeedStore, MockRealtimeFeedAdapter

    store = FeedStore()
    status = store.status()
    if status["item_counts"].get("trending"):
        print(
            f"实时数据源已有数据：{status['batch_count']} 批 / "
            f"{status['item_counts']['trending']} 条热搜条目（{status['db_path']}），跳过注入\n"
        )
        return

    adapter = MockRealtimeFeedAdapter(
        seed,
        req.category,
        req.brand_name,
        product_name=req.product_name,
    )
    adapter.resume_from(store)
    keywords: set[str] = set()
    for _ in range(batches):
        batch = adapter.pull()
        store.save_batch(batch)
        keywords.update(item.keyword for item in batch.trending)
    print(
        f"模拟实时数据已注入：{len(keywords)} 词×{batches} 批"
        f"（seed={seed}，源=模拟实时数据源，落库 {store.db_path}）\n"
    )


def run_module6_demo() -> None:
    """端到端演示模块6 Agent：mock API→DB→实时取值 → run_module6 → trace/溯源/JSON。"""
    from module_agents.module6 import run_module6

    _seed_realtime_feed_if_empty(_load_demo_request())
    _print_module_demo("模块6", run_module6, "Module6Output", "module6")


def run_module1_demo() -> None:
    """端到端演示模块1 Agent：真实 example → run_module1 → trace/溯源/JSON。"""
    from module_agents.module1 import run_module1

    _print_module_demo("模块1", run_module1, "Module1Output", "module1")


def run_module2_demo() -> None:
    """端到端演示模块2 Agent：真实 example → run_module2 → trace/溯源/JSON。"""
    from module_agents.module2 import run_module2

    _print_module_demo("模块2", run_module2, "Module2Output", "module2")


def run_module3_demo() -> None:
    """端到端演示模块3 Agent：真实 example → run_module3 → trace/溯源/JSON。"""
    from module_agents.module3 import run_module3

    _print_module_demo("模块3", run_module3, "Module3Output", "module3")


def run_pipeline_demo() -> None:
    """依赖传递编排演示：M1→M2→M6→M3→M4→M5，上游结论摘要注入下游 prompt。"""
    from module_agents.orchestrator import MODULE_LABELS, PIPELINE_ORDER, run_pipeline

    req = _load_demo_request()
    print(
        f"=== 依赖传递编排演示：{req.brand_name} / 总预算 {req.total_budget_cny:g} 元 ===\n"
        f"执行顺序：{' → '.join(PIPELINE_ORDER)}\n"
    )

    outcome = run_pipeline(req)

    print("--- 每模块执行摘要 ---")
    for row in outcome["pipeline_trace"]:
        label = MODULE_LABELS.get(row["module"], row["module"])
        if row["status"] != "success":
            print(f"{label}: {row['status']}（{row.get('reason')}）")
            continue
        print(
            f"{label}: steps={row['steps_used']} 修复轮={row['repair_rounds_used']} "
            f"溯源={'通过' if row['grounding_passed'] else '有未溯源项'} "
            f"上游摘要注入={row['upstream_digest_chars']}字 本模块摘要={row['digest_chars']}字"
        )

    if not _critic_requested():
        print("\n（如需 Critic 二审，追加 --critic）")
        return

    print("\n--- 各模块 Critic 二审 verdict ---")
    for name, result in outcome["modules"].items():
        label = MODULE_LABELS.get(name, name)
        _print_critic_review(name, label, req, result["output"])


if __name__ == "__main__":
    if "--offline" in sys.argv:
        run_offline()
    elif "--pipeline" in sys.argv:
        run_pipeline_demo()
    elif "--module1" in sys.argv:
        run_module1_demo()
    elif "--module2" in sys.argv:
        run_module2_demo()
    elif "--module3" in sys.argv:
        run_module3_demo()
    elif "--module5" in sys.argv:
        run_module5_demo()
    elif "--module4" in sys.argv:
        run_module4_demo()
    elif "--module6" in sys.argv:
        run_module6_demo()
    else:
        run_live()
