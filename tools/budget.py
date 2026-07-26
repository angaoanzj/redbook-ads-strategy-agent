"""预算拆分工具：原 engine._budget_ratios 的工具化版本。

与旧版区别：比例不再由 if/else 写死。LLM 可在护栏区间内自选比例并说明理由；
不选则落到目标对应的默认档。算术（金额、阶段拆分）始终由代码完成。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from tools.registry import ToolSpec

Goal = Literal[
    "awareness", "engagement", "search_growth", "conversion", "leads", "live_traffic"
]

# 默认档位（作业要求：转化类 3:7，曝光类 5:5，其余 4:6）
DEFAULT_ORGANIC_RATIO: dict[str, float] = {
    "conversion": 0.30,
    "leads": 0.30,
    "live_traffic": 0.30,
    "awareness": 0.50,
    "engagement": 0.50,
    "search_growth": 0.40,
}

GOAL_LABELS_ZH: dict[str, str] = {
    "awareness": "品牌曝光",
    "engagement": "点赞收藏",
    "search_growth": "搜索增长",
    "conversion": "商品成交",
    "leads": "客资收集",
    "live_traffic": "直播引流",
}

# 自然:聚光 建议配比 + 原因（作业口径）
GOAL_SPLIT_GUIDE: dict[str, dict[str, Any]] = {
    "conversion": {
        "organic_ratio": 0.30,
        "paid_ratio": 0.70,
        "ratio_label": "3:7",
        "rationale": (
            "成交目标以聚光承接高意向流量为主（约7成），"
            "自然内容保留约3成用于素材筛选与信任背书，避免无素材硬投。"
        ),
    },
    "leads": {
        "organic_ratio": 0.30,
        "paid_ratio": 0.70,
        "ratio_label": "3:7",
        "rationale": (
            "客资收集同样依赖付费定向与表单/私信链路放大；"
            "自然侧先验证痛点与信任素材，再把预算压到聚光获客。"
        ),
    },
    "live_traffic": {
        "organic_ratio": 0.30,
        "paid_ratio": 0.70,
        "ratio_label": "3:7",
        "rationale": (
            "直播引流以聚光在开播窗口集中拉人；"
            "自然内容预热场次与回放种草，预算不宜超过约3成。"
        ),
    },
    "awareness": {
        "organic_ratio": 0.50,
        "paid_ratio": 0.50,
        "ratio_label": "5:5",
        "rationale": (
            "品牌曝光需先用自然内容铺认知与话题资产，"
            "聚光只做等量放大与人群触达，避免过度付费堆曝光却无内容沉淀。"
        ),
    },
    "engagement": {
        "organic_ratio": 0.50,
        "paid_ratio": 0.50,
        "ratio_label": "5:5",
        "rationale": (
            "互动目标依赖内容质量与社区讨论；自然/聚光对半，"
            "先产出高互动笔记，再小预算加热胜出内容。"
        ),
    },
    "search_growth": {
        "organic_ratio": 0.40,
        "paid_ratio": 0.60,
        "ratio_label": "4:6",
        "rationale": (
            "搜索增长需要自然笔记占位核心/长尾词（约4成），"
            "同时用聚光搜索推广加速词权与高意向承接（约6成）。"
        ),
    },
}


def goal_split_guide(goal: str) -> dict[str, Any]:
    """Return recommended organic/paid split + rationale for a campaign goal."""
    guide = GOAL_SPLIT_GUIDE.get(goal) or {
        "organic_ratio": DEFAULT_ORGANIC_RATIO.get(goal, 0.40),
        "paid_ratio": 1.0 - DEFAULT_ORGANIC_RATIO.get(goal, 0.40),
        "ratio_label": "4:6",
        "rationale": "未识别目标，回退搜索增长档（自然4 / 聚光6）作为保守起点。",
    }
    organic = float(guide["organic_ratio"])
    paid = float(guide.get("paid_ratio") if guide.get("paid_ratio") is not None else 1.0 - organic)
    return {
        "goal": goal,
        "goal_label": GOAL_LABELS_ZH.get(goal, goal),
        "organic_ratio": organic,
        "paid_ratio": paid,
        "ratio_label": guide.get("ratio_label")
        or f"{int(round(organic * 10))}:{int(round(paid * 10))}",
        "rationale": guide.get("rationale") or "",
    }


def all_goal_split_matrix() -> list[dict[str, Any]]:
    """Comparison table of default splits across all goals."""
    return [goal_split_guide(goal) for goal in DEFAULT_ORGANIC_RATIO]

# 分阶段占付费（聚光）预算比例（作业要求：预热 20% / 爆发 60% / 长尾 20%）
PHASE_RATIOS = [("预热期", 0.20), ("爆发期", 0.60), ("长尾期", 0.20)]

# 分阶段全域投放节奏（自然 + 聚光协同）
PHASE_PLAYBOOK: list[dict[str, Any]] = [
    {
        "key": "warmup",
        "name": "预热期",
        "paid_ratio": 0.20,
        "day_share": 0.25,
        "min_days": 2,
        "summary": "自然内容铺量 + 小预算聚光测试",
        "organic_focus": "自然内容铺量：按方向矩阵发文，验证标题/封面/场景，沉淀可放大素材池",
        "paid_focus": "小预算聚光测试：搜索高意向词 + 精准定向冷启动，只做可比较探测",
        "key_actions": [
            "自然侧：每个内容方向至少发 1–2 篇，保持唯一变量测试",
            "聚光侧：用约占投流预算 20% 做搜索/精准小预算测试",
            "门槛：自然笔记 24h CTR/互动过线后，才复制进聚光素材池",
            "不同时大改出价、定向与素材，保证测试可归因",
        ],
        "exit_criteria": "形成可比较样本（点击/转化达最小门槛）且筛出至少 1 组可放大素材/定向",
        "owner": "内容负责人 + 优化师",
    },
    {
        "key": "burst",
        "name": "爆发期",
        "paid_ratio": 0.60,
        "day_share": 0.50,
        "min_days": 3,
        "summary": "自然爆款放大 + 聚光大规模放量",
        "organic_focus": "自然爆款放大：复用胜出选题与封面结构，提高发布密度与话题连续性",
        "paid_focus": "聚光大规模放量：把预算集中到过门槛素材、定向与搜推胜出版位",
        "key_actions": [
            "只放大预热期胜出的素材/定向/词包，不新增过多未验证变量",
            "聚光侧投入约占投流预算 60%，按观察窗小步提价（如成本低目标 10% 则提价 5%）",
            "搜索与信息流分计划放量，执行搜推二次触达",
            "触及止损线立即缩预算或暂停对应单元",
        ],
        "exit_criteria": "成本连续两个观察窗稳定，且主目标（转化/曝光等）可持续达成",
        "owner": "优化师 + 投手",
    },
    {
        "key": "tail",
        "name": "长尾期",
        "paid_ratio": 0.20,
        "day_share": 0.25,
        "min_days": 2,
        "summary": "优质内容持续投流 + 搜索词占位",
        "organic_focus": "优质内容续航：保留高表现笔记更新与评论区运营，维持自然搜索可见",
        "paid_focus": "搜索词占位 + 优质内容持续投流：收缩到高 ROI 搜索词与稳健素材",
        "key_actions": [
            "聚光侧保留约占投流预算 20%，优先搜索占位与信息流维稳",
            "停投衰退素材，轮换已验证的标题/封面组合",
            "把付费数据反哺下一轮选题与词库",
            "为下一周期预热沉淀词包与素材基线",
        ],
        "exit_criteria": "完成复盘：胜出素材/词包/定向清单入库，供下一周期直接复用",
        "owner": "优化师 + 内容负责人",
    },
]


def build_campaign_phases(
    *,
    campaign_days: int,
    paid_budget_cny: float,
) -> list[dict[str, Any]]:
    """Build warmup / burst / tail phases with day split and paid budget shares."""
    days = max(7, int(campaign_days or 30))
    paid = float(paid_budget_cny or 0)
    raw_days = [
        max(int(item["min_days"]), round(days * float(item["day_share"])))
        for item in PHASE_PLAYBOOK
    ]
    # 保证三阶段天数之和等于投放周期（尾差归爆发期）
    drift = days - sum(raw_days)
    raw_days[1] = max(int(PHASE_PLAYBOOK[1]["min_days"]), raw_days[1] + drift)

    phases: list[dict[str, Any]] = []
    paid_amounts = [round(paid * float(item["paid_ratio"])) for item in PHASE_PLAYBOOK]
    paid_drift = round(paid) - sum(paid_amounts)
    paid_amounts[1] += paid_drift

    cursor = 1
    for index, item in enumerate(PHASE_PLAYBOOK):
        phase_days = raw_days[index]
        start_day = cursor
        end_day = min(days, cursor + phase_days - 1)
        cursor = end_day + 1
        phases.append(
            {
                "key": item["key"],
                "name": item["name"],
                "phase": item["name"],
                "days": phase_days,
                "day_range": f"第{start_day}–{end_day}天",
                "paid_ratio": float(item["paid_ratio"]),
                "budget_ratio": float(item["paid_ratio"]),
                "ratio": float(item["paid_ratio"]),
                "paid_budget_cny": paid_amounts[index],
                "summary": item["summary"],
                "action": item["summary"],
                "organic_focus": item["organic_focus"],
                "paid_focus": item["paid_focus"],
                "key_actions": list(item["key_actions"]),
                "exit_criteria": item["exit_criteria"],
                "owner": item["owner"],
            }
        )
    return phases


def build_organic_paid_synergy(
    *,
    material_screening: dict[str, Any] | None = None,
    probe_budget_cny: float | None = None,
    search_keywords: list[str] | None = None,
    rising_follow: list[str] | None = None,
    content_directions: list[str] | None = None,
    goal: str = "conversion",
) -> dict[str, Any]:
    """自然流 ↔ 付费流协同：启动阈值 + 回流机制（承接上游模块结果）。"""
    screening = material_screening or {}
    hours = int(screening.get("observation_hours") or 24)
    ctr_pct = screening.get("ctr_percent")
    if ctr_pct is None and isinstance(screening.get("ctr_threshold"), (int, float)):
        ctr_pct = round(float(screening["ctr_threshold"]) * 100)
    ctr_pct = int(ctr_pct if ctr_pct is not None else 10)
    eng_pct = screening.get("engagement_rate_percent")
    if eng_pct is None and isinstance(screening.get("engagement_threshold"), (int, float)):
        eng_pct = round(float(screening["engagement_threshold"]) * 100)
    eng_pct = int(eng_pct if eng_pct is not None else 7)
    rule_text = screening.get("rule_text") or (
        f"发布{hours}小时内 CTR>{ctr_pct}% 且互动率>{eng_pct}% 的自然笔记，优先进入聚光素材池"
    )
    warning = screening.get("warning") or "阈值需用品牌历史中位数校准；示例值非平台通用事实"
    search_kw = [str(x).strip() for x in (search_keywords or []) if str(x).strip()][:6]
    rising = [str(x).strip() for x in (rising_follow or []) if str(x).strip()][:4]
    directions = [str(x).strip() for x in (content_directions or []) if str(x).strip()][:3]
    guide = goal_split_guide(goal)
    probe = round(float(probe_budget_cny)) if isinstance(probe_budget_cny, (int, float)) else None

    start_triggers = [
        {
            "metric": f"自然笔记{hours}h CTR",
            "threshold": f">{ctr_pct}%",
            "action": "达标后复制进聚光创意池，用冷启动探测预算开测",
        },
        {
            "metric": f"自然笔记{hours}h 互动率",
            "threshold": f">{eng_pct}%",
            "action": "与 CTR 同时过线才启动投流，避免单指标虚高",
        },
        {
            "metric": "冷启动最小点击/转化样本",
            "threshold": "达账户观察窗最小样本",
            "action": "未达样本前不提价、不扩定向；只换素材或暂停",
        },
    ]
    recirculation = [
        "付费点击/收藏人群做信息流相似扩量，撬动二次种草与自然讨论回流",
        "高转化搜索词反哺自然标题/标签布局，巩固搜索占位",
        "聚光胜出封面结构同步给自然内容矩阵，提高下一轮自然过线率",
    ]
    if search_kw:
        recirculation.insert(
            1,
            f"优先用搜索词占位并回流选题：{'、'.join(search_kw)}",
        )
    if rising:
        recirculation.append(f"热搜跟进词仅小预算试探：{'、'.join(rising)}")
    if directions:
        recirculation.append(f"内容方向沿用画像矩阵：{'、'.join(directions)}")

    return {
        "principle": (
            "先自然验证，再小预算投流；付费数据反哺选题与词库，形成自然↔付费闭环。"
            f"本案目标「{guide['goal_label']}」自然:聚光={guide['ratio_label']}。"
        ),
        "start_paid_when": {
            "observation_hours": hours,
            "ctr_percent": ctr_pct,
            "engagement_rate_percent": eng_pct,
            "rule_text": rule_text,
            "probe_budget_cny": probe,
            "warning": warning,
        },
        "triggers": start_triggers,
        "recirculation_loops": recirculation,
        "phase_handoff": [
            {
                "from_phase": "预热期",
                "to_phase": "爆发期",
                "condition": "至少 1 组素材/定向过门槛且成本未触止损",
                "action": "把预热预算胜出单元复制放大，爆发期集中 60% 投流预算",
            },
            {
                "from_phase": "爆发期",
                "to_phase": "长尾期",
                "condition": "主目标连续两个观察窗稳定",
                "action": "收缩到高 ROI 搜索词与稳健素材，保留 20% 投流做占位",
            },
        ],
    }


def build_emergency_adjustments(
    *,
    phases: list[dict[str, Any]] | None = None,
    goal: str = "conversion",
    organic_budget_cny: float | None = None,
    paid_budget_cny: float | None = None,
) -> list[dict[str, Any]]:
    """未达预期时的分阶段应急：调预算分配 + 调内容方向。"""
    guide = goal_split_guide(goal)
    phase_map = {(row.get("name") or row.get("phase")): row for row in (phases or [])}
    warmup = phase_map.get("预热期") or {}
    burst = phase_map.get("爆发期") or {}
    tail = phase_map.get("长尾期") or {}
    organic = (
        f"¥{int(round(organic_budget_cny)):,}"
        if isinstance(organic_budget_cny, (int, float))
        else "自然预算"
    )
    paid = (
        f"¥{int(round(paid_budget_cny)):,}"
        if isinstance(paid_budget_cny, (int, float))
        else "聚光预算"
    )
    warmup_paid = warmup.get("paid_budget_cny")
    burst_paid = burst.get("paid_budget_cny")

    return [
        {
            "scenario": "自然流量未达预期",
            "symptom": "预热期自然 CTR/互动持续低于门槛，可放大素材池不足",
            "phase_focus": "预热期为主，必要时延长预热、压缩爆发",
            "budget_adjustment": (
                f"暂缓把预热投流（约 ¥{int(warmup_paid):,}）转入爆发；"
                f"把 {organic} 中至少 30% 回流到首屏/封面/选题重做，"
                f"聚光仅保留探测额，不扩量。"
                if isinstance(warmup_paid, (int, float))
                else "延长预热、压缩爆发；自然预算优先重做首屏，聚光只保留探测额。"
            ),
            "content_adjustment": [
                "暂停同质扩产，只保留 1–2 个方向做唯一变量测试",
                "重做标题钩子与封面信息密度，对齐画像痛点",
                "评论区引导收藏/提问，抬升互动率后再评估投流",
            ],
            "owner": "内容负责人",
        },
        {
            "scenario": "聚光效果未达预期（点击/成本）",
            "symptom": "CPC/CTR 劣于止损线，或冷启动长时间无量",
            "phase_focus": "预热期纠偏；爆发期触及止损立即缩预算",
            "budget_adjustment": (
                f"爆发期预算（约 ¥{int(burst_paid):,}）按观察窗下调 20%–40%，"
                f"撤回至搜索高意向词与已验证素材；"
                f"总配比可临时向自然侧倾斜（在 {guide['ratio_label']} 护栏内 ±10%）。"
                if isinstance(burst_paid, (int, float))
                else "下调爆发期投流份额，预算撤回已验证搜索词/素材。"
            ),
            "content_adjustment": [
                "先换素材，再改定向，不同时大改出价+定向+素材",
                "收窄到关键词策略中的核心/长尾高意向词",
                "暂停蓝海试探词，避免无效消耗",
            ],
            "owner": "优化师",
        },
        {
            "scenario": "转化/目标完成率未达预期",
            "symptom": "有点击但转化/收藏/搜索抬升不足",
            "phase_focus": "爆发期中后段与长尾期",
            "budget_adjustment": (
                f"从信息流宽定向抽预算到搜索承接与高意向人群包；"
                f"长尾期（约 ¥{int(tail.get('paid_budget_cny')):,}）优先搜索词占位。"
                if isinstance(tail.get("paid_budget_cny"), (int, float))
                else "压缩宽定向信息流，把预算转到搜索承接与高意向包。"
            ),
            "content_adjustment": [
                "检查落地页/价格力/私信表单承接，而不是只加预算",
                "正文补齐信任证据与对比决策信息",
                "用付费高转化词反写自然笔记标题，提升搜索自然回流",
            ],
            "owner": "优化师 + 运营",
        },
        {
            "scenario": "阶段节奏失衡（爆发过早/过晚）",
            "symptom": "未筛出胜出素材就进入爆发，或爆发后无可续航内容",
            "phase_focus": "全周期重切三阶段",
            "budget_adjustment": (
                f"若爆发过早：把部分爆发预算退回预热探测；"
                f"若爆发过晚：在成本稳定前提下，把长尾 20% 中最多一半临时并入爆发。"
                f"全案仍以 {paid} 为投流上限。"
            ),
            "content_adjustment": [
                "爆发期禁止大批量上新未验证创意",
                "长尾期必须留下胜出素材/词包清单供下一周期复用",
            ],
            "owner": "投放负责人",
        },
    ]


class BudgetSplitArgs(BaseModel):
    """LLM 提交的预算决策参数。"""

    total_budget_cny: float = Field(gt=0, description="总投放预算（元）")
    goal: Goal = Field(description="核心推广目标")
    organic_ratio: float | None = Field(
        default=None,
        ge=0.20,
        le=0.70,
        description=(
            "自然内容预算占比（0.20–0.70）。不填则使用目标默认档："
            "转化/客资/直播 0.30，曝光/互动 0.50，搜索增长 0.40。"
            "若偏离默认档超过 ±0.10，必须在 rationale 中说明证据依据。"
        ),
    )
    rationale: str = Field(
        min_length=10,
        description="选择该比例的理由，必须引用输入证据或默认档说明",
    )


def compute_budget_split(args: BudgetSplitArgs) -> dict[str, Any]:
    default_ratio = DEFAULT_ORGANIC_RATIO[args.goal]
    ratio = args.organic_ratio if args.organic_ratio is not None else default_ratio
    deviation = round(abs(ratio - default_ratio), 4)
    organic = round(args.total_budget_cny * ratio)
    paid = round(args.total_budget_cny - organic)
    detailed_phases = build_campaign_phases(campaign_days=30, paid_budget_cny=paid)
    phases = [
        {
            "phase": row["name"],
            "paid_budget_cny": row["paid_budget_cny"],
            "share_of_paid": row["paid_ratio"],
            "summary": row["summary"],
        }
        for row in detailed_phases
    ]
    return {
        "goal": args.goal,
        "organic_ratio": ratio,
        "default_ratio_for_goal": default_ratio,
        "deviation_from_default": deviation,
        "needs_review": deviation > 0.10,
        "organic_budget_cny": organic,
        "paid_budget_cny": paid,
        "paid_phases": phases,
        "campaign_phases": detailed_phases,
        "decision_rationale": args.rationale,
        "arithmetic_check": organic + paid == round(args.total_budget_cny),
    }


BUDGET_TOOLS = [
    ToolSpec(
        name="compute_budget_split",
        description=(
            "按推广目标拆分总预算为自然内容预算与聚光投流预算，"
            "并输出预热/爆发/长尾三阶段的付费预算。金额计算由本工具保证准确。"
        ),
        args_model=BudgetSplitArgs,
        fn=compute_budget_split,
    )
]
