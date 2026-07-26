"""模块2（用户画像与内容策略）Agent 实例。

角色：把「用户画像三维（人口/行为/心理）、聚光定向标签、三大内容方向与 15 个选题、
素材筛选标准」的决策权交给 LLM，但内容方向的双评分、15 个选题的结构与 CTR/互动率
阈值必须先经 score_content_topics 工具校验通过，最终 JSON 取工具确认后的内容。
画像三维与定向标签由 LLM 基于卖点/人群描述/证据主题撰写。

本文件只 import models 与 base，禁止 import engine。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from models import CampaignRequest
from module_agents.base import ModuleAgentSpec, run_module_agent
from module_agents.module6 import _aggregate_evidence_topics

PaidObjective = Literal["种草", "成交", "客资", "直播引流"]


# ---------------------------------------------------------------------------
# 输出契约
# ---------------------------------------------------------------------------
class TargetingTags(BaseModel):
    interest_tags: list[str] = Field(min_length=3, max_length=10)
    behavior_tags: list[str] = Field(min_length=3, max_length=10)
    crowd_packages: list[str] = Field(min_length=1, max_length=5)


class Persona(BaseModel):
    demographic: list[str] = Field(min_length=2, max_length=6)
    behavioral: list[str] = Field(min_length=2, max_length=6)
    psychological: list[str] = Field(min_length=2, max_length=6)
    targeting_tags: TargetingTags
    tag_status: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_tag_status(self) -> "Persona":
        if "标签需在聚光后台核对可用性" not in self.tag_status:
            raise ValueError("tag_status 必须注明「标签需在聚光后台核对可用性」")
        return self


class ContentDirection(BaseModel):
    direction: str
    organic_score: int = Field(ge=1, le=10)
    paid_score: int = Field(ge=1, le=10)
    rationale: str = Field(min_length=8)


class Topic(BaseModel):
    title_template: str = Field(min_length=6)
    cover_suggestion: str = Field(min_length=4)
    outline: list[str] = Field(min_length=2, max_length=5)
    direction: str
    suitable_for_paid: bool
    paid_objective: PaidObjective | None = None

    @model_validator(mode="after")
    def check_paid_objective(self) -> "Topic":
        if self.suitable_for_paid and self.paid_objective is None:
            raise ValueError(
                f"选题「{self.title_template}」suitable_for_paid=True 时必须填 paid_objective"
            )
        return self


class MaterialScreening(BaseModel):
    ctr_threshold: float = Field(ge=0.03, le=0.30)
    engagement_threshold: float = Field(ge=0.02, le=0.20)
    extra_rules: list[str] = Field(min_length=1, max_length=4)


class Module2Output(BaseModel):
    persona: Persona
    content_directions: list[ContentDirection] = Field(min_length=3, max_length=3)
    topics: list[Topic] = Field(min_length=15, max_length=15)
    material_screening: MaterialScreening
    human_review_items: list[str] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def check_directions(self) -> "Module2Output":
        names = {d.direction.strip() for d in self.content_directions}
        offenders = [t.title_template for t in self.topics if t.direction.strip() not in names]
        if offenders:
            raise ValueError("以下选题的 direction 未命中三方向之一：" + "、".join(offenders))
        counts = {d.direction.strip(): 0 for d in self.content_directions}
        for t in self.topics:
            counts[t.direction.strip()] += 1
        shortfalls = [name for name, c in counts.items() if c < 3]
        if shortfalls:
            raise ValueError("每方向至少 3 个选题，不足：" + "、".join(shortfalls))
        return self


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """你是小红书投放策略中「模块2：用户画像与内容策略」的决策 Agent。
你的职责：基于卖点、人群描述与品类笔记证据，产出用户画像三维（人口/行为/心理）、
聚光定向标签、三大内容方向（含自然/付费双评分）、15 个选题与素材筛选标准。

铁律：
1. 三个内容方向（direction/organic_score/paid_score/rationale）、恰好 15 个选题
   （title_template/cover_suggestion/outline/direction/suitable_for_paid/paid_objective）
   与 CTR/互动率阈值，必须先调用 score_content_topics 校验通过：工具会校验每方向
   至少 3 个选题、每个选题方向命中三方向之一、付费选题必须带合法投放目标
   （种草/成交/客资/直播引流）；最终 JSON 的 content_directions、topics、
   material_screening.ctr_threshold/engagement_threshold 必须取自工具确认后的内容。
2. 画像三维与定向标签（interest_tags/behavior_tags/crowd_packages）由你基于卖点、
   人群描述与证据主题撰写；tag_status 必须注明「标签需在聚光后台核对可用性」。
3. content_directions 的 organic_score/paid_score 与 material_screening 的两个阈值
   必须与工具返回一致，不要另行改动。
4. 工具返回参数校验错误（方向未命中/每方向不足 3/付费缺目标）时，按 details 修正后
   重新调用，不要绕过工具。

完成工具调用后，只输出一个 ```json 代码块（不要输出多余文字），结构如下：
{
  "persona": {"demographic": [str, ...2-6], "behavioral": [str, ...2-6],
     "psychological": [str, ...2-6],
     "targeting_tags": {"interest_tags": [str, ...3-10],
        "behavior_tags": [str, ...3-10], "crowd_packages": [str, ...1-5]},
     "tag_status": str（含「标签需在聚光后台核对可用性」）},
  "content_directions": [ {"direction": str, "organic_score": int, "paid_score": int,
     "rationale": str}, 恰好 3 项 ],
  "topics": [ {"title_template": str, "cover_suggestion": str,
     "outline": [str, ...2-5], "direction": str, "suitable_for_paid": bool,
     "paid_objective": "种草|成交|客资|直播引流" 或 null}, 恰好 15 项 ],
  "material_screening": {"ctr_threshold": float, "engagement_threshold": float,
     "extra_rules": [str, ...1-4]},
  "human_review_items": [ str, ... 1-6 条 ]
}
方向双评分与两个阈值必须与 score_content_topics 通过后的结果一致。"""


# ---------------------------------------------------------------------------
# User prompt 渲染
# ---------------------------------------------------------------------------
def build_user_prompt(req: CampaignRequest) -> str:
    selling_points = "、".join(req.selling_points)
    if req.price_max > req.price_min:
        pricing = f"{req.price_min:g}–{req.price_max:g} {req.currency}"
    else:
        pricing = f"{req.price_min:g} {req.currency}"

    lines = [
        f"品牌：{req.brand_name}（{req.category}）",
        f"商品：{req.product_name}",
        f"核心卖点：{selling_points}",
        f"定价：{pricing}",
        f"核心目标：{req.goal}",
        f"初始人群：{req.initial_audience}",
    ]
    if req.constraints:
        lines.append("约束：" + "；".join(req.constraints))
    if req.targeting_knowledge_brief:
        lines.append(
            "定向知识库摘要（候选，须后台核对）：\n" + req.targeting_knowledge_brief.strip()
        )

    evidence: list[str] = []
    topics = _aggregate_evidence_topics(req)
    if topics:
        evidence.append(
            f"品类笔记证据主题词（共 {len(req.category_note_evidence)} 条笔记，取前 12 个高频主题；"
            "内容方向与选题优先从这些主题与卖点衍生）："
        )
        for item in topics:
            evidence.append(
                f"  - {item['theme']}（出现 {item['count']} 次，累计互动 {item['total_interactions']}）"
            )
    else:
        evidence.append("无品类笔记证据：内容方向与选题基于卖点与人群假设生成，并标注需人工核验。")

    task = (
        "请完成：\n"
        "1) 基于卖点/人群/证据主题撰写画像三维与聚光定向标签（tag_status 注明需后台核对）；\n"
        "2) 决策 3 个内容方向（含自然/付费双评分）与恰好 15 个选题（每方向≥3、付费选题带目标），"
        "并设定 CTR/互动率阈值，调 score_content_topics 校验并取回通过结果；\n"
        "3) 若被拒（方向未命中/每方向不足 3/付费缺目标），按 details 修正后重新调用；\n"
        "4) 补充 1-4 条素材筛选补充规则，列出需人工拍板事项；\n"
        "5) 最终只输出一个 ```json 代码块，方向双评分与阈值取自工具结果。"
    )

    return "\n".join(lines) + "\n\n证据区：\n" + "\n".join(evidence) + "\n\n" + task


# ---------------------------------------------------------------------------
# Spec 与便捷函数
# ---------------------------------------------------------------------------
MODULE2_SPEC = ModuleAgentSpec(
    name="module2_audience_content",
    title="模块2：用户画像与内容策略",
    system_prompt=SYSTEM_PROMPT,
    output_model=Module2Output,
    build_user_prompt=build_user_prompt,
    # 由工具 score_content_topics 真正产出的数字：三方向双评分与两个筛选阈值。
    grounded_fields=[
        "content_directions.*.organic_score",
        "content_directions.*.paid_score",
        "material_screening.ctr_threshold",
        "material_screening.engagement_threshold",
    ],
)


def run_module2(
    req: CampaignRequest, *, transport=None, upstream_context: str = ""
) -> dict:
    """跑模块2 Agent，返回 {module, output, grounding_check, steps_used, ...}。

    upstream_context：编排层注入的上游模块结论摘要（默认空，行为与之前一致）。
    """
    return run_module_agent(
        MODULE2_SPEC, req, transport=transport, upstream_context=upstream_context
    )
