# 模块5：全域预算节奏 SOP

> 文档级规范性声明：本 SOP 的全部十个业务章节（职责与边界、输入、前序依赖、证据、执行步骤、输出契约、module_state、Grounding 自检、降级、人工拍板）均为强制执行契约；控制规则表是禁止与必须规则的唯一增删入口，任何表外文字、代码块或示例不得取消、替代或覆盖这些契约。

本 SOP 复用 `module_agents/module5.py`、`tools/budget.py`、`tools/creators.py`、`tools/bidding.py` 和共享治理文件的当前输出契约。M5 是全案预算与节奏收口模块，在所有上游状态可追溯、冲突已解决、Mock 已隔离后形成待审批的正式业务输出。

## 1. 职责与边界

M5 负责自然/付费预算拆分、预热/爆发/长尾三阶段付费节奏、达人分层预算、冷启动/放量出价、自然与付费联动规则、应急动作和人工复核项。

正式预算数字是“已批准总预算 + 已批准比例”的确定性计算结果，不是历史事实或效果承诺。未批准的未来建议保持范围表达；历史账户数据保持原始精确值、来源、期间和公式。任何采购、下单、放量或账户执行仍由人工审批。

## 2. 输入

M1 提供赛道边界与指标登记；M2 提供画像、素材和内容门槛；M6 提供规范关键词；M3 提供达人层级、证据候选和开放名额；M4 提供账户测试方案、正式比例候选、出价/止损与风险 owner。所有状态使用同一 `run_id` 和同版 `benchmark_registry`。

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
      "benchmark_evidence",
      "creator_evidence",
      "owned_history_summary",
      "owned_content_history"
    ],
    "workflow": ["run_id", "benchmark_registry", "evidence_registry"],
    "upstream_module_states": ["M1", "M2", "M6", "M3", "M4"]
  }
}
```

## 3. 前序依赖

> 规范性声明：本节操作约束仅以“控制规则表”为准；表外文字只作解释、状态描述或示例，不授予例外。

| 规则 ID | 效果 | 对象 | 约束 |
| --- | --- | --- | --- |
| M5-M1-DEPENDENCY | 必须 | M5 | 消费同一 run_id 的 M1 状态 |
| M5-M2-DEPENDENCY | 必须 | M5 | 消费同一 run_id 的 M2 状态 |
| M5-M6-DEPENDENCY | 必须 | M5 | 消费同一 run_id 的 M6 状态 |
| M5-M3-DEPENDENCY | 必须 | M5 | 消费同一 run_id 的 M3 状态 |
| M5-M4-DEPENDENCY | 必须 | M5 | 消费同一 run_id 的 M4 状态 |

## 4. 证据

> 规范性声明：本节操作约束仅以“控制规则表”为准；表外文字只作解释、状态描述或示例，不授予例外。

| 规则 ID | 效果 | 对象 | 约束 |
| --- | --- | --- | --- |
| M5-HISTORY-FUTURE-PRECISION | 必须 | 历史事实与未来建议 | 历史保留来源精确值，未来未批准建议使用范围 |
| M5-NO-UNRESOLVED-FORMAL-OUTPUT | 禁止 | 存在未解决同优先级冲突或 Mock 污染的 M5 | 输出正式预算、采购、下单或放量结论 |

## 5. 执行步骤

> 规范性声明：本节操作约束仅以“控制规则表”为准；表外文字只作解释、状态描述或示例，不授予例外。

| 规则 ID | 效果 | 对象 | 约束 |
| --- | --- | --- | --- |
| M5-TOTAL-BUDGET-CONSERVATION | 必须 | budget_split | organic_budget_cny + paid_budget_cny = normalized_total_budget_cny |
| M5-PHASE-BUDGET-CONSERVATION | 必须 | phases | sum(phases[].paid_budget_cny) = budget_split.paid_budget_cny |
| M5-COMPLETE-ACTION-PLAN | 必须 | M5 正式业务输出 | 同时包含预算、阶段、达人分层、出价、联动规则与应急动作 |
| M5-PHASE-REMAINDER | 必须 | 阶段整数尾差 | 归入 phases[1]（爆发期）后执行阶段守恒检查 |
| M5-CREATOR-TIER-ROUNDING | 必须 | 达人层级金额 | 按 plan_creator_tiers 对每层独立 round，不重分配整数尾差 |

```json
{
  "validation_contract": {
    "normalization": {
      "raw_field": "campaign_request.total_budget_cny",
      "normalized_field": "normalized_total_budget_cny",
      "formula": "int(round(total_budget_cny))",
      "rounding_semantics": "Python round; ties-to-even",
      "rounding_delta_formula": "normalized_total_budget_cny - total_budget_cny",
      "module_state_record": {
        "location": "assumptions/decisions",
        "fields": [
          "raw_total_budget_cny",
          "normalized_total_budget_cny",
          "rounding_delta"
        ]
      },
      "examples": [
        {
          "raw_total_budget_cny": 100000.4,
          "normalized_total_budget_cny": 100000,
          "rounding_delta": -0.4
        },
        {
          "raw_total_budget_cny": 100000.5,
          "normalized_total_budget_cny": 100000,
          "rounding_delta": -0.5
        },
        {
          "raw_total_budget_cny": 100000.6,
          "normalized_total_budget_cny": 100001,
          "rounding_delta": 0.4
        }
      ]
    },
    "budget_conservation": {
      "total_budget": {
        "equation": "budget_split.organic_budget_cny + budget_split.paid_budget_cny = normalized_total_budget_cny",
        "on_failure": "blocked"
      },
      "paid_phases": {
        "equation": "sum(phases[].paid_budget_cny) = budget_split.paid_budget_cny",
        "on_failure": "blocked"
      }
    },
    "phase_remainder": {
      "target": "phases[1].paid_budget_cny",
      "target_phase": "爆发期",
      "required_total": "budget_split.paid_budget_cny",
      "formula": "target += required_total - sum(rounded_items)"
    },
    "creator_tier_rounding": {
      "source_tool": "plan_creator_tiers",
      "collaboration_pool_output": "round(organic_budget_cny)",
      "amplification_pool_raw": "paid_budget_cny * amplification_ratio",
      "amplification_pool_output": "round(amplification_pool_raw)",
      "tier_collaboration": "round(organic_budget_cny * budget_ratio)",
      "tier_amplification": "round(amplification_pool_raw * budget_ratio)",
      "remainder_policy": "none; retain independently rounded tier amounts",
      "sum_behavior": "tier sums may differ from rounded pool outputs"
    }
  }
}
```

以下 `calculation_contract` 是 `tools/budget.py`、`tools/creators.py` 与 `tools/bidding.py` 的零代码等价计算契约。必须先按契约计算，再映射到输出；输入、倍率、来源、中间值、舍入和尾差都要保留。

```json
{
  "calculation_contract": {
    "budget_split": {
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
      "review_rule": "round(abs(organic_ratio - goal_default), 4) > 0.10",
      "phase_ratios": [["预热期", 0.20], ["爆发期", 0.60], ["长尾期", 0.20]],
      "phase_formula": "round(paid_budget_cny * phase_ratio)",
      "phase_drift": "paid_budget_cny - sum(rounded_phase_budgets)",
      "phase_drift_target": "爆发期"
    },
    "creator_tier_plan": {
      "allowed_tiers": ["素人", "达人", "KOL"],
      "allocation_count": {"min": 1, "max": 3},
      "creator_count_per_tier": {"min": 1, "max": 100},
      "budget_ratio_per_tier": {"exclusive_min": 0, "exclusive_max": 1},
      "budget_ratio_rule": "abs(sum(budget_ratio) - 1.0) <= 0.01",
      "tiers_unique": true,
      "amplification_ratio": {"default": 0.30, "min": 0.10, "max": 0.50},
      "amplification_pool_raw": "paid_budget_cny * amplification_ratio",
      "collaboration_pool_output": "round(organic_budget_cny)",
      "amplification_pool_output": "round(amplification_pool_raw)",
      "tier_collaboration": "round(organic_budget_cny * budget_ratio)",
      "quote_per_creator": "round(tier_collaboration / count)",
      "tier_amplification": "round(amplification_pool_raw * budget_ratio)",
      "spotlight_per_note": "round(tier_amplification / count)",
      "rounding": "Python round; ties-to-even",
      "remainder_policy": "none; retain independently rounded tier amounts"
    },
    "bid_plan": {
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
    }
  }
}
```

1. 校验 M1/M2/M6/M3/M4 状态、`run_id`、证据 ID、同优先级冲突、Mock 标识和人工审批结果。硬前序、冲突或污染门禁未通过时停止正式业务输出。
2. 将历史账户值按 `historical_fact + exact` 保存；未来未批准的预算比例、出价和效果目标按 `future_recommendation + range` 保存。人工批准的比例另存审批 ID，随后进入确定性金额计算。
3. 先记录原始 `total_budget_cny`，再按 Python `int(round(total_budget_cny))` 的 ties-to-even 语义得到 `normalized_total_budget_cny`，并计算 `rounding_delta = normalized_total_budget_cny - total_budget_cny`。三项记录写入 `module_state.assumptions/decisions`，不增加 `Module5Output` 字段。
4. 执行与 `compute_budget_split` 同等的预算拆分。自然预算与付费预算相加等于 `normalized_total_budget_cny`；`spotlight_budget_cny` 与拆分结果冲突时进入人工裁决。
5. 从预算结果逐项转录恰好三个阶段。各阶段先按 Python `round` 取整数，再把 `paid_budget_cny - sum(phases[].paid_budget_cny)` 加到 `phases[1]`（爆发期）；例如付费预算 `70002` 对应 `[14000, 42002, 14000]`。每阶段 `key_actions` 覆盖内容、投流、复盘与切换条件。
6. 执行与 `plan_creator_tiers` 相同的分层计算，并与 M3 已确认层级/开放名额核对。合作金额按 `round(organic_budget_cny * budget_ratio)` 逐层独立计算；放大金额按未取整的 `paid_budget_cny * amplification_ratio` 乘各层比例后逐层独立 `round`。工具分别对合作池和放大池取整，但不把层级尾差重分配给任何 tier，因此层级金额之和可能与池输出相差整数尾差。
7. 从同版 `benchmark_registry` 的 CPC 按 `bid_plan` 计算出价。冷启动未另行批准时使用 0.9–1.1；放量必须记录一组 0.9–1.6 护栏内且下限小于上限的明确倍率，否则 `scaling = null`。缺 CPC 时两个出价带为 `null`，`basis` 说明缺口。M4 已批准止损和比例作为只读联动边界。
8. 生成 2–5 条 `synergy_rules`：自然素材达到何种证据化门槛后启动/放大付费，以及付费搜索词、点击与转化信号如何回流 M2/M6。阈值记录来源或策略假设。
9. 生成 2–4 条 `contingency_plans`，至少覆盖自然互动低、付费点击低、转化低；每条包括场景、量化触发条件和预算/素材/定向/出价调整动作，并引用 M4 风险 owner 或升级路径。
10. 复算总预算与阶段付费两条守恒方程；达人合作与放大金额按 `plan_creator_tiers` 的逐层独立舍入结果核对，并记录其与对应池输出的潜在整数差额。随后核对输出块完整性，列出预算、达人、出价、联动和应急审批项并执行 Grounding 自检。

## 6. 输出契约

字段及父级关系复制自当前 `Module5Output`：

```json
{
  "output_contract": {
    "$": [
      "budget_split",
      "phases",
      "creator_tier_plan",
      "bid_plan",
      "synergy_rules",
      "contingency_plans",
      "human_review_items"
    ],
    "$.budget_split": [
      "organic_budget_cny",
      "paid_budget_cny",
      "organic_ratio",
      "needs_review"
    ],
    "$.phases[]": ["phase", "paid_budget_cny", "key_actions"],
    "$.creator_tier_plan": ["tiers", "amplification_pool_cny"],
    "$.creator_tier_plan.tiers[]": [
      "tier",
      "count",
      "collaboration_budget_cny",
      "spotlight_amplification_budget_cny"
    ],
    "$.bid_plan": ["cold_start", "scaling", "basis"],
    "$.bid_plan.cold_start": ["low_cny", "high_cny"],
    "$.bid_plan.scaling": ["low_cny", "high_cny"],
    "$.synergy_rules[]": ["metric", "threshold", "action"],
    "$.contingency_plans[]": ["scenario", "trigger", "adjustment"]
  }
}
```

`phases` 恰好为预热期、爆发期、长尾期三项；每项 `key_actions` 为 1–5 条；达人层级至少一项；`synergy_rules` 为 2–5 项；`contingency_plans` 为 2–4 项；`human_review_items` 为 1–6 项。`cold_start` 与 `scaling` 在缺基准时按当前模型置 `null`。

## 7. module_state

```yaml
module_state:
  run_id: "与 M1、M2、M6、M3、M4 相同"
  module: "M5"
  status: "completed | completed_with_gaps | blocked | awaiting_human_review"
  evidence_ids: []
  confirmed_facts: []
  assumptions:
    - raw_total_budget_cny: 100000.5
      rounding_delta: -0.5
      note: "示例；实际值取本次 campaign_request 与规范化计算"
  decisions:
    - normalized_total_budget_cny: 100000
      rounding_policy: "int(round(total_budget_cny)); Python ties-to-even"
  unresolved_gaps: []
  human_review_items: []
  confidence: "low | medium | high"
  decision_source: "evidence | deterministic_calculation | strategy_hypothesis | mock | human_confirmed | mixed"
```

`confirmed_facts` 只保存带来源、期间和精确值的历史事实。`decisions` 保存审批 ID、预算计算、阶段节奏、达人分层、出价、联动和应急方案；未批准范围与缺证据阈值进入 `assumptions`。

## 8. Grounding 自检

1. 所有历史值是否保留证据 ID、来源、期间、公式和精确值，未来未批准建议是否保持范围？
2. `decision_source` 是否区分历史证据、确定性预算/出价计算、策略规则、Mock 和人工确认？
3. `confidence` 是否反映上游缺口、指标完整性、达人名额、冲突和审批状态？
4. 是否记录原始总预算、规范化总预算和舍入差额；自然预算加付费预算是否等于规范化总预算，三阶段付费金额是否等于付费预算；阶段尾差是否进入爆发期；达人层级是否逐层独立舍入且未重分配尾差？
5. 正式输出是否同时覆盖预算、阶段、达人层级、出价、联动和应急动作？
6. 未解决同优先级冲突或 Mock 污染是否触发 `blocked`，且没有正式预算、采购、下单或放量结论？

## 9. 降级

- 任一硬前序缺失或 `run_id`/登记版本不一致：只输出 `blocked` 状态与补数清单。
- 同优先级证据冲突未裁决：保留候选、来源和差异，不输出正式业务契约。
- 任一预算守恒式失败：记录差额、计算口径和修正请求，状态为 `blocked`。
- 输入链路含未隔离 Mock：停止正式预算、达人采购、下单和放量结论，转人工清理。
- 无 CPC：`cold_start`、`scaling` 为 `null`，不生成金额出价。
- 无历史自然/付费数据：联动阈值标为保守测试范围，状态为 `completed_with_gaps` 或 `awaiting_human_review`。

## 10. 人工拍板

人工必须确认：总预算与币种；自然/付费比例；三阶段金额和切换条件；达人层级、名单、报价与采购；CPC 来源和两个出价带；M4 止损与正式搜索/信息流配对；联动门槛；应急动作、owner 与升级路径；所有账户执行和放量。审批 ID 写入 `decisions`，未确认项留在 `human_review_items` 与 `unresolved_gaps`。
