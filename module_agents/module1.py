"""模块1（赛道与竞品分析）Agent 实例。

角色：把「赛道自然/付费格局判读、竞品共性与内容缺口、投放风险预警」的决策权交给
LLM，但竞品结论必须先经 summarize_competitor_landscape 聚合校验；付费格局的数字
只能取证据值并带来源，无证据一律 null + missing_notice，绝不编造 CPC/CPM/转化成本。

本文件只 import models 与 base，禁止 import engine。
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel, Field, model_validator

from models import CampaignRequest
from module_agents.base import ModuleAgentSpec, run_module_agent
from module_agents._evidence_aggregation import (
    extract_hour as _extract_hour,
    hour_bucket as _hour_bucket,
    note_interactions as _note_interactions,
)


# ---------------------------------------------------------------------------
# 输出契约
# ---------------------------------------------------------------------------
class HotFormat(BaseModel):
    format: str
    avg_interactions: float


class OrganicLandscape(BaseModel):
    sample_size: int = Field(ge=0)
    # 允许空列表：无品类笔记证据时必须留空，禁止编造形式与互动数（见 SYSTEM_PROMPT 铁律）
    hot_formats: list[HotFormat] = Field(min_length=0, max_length=4)
    peak_hour_hypothesis: str
    content_form_advice: list[str] = Field(min_length=2, max_length=4)
    boundary_note: str = Field(min_length=1)


class PaidLandscape(BaseModel):
    cpc_cny: float | None = None
    cpc_source: str | None = None
    cpm_cny: float | None = None
    cpm_source: str | None = None
    conversion_cost_cny: float | None = None
    conversion_cost_source: str | None = None
    missing_notice: str | None = None

    @model_validator(mode="after")
    def check_sources(self) -> "PaidLandscape":
        pairs = [
            ("cpc_cny", self.cpc_cny, self.cpc_source),
            ("cpm_cny", self.cpm_cny, self.cpm_source),
            ("conversion_cost_cny", self.conversion_cost_cny, self.conversion_cost_source),
        ]
        for name, value, source in pairs:
            if value is not None and not (source and source.strip()):
                raise ValueError(f"{name} 非空时必须提供对应来源")
        return self


class CompetitorBreakdown(BaseModel):
    common_patterns: list[str] = Field(min_length=1, max_length=5)
    content_gaps: list[str] = Field(default_factory=list)
    ad_labeled_count: int = Field(ge=0)
    targeting_hypotheses: list[str] = Field(min_length=1, max_length=4)
    budget_inference_policy: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_hypothesis_wording(self) -> "CompetitorBreakdown":
        offenders = [h for h in self.targeting_hypotheses if "假设" not in h]
        if offenders:
            raise ValueError(
                "targeting_hypotheses 每条措辞必须含「假设」，不得表述为竞品真实定向："
                + "、".join(offenders)
            )
        return self


class RiskAlert(BaseModel):
    risk: str
    source: str
    action: str


class Module1Output(BaseModel):
    organic_landscape: OrganicLandscape
    paid_landscape: PaidLandscape
    competitor_breakdown: CompetitorBreakdown
    risk_alerts: list[RiskAlert] = Field(min_length=2, max_length=6)
    human_review_items: list[str] = Field(min_length=1, max_length=6)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """你是小红书投放投手顾问，负责「模块1：赛道与竞品」的人话解读。
读者是品牌投手：要能直接拿去开会、开测，不要空话。

写作风格（必须遵守）：
- 用短句、说结论；每条尽量点名证据里的账号/标题钩子/主题/广告标识/评论意图。
- 禁止正确的废话：「建议加强内容运营」「持续优化投放」「提升用户体验」一律不许写。
- 动作要可执行：写清「测什么 / 对谁测 / 为什么 / 本周先做什么」。
- 数字图表由本地系统另算；你只负责把证据翻译成判断与动作，不编造趋势数字。

分块写法（对应 JSON 字段）：
1) competitor_breakdown.common_patterns＝爆款共性：每条=「看到了什么 → 对我们意味着什么」
2) competitor_breakdown.content_gaps＝空白点：优先用工具返回的缺口，再用卖点补强；写成可抢占切口
3) organic_landscape.peak_hour_hypothesis＝高峰时段人话（必须带「假设/待验证」若样本不足）
4) organic_landscape.content_form_advice＝形式建议：图文/视频各怎么拍，绑定卖点
5) targeting_hypotheses＝定向测试包（不是竞品真实定向）：每条必须含「假设」，并写成
   「假设人群 + 测试素材角度 + 观察指标」
6) risk_alerts＝风险：risk=问题，source=证据来源，action=0-48h 可做动作

铁律：
0. organic_landscape.hot_formats 只能来自品类笔记聚合；无笔记证据时 hot_formats=[]，
   禁止编造形式与互动数；用 boundary_note / human_review_items 说明缺口。
1. 竞品结论必须先调用 summarize_competitor_landscape：只转录证据区出现过的竞品，
   禁止新增证据里没有的竞品/URL。工具返回的 ad_labeled_count、content_gaps、
   budget_inference_policy、targeting_hypothesis_policy 必须原样采用。
2. 无竞品时 competitors=[] 调工具，禁止编造竞品凑数。
3. targeting_hypotheses 每条必须含「假设」，禁止写成竞品真实定向/真实预算。
4. paid_landscape 的 cpc/cpm/conversion_cost 只能取证据区数值并带来源；没有就 null +
   missing_notice，绝不编造。
5. boundary_note 必须声明：本样本≠全平台大盘。
6. 工具参数校验失败时按 details 修正重调，不要绕过工具。

完成工具调用后，只输出一个 ```json 代码块（不要多余文字）：
{
  "organic_landscape": {"sample_size": int, "hot_formats": [ {"format": str,
     "avg_interactions": float}, 0-4 项 ], "peak_hour_hypothesis": str,
     "content_form_advice": [str, ... 2-4 条], "boundary_note": str},
  "paid_landscape": {"cpc_cny": float|null, "cpc_source": str|null,
     "cpm_cny": float|null, "cpm_source": str|null,
     "conversion_cost_cny": float|null, "conversion_cost_source": str|null,
     "missing_notice": str|null},
  "competitor_breakdown": {"common_patterns": [str, ... 1-5 条],
     "content_gaps": [str, ...], "ad_labeled_count": int,
     "targeting_hypotheses": [str（含「假设」）, ... 1-4 条],
     "budget_inference_policy": str},
  "risk_alerts": [ {"risk": str, "source": str, "action": str}, 2-6 项 ],
  "human_review_items": [ str, ... 1-6 条 ]
}
ad_labeled_count 与 budget_inference_policy 必须与工具一致。"""


# ---------------------------------------------------------------------------
# 证据聚合（自实现，不 import engine）
# ---------------------------------------------------------------------------
_PAID_METRIC_HINTS = {
    "cpc": ("cpc", "cost_per_click", "点击成本"),
    "cpm": ("cpm", "cost_per_mille", "千次曝光"),
    "conversion": ("conversion", "cvr", "转化成本", "cpa"),
}


def _aggregate_organic(req: CampaignRequest) -> dict[str, Any]:
    type_counts: Counter[str] = Counter()
    type_interactions: Counter[str] = Counter()
    slot_counts: Counter[str] = Counter()
    for note in req.category_note_evidence:
        note_type = (note.note_type or "未标注形态").strip() or "未标注形态"
        type_counts[note_type] += 1
        type_interactions[note_type] += _note_interactions(note)
        hour = _extract_hour(note.published_at)
        if hour is not None:
            slot_counts[_hour_bucket(hour)] += 1
    formats = []
    for note_type, count in type_counts.most_common():
        avg = round(type_interactions[note_type] / count, 2) if count else 0.0
        formats.append({"note_type": note_type, "count": count, "avg_interactions": avg})
    return {
        "sample_size": len(req.category_note_evidence),
        "formats": formats,
        "time_slots": slot_counts.most_common(),
    }


# ---------------------------------------------------------------------------
# User prompt 渲染
# ---------------------------------------------------------------------------
def build_user_prompt(req: CampaignRequest) -> str:
    selling_points = "、".join(req.selling_points)
    lines = [
        f"品牌：{req.brand_name}（{req.category}）",
        f"商品：{req.product_name}",
        f"核心卖点：{selling_points}",
        f"核心目标：{req.goal}，初始人群：{req.initial_audience}",
    ]
    if req.constraints:
        lines.append("约束：" + "；".join(req.constraints))

    evidence: list[str] = []

    # 自然格局：笔记形态分布 + 平均互动 + 发布时段
    organic = _aggregate_organic(req)
    if organic["formats"]:
        evidence.append(
            f"品类笔记证据（共 {organic['sample_size']} 条；hot_formats 与 avg_interactions "
            "只能取自下列聚合，boundary_note 必须声明样本≠全平台大盘）："
        )
        for row in organic["formats"]:
            evidence.append(
                f"  - 形态「{row['note_type']}」：{row['count']} 条，平均互动 {row['avg_interactions']}"
            )
        if organic["time_slots"]:
            slots = "，".join(f"{slot} {count}条" for slot, count in organic["time_slots"])
            evidence.append(f"  发布时段分布（仅计有 published_at 的笔记）：{slots}")
        else:
            evidence.append("  发布时段：无 published_at 数据，peak_hour_hypothesis 需标注为待验证假设。")
    else:
        evidence.append(
            "无品类笔记证据：hot_formats 必须留空（空数组），禁止编造形式与互动数；"
            "organic_landscape 其余字段保守假设，并在 boundary_note 声明证据不足。"
        )

    # 竞品逐条（尽量给全标题/主题/受众，方便模型写人话共性）
    if req.competitor_evidence:
        evidence.append(
            f"竞品证据（共 {len(req.competitor_evidence)} 条；转录进 summarize_competitor_landscape，"
            "禁止新增证据里没有的竞品；写共性时优先引用下列标题/主题/受众信号）："
        )
        for comp in req.competitor_evidence:
            ad = (
                "带广告标识" if comp.is_ad_labeled is True
                else "无广告标识" if comp.is_ad_labeled is False
                else "广告标识未知"
            )
            inter = comp.interactions if comp.interactions is not None else "互动未知"
            title = (comp.title or "").strip()
            themes = "、".join((comp.content_themes or [])[:4])
            audience = "、".join((comp.observed_audience or [])[:4])
            note = f"；备注：{comp.notes}" if comp.notes else ""
            bits = [
                f"{comp.account_name}",
                f"标题：{title}" if title else "标题：—",
                f"形态：{comp.note_format or '未知'}",
                f"互动：{inter}",
                ad,
            ]
            if themes:
                bits.append(f"主题：{themes}")
            if audience:
                bits.append(f"受众/评论信号：{audience}")
            evidence.append("  - " + "｜".join(bits) + note)
    else:
        evidence.append(
            "无竞品证据：调用 summarize_competitor_landscape 时 competitors 传空列表"
            "（工具会返回诚实的无竞品结论，content_gaps=全部卖点、ad_labeled_count=0、"
            "预算政策=禁止推测），禁止编造竞品条目或 URL；并在 human_review_items 标注需补采竞品。"
        )

    # 付费基准指标
    paid_lines: list[str] = []
    for item in req.benchmark_evidence:
        name = (item.metric_name or "").lower()
        for hints in _PAID_METRIC_HINTS.values():
            if any(hint in name for hint in hints):
                paid_lines.append(
                    f"  - {item.metric_name} = {item.value:g} {item.unit}（来源：{item.source_name}）"
                )
                break
    if paid_lines:
        evidence.append("付费基准指标（paid_landscape 只能取这些值并带来源，其余填 null）：")
        evidence.extend(paid_lines)
    else:
        evidence.append(
            "无 CPC/CPM/转化成本类基准证据：paid_landscape 三个数字全部填 null，"
            "并在 missing_notice 说明缺口。"
        )

    # 违规台账与官方规则标题
    if req.account_violation_evidence:
        evidence.append("账户/赛道违规台账（作为 risk_alerts 依据）：")
        for v in req.account_violation_evidence:
            evidence.append(
                f"  - {v.reason}：{v.period} 内 {v.occurrence_count} 次（来源：{v.source_name}）"
            )
    if req.official_rule_evidence:
        titles = "；".join(rule.title for rule in req.official_rule_evidence)
        evidence.append(f"官方规则条文标题（作为拒审/合规风险依据）：{titles}")
    if not req.account_violation_evidence and not req.official_rule_evidence:
        evidence.append("无违规台账/官方规则证据：risk_alerts 仍需覆盖通用投放风险并标注来源为「通用经验，待证据补充」。")

    task = (
        "请完成（先工具、后 JSON；文字要像投手 briefing）：\n"
        "1) 调 summarize_competitor_landscape（转录竞品、传入自身卖点与已覆盖主题），"
        "取回 content_gaps、ad_labeled_count、预算/定向政策；\n"
        "2) 用证据写 common_patterns（爆款共性）与 content_gaps（空白点）——"
        "每条点名账号/标题钩子/主题，并落到「我们可怎么做」；\n"
        "3) 基于笔记聚合写 hot_formats / peak_hour_hypothesis / content_form_advice /"
        "boundary_note；\n"
        "4) paid_landscape 只取证据数字并带来源，无证据填 null + missing_notice；\n"
        "5) targeting_hypotheses 写成 1-4 条「假设人群+测试角度+观察指标」测试包；\n"
        "6) risk_alerts 2-6 条（含来源与 0-48h 动作），human_review_items 列出需人工拍板项；\n"
        "7) 最终只输出一个 ```json 代码块。"
    )

    return "\n".join(lines) + "\n\n证据区：\n" + "\n".join(evidence) + "\n\n" + task


# ---------------------------------------------------------------------------
# Spec 与便捷函数
# ---------------------------------------------------------------------------
MODULE1_SPEC = ModuleAgentSpec(
    name="module1_market_competitor",
    title="模块1：赛道与竞品分析",
    system_prompt=SYSTEM_PROMPT,
    output_model=Module1Output,
    build_user_prompt=build_user_prompt,
    # 自然/付费格局的数字多来自 prompt 证据而非工具结果，靠契约 source 字段约束；
    # 唯一由工具（summarize_competitor_landscape）真正产出的数字是 ad_labeled_count。
    grounded_fields=[
        "competitor_breakdown.ad_labeled_count",
    ],
)


def run_module1(
    req: CampaignRequest, *, transport=None, upstream_context: str = ""
) -> dict:
    """跑模块1 Agent，返回 {module, output, grounding_check, steps_used, ...}。

    upstream_context：编排层注入的上游模块结论摘要（默认空，行为与之前一致）。
    """
    return run_module_agent(
        MODULE1_SPEC, req, transport=transport, upstream_context=upstream_context
    )
