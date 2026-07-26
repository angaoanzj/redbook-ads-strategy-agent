# 模块1：赛道与竞品分析 SOP

本 SOP 复用 `module_agents/module1.py`、`tools/competitors.py` 和共享治理文件的当前契约。零代码平台没有代码版的 Pydantic 与工具强校验，操作者必须逐项执行本文件的校验并保存证据。

## 1. 职责与边界

M1 负责基于已提供证据输出自然内容样本格局、付费基准、竞品拆解、风险提示和人工复核项，并建立供 M2、M6 消费的赛道观察边界。

禁止结论：不得把公开样本外推为平台大盘；不得确认竞品真实预算、真实定向、订单、转化或账户表现；不得把官方规则标题写成该赛道的实际违规频次；不得在缺少登记指标时生成 CPC、CPM 或转化成本。

## 2. 输入

以下字段名与 `CampaignRequest` 一致：

- `brand_name`、`category`、`product_name`、`selling_points`
- `initial_audience`、`goal`、`constraints`
- `category_note_evidence`：公开品类笔记样本；每条保留 `note_id`、`note_url`、互动快照、`collected_at`、`source_name`、`evidence_grade` 和 `is_mock`
- `competitor_evidence`：竞品账号或笔记公开观察；只接收可复查条目
- `benchmark_evidence`：CPC、CPM、转化成本等候选指标
- `account_violation_evidence`：带期间与次数的账户/赛道违规台账
- `official_rule_evidence`：官方规则原文与来源

工作流还必须接收 `run_id`、当前 `benchmark_registry.version` 和本次证据登记表。缺少品牌范围、目标期或证据观察时点时不得开始正式判读。

以下 JSON 是输入字段的规范机器契约；列表之外的字段不得静默加入本模块输入：

```json
{
  "input_contract": {
    "campaign_request": [
      "brand_name",
      "category",
      "product_name",
      "selling_points",
      "initial_audience",
      "goal",
      "constraints",
      "category_note_evidence",
      "competitor_evidence",
      "benchmark_evidence",
      "account_violation_evidence",
      "official_rule_evidence"
    ],
    "workflow": ["run_id", "benchmark_registry", "evidence_registry"],
    "upstream_module_states": []
  }
}
```

## 3. 前序依赖

M1 没有业务前序模块，但必须先读取 `01_全局证据与数据纪律.md`、`02_模块状态输出契约.md`、`03_跨模块依赖与冲突处理.md` 和 `04_指标单一事实源规范.md`。只可使用本次 `run_id` 下的输入、证据登记和 `benchmark_registry`，不得从旧对话补写事实。

若品牌范围、目标期或证据文件无法确认，输出 `blocked`；若仅缺竞品、付费或违规频次证据，可输出 `completed_with_gaps`，但必须降低 `confidence` 并保留缺口。

## 4. 证据

> 规范性声明：本节操作约束仅以“控制规则表”为准；表外文字只作解释、状态描述或示例，不授予例外。

| 规则 ID | 效果 | 对象 | 约束 |
| --- | --- | --- | --- |
| M1-SAMPLE-EXTRAPOLATION | 禁止 | B_公开观察样本 | 外推为平台大盘或样本外事实 |
| M1-SSOT-BYPASS | 禁止 | CPC、CPM、转化成本 | 绕过 benchmark_registry 读取或生成数值 |
| M1-COMPETITOR-PRIVATE-FACTS | 禁止 | 公开竞品观察 | 推断竞品真实预算、真实定向或账户事实 |
| M1-RULE-FREQUENCY | 禁止 | 官方规则 | 替代 account_violation_evidence 证明观察到的违规频次 |

解释说明（非规范性）：

- `M1-SAMPLE-EXTRAPOLATION` 的背景是公开笔记覆盖范围有限；样本记录包括样本量、观察时点和“样本不等于全平台大盘”的边界说明。
- `M1-COMPETITOR-PRIVATE-FACTS` 区分公开互动、广告标识、观察人群与私有账户事实，前一类信号不构成后一类事实证明。
- `M1-RULE-FREQUENCY` 把官方规则定位为合规基线；观察频次的数据载体是带次数与期间的 `account_violation_evidence`。
- `M1-SSOT-BYPASS` 对应的登记信息包括 `benchmark_registry.version`、`selected_source`、`period`、单位和公式；行业基准的用途分类是测试参考。
- 证据记录同时保留证据 ID、等级与 Mock 状态；`confirmed_facts` 表示已满足证据等级的事实集合。
- 竞品证据为空的状态示例是：竞品清单为空、`ad_labeled_count` 为 0、自身卖点列入待验证 `content_gaps`，预算口径显示“无竞品证据：禁止推测竞品预算”。

## 5. 执行步骤

1. 校验 `run_id`、目标期、来源 URL/文件、采集时间、证据等级和 Mock 标识；为每项证据分配 ID。
2. 聚合 `category_note_evidence`：按 `note_type` 计算样本数和平均互动，记录发布时段。无样本时 `hot_formats` 留空，时段只能写待验证假设。
3. 对竞品清单执行与 `summarize_competitor_landscape` 同等的确定性检查：只转录证据中的竞品，按形态统计，计算内容缺口和广告标识数；不得增加账号、URL 或预算数字。
4. 从同版 `benchmark_registry` 读取 CPC、CPM、转化成本。缺任何一项就把对应值和来源置空，并写入 `missing_notice`。
5. 将官方规则检查项与违规台账频次分开生成 `risk_alerts`；每项包含风险、来源和行动。
6. 列出证据冲突、缺数、低置信度结论和必须人工确认的事项，执行 Grounding 自检后生成输出与 `module_state`。

## 6. 输出契约

字段名和基数复制自当前 `Module1Output` 及其嵌套模型：

以下 JSON 只描述字段所属关系；它是用于检测多字段、少字段和错父级的规范机器契约：

```json
{
  "output_contract": {
    "$": [
      "organic_landscape",
      "paid_landscape",
      "competitor_breakdown",
      "risk_alerts",
      "human_review_items"
    ],
    "$.organic_landscape": [
      "sample_size",
      "hot_formats",
      "peak_hour_hypothesis",
      "content_form_advice",
      "boundary_note"
    ],
    "$.organic_landscape.hot_formats[]": ["format", "avg_interactions"],
    "$.paid_landscape": [
      "cpc_cny",
      "cpc_source",
      "cpm_cny",
      "cpm_source",
      "conversion_cost_cny",
      "conversion_cost_source",
      "missing_notice"
    ],
    "$.competitor_breakdown": [
      "common_patterns",
      "content_gaps",
      "ad_labeled_count",
      "targeting_hypotheses",
      "budget_inference_policy"
    ],
    "$.risk_alerts[]": ["risk", "source", "action"]
  }
}
```

```yaml
output:
  organic_landscape:
    sample_size: int >= 0
    hot_formats:
      - format: str
        avg_interactions: float
    peak_hour_hypothesis: str
    content_form_advice: [str, str]
    boundary_note: str
  paid_landscape:
    cpc_cny: float | null
    cpc_source: str | null
    cpm_cny: float | null
    cpm_source: str | null
    conversion_cost_cny: float | null
    conversion_cost_source: str | null
    missing_notice: str | null
  competitor_breakdown:
    common_patterns: [str]
    content_gaps: [str]
    ad_labeled_count: int >= 0
    targeting_hypotheses: [str]
    budget_inference_policy: str
  risk_alerts:
    - risk: str
      source: str
      action: str
  human_review_items: [str]
```

约束：`hot_formats` 为 0–4 项；`content_form_advice` 为 2–4 项；每条 `targeting_hypotheses` 必须含“假设”；`risk_alerts` 为 2–6 项；`human_review_items` 为 1–6 项。任何非空付费数字必须有对应来源。

## 7. module_state

输出业务结果后追加完整状态；事实、假设和决策分开存放：

```yaml
module_state:
  run_id: "沿用本次 run_id"
  module: "M1"
  status: "completed | completed_with_gaps | blocked | awaiting_human_review"
  evidence_ids: []
  confirmed_facts: []
  assumptions: []
  decisions: []
  unresolved_gaps: []
  human_review_items: []
  confidence: "low | medium | high"
  decision_source: "evidence | deterministic_calculation | strategy_hypothesis | mock | human_confirmed | mixed"
```

每个 `confirmed_facts` 项必须绑定一个证据 ID；计算结果在 `decision_source` 标记 `deterministic_calculation`；样本判读不升级为账户事实。

## 8. Grounding 自检

1. 每个事实和数字是否能回到证据 ID、来源、期间、单位和公式？
2. `decision_source` 是否区分公开观察、指标登记、确定性聚合、策略假设、Mock 与人工确认？
3. `confidence` 是否因竞品、付费基准、违规台账缺失或冲突而降低？
4. `ad_labeled_count`、内容缺口和预算政策是否只来自输入竞品清单的确定性聚合？
5. 官方规则与真实违规频次、样本观察与平台大盘是否保持分离？

## 9. 降级

- 无品类笔记：`sample_size: 0`、`hot_formats: []`，其余仅为保守测试假设。
- 无竞品：不生成竞品条目；内容缺口视为待验证，禁止预算和定向推断。
- 无 CPC/CPM/转化成本：对应值与来源为 `null`，填写 `missing_notice`，不得生成出价或成本结论。
- 无违规台账：只输出官方合规检查或通用人工预审，不得输出“高频违规榜”。
- 输入含 Mock：只能形成模拟结果，`decision_source: mock`，不得进入正式预算、采购或下单。

## 10. 人工拍板

人工必须确认：公开样本是否适用于本次品类与期间；竞品身份、广告标识和证据真实性；指标登记项的公式、范围与来源选择；合规风险解释；任何后续测试预算、账户定向或放量动作。未确认项必须同时留在 `human_review_items` 和 `unresolved_gaps`。
