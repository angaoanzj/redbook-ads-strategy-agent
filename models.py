from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator


Goal = Literal["awareness", "engagement", "search_growth", "conversion", "leads", "live_traffic"]


class MetricEvidence(BaseModel):
    source_name: str
    source_url: str | None = None
    collected_at: str
    metric_name: str
    value: float
    unit: str
    notes: str | None = None
    evidence_grade: str = "C_user_provided"
    is_mock: bool = False
    mock_seed: str | None = None
    # 指标单一事实源规范（docs/no-code-agent/04_指标单一事实源规范.md）：
    # 统计期 / 计算口径 / 数值类型。全部可选且默认 None，旧 example 与存档不受影响；
    # 缺失时 evidence_policy 只能判定为「口径不可比」，不会伪造精度。
    period: str | None = Field(
        default=None, description="统计期，如 2026-01-01/2026-05-31"
    )
    formula: str | None = Field(default=None, description="计算口径，如 spend / clicks")
    value_kind: Literal["historical_fact", "forward_estimate"] | None = Field(
        default=None,
        description="historical_fact 必须是标量精确值；forward_estimate 必须表达为范围",
    )


class CompetitorEvidence(BaseModel):
    """对标账号/笔记证据：来自用户给定链接的公开页抓取，或用户导入/示例缓存。"""

    account_name: str
    profile_or_note_url: str
    title: str | None = None
    note_format: str | None = None
    interactions: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    favorites: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    is_ad_labeled: bool | None = None
    observed_audience: list[str] = Field(default_factory=list)
    content_themes: list[str] = Field(
        default_factory=list,
        description="由给定链接公开页拆解或用户导入的内容主题，用于爆款共性",
    )
    notes: str | None = None
    campaign_duration_days: int | None = Field(default=None, ge=1)
    estimated_budget_low_cny: float | None = Field(default=None, ge=0)
    estimated_budget_high_cny: float | None = Field(default=None, ge=0)
    source_name: str = "给定链接公开页抓取"
    collected_at: str | None = None
    is_mock: bool = False
    evidence_grade: str = "C_user_provided"
    mock_seed: str | None = None


class CreatorEvidence(BaseModel):
    name: str
    profile_url: str
    followers: int | None = Field(default=None, ge=0)
    average_interactions: int | None = Field(default=None, ge=0)
    quote_cny: float | None = Field(default=None, ge=0)
    audience_tags: list[str] = Field(default_factory=list)
    past_campaign_result: str | None = None
    source_name: str
    collected_at: str
    is_mock: bool = False
    evidence_grade: str = "C_user_provided"
    mock_seed: str | None = None


class CategoryNoteEvidence(BaseModel):
    search_keyword: str
    search_sort: str | None = None
    search_rank: int | None = Field(default=None, ge=1)
    note_id: str
    note_url: str
    title: str
    description: str | None = None
    note_type: str | None = None
    author_nickname: str | None = None
    likes: int | None = Field(default=None, ge=0)
    favorites: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    tags: list[str] = Field(default_factory=list)
    published_at: str | None = None
    image_count: int | None = Field(default=None, ge=0)
    cover_url: str | None = None
    has_video: bool | None = None
    platform: str = "xiaohongshu"
    author_id: str | None = None
    author_followers_snapshot: int | None = Field(default=None, ge=0)
    views: int | None = Field(default=None, ge=0)
    ad_label_status: str | None = None
    ad_evidence_url: str | None = None
    metric_snapshot_at: str | None = None
    is_mock: bool = False
    collected_at: str
    source_name: str
    evidence_grade: str = "B_public_observation"
    mock_seed: str | None = None


class OfficialRuleEvidence(BaseModel):
    rule_id: str
    title: str
    category_path: list[str] = Field(default_factory=list)
    source_url: str
    source_updated_at: str | None = None
    collected_at: str
    full_text: str = ""
    risk_items: list[str] = Field(default_factory=list)
    source_name: str = "小红书聚光官方帮助中心"
    evidence_grade: str = "A_official_public_rule"


class TrendKeywordEvidence(BaseModel):
    """合规趋势源或人工粘贴的热搜词，禁止由模型伪造实时热搜。"""

    keyword: str
    source_name: str
    collected_at: str
    heat_score: float | None = Field(default=None, ge=0)
    notes: str | None = None
    is_mock: bool = False
    evidence_grade: str = "C_user_provided"
    mock_seed: str | None = None


class AccountViolationEvidence(BaseModel):
    """账户/赛道拒审与限流频次台账；与官方规则条文分开，不可互相替代。"""

    reason: str
    occurrence_count: int = Field(ge=1)
    period: str
    source_name: str
    collected_at: str
    notes: str | None = None
    is_mock: bool = False
    evidence_grade: str = "C_user_provided"
    mock_seed: str | None = None


class PaidRiskDemoScenario(BaseModel):
    """模块4五类投流问题的 Mock 演示诊断情景；禁止当作真实账户事故。"""

    issue: str
    example_diagnosis: str
    demo_signals: dict[str, Any] = Field(default_factory=dict)
    source_name: str
    collected_at: str
    notes: str | None = None
    is_mock: bool = True
    evidence_grade: str = "M"
    mock_seed: str | None = None


class BenchmarkSampleNote(BaseModel):
    account: str
    title: str = ""
    angle: str = ""
    format: str = ""
    likes: int | None = None
    collects: int | None = None
    comments: int | None = None
    ad_label: str = "未标注"
    published: str = ""


class BenchmarkStat(BaseModel):
    label: str
    value: str | int | float
    tone: str | None = None


class BenchmarkKvRow(BaseModel):
    dimension: str = ""
    observation: str = ""
    note: str = ""
    ad_label: str = ""
    content_type: str = ""
    duration_judgment: str = ""
    title: str = ""
    body: str = ""
    priority: str = ""
    action: str = ""
    gap: str = ""


class BenchmarkPeakSlot(BaseModel):
    slot: str
    count: int


class BenchmarkSpotlightMetrics(BaseModel):
    cpc: float | str | None = None
    cpm: float | str | None = None
    ctr: float | str | None = None
    interaction_cost: float | str | None = None
    conversion_cost: float | str | None = None


class BenchmarkMonthlyRow(BaseModel):
    month: str
    spend: str
    cpc: str
    cpm: str
    ctr: str


class CompetitorBenchmarkBrief(BaseModel):
    """用户提供的对标拆解看板文案（如珍妮曲奇示例），供网页「对标拆解」页渲染。"""

    headline: str
    subtitle: str = ""
    pills: list[str] = Field(default_factory=list)
    evidence_boundary: str = ""
    hero_stats: list[BenchmarkStat] = Field(default_factory=list)
    sample_notes: list[BenchmarkSampleNote] = Field(default_factory=list)
    organic_summary: str = ""
    organic_commonalities: list[str] = Field(default_factory=list)
    organic_gaps: list[str] = Field(default_factory=list)
    organic_trend_caption: str = ""
    organic_trend_categories: list[str] = Field(default_factory=list)
    organic_trend_exposure_wan: list[float] = Field(default_factory=list)
    organic_trend_note_counts: list[float] = Field(default_factory=list)
    peak_caption: str = ""
    peak_slots: list[BenchmarkPeakSlot] = Field(default_factory=list)
    format_note: str = ""
    spotlight_notice: str = ""
    spotlight_metrics: BenchmarkSpotlightMetrics | None = None
    spotlight_monthly: list[BenchmarkMonthlyRow] = Field(default_factory=list)
    spotlight_goal_notes: list[str] = Field(default_factory=list)
    spotlight_traffic_notes: list[str] = Field(default_factory=list)
    commonality_rows: list[BenchmarkKvRow] = Field(default_factory=list)
    paid_note_rows: list[BenchmarkKvRow] = Field(default_factory=list)
    paid_conclusion: str = ""
    targeting_cards: list[BenchmarkKvRow] = Field(default_factory=list)
    risk_content_signals: list[str] = Field(default_factory=list)
    risk_rejection_signals: list[str] = Field(default_factory=list)
    risk_note: str = ""
    counter_actions: list[BenchmarkKvRow] = Field(default_factory=list)


class CampaignRequest(BaseModel):
    brand_name: str
    category: str
    product_name: str
    selling_points: list[str] = Field(min_length=1, max_length=8)
    price_min: float = Field(ge=0, validation_alias=AliasChoices("price_min", "price_min_cny"))
    price_max: float = Field(ge=0, validation_alias=AliasChoices("price_max", "price_max_cny"))
    currency: str = Field(default="CNY", description="价格币种，如 CNY、HKD")
    initial_audience: str
    total_budget_cny: float = Field(gt=0)
    spotlight_budget_cny: float | None = Field(default=None, gt=0)
    campaign_days: int = Field(default=30, ge=7, le=365)
    goal: Goal
    analysis_days: int = Field(default=30, ge=7, le=180)
    competitor_links: list[str] = Field(default_factory=list, max_length=5)
    competitor_candidates: list[str] = Field(default_factory=list, max_length=20)
    competitor_evidence: list[CompetitorEvidence] = Field(default_factory=list)
    competitor_benchmark_brief: CompetitorBenchmarkBrief | None = Field(
        default=None,
        description="对标拆解看板文案；可手写导入，或由给定链接抓取后自动合成",
    )
    benchmark_evidence: list[MetricEvidence] = Field(default_factory=list)
    creator_evidence: list[CreatorEvidence] = Field(default_factory=list)
    category_note_evidence: list[CategoryNoteEvidence] = Field(default_factory=list, max_length=1000)
    official_rule_evidence: list[OfficialRuleEvidence] = Field(default_factory=list, max_length=50)
    trending_keyword_evidence: list[TrendKeywordEvidence] = Field(default_factory=list, max_length=50)
    account_violation_evidence: list[AccountViolationEvidence] = Field(default_factory=list, max_length=100)
    paid_risk_demo_scenarios: list[PaidRiskDemoScenario] = Field(
        default_factory=list,
        max_length=10,
        description="Mock 演示用投流问题诊断情景，供模块4 SOP 挂载示例信号",
    )
    owned_history_summary: str | None = None
    owned_content_history: list[dict[str, Any]] = Field(default_factory=list)
    paid_monthly_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="知识库导入的品牌投流月度明细，供聚光看板 monthly_rows 展示",
    )
    targeting_knowledge_brief: str | None = Field(
        default=None,
        description="知识库检索到的聚光定向标签候选摘要；非平台已确认可投标签",
    )
    targeting_knowledge_pack: dict[str, Any] | None = Field(
        default=None,
        description="知识库结构化定向包：三维画像候选 + 兴趣/行为/人群包标签（须后台核验）",
    )
    draft_title: str | None = Field(
        default=None,
        max_length=200,
        description="可选：待审笔记草稿标题；空则用 product_name 做轻量预审",
    )
    draft_body: str | None = Field(
        default=None,
        max_length=5000,
        description="可选：待审笔记草稿正文",
    )
    draft_tags: list[str] = Field(
        default_factory=list,
        max_length=30,
        description="可选：待审笔记标签/话题",
    )
    draft_image_urls: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="可选：待审图片 URL（OCR/Logo 待接入前仅登记 pending）",
    )
    draft_video_urls: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="可选：待审视频 URL（抽帧审核待接入前仅登记 pending）",
    )
    constraints: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ranges(self) -> "CampaignRequest":
        if self.price_max < self.price_min:
            raise ValueError("price_max 不能小于 price_min")
        if self.spotlight_budget_cny and self.spotlight_budget_cny > self.total_budget_cny:
            raise ValueError("spotlight_budget_cny 不能大于 total_budget_cny")
        return self


class EvidenceGap(BaseModel):
    field: str
    impact: str
    recommended_source: str


class FieldCorrection(BaseModel):
    """可计算的字段级反馈：哪个字段 / 建议值 / 实际执行值。"""

    field: str = Field(min_length=1, max_length=120)
    suggested_value: str | float | int | None = None
    actual_value: str | float | int | None = None
    note: str | None = Field(default=None, max_length=500)


class FeedbackRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    report_id: str = Field(min_length=1, max_length=128)
    rating: Literal["满意", "一般", "不满意"]
    comment: str | None = Field(default=None, max_length=2000)
    sections: list[str] = Field(default_factory=list, max_length=20)
    field_corrections: list[FieldCorrection] = Field(default_factory=list, max_length=30)


class BackfilledCaseRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    report_id: str = Field(min_length=1, max_length=128)
    brand_name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=200)
    problem_summary: str = Field(min_length=1, max_length=2000)
    strategy_summary: str = Field(min_length=1, max_length=4000)
    evidence_grade: str = Field(min_length=1, max_length=50)
    requested_case_type: Literal["verified_case", "demo_case"] = "verified_case"
    confirmed: Literal[True]


class StrategyResponse(BaseModel):
    report_id: str = ""
    session_state: dict[str, Any] = Field(default_factory=dict)
    run_id: str
    generated_at: str
    data_confidence: Literal["low", "medium", "high"]
    evidence_gaps: list[EvidenceGap]
    modules: dict[str, Any]
    report_view: dict[str, Any]
    report_markdown: str
    trace: list[dict[str, Any]]
    session_memory: dict[str, Any] = Field(default_factory=dict)
