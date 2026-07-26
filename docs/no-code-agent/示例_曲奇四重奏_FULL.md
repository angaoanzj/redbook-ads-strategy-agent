# 曲奇四重奏 `/full` 可追溯示例

这是基于仓库既有曲奇四重奏输入的**结构示例**，不是投放、采购、下单或达人合作指令。它只使用 `examples/cookie_quartet_full_case.json`、`examples/cookie_quartet_with_workbook_data.json`、`data/quartet_brand_dossier.json`、`data/quartet_public_sources.json` 和 `docs/QUARTET_DATA_PROVENANCE.md` 中已有的来源口径。示例运行 ID 为 `CQ-2026-07-25-001`，唯一顺序为 `M1 → M2 → M6 → M3 → M4 → M5`。

## 简要输入与边界

- 品牌：曲奇四重奏；品类：香港蝴蝶酥伴手礼；产品：经典－原味蝴蝶酥礼盒，价格 HKD 228。
- 品牌输入的初始人群：30—55 岁首次到港游客、家庭游客、送长辈人群、偏好经典口味者；这不是已验证的真实平台人群。
- 本次总预算输入为 CNY 100000，聚光预算输入为 CNY 70000，周期 30 天，目标为 conversion；金额只有经人工审批后才可执行。
- 工作簿数据需求：必须保留 `数据需求.xlsx`、工作表、期间、公式和导入责任人。现有工作簿未说明具体平台导出来源，正式使用前需数据负责人确认。
- 公开观察只描述样本与采集时点；不确认竞品聚光账户、真实定向、订单、真实转化或账户后台事实。

## evidence_registry

| ID | 标签 | 已有来源与可用结论 | 不能推出什么 |
| --- | --- | --- | --- |
| A-01 | `A_官方或授权` | 本次未提供官方规则原文、授权账户导出或书面授权材料，登记为 `unavailable`。 | 不得用公开网页补成授权账户事实。 |
| B-01 | `B_公开观察` | `data/quartet_public_sources.json` 记录品牌官网、香港品牌发展局和商场门店公开页；整个混合公开来源包统一按公开观察处理。 | 不把宣传销售口径、商场列表或品牌网页当作授权经营数据。 |
| B-02 | `B_公开观察` | `cookie_quartet_full_case.json` 的公开笔记样本、公开作者样本与竞品搜索链接；只描述样本内主题、形态和观察时点。 | 不推断平台大盘、竞品预算、竞品真实定向、订单或账户表现。 |
| C-01 | `C_用户导入` | `数据需求.xlsx` 的产品、投流和内容工作表；2026 年 1—5 月加权汇总指标来自现有示例。 | 原文件未标平台导出来源，不能直接证明账户归因或平台规则。 |
| D-01 | `D_行业基准` | 本次已有输入未提供可比的行业数值；登记为空，只允许未来补充后作测试范围参考。 | 不用行业常识补成账户历史或单点指标。 |
| E-01 | `E_策略假设` | 测试画像、候选标签、内容方向、关键词分层及比例候选。 | 不写为真实受众、后台可投标签或已验证效果。 |
| Mock-01 | `Mock` | 现有全量示例的 CVR 0.012 和模拟拒审台账仅用于演示/回归结构。 | Mock 不进入正式预算、采购、下单或正式决策。 |

`Mock` 与正式输入严格隔离：本例不把 Mock CVR 写进 `benchmark_registry.selected_value`，也不以模拟拒审次数判断账户风险。

以下 JSON 是本例唯一的机器可读 `evidence_registry`。字段与 `01_全局证据与数据纪律.md` 完全一致；表格和其余说明只帮助操作者阅读，不能另建别名或改写证据等级。

```json
{
  "evidence_registry": {
    "version": "CQ-2026-07-25.1",
    "run_id": "CQ-2026-07-25-001",
    "evidence": [
      {"id": "A-01", "evidence_level": "A_官方或授权", "source_type": "official_or_authorized", "source_name": null, "source_url": null, "collected_at": "2026-07-25", "period": null, "status": "unavailable", "is_mock": false, "allowed_use": ["补数清单"], "prohibited_use": ["账户事实", "正式指标"]},
      {"id": "B-01", "evidence_level": "B_公开观察", "source_type": "public_source_bundle", "source_name": "data/quartet_public_sources.json", "source_url": "见 sources[].url", "collected_at": "2026-07-25", "period": "公开页面访问时点", "status": "available", "is_mock": false, "allowed_use": ["品牌公开资料核验", "门店公开观察"], "prohibited_use": ["授权经营数据", "账户事实"]},
      {"id": "B-02", "evidence_level": "B_公开观察", "source_type": "public_note_sample", "source_name": "examples/cookie_quartet_full_case.json", "source_url": "见公开样本 source_url", "collected_at": "2026-07-25", "period": "样本观察时点", "status": "available", "is_mock": false, "allowed_use": ["样本内主题与形态描述"], "prohibited_use": ["平台大盘", "竞品真实预算", "竞品真实定向", "竞品订单"]},
      {"id": "C-01", "evidence_level": "C_用户导入", "source_type": "user_workbook", "source_name": "数据需求.xlsx", "source_url": null, "collected_at": "2026-07-25", "period": "2026-01/2026-05", "status": "available", "is_mock": false, "allowed_use": ["用户声明范围内的历史聚合"], "prohibited_use": ["未复核账户归因", "竞品账户事实"]},
      {"id": "D-01", "evidence_level": "D_行业基准", "source_type": "industry_benchmark", "source_name": null, "source_url": null, "collected_at": "2026-07-25", "period": null, "status": "unavailable", "is_mock": false, "allowed_use": ["补数清单"], "prohibited_use": ["账户历史", "单点正式指标"]},
      {"id": "E-01", "evidence_level": "E_策略假设", "source_type": "strategy_assumption", "source_name": "本例测试方案", "source_url": null, "collected_at": "2026-07-25", "period": "未来首轮测试", "status": "assumption", "is_mock": false, "allowed_use": ["待审批测试方案", "比例情景"], "prohibited_use": ["历史事实", "未审批正式预算"]},
      {"id": "Mock-01", "evidence_level": "Mock", "source_type": "simulation", "source_name": "examples/cookie_quartet_full_case.json", "source_url": null, "collected_at": "2026-07-25", "period": "演示情景", "status": "mock", "is_mock": true, "allowed_use": ["结构演示", "回归测试"], "prohibited_use": ["正式预算", "采购", "下单", "账户事实"]}
    ],
    "claims": [
      {"id": "CLAIM-COMPETITOR-SPOTLIGHT-ACCOUNT", "subject": "竞品聚光账户", "claim_type": "private_competitor_account", "status": "unavailable", "value": null, "unit": null, "evidence_ids": [], "formal_use": false, "required_evidence": "竞品授权账户报表"},
      {"id": "CLAIM-COMPETITOR-TARGETING", "subject": "竞品真实定向", "claim_type": "private_competitor_targeting", "status": "unavailable", "value": null, "unit": null, "evidence_ids": [], "formal_use": false, "required_evidence": "竞品授权账户报表"},
      {"id": "CLAIM-COMPETITOR-ORDERS", "subject": "竞品订单", "claim_type": "private_competitor_orders", "status": "unavailable", "value": null, "unit": null, "evidence_ids": [], "formal_use": false, "required_evidence": "竞品授权订单报表"},
      {"id": "CLAIM-MOCK-CVR", "subject": "CVR", "claim_type": "mock_metric", "status": "mock", "value": 0.012, "unit": "ratio", "evidence_ids": ["Mock-01"], "formal_use": false, "required_evidence": "非 Mock 的授权聚光转化导出"}
    ],
    "competitor_subjects": [
      {"name": "奇华", "evidence_ids": ["B-02"], "status": "public_observation"},
      {"name": "珍妮曲奇", "evidence_ids": ["B-02"], "status": "public_observation"}
    ]
  }
}
```

## `benchmark_registry` 选择

以下登记复用工作簿示例的精确历史值；所有值都带 C-01、期间与公式。CPC/CTR/CPM 是工作簿聚合，不等于竞品或聚光账户的实时数据。CVR 的现有 0.012 是 Mock，故不选入 SSOT。

```json
{
  "benchmark_registry": {
    "version": "CQ-2026-07-25.1",
    "metrics": {
      "CPC": {"candidates": [{"value": 0.3005181259, "source": "C-01", "period": "2026-01/2026-05", "formula": "spend / clicks", "evidence_level": "C_用户导入"}], "selected_value": 0.3005181259, "selected_source": "C-01", "selection_reason": "同口径的用户导入工作簿聚合", "period": "2026-01/2026-05", "formula": "spend / clicks", "evidence_level": "C_用户导入", "value_kind": "historical_fact", "value_precision": "exact", "formal_use": false, "formal_selection_status": "awaiting_human_review"},
      "CPM": {"candidates": [{"value": 48.22115472, "source": "C-01", "period": "2026-01/2026-05", "formula": "spend / impressions * 1000", "evidence_level": "C_用户导入"}], "selected_value": 48.22115472, "selected_source": "C-01", "selection_reason": "同口径的用户导入工作簿聚合", "period": "2026-01/2026-05", "formula": "spend / impressions * 1000", "evidence_level": "C_用户导入", "value_kind": "historical_fact", "value_precision": "exact", "formal_use": false, "formal_selection_status": "awaiting_human_review"},
      "CPA": {"candidates": [], "selected_value": null, "selected_source": null, "selection_reason": "无账户级转化数据，不可确认", "period": null, "formula": "spend / acquisitions", "evidence_level": null},
      "CTR": {"candidates": [{"value": 0.1604600541, "source": "C-01", "period": "2026-01/2026-05", "formula": "clicks / impressions", "evidence_level": "C_用户导入"}], "selected_value": 0.1604600541, "selected_source": "C-01", "selection_reason": "同口径的用户导入工作簿聚合", "period": "2026-01/2026-05", "formula": "clicks / impressions", "evidence_level": "C_用户导入", "value_kind": "historical_fact", "value_precision": "exact", "formal_use": false, "formal_selection_status": "awaiting_human_review"},
      "CVR": {"candidates": [], "selected_value": null, "selected_source": null, "selection_reason": "现有 0.012 为 Mock；正式值不可确认", "period": null, "formula": "acquisitions / clicks", "evidence_level": null},
      "ROAS": {"candidates": [], "selected_value": null, "selected_source": null, "selection_reason": "待提供归因口径收入与花费", "period": null, "formula": "attributed_revenue / spend", "evidence_level": null}
    },
    "ratios": {
      "recommended_ratio": {"value_kind": "future_recommendation", "range_representation": "complementary_pairs", "pairs": [{"search": 60, "feed": 40, "evidence_id": "E-01", "evidence_level": "E_策略假设", "source": "本例首轮搜推比例测试设计", "period": "未来首轮测试", "formula": "search + feed = 100%", "selection_reason": "偏搜索意图测试范围的下界候选", "formal_use": false}, {"search": 70, "feed": 30, "evidence_id": "E-01", "evidence_level": "E_策略假设", "source": "本例首轮搜推比例测试设计", "period": "未来首轮测试", "formula": "search + feed = 100%", "selection_reason": "偏搜索意图测试范围的上界候选", "formal_use": false}], "conservation_rule": "search + feed = 100%", "purpose": "经人工审批后用于正式预算计算", "formal_use": false},
      "scenario_ratio": {"value_kind": "future_recommendation", "range_representation": "complementary_pairs", "pairs": [{"search": 50, "feed": 50, "evidence_id": "E-01", "evidence_level": "E_策略假设", "source": "本例首轮搜推比例测试设计", "period": "未来首轮测试", "formula": "search + feed = 100%", "selection_reason": "均衡搜推的 A/B 对照情景", "formal_use": false}, {"search": 55, "feed": 45, "evidence_id": "E-01", "evidence_level": "E_策略假设", "source": "本例首轮搜推比例测试设计", "period": "未来首轮测试", "formula": "search + feed = 100%", "selection_reason": "轻度偏搜索的 A/B 对照情景", "formal_use": false}], "conservation_rule": "search + feed = 100%", "purpose": "仅用于 A/B 情景比较，不进入正式预算汇总", "formal_use": false}
    }
  }
}
```

## /full 状态交接

下列每个状态都携带同一 `run_id`、证据 ID、缺口和人工复核项；新会话必须原样粘贴这些状态及上述登记表后才能续跑。

### M1 module_state

```json
{
  "module_state": {
    "run_id": "CQ-2026-07-25-001", "module": "M1", "status": "completed_with_gaps", "evidence_ids": ["B-01", "B-02", "C-01"],
    "confirmed_facts": ["C-01：经典－原味蝴蝶酥礼盒价格为 HKD 228", "C-01：工作簿含 2026-01/2026-05 聚合投流与内容数据"],
    "assumptions": [{"assumption": "公开样本主题观察不代表全平台", "evidence_ids": ["B-02"]}],
    "decisions": [{"decision": "register_workbook_metrics", "metrics": ["CTR", "CPC", "CPM"], "source": "C-01"}],
    "unresolved_gaps": ["CLAIM-COMPETITOR-SPOTLIGHT-ACCOUNT", "CLAIM-COMPETITOR-TARGETING", "CLAIM-COMPETITOR-ORDERS"],
    "human_review_items": ["确认工作簿平台导出来源与指标口径"], "confidence": "medium", "decision_source": "mixed"
  }
}
```

### M2 module_state

```json
{
  "module_state": {
    "run_id": "CQ-2026-07-25-001", "module": "M2", "status": "completed_with_gaps", "evidence_ids": ["B-02", "C-01", "E-01"],
    "confirmed_facts": ["C-01：品牌输入包含首次到港游客、家庭与送长辈场景"],
    "assumptions": [{"assumption": "伴手礼、经典口味与送礼是待验证内容角度和候选标签", "evidence_level": "E_策略假设"}],
    "decisions": [{"decision": "test_persona_only", "targeting_status": "requires_platform_validation"}],
    "unresolved_gaps": ["真实受众画像、偏好与转化归因不可确认"],
    "human_review_items": ["品牌确认三类内容角度和敏感标签边界"], "confidence": "low", "decision_source": "strategy_hypothesis"
  }
}
```

### M6 module_state

```json
{
  "module_state": {
    "run_id": "CQ-2026-07-25-001", "module": "M6", "status": "completed_with_gaps", "evidence_ids": ["B-02", "E-01"],
    "confirmed_facts": ["B-02：公开样本出现香港伴手礼、蝴蝶酥、曲奇等词语"],
    "assumptions": [{"assumption": "将公开样本词和送礼场景组织为待验证关键词分层", "evidence_level": "E_策略假设"}],
    "decisions": [{"decision": "freeze_keyword_registry", "version": "CQ-2026-07-25.1", "m3_may_only": "transform_this_registry"}],
    "unresolved_gaps": ["平台真实搜索量、热度排名、竞争度和建议价不可确认"],
    "human_review_items": ["确认关键词品牌安全与后台可用性"], "confidence": "low", "decision_source": "mixed"
  }
}
```

### M3 module_state

```json
{
  "module_state": {
    "run_id": "CQ-2026-07-25-001", "module": "M3", "status": "completed_with_gaps", "evidence_ids": ["B-02", "E-01"],
    "confirmed_facts": [],
    "assumptions": [{"assumption": "按 M6 规范词库建立筛选维度，不新增关键词", "evidence_level": "E_策略假设"}],
    "decisions": [{"decision": "creator_boundary", "matched_creators": [], "formal_procurement": false}],
    "unresolved_gaps": ["达人实名、最新报价、档期、受众匹配和履约能力不可确认"],
    "human_review_items": ["导入授权达人表并逐条完成身份、报价和档期核验"], "confidence": "low", "decision_source": "strategy_hypothesis"
  }
}
```

M3 的达人边界：现有公开作者样本可以保留为 `B_公开观察` 的核验候选，但不会形成真实推荐。没有蒲公英/授权材料中的身份、最新报价、档期、受众和履约证据时，`matched_creators: []`；不创建采购、下单或合作承诺。

### M4 module_state

```json
{
  "module_state": {
    "run_id": "CQ-2026-07-25-001", "module": "M4", "status": "awaiting_human_review", "evidence_ids": ["C-01", "E-01"],
    "confirmed_facts": ["C-01：SSOT 已选 CTR、CPC、CPM 的期间为 2026-01/2026-05"],
    "assumptions": [{"assumption": "候选比例需要人工审批", "evidence_level": "E_策略假设"}],
    "decisions": [{"decision": "search_feed_split", "source_path": "benchmark_registry.ratios.recommended_ratio.pairs[0]", "selected_pair": {"search": 60, "feed": 40, "evidence_id": "E-01", "evidence_level": "E_策略假设", "source": "本例首轮搜推比例测试设计", "period": "未来首轮测试", "formula": "search + feed = 100%", "selection_reason": "偏搜索意图测试范围的下界候选", "formal_use": false}, "evidence_id": "E-01", "selection_reason": "偏搜索意图测试范围的下界候选", "formal_use": false}, {"decision": "scenario_ratio", "source_path": "benchmark_registry.ratios.scenario_ratio.pairs", "formal_use": false}],
    "unresolved_gaps": ["聚光真实定向、竞价、转化、时段和账户权限不可确认"],
    "human_review_items": ["审批比例、测试带宽、出价/止损、风险 owner 和账户执行权限"], "confidence": "low", "decision_source": "mixed"
  }
}
```

M4 只展示 SSOT 比例的待审批测试写法：`recommended_ratio` 的 search 60% / feed 40% 是 `E-01` 策略假设“偏搜索意图测试范围的下界候选”，并非历史比例；`scenario_ratio` 的 50% / 50% 同样绑定 `E-01`，只作 A/B 情景。每对比例均互补守恒，候选标签、出价、时段和预测均不是后台事实；缺少非 Mock CVR 时不生成转化或 ROI 承诺。

下方是输入总预算的规范化**待审批金额演算**，不用任何竞品或 Mock 数据。原始输入已是整数，故 `rounding_delta` 为 0；付费阶段采用 20% / 60% / 20%，三项相加为 70000。它验证守恒，不构成放量、采购或下单结论。

```json
{
  "budget_ledger": {
    "normalized_total_budget_cny": 100000,
    "organic_budget_cny": 30000,
    "paid_budget_cny": 70000,
    "paid_phases": [
      {"phase": "预热期", "paid_budget_cny": 14000},
      {"phase": "爆发期", "paid_budget_cny": 42000},
      {"phase": "长尾期", "paid_budget_cny": 14000}
    ]
  }
}
```

### M5 module_state

```json
{
  "module_state": {
    "run_id": "CQ-2026-07-25-001", "module": "M5", "status": "awaiting_human_review", "evidence_ids": ["C-01", "E-01"],
    "confirmed_facts": ["C-01：本次总预算输入为 CNY 100000，聚光预算输入为 CNY 70000"],
    "assumptions": [{"raw_total_budget_cny": 100000, "rounding_delta": 0, "natural_paid_ratio": {"organic": 30, "paid": 70}, "evidence_level": "E_策略假设"}],
    "decisions": [{"normalized_total_budget_cny": 100000, "rounding_delta": 0, "budget_conservation": "passed", "approval_required": true}],
    "unresolved_gaps": ["正式比例、达人采购、账户执行和非 Mock 转化指标未获批准"],
    "human_review_items": ["人工审批总预算、比例、阶段、达人、出价、账户权限和放量条件"], "confidence": "medium", "decision_source": "deterministic_calculation"
  }
}
```

## 未解决缺口与人工审批

| 缺口 | 可接受补数 | 本例处理 |
| --- | --- | --- |
| 竞品聚光账户、真实定向与订单 | 授权账户报表或用户导入 | 不可确认；不用于竞品比较、预算或定向决定。 |
| 品牌工作簿来源与归因口径 | `数据需求.xlsx` 的导出说明、平台、账户和数据负责人确认 | C-01 保留原值，正式使用前人工审批。 |
| 达人身份、报价、档期和履约 | 蒲公英/授权达人表与人工核验 | M3 保留 `matched_creators: []`。 |
| 非 Mock CVR、真实出价和后台标签 | 授权聚光导出与账户内核验 | M4/M5 不作转化承诺或账户执行。 |

人工审批的最小清单：工作簿口径、品牌/合规表达、M4 的比例与测试边界、M5 的金额与阶段、达人合作、采购/下单和账户权限。审批前所有金额都只是计算草案。

## `/full` 最终审计

| 检查项 | 本例结果 | 处理 |
| --- | --- | --- |
| 来源覆盖 | 通过 | A 与 D 登记为不可用；B/C 的已有来源、E 假设和 Mock 均有 ID 与边界。 |
| SSOT 冲突 | 无已裁决冲突；CVR 缺正式值 | CVR 保持 null，Mock 未成为 selected_value。 |
| 预算守恒 | 通过 | 30000 + 70000 = 100000；14000 + 42000 + 14000 = 70000。 |
| Mock 隔离 | 通过 | Mock 仅作演示；未进入 SSOT 选择、预算、采购、下单或正式决策。 |
| 跨模块冲突 | 存在待人工收口项 | M1→M2→M6→M3→M4→M5 的状态、同一 run_id 和登记表已保留；私有账户、达人与工作簿口径缺口未被伪装为事实。 |

审计结论：可交付为待审批方案和补数清单，不能视为正式投放、达人合作、采购或下单决策。
