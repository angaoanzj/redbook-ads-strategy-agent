# 模块4：聚光投流决策 SOP

> 文档级规范性声明：本 SOP 的全部十个业务章节（职责与边界、输入、前序依赖、证据、执行步骤、输出契约、module_state、Grounding 自检、降级、人工拍板）均为强制执行契约；控制规则表是禁止与必须规则的唯一增删入口，任何表外文字、代码块或示例不得取消、替代或覆盖这些契约。

本 SOP 复用 `module_agents/module4.py`、`tools/bidding.py`、`tools/forecast.py`、`tools/budget.py` 和共享治理文件的当前输出契约。M4 生成聚光账户测试方案、定向候选、出价与止损、搜索/信息流分配、时段安排和五类风险预案。

## 1. 职责与边界

M4 的业务输出是待审批的聚光决策方案，不是账户后台事实或自动执行指令。`account_structure.campaigns` 表示聚光付费计划层级，只使用产品种草、商品成交、客资收集、直播引流四类目标，以及搜索推广、信息流推广、搜索+信息流三类版位。

账户计划占比、三个定向包占比和 `search_feed_split` 各自独立守恒。投放时段匹配有证据的高互动时段；缺时段证据时标记目标人群作息假设，不写运营值班表。

## 2. 输入

M1 提供赛道边界和登记基准；M2 提供 `material_screening`、内容方向与 `persona`；M6 提供规范关键词；M3 提供达人证据、候选和开放名额。工作流读取同一 `run_id`、同版 `benchmark_registry` 与完整证据登记。

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
      "total_budget_cny",
      "spotlight_budget_cny",
      "campaign_days",
      "goal",
      "constraints",
      "category_note_evidence",
      "benchmark_evidence",
      "paid_risk_demo_scenarios"
    ],
    "workflow": ["run_id", "benchmark_registry", "evidence_registry"],
    "upstream_module_states": ["M1", "M2", "M6", "M3"]
  }
}
```

## 3. 前序依赖

> 规范性声明：本节操作约束仅以“控制规则表”为准；表外文字只作解释、状态描述或示例，不授予例外。

| 规则 ID | 效果 | 对象 | 约束 |
| --- | --- | --- | --- |
| M4-M1-DEPENDENCY | 必须 | M4 | 消费同一 run_id 的 M1 benchmark 与赛道边界状态 |
| M4-M2-DEPENDENCY | 必须 | M4 | 消费同一 run_id 的 M2 material 与 persona 状态 |
| M4-M6-DEPENDENCY | 必须 | M4 | 消费同一 run_id 的 M6 规范关键词状态 |
| M4-M3-DEPENDENCY | 必须 | M4 | 消费同一 run_id 的 M3 达人候选与名额状态 |

## 4. 证据

> 规范性声明：本节操作约束仅以“控制规则表”为准；表外文字只作解释、状态描述或示例，不授予例外。

| 规则 ID | 效果 | 对象 | 约束 |
| --- | --- | --- | --- |
| M4-BENCHMARK-CITATION | 必须 | 出价、测试带宽与止损线 | 引用同版 benchmark_registry 的 selected_source、period 与公式 |
| M4-NO-INTERNAL-ACCOUNT-FACTS | 禁止 | 公开观察、策略假设或 Mock 情景 | 表述为内部账户定向、竞价、转化或事故事实 |

## 5. 执行步骤

> 规范性声明：本节操作约束仅以“控制规则表”为准；表外文字只作解释、状态描述或示例，不授予例外。

| 规则 ID | 效果 | 对象 | 约束 |
| --- | --- | --- | --- |
| M4-RATIO-SEPARATION | 禁止 | scenario_ratio | 替代 recommended_ratio 或进入正式预算计算 |
| M4-RATIO-CONSERVATION | 必须 | recommended_ratio 与 scenario_ratio 的每个 search/feed 配对 | 各自满足 search + feed = 1.0（100%） |
| M4-RISK-COMPONENTS | 必须 | 每个 risk_playbook 项 | 在 symptom/response 中包含诊断、动作、停止或升级条件与 owner |

```json
{
  "validation_contract": {
    "ratio_contract": {
      "recommended_ratio": {
        "source": "benchmark_registry.ratios.recommended_ratio.pairs",
        "use": "formal_budget",
        "equation": "search + feed = 1.0"
      },
      "scenario_ratio": {
        "source": "benchmark_registry.ratios.scenario_ratio.pairs",
        "use": "scenario_only",
        "equation": "search + feed = 1.0"
      }
    }
  }
}
```

以下 `calculation_contract` 是 `tools/budget.py`、`tools/bidding.py` 与 `tools/forecast.py` 的零代码等价契约。所有输入、来源、币种、公式、中间值和结果都必须留痕；缺值时严格使用下列降级，不得由模型补数。

```json
{
  "calculation_contract": {
    "paid_budget_source": {
      "provided": "paid_budget_cny = spotlight_budget_cny",
      "missing_spotlight_fallback": "compute_budget_split(total_budget_cny, goal, organic_ratio)",
      "organic_ratio_bounds": [0.20, 0.70],
      "goal_default_organic_ratio": {
        "conversion": 0.30,
        "leads": 0.30,
        "live_traffic": 0.30,
        "awareness": 0.50,
        "engagement": 0.50,
        "search_growth": 0.40
      },
      "organic_budget_formula": "round(total_budget_cny * organic_ratio)",
      "paid_budget_formula": "round(total_budget_cny - organic_budget_cny)",
      "review_rule": "round(abs(organic_ratio - goal_default), 4) > 0.10"
    },
    "bid_range": {
      "stage_guardrails": {
        "cold_start": [0.80, 1.30],
        "scaling": [0.90, 1.60]
      },
      "cold_start_default": [0.9, 1.1],
      "scaling_default": null,
      "validation": "low_multiplier < high_multiplier and both multipliers are within the selected stage guardrail",
      "source_rule": "baseline_cpc_cny != null requires baseline_source",
      "low_formula": "round(baseline_cpc_cny * low_multiplier, 2)",
      "high_formula": "round(baseline_cpc_cny * high_multiplier, 2)",
      "missing_cpc": "low = null; high = null; use account real-time suggested price for a small test",
      "missing_scaling_pair": "scaling = null"
    },
    "aov_conversion": {
      "native_midpoint": "(price_min + price_max) / 2",
      "CNY_or_RMB": "aov_cny = native_midpoint",
      "HKD_rate": 0.92,
      "HKD": "aov_cny = native_midpoint * 0.92",
      "pre_forecast_rounding": "none",
      "other_currency": "require a human-approved FX rate and source; otherwise ROI is null"
    },
    "forecast": {
      "constants": {
        "no_cvr_cpa_multiplier": 25,
        "test_budget_ratio": 0.15,
        "test_budget_ratio_no_cpa": 0.10,
        "test_budget_floor_ratio": 0.05,
        "sample_safety": 1.5,
        "stop_cpc_multiplier": 1.5,
        "stop_cpa_multiplier": 1.2,
        "roi_band_low": 0.7,
        "roi_band_high": 1.2,
        "min_impressions": 3000,
        "min_clicks": 100,
        "target_min_conversions_default": 20,
        "target_min_conversions_range": [10, 100]
      },
      "target_cpa_with_cvr": "baseline_cpc_cny / baseline_cvr",
      "target_cpa_without_cvr": "baseline_cpc_cny * no_cvr_cpa_multiplier",
      "target_cpa_without_cpc": null,
      "test_budget_with_cpa": "max(round(paid_budget_cny * test_budget_floor_ratio), round(min(paid_budget_cny * test_budget_ratio, target_cpa * target_min_conversions * sample_safety)))",
      "test_budget_without_cpa": "max(round(paid_budget_cny * test_budget_floor_ratio), round(paid_budget_cny * test_budget_ratio_no_cpa))",
      "cpc_stop": "round(baseline_cpc_cny * stop_cpc_multiplier, 2)",
      "cpa_stop": "round(target_cpa * stop_cpa_multiplier, 2)",
      "stop_condition": "(CPC > cpc_stop or CPA > cpa_stop) and (impressions >= min_impressions or clicks >= min_clicks)",
      "roi_condition": "CPC, CTR and CVR are all present",
      "roi_point": "round((1 / CPC) * CVR * aov_cny - 1, 2)",
      "roi_band": "[round(unrounded_roi * roi_band_low, 2), round(unrounded_roi * roi_band_high, 2)]"
    }
  }
}
```

1. 校验四份上游状态、`run_id`、证据 ID、冲突、缺口和审批边界；硬前序缺失时输出 `blocked`。
2. 从 M1 `benchmark_registry` 读取 CPC/CTR/CVR/CPA 的已选值、来源、期间和公式。提供 `spotlight_budget_cny` 时直接作为预测预算；缺失时按 `paid_budget_source` 调用预算拆分口径，未显式批准 `organic_ratio` 时使用目标默认档。
3. 按 `aov_conversion` 计算原币价带中值和 CNY 客单价。HKD 使用当前代码参考系数 0.92 且预测前不先舍入；其他币种没有固定系数，缺人工批准汇率及来源时 ROI 保持 `null`。
4. 按 `bid_range` 执行冷启动计算；默认倍率为 0.9–1.1。放量只有在明确记录一组 0.9–1.6 护栏内且下限小于上限的倍率时才计算，否则 `scaling = null`。缺 CPC 时金额上下界与 CPC 止损保持 `null`。
5. 按 `forecast` 依次计算目标 CPA、测试带宽及 5% 下限、CPC/CPA 止损和 ROI。无 CVR 时的 `CPC × 25` 是约 4% 点击转化的保守测试占位，不是账户事实；CPC/CTR/CVR 任一缺失都不输出 ROI。
6. 建立 2–4 个聚光付费计划，计划占比合计 1.0；建立恰好三个定向包，定向包占比合计 1.0。M2 标签与 M3 达人相似人群只记作待后台验证候选。
7. 从 `recommended_ratio.pairs` 选择一组经人工审批的正式配对写入 `search_feed_split`。`scenario_ratio.pairs` 只保留在 A/B 情景记录，不写入正式分配字段。
8. 生成 2–4 个投放时段。优先引用 `category_note_evidence` 聚合出的高互动时段；无证据时在 action 中标明作息假设及验证窗口。
9. 风险预案恰好覆盖冷启动失败、成本过高、流量跑不动、拒审、衰退。`symptom` 写证据化信号与诊断依据；`response` 统一使用“诊断：…；动作：…；停止/升级：…；owner：…”结构。
10. 将账户后台核验、出价/止损审批、预算比例、风险 owner 和实际执行权限列入 `human_review_items`，完成 Grounding 自检。

## 6. 输出契约

字段及父级关系复制自当前 `Module4Output`：

```json
{
  "output_contract": {
    "$": [
      "account_structure",
      "targeting_packages",
      "bidding",
      "search_feed_split",
      "daily_schedule",
      "forecast",
      "risk_playbook",
      "human_review_items"
    ],
    "$.account_structure": [
      "campaign_naming_rule",
      "unit_naming_rule",
      "campaigns"
    ],
    "$.account_structure.campaigns[]": [
      "name",
      "objective",
      "budget_share",
      "placement"
    ],
    "$.targeting_packages[]": [
      "package",
      "audience_desc",
      "budget_share",
      "applicable_stage",
      "smart_expansion"
    ],
    "$.bidding": ["cold_start", "scaling_rules"],
    "$.bidding.cold_start": [
      "method",
      "bid_low_cny",
      "bid_high_cny",
      "basis"
    ],
    "$.search_feed_split": ["search", "feed", "synergy_note"],
    "$.daily_schedule[]": ["time_range", "action"],
    "$.forecast": [
      "test_budget_cny",
      "stop_loss_cpc_cny",
      "stop_loss_cpa_cny",
      "roi_point",
      "roi_band",
      "status"
    ],
    "$.risk_playbook[]": ["problem", "symptom", "response"]
  }
}
```

`campaigns` 为 2–4 项且占比合计 1.0；`targeting_packages` 恰好 3 项且占比合计 1.0；`search_feed_split.search + search_feed_split.feed = 1.0`；`daily_schedule` 为 2–4 项；`risk_playbook` 恰好 5 项；`human_review_items` 为 1–6 项。调价动作使用百分比，出价和预测缺证据时按当前模型的 nullable 字段降级。

## 7. module_state

```yaml
module_state:
  run_id: "与 M1、M2、M6、M3 相同"
  module: "M4"
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

`decisions` 保存账户结构、定向候选、正式比例来源、出价/止损计算和风险 owner。账户后台状态、实际竞价和真实转化仅在授权账户证据支持时进入 `confirmed_facts`。

## 8. Grounding 自检

1. 每个出价、测试带宽、止损和 ROI 是否回到同版 `benchmark_registry` 的证据 ID、`selected_source`、期间和公式？
2. `decision_source` 是否区分历史基准、确定性计算、策略方案、Mock 情景和人工确认？
3. `confidence` 是否反映 CPC/CTR/CVR、时段、后台标签和达人状态缺口？
4. 正式 `search_feed_split` 是否来自 `recommended_ratio`，与 `scenario_ratio` 分离，且每对合计 100%？
5. 五个风险项是否各自包含诊断、动作、停止/升级条件和 owner？
6. 是否没有把公开观察、假设或 Mock 描述成内部账户事实？

## 9. 降级

- 任一硬前序缺失或 `run_id` 不一致：输出 `blocked` 和缺失状态清单。
- CPC 缺失：`bid_low_cny`、`bid_high_cny` 与 CPC 止损为 `null`，不生成金额出价。
- CTR/CVR 缺失：不输出 ROI 单点/区间，保留测试带宽和现有证据支持的止损项。
- 无时段证据：输出显式作息假设与小范围验证时段。
- 风险情景为 Mock：只作为预案结构演示，不能描述为真实账户事故。
- `recommended_ratio` 未审批或配对不守恒：不形成正式 `search_feed_split`，状态为 `awaiting_human_review`。

## 10. 人工拍板

人工必须确认：聚光推广目标和版位；后台真实标签与达人相似人群资格；`benchmark_registry` 版本；出价、测试带宽、止损和放量规则；正式搜索/信息流配对；投放时段；五类风险的 owner 与升级路径；账户执行权限。未确认项保留在 `human_review_items`。
