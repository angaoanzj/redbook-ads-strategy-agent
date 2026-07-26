# 模块6：关键词策略 SOP

本 SOP 复用 `module_agents/module6.py`、`tools/keywords.py` 和共享治理文件的当前输出契约。它定义零代码全案中的关键词单一事实源，并位于 M2 与 M3 之间。

## 1. 职责与边界

> 规范性声明：本节操作约束仅以“控制规则表”为准；表外文字只作解释、状态描述或示例，不授予例外。

| 规则 ID | 效果 | 对象 | 约束 |
| --- | --- | --- | --- |
| M6-CANONICAL-OWNERSHIP | 必须 | M6 | 作为零代码流程唯一规范关键词库所有者 |
| M6-M3-NO-REGENERATION | 禁止 | M3 | 脱离 M6 module_state 重新生成关键词 |

职责说明（非规范性）：M6 的产物包括关键词分层、标题/正文/标签布局、分层预算比例、趋势监控和人工复核项。`M6-CANONICAL-OWNERSHIP` 将这些产物组织为零代码流程的规范词库。

交接说明（非规范性）：`M6-M3-NO-REGENERATION` 对应的 M3 输入是 M6 输出与完整 `module_state`。当前 Python `module_agents/module3.py` 仍会再次调用关键词工具，这是代码运行时与零代码目标依赖的已知差异。

边界说明（非规范性）：缺证据种子词的状态是待验证候选；平台搜索量、竞争度、建议价、竞价事实和金额出价分别依赖对应的数据源与基准 CPC。

## 2. 输入

以下字段名与 `CampaignRequest` 一致：

- `brand_name`、`category`、`product_name`、`selling_points`
- `initial_audience`、`goal`、`constraints`
- `category_note_evidence`：用于聚合 `tags`、`search_keyword`、笔记数量和互动快照
- `benchmark_evidence`：只向 `benchmark_registry` 提交候选 CPC，不能直接覆盖已选值
- `trending_keyword_evidence`：合规趋势源或人工导入趋势词，保留来源、采集时间、热度值和 Mock 状态

工作流还必须接收同一 `run_id` 的 M1、M2 完整 `module_state`，M2 的内容方向与选题，证据登记，以及同版 `benchmark_registry`。

以下 JSON 是输入字段的规范机器契约：

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
      "benchmark_evidence",
      "trending_keyword_evidence"
    ],
    "workflow": ["run_id", "benchmark_registry", "evidence_registry"],
    "upstream_module_states": ["M1", "M2"]
  }
}
```

## 3. 前序依赖

> 规范性声明：本节操作约束仅以“控制规则表”为准；表外文字只作解释、状态描述或示例，不授予例外。

| 规则 ID | 效果 | 对象 | 约束 |
| --- | --- | --- | --- |
| M6-M1-DEPENDENCY | 必须 | M6 | 消费同一 run_id 的 M1 module_state |
| M6-M2-DEPENDENCY | 必须 | M6 | 消费同一 run_id 的 M2 module_state |

依赖说明（非规范性）：M1 状态提供赛道样本边界、确认事实、付费基准和风险限制；M2 状态提供画像边界、内容方向、选题决策、假设和未解决缺口。

状态说明（非规范性）：结构化消费范围由两份 `module_state` 的 `confirmed_facts`、`decisions`、明确列出的 `assumptions` 和证据 ID 构成。任一状态缺失对应 `blocked`；带缺口状态对应待验证种子词、继承缺口和较低 `confidence`。M3 handoff 的载荷是 M6 词库及其状态。

## 4. 证据

> 规范性声明：本节操作约束仅以“控制规则表”为准；表外文字只作解释、状态描述或示例，不授予例外。

| 规则 ID | 效果 | 对象 | 约束 |
| --- | --- | --- | --- |
| M6-UNSUPPORTED-MARKET-CLAIMS | 禁止 | 缺少搜索量、笔记数量或当前来源证据的关键词 | 声称蓝海、趋势、热搜或实时热度 |

解释说明（非规范性）：

- 词语来源类别包括 `category_note_evidence`、品牌输入和 M2 已确认主题；品牌输入派生词与无样本扩展词的状态是待验证种子词。
- `M6-UNSUPPORTED-MARKET-CLAIMS` 将 `blue_ocean` 定义为待验证分层标签，市场含义需要搜索量、笔记数量和当前来源共同支持。
- 趋势证据记录包含 `source_name`、`collected_at`、适用期间和 Mock 状态；仅有搜索摘要或过期截图的结果状态是“不可确认”。
- 基准 CPC 的登记字段包括 `benchmark_registry.selected_value`、`selected_source`、`period`、公式和版本；缺失基准对应空金额出价，`bid_note` 保留倍率带含义。
- 未来 `level_budget_split` 的值类型是 `E_策略假设`，与历史事实分开记录，并关联人工批准状态。
- `Mock` 趋势或笔记的用途类型是分层与监控结构演示，不属于正式词库热度证据。

## 5. 执行步骤

以下 `calculation_contract` 是 `tools/keywords.py` 的零代码等价契约。校验与出价必须按优先级执行：先判 `blue_ocean`，再判 `feed` 版位，其余 `search`/`both` 才按意向选择倍率；这意味着 `blue_ocean + feed` 仍使用 0.6–0.8。模型不得自行修改倍率或优先级。

```json
{
  "calculation_contract": {
    "keyword_validation": {
      "keyword_count": {"min": 8, "max": 40},
      "keyword_length": {"min": 2, "max": 24},
      "normalization": "casefold().strip()",
      "minimum_per_level": {
        "core": 2,
        "long_tail": 4,
        "blue_ocean": 2
      },
      "budget_ratio_per_level": {"min": 0, "max": 1},
      "budget_ratio_rule": "abs(core + long_tail + blue_ocean - 1.0) <= 0.01",
      "baseline_cpc_rule": "baseline_cpc_cny is null or baseline_cpc_cny > 0",
      "evidence_coverage": "round(from_evidence_count / total, 3) if total else 0.0"
    },
    "bid_bands": {
      "precedence": ["blue_ocean", "feed", "search_or_both_by_intent"],
      "blue_ocean": [0.6, 0.8],
      "feed": [0.7, 1.0],
      "search_high": [1.0, 1.3],
      "search_mid": [0.9, 1.1],
      "search_low": [0.8, 1.0],
      "bid_range": "[round(baseline_cpc_cny * low_multiplier, 2), round(baseline_cpc_cny * high_multiplier, 2)]",
      "missing_cpc": "bid_range_cny = null",
      "source_rule": "baseline_cpc_cny != null requires baseline_source"
    }
  }
}
```

1. 校验 M1/M2 状态、`run_id`、证据 ID、缺口和冲突；确认可用主题及禁止词/合规边界。
2. 聚合品类笔记的 `tags` 与 `search_keyword`，记录每个主题的出现笔记数、累计互动、观察期间和来源。单条笔记内去重。
3. 从证据主题、品牌/品类词和 M2 内容方向构造 8–40 个候选词；每词标记 `level`、`intent`、`lane` 和是否来自证据。
4. 执行与 `build_keyword_tiers` 同等的确定性校验：大小写归一后去重；`core` 至少 2 个、`long_tail` 至少 4 个、`blue_ocean` 至少 2 个；三级预算比例误差范围内合计 1.0。
5. 有登记 CPC 时按 `bid_bands` 的固定优先级和倍率计算测试出价；无 CPC 时 `bid_range_cny = null`，仅保留倍率说明。最终 `keyword_levels` 和 `level_budget_split` 只采用校验通过版本。
6. 生成 3–6 条 `layout_rules`，覆盖标题、正文和标签；生成趋势监控机制、2–4 条跟进标准和数据源状态。无合规趋势源时写“待接入数据源”。
7. 冻结规范词库版本，记录 M3 handoff 所需 `run_id`、M6 状态、证据 ID 和词库内容；执行 Grounding 自检。

## 6. 输出契约

字段名和基数复制自当前 `Module6Output` 及其嵌套模型：

```json
{
  "output_contract": {
    "$": [
      "keyword_levels",
      "layout_rules",
      "level_budget_split",
      "trending_monitor",
      "human_review_items"
    ],
    "$.keyword_levels": ["core", "long_tail", "blue_ocean"],
    "$.keyword_levels.core[]": ["keyword", "intent", "lane", "bid_note"],
    "$.keyword_levels.long_tail[]": ["keyword", "intent", "lane", "bid_note"],
    "$.keyword_levels.blue_ocean[]": ["keyword", "intent", "lane", "bid_note"],
    "$.layout_rules[]": ["position", "rule"],
    "$.level_budget_split": ["core", "long_tail", "blue_ocean"],
    "$.trending_monitor": [
      "mechanism",
      "follow_criteria",
      "data_source_status",
      "rising_keywords"
    ],
    "$.trending_monitor.rising_keywords[]": [
      "keyword",
      "heat_score",
      "trend",
      "recommendation",
      "reason"
    ]
  }
}
```

```yaml
output:
  keyword_levels:
    core:
      - keyword: str
        intent: "high | mid | low"
        lane: "search | feed | both"
        bid_note: str
    long_tail:
      - keyword: str
        intent: "high | mid | low"
        lane: "search | feed | both"
        bid_note: str
    blue_ocean:
      - keyword: str
        intent: "high | mid | low"
        lane: "search | feed | both"
        bid_note: str
  layout_rules:
    - position: "标题 | 正文 | 标签"
      rule: str
  level_budget_split:
    core: float 0..1
    long_tail: float 0..1
    blue_ocean: float 0..1
  trending_monitor:
    mechanism: str
    follow_criteria: [str]
    data_source_status: str
    rising_keywords:
      - keyword: str
        heat_score: float >= 0
        trend: "rising | flat | cooling | unknown"
        recommendation: "跟进 | 观察 | 不跟进"
        reason: str
  human_review_items: [str]
```

约束：关键词长度 2–24 字；`core` 至少 2 项，`long_tail` 至少 4 项，`blue_ocean` 至少 2 项；`layout_rules` 为 3–6 项；三级比例合计 1.0，允许浮点误差 0.01；跟进标准 2–4 条；人工复核项 1–6 条；`rising_keywords` 为 0–20 项，词与热度只能转录热搜数据快照，无热搜数据时留空。

`rising_keywords` 的固定判定规则（与代码版 `evaluate_trending_keywords` 同口径，不可自行改判）：与品类/品牌词无匹配记 `不跟进`；热度较上一快照上升超过 5% 记 `rising`，相关且 `rising` 记 `跟进`；下降超过 5% 记 `cooling` 并记 `不跟进`；缺上一快照热度记 `unknown`，相关且热度不低于本批中位数记 `观察`；其余记 `观察`。

## 7. module_state

```yaml
module_state:
  run_id: "与 M1、M2 相同"
  module: "M6"
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

`decisions` 应保存规范词库版本、分层、布局和预算比例；没有搜索量/竞争度证据的 `blue_ocean` 项只能进入 `assumptions`。M3 handoff 必须携带整个状态和输出，不能只复制词语文本。

## 8. Grounding 自检

1. 每个词是否绑定证据 ID，或明确标为品牌输入派生/测试种子？
2. `decision_source` 是否区分证据主题、确定性去重与计数、策略分层、Mock 和人工确认？
3. `confidence` 是否反映 M1/M2 缺口、搜索量/笔记数、趋势时效和 CPC 完整性？
4. 是否把 `blue_ocean` 当作待验证层级而非市场结论，且没有虚构趋势或实时热度？
5. 三级数量、去重和比例是否通过；CPC 缺失时是否没有金额出价？
6. M3 handoff 是否明确消费 M6 规范词库并禁止重新生成？

## 9. 降级

- M1 或 M2 状态缺失：`blocked`，列出缺失状态，不建立正式词库。
- 无品类笔记：只生成品牌输入派生的待验证种子词，所有项按 `E_策略假设` 处理。
- 无搜索量、笔记数量或当前趋势来源：不输出蓝海/热度结论，`data_source_status: 待接入数据源`，`rising_keywords: []`。
- 无登记 CPC：`bid_note` 仅描述固定倍率带和待校准要求，不给金额出价。
- 趋势证据过期、冲突或全为 Mock：只建立采集与监控清单，状态为 `completed_with_gaps` 或 `awaiting_human_review`。

## 10. 人工拍板

人工必须确认：词义、品牌安全和禁用词；所谓 `blue_ocean` 候选的搜索量、笔记数和竞争度验证；趋势来源与时效；关键词在账户中的可用性和实时建议价；三级预算比例；向 M3 交付的规范词库版本。任何未确认的出价、预算或热度判断保留在 `human_review_items`。
