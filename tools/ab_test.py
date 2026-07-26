"""A/B 测试方案生成工具（加分项）。

输出的是「预热期怎么测」的实验设计表，不是投放后的效果结果。
scenario_ratio 仅用于探测预算情景拆分提示，不进入正式预算汇总。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from tools.registry import ToolSpec


class TopicVariant(BaseModel):
    direction: str = Field(description="内容方向")
    title: str = Field(default="", description="标题文案或模板")
    cover: str = Field(default="", description="封面建议")
    body: str = Field(default="", description="正文/内容要点建议")


class AbTestArgs(BaseModel):
    directions: list[str] = Field(min_length=1, max_length=5, description="内容方向名")
    title_variants_per_direction: int = Field(default=2, ge=1, le=3)
    cover_variants_per_direction: int = Field(default=2, ge=1, le=3)
    probe_budget_cny: float | None = Field(default=None, ge=0)
    min_clicks_per_cell: int = Field(default=50, ge=20, le=500)
    ctr_win_threshold: float = Field(default=0.10, ge=0.03, le=0.40)
    engagement_win_threshold: float = Field(default=0.07, ge=0.02, le=0.30)
    topic_variants: list[TopicVariant] = Field(
        default_factory=list,
        description="来自模块2的选题标题/封面，用于填满矩阵文案",
    )


def _variants_by_direction(
    directions: list[str],
    topic_variants: list[TopicVariant],
    title_n: int,
    cover_n: int,
) -> dict[str, dict[str, list[str]]]:
    """为每个方向准备标题列表与封面列表。"""
    grouped: dict[str, list[TopicVariant]] = {d: [] for d in directions}
    for row in topic_variants:
        name = (row.direction or "").strip()
        if name in grouped:
            grouped[name].append(row)
        elif directions:
            # 方向名不完全一致时，轮转塞进各方向
            pass
    # 未匹配的选题按顺序轮转补给各方向
    unmatched = [
        row
        for row in topic_variants
        if (row.direction or "").strip() not in grouped
    ]
    if unmatched:
        for index, row in enumerate(unmatched):
            grouped[directions[index % len(directions)]].append(row)

    prepared: dict[str, dict[str, list[str]]] = {}
    for direction in directions:
        rows = grouped.get(direction) or []
        titles = [r.title.strip() for r in rows if r.title and r.title.strip()]
        covers = [r.cover.strip() for r in rows if r.cover and r.cover.strip()]
        bodies = [r.body.strip() for r in rows if r.body and r.body.strip()]
        # 标题不够时用可读占位，并标明「待替换」
        while len(titles) < title_n:
            idx = len(titles) + 1
            titles.append(f"「{direction}」待填标题{idx}")
        while len(covers) < cover_n:
            idx = len(covers) + 1
            covers.append(f"「{direction}」待填封面{idx}")
        while len(bodies) < max(title_n, cover_n, 1):
            idx = len(bodies) + 1
            bodies.append(f"「{direction}」待填正文要点{idx}：痛点开场→证据→行动号召")
        prepared[direction] = {
            "titles": titles[:title_n],
            "covers": covers[:cover_n],
            "bodies": bodies,
        }
    return prepared


def build_ab_matrix(args: AbTestArgs) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    titles_n = args.title_variants_per_direction
    covers_n = args.cover_variants_per_direction
    cell_count = len(args.directions) * titles_n * covers_n
    equal_share = round(1 / cell_count, 4) if cell_count else 0
    prepared = _variants_by_direction(
        list(args.directions),
        list(args.topic_variants or []),
        titles_n,
        covers_n,
    )
    for direction in args.directions:
        pack = prepared[direction]
        for title_i in range(1, titles_n + 1):
            for cover_i in range(1, covers_n + 1):
                title_text = pack["titles"][title_i - 1]
                cover_text = pack["covers"][cover_i - 1]
                body_pool = pack["bodies"] or [f"「{direction}」待填正文要点"]
                body_text = body_pool[(title_i + cover_i - 2) % len(body_pool)]
                cells.append(
                    {
                        "cell_id": f"{direction}-T{title_i}-C{cover_i}",
                        "direction": direction,
                        "title_variant": f"标题方案{title_i}",
                        "cover_variant": f"封面方案{cover_i}",
                        "content_variant": f"正文方案{((title_i + cover_i - 2) % len(body_pool)) + 1}",
                        "title_text": title_text,
                        "cover_text": cover_text,
                        "body_text": body_text,
                        "what_to_test": (
                            f"用「{title_text}」当标题，配「{cover_text}」封面，"
                            f"正文按「{body_text}」展开，只测这个组合好不好"
                        ),
                        "scenario_ratio": equal_share,
                        "probe_share_label": f"约{equal_share:.0%}",
                        "min_clicks": args.min_clicks_per_cell,
                        "result_status": "待投放",
                        "result_note": "尚未有真实数据；这是实验计划，不是效果结果",
                        "purpose": "预热期小流量对比用，不进入正式预算汇总",
                    }
                )
    per_cell_budget = None
    if isinstance(args.probe_budget_cny, (int, float)) and cell_count:
        per_cell_budget = round(float(args.probe_budget_cny) / cell_count, 2)

    return {
        "title": "A/B 测试计划（不是效果结果）",
        "what_it_is": (
            "这是预热期的实验设计表：自动生成「内容方向 × 标题 × 封面 × 正文要点」要测哪些组合，"
            "并给出测试指标与判断标准。现在还没有 CTR/互动等实测结果；"
            "投完并攒够点击后，才能判断哪一格胜出。"
        ),
        "how_to_read": [
            "每一行 = 一条要测的笔记组合（标题+封面+正文要点只按该行搭配）",
            "探测份额 = 建议把探测预算大致均分到各格，不是全案预算占比",
            "单格至少攒够最小点击后，再比 CTR 和互动率",
            "胜出组合再进入爆发期放大；未达样本前不要凭单日数据宣布胜负",
        ],
        "status": "plan_only",
        "status_label": "仅实验计划 · 无实测效果",
        "matrix": cells,
        "cell_count": cell_count,
        "probe_budget_cny": args.probe_budget_cny,
        "budget_per_cell_cny": per_cell_budget,
        "success_metrics": [
            f"单格点击≥{args.min_clicks_per_cell} 才开始比较",
            f"胜出格 CTR≥{args.ctr_win_threshold:.0%} 或明显高于同方向其他格",
            f"胜出格互动率≥{args.engagement_win_threshold:.0%}",
        ],
        "decision_rule": (
            "达到最小点击后，只放大 CTR 与互动率同时领先的格子；"
            "未达样本前禁止按单日波动宣布胜负。"
        ),
        "human_review_items": [
            "每个格子尽量只改标题或封面一个变量（本表按正交组合列出）",
            "探测份额不要写进正式预算计划",
            "把「待填标题/封面」替换成模块2真实选题后再开测",
        ],
    }


AB_TEST_TOOLS = [
    ToolSpec(
        name="build_ab_test_matrix",
        description="按内容方向生成标题×封面正交 A/B 实验计划（非效果结果）与判断标准",
        args_model=AbTestArgs,
        fn=build_ab_matrix,
    )
]
