"""内容选题评分工具：把「三方向双评分」与「15 选题结构化校验」工具化。

分工：LLM 决策三个内容方向（含自然/付费双评分）与 15 个选题；本工具校验
每方向至少 3 个选题、每个选题的方向必须命中三方向之一（否则点名拒绝）、
付费选题必须带合法投放目标，并结构化返回按方向分组的选题、双评分矩阵、
付费适配统计与素材筛选标准（含 CTR/互动率阈值）。

本文件只依赖 pydantic 与 tools.registry，绝不 import engine。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from tools.registry import ToolSpec

MIN_TOPICS_PER_DIRECTION = 3
PaidObjective = Literal["种草", "成交", "客资", "直播引流"]


class DirectionScore(BaseModel):
    direction: str = Field(min_length=1, description="内容方向名")
    organic_score: int = Field(ge=1, le=10, description="自然流量适配评分 1-10")
    paid_score: int = Field(ge=1, le=10, description="付费投放适配评分 1-10")
    rationale: str = Field(min_length=8, description="该方向评分理由")


class TopicItem(BaseModel):
    title_template: str = Field(min_length=6, description="标题模板，至少 6 字")
    cover_suggestion: str = Field(min_length=4, description="封面建议，至少 4 字")
    outline: list[str] = Field(min_length=2, max_length=5, description="内容大纲 2-5 条")
    direction: str = Field(min_length=1, description="所属方向，必须命中三方向之一")
    suitable_for_paid: bool = Field(description="是否适合付费投放")
    paid_objective: PaidObjective | None = Field(
        default=None, description="付费投放目标，suitable_for_paid=True 时必填"
    )

    @model_validator(mode="after")
    def check_paid_objective(self) -> "TopicItem":
        if self.suitable_for_paid and self.paid_objective is None:
            raise ValueError(
                f"选题「{self.title_template}」标记 suitable_for_paid=True，"
                "必须填写 paid_objective（种草/成交/客资/直播引流）"
            )
        return self


class ContentTopicsArgs(BaseModel):
    """LLM 提交的三方向双评分与 15 个选题。"""

    directions: list[DirectionScore] = Field(
        min_length=3, max_length=3, description="恰好 3 个内容方向"
    )
    topics: list[TopicItem] = Field(
        min_length=15, max_length=15, description="恰好 15 个选题"
    )
    ctr_threshold: float = Field(
        default=0.10, ge=0.03, le=0.30, description="素材筛选：发布 24h CTR 阈值"
    )
    engagement_threshold: float = Field(
        default=0.07, ge=0.02, le=0.20, description="素材筛选：互动率阈值"
    )
    rationale: str = Field(min_length=10, description="选题矩阵的决策理由")

    @model_validator(mode="after")
    def check(self) -> "ContentTopicsArgs":
        direction_names = [d.direction.strip() for d in self.directions]
        if len(set(direction_names)) != len(direction_names):
            raise ValueError("directions 方向名不能重复")
        valid = set(direction_names)
        # 每个选题的方向必须命中三方向之一，否则点名拒绝
        offenders = [
            t.title_template for t in self.topics if t.direction.strip() not in valid
        ]
        if offenders:
            raise ValueError(
                "以下选题的 direction 未命中三方向之一："
                + "、".join(offenders)
                + f"（合法方向：{'、'.join(direction_names)}）"
            )
        # 每方向至少 3 个选题
        counts = {name: 0 for name in direction_names}
        for t in self.topics:
            counts[t.direction.strip()] += 1
        shortfalls = [
            f"{name}（当前 {counts[name]}）"
            for name in direction_names
            if counts[name] < MIN_TOPICS_PER_DIRECTION
        ]
        if shortfalls:
            raise ValueError(
                f"每个方向至少 {MIN_TOPICS_PER_DIRECTION} 个选题，不足："
                + "；".join(shortfalls)
            )
        return self


def score_content_topics(args: ContentTopicsArgs) -> dict[str, Any]:
    direction_names = [d.direction.strip() for d in args.directions]

    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in direction_names}
    paid_count = 0
    paid_objective_stats: dict[str, int] = {}
    for topic in args.topics:
        name = topic.direction.strip()
        grouped[name].append({
            "title_template": topic.title_template,
            "cover_suggestion": topic.cover_suggestion,
            "outline": list(topic.outline),
            "suitable_for_paid": topic.suitable_for_paid,
            "paid_objective": topic.paid_objective,
        })
        if topic.suitable_for_paid:
            paid_count += 1
            if topic.paid_objective:
                paid_objective_stats[topic.paid_objective] = (
                    paid_objective_stats.get(topic.paid_objective, 0) + 1
                )

    score_matrix = [
        {
            "direction": d.direction.strip(),
            "organic_score": d.organic_score,
            "paid_score": d.paid_score,
            "rationale": d.rationale,
        }
        for d in args.directions
    ]

    return {
        "topics_by_direction": grouped,
        "counts_by_direction": {name: len(rows) for name, rows in grouped.items()},
        "score_matrix": score_matrix,
        "paid_fit": {
            "paid_topic_count": paid_count,
            "organic_only_count": len(args.topics) - paid_count,
            "paid_objective_breakdown": paid_objective_stats,
        },
        "material_screening": {
            "ctr_threshold": args.ctr_threshold,
            "engagement_threshold": args.engagement_threshold,
            "criteria": [
                f"发布 24h CTR > {args.ctr_threshold}",
                f"互动率 > {args.engagement_threshold}",
                "评论正向占比人工判断",
            ],
        },
        "decision_rationale": args.rationale,
        "policy": "本工具只做选题分组与阈值校验；选题内容与方向由 LLM 基于卖点/人群/证据撰写",
    }


TOPIC_TOOLS = [
    ToolSpec(
        name="score_content_topics",
        description=(
            "校验三个内容方向（各含自然/付费双评分）与恰好 15 个选题："
            "每方向至少 3 个选题、每个选题方向必须命中三方向之一（否则点名拒绝）、"
            "付费选题必须带合法投放目标；返回分组选题、双评分矩阵、付费适配统计与素材筛选标准。"
        ),
        args_model=ContentTopicsArgs,
        fn=score_content_topics,
    )
]
