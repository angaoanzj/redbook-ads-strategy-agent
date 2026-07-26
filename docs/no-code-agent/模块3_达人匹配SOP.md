# 模块3：达人匹配 SOP

> 文档级规范性声明：本 SOP 的全部十个业务章节（职责与边界、输入、前序依赖、证据、执行步骤、输出契约、module_state、Grounding 自检、降级、人工拍板）均为强制执行契约；控制规则表是禁止与必须规则的唯一增删入口，任何表外文字、代码块或示例不得取消、替代或覆盖这些契约。

本 SOP 复用 `module_agents/module3.py`、`tools/creator_match.py`、`tools/creators.py` 和共享治理文件的当前输出契约。零代码业务顺序中，M3 位于 M6 之后，负责把规范关键词与用户画像转成达人计划和证据化候选名单。

## 1. 职责与边界

> 规范性声明：本节操作约束仅以“控制规则表”为准；表外文字只作解释、状态描述或示例，不授予例外。

| 规则 ID | 效果 | 对象 | 约束 |
| --- | --- | --- | --- |
| M3-M6-CANONICAL-KEYWORDS | 必须 | M3 keyword_tracks | 只转换同一 run_id 的 M6 规范词库，不重新生成、另建或扩充关键词 |

## 2. 输入

业务输入来自三组结构化载荷：当前 `CampaignRequest` 字段、工作流登记和同一 `run_id` 的 M2/M6 状态。M2 提供 `persona`、内容方向、选题和素材门槛；M6 提供冻结版本的规范关键词、布局、预算比例和证据 ID。

达人输入逐条保留 `name`、`profile_url`、粉丝量、篇均互动、`quote_cny`、`audience_tags`、`past_campaign_result`、`source_name`、`collected_at`、证据等级和 Mock 标识。`category_note_evidence` 与 `benchmark_evidence` 只用于核对当前代码契约所需的主题/成本上下文，不取得关键词所有权。

```json
{
  "input_contract": {
    "campaign_request": [
      "brand_name",
      "category",
      "product_name",
      "selling_points",
      "initial_audience",
      "total_budget_cny",
      "spotlight_budget_cny",
      "campaign_days",
      "goal",
      "constraints",
      "category_note_evidence",
      "benchmark_evidence",
      "creator_evidence"
    ],
    "workflow": ["run_id", "benchmark_registry", "evidence_registry"],
    "upstream_module_states": ["M2", "M6"]
  }
}
```

## 3. 前序依赖

> 规范性声明：本节操作约束仅以“控制规则表”为准；表外文字只作解释、状态描述或示例，不授予例外。

| 规则 ID | 效果 | 对象 | 约束 |
| --- | --- | --- | --- |
| M3-M2-DEPENDENCY | 必须 | M3 | 消费同一 run_id 的 M2 persona 与 content 状态 |
| M3-M6-DEPENDENCY | 必须 | M3 | 消费同一 run_id 的 M6 规范关键词状态 |

## 4. 证据

> 规范性声明：本节操作约束仅以“控制规则表”为准；表外文字只作解释、状态描述或示例，不授予例外。

| 规则 ID | 效果 | 对象 | 约束 |
| --- | --- | --- | --- |
| M3-CREATOR-EVIDENCE | 必须 | 每个达人候选 | 绑定可复核身份、报价、过往结果、受众匹配证据与名额状态 |
| M3-NO-FAKE-RECOMMENDATION | 禁止 | placeholder 或 Mock 达人 | 描述为真实推荐或写入 matched_creators |
| M3-NO-PREVERIFICATION-PURCHASE | 禁止 | 未人工核验的达人候选 | 进入采购、下单或合作承诺 |

## 5. 执行步骤

以下 `calculation_contract` 是 `tools/creators.py` 与 `tools/creator_match.py` 的零代码等价计算契约。执行时必须保存输入、逐步计算值和结果；Python `round` 按 ties-to-even 处理。模型不得自行调整阈值、分数、排序、名额或舍入口径。

```json
{
  "calculation_contract": {
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
    "creator_matching": {
      "candidate_max": 50,
      "audience_keyword_count": {"min": 2, "max": 12},
      "normalization": "casefold().strip()",
      "follower_thresholds": {
        "amateur_lt": 10000,
        "creator_lt": 500000,
        "otherwise": "KOL",
        "missing": "待判定"
      },
      "score_formula": "min(BASE_MATCH_SCORE + PER_TAG_BONUS * len(keyword_set & tag_set), MAX_MATCH_SCORE)",
      "score_constants": {"base": 55, "per_overlap": 10, "cap": 95},
      "engagement_rate": "round(average_interactions / followers, 4) if average_interactions is not null and followers else null",
      "per_note_cap_ratio": {"default": 0.5, "min": 0.2, "max": 1.0},
      "suggested_note_budget": "round(tier_budget * per_note_cap_ratio) if tier has budget else null",
      "sort_order": ["match_score desc", "engagement_rate desc; null treated as -1.0"],
      "top_n": 20,
      "open_slots": {
        "trigger": "candidate_count < 20",
        "active_tiers": "tiers in [素人, 达人, KOL] whose tier_budget > 0",
        "base_target": "20 // len(active_tiers)",
        "remainder": "20 % len(active_tiers)",
        "remainder_assignment": "first active tiers in [素人, 达人, KOL] receive +1",
        "slots_needed": "max(target - matched_count_in_tier, 0)",
        "no_active_tiers": [],
        "policy": "never fabricate creators"
      }
    }
  }
}
```

1. 校验 M2/M6 的 `run_id`、状态、证据 ID、缺口、冲突和 `confidence`。任一硬前序缺失时停止业务输出并写 `blocked`。
2. 从 M6 `keyword_levels` 转换 `keyword_tracks`：`organic.core/long_tail/blue_ocean` 保持原词、意图和 lane；`search_ads`、`feed_ads` 仅从同版 M6 词项筛选，并沿用对应 `bid_note`。转换前后对关键词集合做差集检查，新增词集合必须为空。
3. 从 M2 `persona`、内容方向和品牌卖点提炼受众匹配词；不得把候选定向标签升级为账户事实。
4. 按 `plan_creator_tiers` 的确定性口径生成 `creator_plan`，保存工具输入、返回值、预算依据和尾差处理。各层合作预算、放大预算与 `amplification_pool_cny` 原样进入输出。
5. 对每条非 Mock 达人证据执行与 `match_creators` 同等的检查。匹配记录引用证据 ID，并核对身份 URL、报价、过往结果、受众标签、层级预算和档期状态。
6. 达人证据不足时，`matched_creators` 保持空或仅保留满足完整证据的条目；按层级输出 `open_slots`，把缺报价、缺过往结果、缺档期、受众不确定项写入 `human_review_items`。
7. 人工核验身份、报价、历史结果、受众适配、档期与品牌安全后，另行形成采购审批；M3 文本本身不是采购指令。

## 6. 输出契约

字段及父级关系复制自当前 `Module3Output`：

```json
{
  "output_contract": {
    "$": [
      "keyword_tracks",
      "creator_plan",
      "matched_creators",
      "open_slots",
      "human_review_items"
    ],
    "$.keyword_tracks": ["organic", "search_ads", "feed_ads"],
    "$.keyword_tracks.organic": ["core", "long_tail", "blue_ocean"],
    "$.keyword_tracks.organic.core[]": ["keyword", "intent", "lane"],
    "$.keyword_tracks.organic.long_tail[]": ["keyword", "intent", "lane"],
    "$.keyword_tracks.organic.blue_ocean[]": ["keyword", "intent", "lane"],
    "$.keyword_tracks.search_ads[]": ["keyword", "bid_note"],
    "$.keyword_tracks.feed_ads[]": ["keyword", "bid_note"],
    "$.creator_plan": ["tiers", "amplification_pool_cny"],
    "$.creator_plan.tiers[]": [
      "tier",
      "count",
      "collaboration_budget_cny",
      "spotlight_amplification_budget_cny"
    ],
    "$.matched_creators[]": [
      "name",
      "tier",
      "match_score",
      "suggested_note_budget_cny",
      "source"
    ],
    "$.open_slots[]": ["tier", "slots_needed"]
  }
}
```

`organic` 三层的最小数量分别为 2、4、2；`search_ads` 与 `feed_ads` 各 3–15 项；`matched_creators` 最多 20 项；`open_slots` 最多 3 项；`human_review_items` 为 1–6 项。`source` 写证据登记引用，不以模型判断替代原始来源。

## 7. module_state

```yaml
module_state:
  run_id: "与 M2、M6 相同"
  module: "M3"
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

`decisions` 保存 M6 词库版本、达人层级预算和匹配阈值；达人报价、过往结果和受众标签只有在输入证据完整时进入 `confirmed_facts`。开放名额和档期缺口进入 `unresolved_gaps`。

## 8. Grounding 自检

1. `keyword_tracks` 每个词是否都能回到同版 M6 证据 ID，且新增词差集为空？
2. 每个达人事实、报价、过往结果、受众匹配与档期状态是否绑定证据 ID 和采集时间？
3. `decision_source` 是否区分证据转录、确定性预算/匹配、策略假设、Mock 和人工确认？
4. `confidence` 是否反映 M2/M6 缺口、达人证据完整性和开放名额？
5. placeholder/Mock 是否完全排除在 `matched_creators` 与采购路径之外？

## 9. 降级

- M2 或 M6 缺失、`run_id` 不一致：只输出 `blocked` 状态和补数清单。
- M6 有缺口：继承关键词缺口，不增加词项，状态为 `completed_with_gaps`。
- 无达人证据：`matched_creators: []`，按层级列 `open_slots` 和导入蒲公英/CSV 的人工任务。
- 达人全为 Mock 或 placeholder：只作结构演示，不生成真实推荐，状态标记 `completed_with_gaps` 或 `awaiting_human_review`。
- 报价、过往结果、受众或档期缺失：候选留在证据核验队列，不进入合作承诺。

## 10. 人工拍板

人工必须确认：M6 规范词库版本及转换差集；达人实名与主页；最新报价、授权使用范围、历史结果口径、受众匹配、档期与履约风险；分层人数和预算；开放名额补采；所有采购、下单和合作承诺。未确认项同时保留在 `human_review_items` 与 `unresolved_gaps`。
