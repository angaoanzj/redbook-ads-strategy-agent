"""模块3（关键词策略与达人匹配）Agent 实例。

角色：把「三类关键词赛道（自然分层 + 搜索/信息流广告词）、达人分层预算、达人匹配
名单与名额缺口」的决策权交给 LLM；有上游「模块6共享词表」时直接复用，否则必须先经
build_keyword_tiers；分层预算必须先经 plan_creator_tiers、达人名单必须先经
match_creators（只转录证据达人）；最终 JSON 的相关词表、金额、匹配分与单篇放大预算
必须取自工具通过后的结果（共享词表场景下 organic 层取自上游客）。matched_creators 为
空时如实为空，并在 human_review_items 说明。

本文件只 import models 与 base，禁止 import engine。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from models import CampaignRequest
from module_agents.base import ModuleAgentSpec, run_module_agent
from module_agents.module6 import _aggregate_evidence_topics


# ---------------------------------------------------------------------------
# 输出契约
# ---------------------------------------------------------------------------
class OrganicKeyword(BaseModel):
    keyword: str = Field(min_length=2, max_length=24)
    intent: Literal["high", "mid", "low"]
    lane: Literal["search", "feed", "both"]


class OrganicTracks(BaseModel):
    core: list[OrganicKeyword] = Field(min_length=2)
    long_tail: list[OrganicKeyword] = Field(min_length=4)
    blue_ocean: list[OrganicKeyword] = Field(min_length=2)


class AdKeyword(BaseModel):
    keyword: str = Field(min_length=2, max_length=24)
    bid_note: str = Field(min_length=1)


class KeywordTracks(BaseModel):
    organic: OrganicTracks
    search_ads: list[AdKeyword] = Field(min_length=3, max_length=15)
    feed_ads: list[AdKeyword] = Field(min_length=3, max_length=15)


class CreatorTier(BaseModel):
    tier: str
    count: int
    collaboration_budget_cny: int
    spotlight_amplification_budget_cny: int


class CreatorPlan(BaseModel):
    tiers: list[CreatorTier] = Field(min_length=1)
    amplification_pool_cny: int


class MatchedCreator(BaseModel):
    name: str
    tier: str
    match_score: int = Field(ge=0, le=100)
    suggested_note_budget_cny: int | None = None
    source: str


class OpenSlot(BaseModel):
    tier: str
    slots_needed: int = Field(ge=1)


class Module3Output(BaseModel):
    keyword_tracks: KeywordTracks
    creator_plan: CreatorPlan
    matched_creators: list[MatchedCreator] = Field(max_length=20)
    open_slots: list[OpenSlot] = Field(default_factory=list, max_length=3)
    human_review_items: list[str] = Field(min_length=1, max_length=6)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """你是小红书投放策略中「模块3：关键词策略与达人匹配」的决策 Agent。
你的职责：产出三类关键词赛道（自然分层 core/long_tail/blue_ocean、搜索广告词、
信息流广告词）、达人分层预算、达人匹配名单与名额缺口。

铁律：
1. 若上游上下文含「【模块6共享词表】」整段 JSON：keyword_tracks.organic 三层必须直接
   采用该共享词表的 keyword_levels（字段 keyword/intent/lane；bid_note 可忽略），
   level 比例供人工参考；禁止再调用 build_keyword_tiers 另起一套；search_ads /
   feed_ads 仍从该词库挑选并配 bid_note 文案。
   若上游无共享词表，才必须先调用 build_keyword_tiers 校验（去重、各级数量下限、
   预算比例合计为 1、出价数学）；keyword_tracks.organic 的三层必须取自工具通过后的结果；
   search_ads/feed_ads 从词库中挑选并配 bid_note 文案。
2. 达人分层预算必须先调用 plan_creator_tiers；creator_plan.tiers 的
   collaboration_budget_cny/spotlight_amplification_budget_cny 与
   amplification_pool_cny 必须与工具返回一致。
3. 达人匹配名单必须先调用 match_creators：只转录证据区里出现过的达人，从画像/卖点
   提炼 audience_keywords，tier_budgets 用 plan_creator_tiers 得到的各层单人预算参考；
   matched_creators 的 match_score 与 suggested_note_budget_cny、open_slots 必须取自
   工具返回。无达人证据时 matched_creators 如实为空，并在 human_review_items 说明需
   导入 CSV/蒲公英后补齐。
4. 工具返回参数校验错误时，按 details 修正后重新调用，不要绕过工具。

完成工具调用后，只输出一个 ```json 代码块（不要输出多余文字），结构如下：
{
  "keyword_tracks": {
     "organic": {"core": [ {"keyword": str, "intent": "high|mid|low",
        "lane": "search|feed|both"}, ≥2 ], "long_tail": [ ...≥4 ],
        "blue_ocean": [ ...≥2 ]},
     "search_ads": [ {"keyword": str, "bid_note": str}, 3-15 项 ],
     "feed_ads": [ {"keyword": str, "bid_note": str}, 3-15 项 ]},
  "creator_plan": {"tiers": [ {"tier": str, "count": int,
     "collaboration_budget_cny": int, "spotlight_amplification_budget_cny": int}, ... ],
     "amplification_pool_cny": int},
  "matched_creators": [ {"name": str, "tier": str, "match_score": int,
     "suggested_note_budget_cny": int 或 null, "source": str}, 0-20 项 ],
  "open_slots": [ {"tier": str, "slots_needed": int}, 0-3 项 ],
  "human_review_items": [ str, ... 1-6 条 ]
}
词表、金额、匹配分与单篇放大预算必须与对应工具通过后的结果一致。"""


# ---------------------------------------------------------------------------
# User prompt 渲染
# ---------------------------------------------------------------------------
_CPC_METRIC_HINTS = ("cpc", "cost_per_click", "cost_per_interaction")


def build_user_prompt(req: CampaignRequest) -> str:
    selling_points = "、".join(req.selling_points)
    lines = [
        f"品牌：{req.brand_name}（{req.category}）",
        f"商品：{req.product_name}",
        f"核心卖点：{selling_points}",
        f"核心目标：{req.goal}，初始人群：{req.initial_audience}",
        f"总预算：{req.total_budget_cny:g} 元，周期 {req.campaign_days} 天",
    ]
    if req.spotlight_budget_cny:
        lines.append(
            f"聚光投流预算：{req.spotlight_budget_cny:g} 元（作为 plan_creator_tiers 的 paid_budget_cny 参考）"
        )
    else:
        lines.append(
            "未提供聚光投流预算：请先按目标用 compute_budget_split 取自然/付费拆分，"
            "再作为 plan_creator_tiers 的输入。"
        )
    if req.constraints:
        lines.append("约束：" + "；".join(req.constraints))

    evidence: list[str] = []

    topics = _aggregate_evidence_topics(req)
    if topics:
        evidence.append(
            f"品类笔记证据主题词（共 {len(req.category_note_evidence)} 条笔记，取前 12 个高频主题；"
            "core/long_tail 优先从这些主题衍生并置 from_evidence=true）："
        )
        for item in topics:
            evidence.append(
                f"  - {item['theme']}（出现 {item['count']} 次，累计互动 {item['total_interactions']}）"
            )
    else:
        evidence.append("无品类笔记证据：关键词只生成待验证种子词（from_evidence=false）。")

    # 基准 CPC
    cpc_lines: list[str] = []
    for item in req.benchmark_evidence:
        name = (item.metric_name or "").lower()
        if any(hint in name for hint in _CPC_METRIC_HINTS):
            cpc_lines.append(
                f"  - {item.metric_name} = {item.value:g} {item.unit}（来源：{item.source_name}）"
            )
    if cpc_lines:
        evidence.append("基准 CPC 证据（传入 build_keyword_tiers 的 baseline_cpc_cny + baseline_source）：")
        evidence.extend(cpc_lines)
    else:
        evidence.append("无基准 CPC 证据：build_keyword_tiers 的 baseline_cpc_cny 传 null，出价区间留空。")

    # 达人证据逐条
    if req.creator_evidence:
        evidence.append(
            f"达人证据（共 {len(req.creator_evidence)} 条；转录进 match_creators，只转录这些达人）："
        )
        for c in req.creator_evidence:
            followers = c.followers if c.followers is not None else "粉丝未知"
            avg = c.average_interactions if c.average_interactions is not None else "篇均互动未知"
            quote = f"{c.quote_cny:g}元" if c.quote_cny is not None else "报价未知"
            tags = "、".join(c.audience_tags) if c.audience_tags else "无标签"
            evidence.append(
                f"  - {c.name}｜粉丝：{followers}｜{avg}｜报价：{quote}｜受众：{tags}｜来源：{c.source_name}"
            )
    else:
        evidence.append(
            "无达人证据：match_creators 的 creators 传空数组，matched_creators 如实为空，"
            "并在 human_review_items 说明需导入 CSV/蒲公英后补齐。"
        )

    task = (
        "请完成：\n"
        "1) 构造候选关键词（8-40 个，标注 level/intent/lane/from_evidence）与三级预算比例，"
        "调 build_keyword_tiers 校验取回，并挑选搜索/信息流广告词配 bid_note；\n"
        "2) 决策达人分层结构，调 plan_creator_tiers 得到各层合作预算与聚光二次放大预算；\n"
        "3) 从画像/卖点提炼 audience_keywords，用 plan_creator_tiers 得到的各层单人预算作为"
        "tier_budgets，调 match_creators 得到匹配名单、单篇放大预算与名额缺口；\n"
        "4) 列出需人工拍板事项；\n"
        "5) 最终只输出一个 ```json 代码块，词表/金额/匹配分/单篇预算取自工具结果。"
    )

    return "\n".join(lines) + "\n\n证据区：\n" + "\n".join(evidence) + "\n\n" + task


# ---------------------------------------------------------------------------
# Spec 与便捷函数
# ---------------------------------------------------------------------------
MODULE3_SPEC = ModuleAgentSpec(
    name="module3_keyword_creator",
    title="模块3：关键词策略与达人匹配",
    system_prompt=SYSTEM_PROMPT,
    output_model=Module3Output,
    build_user_prompt=build_user_prompt,
    # 由工具真正产出的数字：分层预算（plan_creator_tiers）与匹配分/单篇预算（match_creators）。
    grounded_fields=[
        "creator_plan.tiers.*.collaboration_budget_cny",
        "creator_plan.tiers.*.spotlight_amplification_budget_cny",
        "creator_plan.amplification_pool_cny",
        "matched_creators.*.match_score",
        "matched_creators.*.suggested_note_budget_cny",
    ],
)


def run_module3(
    req: CampaignRequest, *, transport=None, upstream_context: str = ""
) -> dict:
    """跑模块3 Agent，返回 {module, output, grounding_check, steps_used, ...}。

    upstream_context：编排层注入的上游模块结论摘要（默认空，行为与之前一致）。
    """
    return run_module_agent(
        MODULE3_SPEC, req, transport=transport, upstream_context=upstream_context
    )
