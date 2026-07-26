# 模块2：用户画像与内容选题 SOP

本 SOP 复用 `module_agents/module2.py`、`tools/topics.py` 和共享治理文件的当前输出契约，并把 M1 的确认事实和观察边界作为零代码业务前序。

## 1. 职责与边界

M2 负责输出三维用户画像、待验证定向标签、恰好三个内容方向及其自然/付费评分、恰好 15 个选题、素材筛选门槛和人工复核项。

禁止结论：不得把初始人群描述、公开笔记主题或模型推断写成真实受众画像、真实偏好、平台可用定向或转化归因；不得把无证据评分和阈值称为已验证表现；不得绕过 M1 的样本边界或删除 M1 未解决缺口。

## 2. 输入

以下字段名与 `CampaignRequest` 一致：

- `brand_name`、`category`、`product_name`、`selling_points`
- `price_min`、`price_max`、`currency`
- `initial_audience`、`goal`、`constraints`
- `category_note_evidence`：用于提取主题、样本互动和内容形态，不代表真实受众全貌

工作流输入还包括同一 `run_id` 的完整 M1 `module_state`、证据登记、M1 输出、当前 `benchmark_registry` 及品牌已确认的人群限制。任何手工补充都必须登记为 `C_用户导入` 或 `E_策略假设`。

以下 JSON 是输入字段的规范机器契约；`upstream_module_states` 明确 M1 是输入而非背景提示：

```json
{
  "input_contract": {
    "campaign_request": [
      "brand_name",
      "category",
      "product_name",
      "selling_points",
      "price_min",
      "price_max",
      "currency",
      "initial_audience",
      "goal",
      "constraints",
      "category_note_evidence"
    ],
    "workflow": ["run_id", "benchmark_registry", "evidence_registry"],
    "upstream_module_states": ["M1"]
  }
}
```

## 3. 前序依赖

> 规范性声明：本节操作约束仅以“控制规则表”为准；表外文字只作解释、状态描述或示例，不授予例外。

| 规则 ID | 效果 | 对象 | 约束 |
| --- | --- | --- | --- |
| M2-M1-DEPENDENCY | 必须 | M2 | 消费同一 run_id 的 M1 module_state |

依赖说明（非规范性）：M2 的结构化上游输入包括 M1 `module_state` 中的 `confirmed_facts`、`decisions`、明确列出的 `assumptions`、`unresolved_gaps` 和证据 ID。自由对话不属于该结构化输入。

状态说明（非规范性）：M1 缺失对应 `blocked`；M1 为 `completed_with_gaps` 时，M2 状态继承相关缺口并降低 `confidence`。M1 的公开样本边界、竞品不可推断项和已选指标作为只读上游状态出现。

## 4. 证据

> 规范性声明：本节操作约束仅以“控制规则表”为准；表外文字只作解释、状态描述或示例，不授予例外。

| 规则 ID | 效果 | 对象 | 约束 |
| --- | --- | --- | --- |
| M2-UNSUPPORTED-SCORING | 禁止 | 无证据的 organic_score、paid_score 与筛选阈值 | 表述为已验证分数；必须标记为 E_策略假设 |
| M2-UNVALIDATED-TARGETING | 禁止 | 未经平台和账户验证的定向标签 | 表述为可用定向；只能作为候选 |

解释说明（非规范性）：

- 人口、行为、心理画像的来源分类包括 M1 确认事实、品牌输入、样本主题与 `E_策略假设`。
- `M2-UNSUPPORTED-SCORING` 对应的评分记录包含支持证据 ID、适用期间、样本范围和理由；缺证据记录的分类是“测试假设”。
- `M2-UNVALIDATED-TARGETING` 对应的 `tag_status` 文案为“标签需在聚光后台核对是否存在且适配本账户”，其状态类型是候选而非账户事实。
- `ctr_threshold` 和 `engagement_threshold` 的证据来源优先级包括品牌历史与 `benchmark_registry`；缺同口径证据的状态类型是测试门槛和人工复核项。
- `Mock` 的用途类型是 15 选题结构演示，不属于正式受众、投放标签或素材胜出证据。

## 5. 执行步骤

1. 校验 M1 状态、`run_id`、证据 ID、冲突、未解决缺口与 `confidence`；确认样本允许结论范围。
2. 从 `selling_points`、`initial_audience`、M1 确认事实和 `category_note_evidence` 提取画像信号，分别生成 `demographic`、`behavioral`、`psychological`，并标记事实或假设来源。
3. 生成 `interest_tags`、`behavior_tags`、`crowd_packages` 候选；统一写入待后台核对状态，不声称平台已存在或账户可投。
4. 生成恰好三个内容方向，并为每个方向填写 1–10 的自然/付费评分和证据化理由。缺证据评分标为测试假设。
5. 生成恰好 15 个选题；每个 `direction` 必须命中三个方向之一，每方向至少 3 个；`suitable_for_paid: true` 时 `paid_objective` 只能是种草、成交、客资或直播引流。
6. 执行与 `score_content_topics` 同等的确定性校验：方向不重复、数量正确、选题归属有效、付费目标有效、CTR 介于 0.03–0.30、互动率介于 0.02–0.20。
7. 记录人工确认项、执行 Grounding 自检，输出业务契约和 `module_state`。

## 6. 输出契约

字段名和基数复制自当前 `Module2Output` 及其嵌套模型：

```json
{
  "output_contract": {
    "$": [
      "persona",
      "content_directions",
      "topics",
      "material_screening",
      "human_review_items"
    ],
    "$.persona": [
      "demographic",
      "behavioral",
      "psychological",
      "targeting_tags",
      "tag_status"
    ],
    "$.persona.targeting_tags": [
      "interest_tags",
      "behavior_tags",
      "crowd_packages"
    ],
    "$.content_directions[]": [
      "direction",
      "organic_score",
      "paid_score",
      "rationale"
    ],
    "$.topics[]": [
      "title_template",
      "cover_suggestion",
      "outline",
      "direction",
      "suitable_for_paid",
      "paid_objective"
    ],
    "$.material_screening": [
      "ctr_threshold",
      "engagement_threshold",
      "extra_rules"
    ]
  }
}
```

```yaml
output:
  persona:
    demographic: [str]
    behavioral: [str]
    psychological: [str]
    targeting_tags:
      interest_tags: [str]
      behavior_tags: [str]
      crowd_packages: [str]
    tag_status: str
  content_directions:
    - direction: str
      organic_score: int 1..10
      paid_score: int 1..10
      rationale: str
  topics:
    - title_template: str
      cover_suggestion: str
      outline: [str]
      direction: str
      suitable_for_paid: bool
      paid_objective: "种草 | 成交 | 客资 | 直播引流 | null"
  material_screening:
    ctr_threshold: float 0.03..0.30
    engagement_threshold: float 0.02..0.20
    extra_rules: [str]
  human_review_items: [str]
```

约束：三维画像各 2–6 项；兴趣/行为标签各 3–10 项；人群包 1–5 项；内容方向恰好 3 项；选题恰好 15 项且每方向至少 3 个；大纲 2–5 条；额外筛选规则 1–4 条；人工复核项 1–6 条。

## 7. module_state

```yaml
module_state:
  run_id: "与 M1 相同"
  module: "M2"
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

只有已被 M1/品牌证据支持的描述可进入 `confirmed_facts`。画像推断、无历史基准的评分、门槛和定向候选进入 `assumptions` 或 `decisions`，并标明验证方法。

## 8. Grounding 自检

1. 每个画像结论、方向评分和门槛是否绑定证据 ID 或显式测试假设？
2. `decision_source` 是否区分 M1 事实、内容样本、确定性结构校验、策略假设、Mock 和人工确认？
3. `confidence` 是否继承 M1 缺口，并反映受众、评分、阈值和平台标签证据完整性？
4. 是否恰好三个方向、15 个选题，每方向至少 3 个，所有付费选题都有合法目标？
5. 是否保留“标签需在聚光后台核对可用性”，且未声称真实定向或转化归因？

## 9. 降级

- M1 缺失：`blocked`，只列所需前序材料，不生成正式画像和评分。
- M1 有缺口或无品类笔记：可基于品牌卖点形成测试画像与选题，但全部相关项标为 `E_策略假设`，状态为 `completed_with_gaps`。
- 无品牌历史 CTR/互动率：使用契约允许范围内的测试门槛，不称行业事实，并请求补充品牌历史分布。
- 无可验证平台标签：保留候选标签及核验清单，不生成可直接投放的定向包。
- 输入含 Mock：输出仅作演示，`decision_source: mock`，不得决定素材胜出或投放。

## 10. 人工拍板

人工必须确认：画像是否符合品牌实际客户；敏感或歧视性标签是否删除；候选标签在聚光后台是否存在且适用于本账户；三个方向、15 个选题和付费目标是否符合品牌与合规要求；测试门槛和停止条件是否适用于本期。未确认项保留在 `human_review_items`。
