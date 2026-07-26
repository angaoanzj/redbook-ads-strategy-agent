# 使用说明书

> 配套文档：[技术架构](./TECHNICAL_ARCHITECTURE.md)｜[测试报告](./TEST_REPORT.md)｜[优化方向](./OPTIMIZATION_ROADMAP.md)｜[项目 README](../README.md)

本文档面向使用者：怎么跑、怎么填、每个模块要什么、输出怎么读、出问题时系统会怎么降级。
安装与启动命令见 [README](../README.md)，这里只补充 README 未展开的部分。

---

## 1. 三种运行方式

### 1.1 网页（推荐给非技术使用者）

启动服务后打开 http://127.0.0.1:8010/ 。首页表单流程：

1. 填品牌、品类、产品、卖点（每行一条）、价格与币种、目标用户、预算、周期、核心目标；
2. 可选导入：品类笔记 JSON、达人候选 CSV、人工粘贴热搜词、竞品链接、待识别竞品品牌；
3. 勾选运行开关：

   | 勾选项 | 对应接口参数 | 默认 |
   | --- | --- | --- |
   | 使用《数据需求.xlsx》2026 年 1—5 月历史基准 | 前端填充 `benchmark_evidence` | 关 |
   | 自动检索本地知识库 | `use_knowledge` | 开 |
   | 使用大模型润色最终报告 | `use_model` | 关 |
   | 启用六模块 LLM Agent 决策 | `use_agent_modules` | 关 |
   | 启用多子 Agent 模拟缺失数据 | `allow_mock` + `mock_seed` | 关 |

4. 生成后按结果页签阅读（有数据才显示对应页）：
   - **赛道与竞品深度分析**：对标样本、共性/空白、趋势与高峰、聚光大盘、投流识别、定向测试包；
   - **目标用户精准画像 / 关键词策略 / 关键词与达人匹配 / 聚光投流前置决策（含执行） / 全域预算与节奏规划**：对应六大模块正文；
   - **附加工具**：数据看板集成、多模态内容审核、A/B 测试方案、竞品投放监控；
   - **证据附录**：六模块原始结构与缺口列表；
5. 右上角显示会话短 ID、成功分析次数、最近报告 ID，可「新建会话」。
6. Markdown / JSON 可从结果区下载，便于粘贴进汇报文档。

### 1.2 API

最小调用（不调模型、不开 Agent）：

```bash
curl -X POST 'http://127.0.0.1:8010/analyze?use_model=false' \
  -H 'Content-Type: application/json' \
  -H 'X-Session-ID: demo-session-001' \
  -H 'Idempotency-Key: demo-analysis-001' \
  --data @examples/cookie_quartet_full_case.json
```

**启用六模块 LLM Agent 决策**（本项目的完整形态，需要 Analyzer Key）：

```bash
curl -X POST 'http://127.0.0.1:8010/analyze?use_model=false&use_agent_modules=true' \
  -H 'Content-Type: application/json' \
  -H 'X-Session-ID: demo-session-001' \
  -H 'Idempotency-Key: demo-analysis-002' \
  --data @examples/cookie_quartet_full_case.json
```

带 Mock 补足与可复现种子：

```bash
curl -X POST 'http://127.0.0.1:8010/analyze?use_model=false&allow_mock=true&mock_seed=demo-001' \
  -H 'Content-Type: application/json' \
  --data @examples/cookie_quartet.json
```

`/analyze` 的全部查询参数：

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `use_model` | bool | `true` | 是否调用聊天模型润色最终 Markdown（只影响文字，不改数字） |
| `use_knowledge` | bool | `true` | 是否自动检索本地品类知识库并合并证据 |
| `allow_mock` | bool | `false` | 是否允许多子 Agent 用带标识的模拟数据补足缺失字段 |
| `mock_seed` | str | 空 | Mock 可复现种子；相同种子生成相同模拟数据 |
| `use_agent_modules` | bool | `false` | 是否启用六模块 LLM Agent 决策 |
| `use_realtime_feed` | bool | `false` | 是否把 `/feeds/pull` 已落库的实时数据源条目合并进本次请求证据（当前为模拟源，见 [7.3](#73-实时数据源合规同构接口当前为模拟源)） |

请求头：`X-Session-ID`（会话标识）、`Idempotency-Key`（幂等键，相同键重放返回同一结果，
相同键配不同请求体返回 409）。上述**每一个查询参数都参与幂等哈希**
（`_analysis_request_hash()`），所以同一个 `Idempotency-Key` 配不同开关组合会返回 409，
不会串用结果。

其余接口一览：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| POST | `/creators/parse-csv` | 上传达人 CSV 转结构化候选 |
| GET | `/knowledge/status`、`/knowledge/search`、`/knowledge/rules`、`/knowledge/competitors` | 知识库状态、检索、规则、竞品识别 |
| POST | `/knowledge/import` | 导入规范化笔记数组 |
| POST | `/feeds/pull` | 拉取一批实时数据源条目并落库（当前为模拟源） |
| GET | `/feeds/status`、`/feeds/latest` | 数据源库存状态与最近批次；见 [7.3](#73-实时数据源合规同构接口当前为模拟源) |
| GET | `/sessions/{id}`、`/sessions/{id}/runs`、`/workflows/{sid}/{rid}`、`/state/status` | 会话、历史、工作流阶段、状态库计数 |
| POST | `/feedback`、`/backfilled-cases`、`/sessions/{id}/reset` | 报告反馈、案例回填、清空会话 |
| GET | `/board/{report_id}` | 加分项：已保存报告的看板投影 |
| POST | `/bonus/content-audit`、`/bonus/ab-test` | 加分项：单独调用内容审核 / A-B 矩阵 |

### 1.3 命令行 demo

```bash
# 离线：不联网、不调模型，演示工具层的校验与自我修正数据流
python demo_agent_loop.py --offline

# live：单模块端到端跑（需 Analyzer Key），打印工具轨迹 + 溯源结果 + 最终 JSON
python demo_agent_loop.py --module1
python demo_agent_loop.py --module2
python demo_agent_loop.py --module3
python demo_agent_loop.py --module4
python demo_agent_loop.py --module5
python demo_agent_loop.py --module6

# 全流程编排：按 M1→M2→M6→M3→M4→M5 跑六个模块，上游结论摘要注入下游
python demo_agent_loop.py --pipeline

# 叠加强模型 Critic 二审（可与 --moduleN 或 --pipeline 组合）
python demo_agent_loop.py --module4 --critic
python demo_agent_loop.py --pipeline --critic

# 不带参数：跑一个独立的预算决策 Agent Loop 演示（非模块契约）
python demo_agent_loop.py
```

`--critic` 是**可叠加 flag**，配合 `--moduleN` 或 `--pipeline` 使用。
它直接调 `run_critic()`，**不看 `AGENT_CRITIC_ENABLED`**——那个开关管的是 `/analyze`
链路（见 7.1），命令行 demo 只要有 Analyzer Key 就能跑二审。
`--offline` / `--pipeline` / `--moduleN` 之间互斥，命中第一个匹配项即执行。

`--offline` 的脚本序列里**故意**放了一个非法参数（达人分层比例合计 0.9），
用来演示工具如何把校验错误作为 tool result 返回、以及下一步如何修正——
真实循环里这一步由 LLM 自己完成。

模块 demo 默认读 `examples/cookie_quartet_full_case.json`（满证据）。
想看零证据降级路径，把 `demo_agent_loop.py` 里的 `EXAMPLE_FILE` 改回
`cookie_quartet_with_workbook_data.json`。

---

## 2. 输入字段总览

### 2.1 品牌任务字段（`CampaignRequest` 必填/常用部分）

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `brand_name` / `category` / `product_name` | 是 | 品牌、品类、产品名 |
| `selling_points` | 是 | 1–8 条核心卖点 |
| `price_min` / `price_max` / `currency` | 是 | 价带与币种；`price_max` 不得小于 `price_min` |
| `initial_audience` | 是 | 目标人群描述文本 |
| `total_budget_cny` | 是 | 总预算（元），> 0 |
| `spotlight_budget_cny` | 否 | 聚光预算；不得大于总预算。缺省时由 `compute_budget_split` 按目标推导 |
| `campaign_days` | 否 | 默认 30，范围 7–365 |
| `goal` | 是 | `awareness` / `engagement` / `search_growth` / `conversion` / `leads` / `live_traffic` |
| `analysis_days` | 否 | 默认 30，范围 7–180，用于知识库检索的时间窗 |
| `constraints` | 否 | 约束条款，会原样进入各模块 prompt |

### 2.2 证据字段

| 字段 | 消费方 | 缺失时的行为 |
| --- | --- | --- |
| `category_note_evidence` | 模块 1/2/3/4/6 | 自然格局留空、选题与关键词退化为待验证种子词、投放时段改按人群作息假设 |
| `competitor_evidence` | 模块 1 | 工具返回诚实的无竞品结论；`content_gaps` = 全部卖点；禁止推测预算 |
| `creator_evidence` | 模块 3/5 | `matched_creators` 如实为空，`human_review_items` 提示导入 CSV/蒲公英 |
| `benchmark_evidence` | 模块 1/3/4/5/6 | 出价区间、ROI、止损全部留 null 并标注证据缺口 |
| `trending_keyword_evidence` | 模块 6 | `data_source_status` 标注「待接入数据源」 |
| `account_violation_evidence` | 模块 1 | 风险预警退化为通用风险并标注「通用经验，待证据补充」 |
| `official_rule_evidence` | 模块 1 | 同上 |
| `owned_history_summary` / `owned_content_history` | 模块 5 | 联动规则的启动门槛保守设定并标注待验证 |
| `paid_risk_demo_scenarios` | 模块 4 | 仅作为 SOP 的示例信号，`is_mock` 恒为 true |

每条证据都带 `source_name` / `collected_at`，多数还有 `evidence_grade` 与 `is_mock`。
这些字段会一路传播到报告与证据附录，**请如实填写来源**——SSOT 的选用规则依赖它。

---

## 3. 六个模块

启用 `use_agent_modules=true` 后，每个模块的 Agent 结果挂在
`modules.<engine_key>.agent_decision`，结构为：

```json
{
  "output": { "...模块契约定义的结构..." },
  "grounding_check": { "passed": true, "mismatches": [] },
  "steps_used": 3
}
```

同级还有 `decision_source`：`llm_agent`（溯源通过）或 `llm_agent_ungrounded`（存在未溯源数字）。
未启用或 Agent 失败时，该模块只有确定性输出，没有 `agent_decision`。

| 模块 | `engine_key` | 便捷函数 |
| --- | --- | --- |
| 模块1 | `module_1_market_competitor` | `module_agents.module1.run_module1` |
| 模块2 | `module_2_audience_content` | `module_agents.module2.run_module2` |
| 模块3 | `module_3_keyword_creator` | `module_agents.module3.run_module3` |
| 模块4 | `module_4_spotlight_decision` | `module_agents.module4.run_module4` |
| 模块5 | `module_5_budget_pacing` | `module_agents.module5.run_module5` |
| 模块6 | `module_6_keyword_strategy` | `module_agents.module6.run_module6` |

### 3.1 模块1：赛道与竞品分析

- **用途**：判读赛道自然流量格局与付费格局、竞品共性与内容缺口、投放风险预警。
- **消费输入**：`category_note_evidence`（形态分布、平均互动、发布时段）、
  `competitor_evidence`、`benchmark_evidence` 中的 CPC/CPM/转化成本类指标、
  `account_violation_evidence`、`official_rule_evidence`。
- **调用工具**：`summarize_competitor_landscape`。
- **输出结构**：`organic_landscape`（样本量 / 热门形态 / 高峰时段假设 / 形式建议 / 边界声明）、
  `paid_landscape`（CPC/CPM/转化成本 + 各自来源 + 缺口说明）、
  `competitor_breakdown`（爆款共性 / 内容缺口 / 广告标识数 / 定向假设 / 预算推断口径）、
  `risk_alerts`（2–6 条）、`human_review_items`。
- **注意**：
  - 无笔记证据时 `hot_formats` 会是空数组，这是**正确行为**，不是 bug；
  - `paid_landscape` 的每个数字都必须有来源，没证据一律 null；
  - `targeting_hypotheses` 每条措辞必须含「假设」，不能当作竞品真实定向；
  - 广告标识数量以工具返回为准，模型不能改。

### 3.2 模块2：用户画像与内容策略

- **用途**：用户画像三维、聚光定向标签、三大内容方向（双评分）、15 个选题、素材筛选标准。
- **消费输入**：`selling_points`、`initial_audience`、`category_note_evidence`（主题词聚合前 12）。
- **调用工具**：`score_content_topics`。
- **输出结构**：`persona`（人口/行为/心理 + `targeting_tags` + `tag_status`）、
  `content_directions`（恰好 3 个，各带自然/付费评分）、`topics`（恰好 15 个）、
  `material_screening`（CTR 阈值 / 互动率阈值 / 补充规则）、`human_review_items`。
- **注意**：
  - 选题必须每方向 ≥3 个、方向名必须命中三方向之一，否则工具会点名拒绝；
  - 标 `suitable_for_paid=true` 的选题必须带 `paid_objective`（种草/成交/客资/直播引流）；
  - CTR/互动率阈值是模型在护栏内自选（0.03–0.30 / 0.02–0.20），不是固定值；
  - `tag_status` 会注明「标签需在聚光后台核对可用性」——定向标签必须去后台验一遍。

### 3.3 模块3：关键词策略与达人匹配

- **用途**：三类关键词赛道（自然分层 + 搜索广告词 + 信息流广告词）、达人分层预算、
  达人匹配名单与名额缺口。
- **消费输入**：笔记主题词、基准 CPC、`creator_evidence`、`spotlight_budget_cny`。
- **调用工具**：`build_keyword_tiers`、`plan_creator_tiers`、`match_creators`
  （无聚光预算时先 `compute_budget_split`）。
- **输出结构**：`keyword_tracks`（`organic.core/long_tail/blue_ocean` + `search_ads` + `feed_ads`）、
  `creator_plan`（各层合作预算与聚光放大预算 + 放大池）、`matched_creators`（≤20）、
  `open_slots`、`human_review_items`。
- **注意**：
  - 达人分层由粉丝数确定性判定：<1 万素人、<50 万达人、≥50 万 KOL、无粉丝数「待判定」；
  - 匹配分 = 55 + 10×（受众标签与关键词交集数），封顶 95——它是相对排序参考，不是绝对质量分；
  - **候选不足 20 位时返回 `open_slots` 而不是补名单**，这是刻意设计；
  - 达人粉丝与报价属公开样本估算，下单前必须蒲公英复核。

### 3.4 模块4：聚光投流前置决策

- **用途**：聚光账户结构、定向包组合、出价、搜索/信息流分配、每日投放时段、
  效果预估、五类风险预案。
- **消费输入**：`benchmark_evidence` 中的 CPC/CTR/CVR、聚光预算、价带（换汇后作 `aov_cny`）、
  笔记发布时段聚合、`paid_risk_demo_scenarios`。
- **调用工具**：`calc_bid_range`、`estimate_paid_performance`（必要时 `compute_budget_split`）。
- **输出结构**：`account_structure`（命名规则 + 2–4 个计划）、`targeting_packages`（恰好 3 个）、
  `bidding`（冷启动出价 + 放量规则）、`search_feed_split`、`daily_schedule`（2–4 段）、
  `forecast`（测试带宽 / 止损 CPC / 止损 CPA / ROI 点值与区间 / 状态）、
  `risk_playbook`（恰好 5 条）、`human_review_items`。
- **注意**：
  - `campaigns` 是**账户计划层级划分**（推广目标 × 版位），不是投放阶段；
    `budget_share` 是计划间分配，不要理解成预热/爆发/长尾节奏；
  - 出价字段名是 `bidding` 不是 `bid_plan`；
  - 缺 CPC/CTR/CVR 任一档时不输出 ROI，只给测试带宽与止损公式；
  - 测试带宽有最低下限（聚光 × 5%），低 CPC 场景下会触发；
  - `daily_schedule` 是**投放时段**，不是运营值班表；
  - ROI 依赖 CVR，若 CVR 是演示补全值，ROI 只是口径演示，不是效果承诺。

### 3.5 模块5：全域预算与节奏

- **用途**：总预算拆分、预热/爆发/长尾三阶段节奏、达人分层预算、出价区间、
  自然→付费联动规则、应急预案。
- **消费输入**：总预算、目标、基准 CPC、达人证据条数、自有历史摘要。
- **调用工具**：`compute_budget_split`、`plan_creator_tiers`、`calc_bid_range`。
- **输出结构**：`budget_split`、`phases`（恰好 3 期）、`creator_tier_plan`、`bid_plan`、
  `synergy_rules`（2–5 条）、`contingency_plans`（2–4 条）、`human_review_items`。
- **注意**：
  - 默认档为 转化/客资/直播 30% 自然、曝光/互动 50%、搜索增长 40%；
    模型可在 20%–70% 区间内自选，偏离默认档超过 ±0.10 时工具会置 `needs_review=true`；
  - 三阶段固定 20% / 60% / 20%，尾差归入爆发期，保证总额精确闭合；
  - 缺基准 CPC 时 `bid_plan` 对应字段是 null，不是 0。

### 3.6 模块6：关键词策略

- **用途**：三级词库、标题/正文/标签布局规则、三级预算比例、热点监控机制。
- **消费输入**：笔记主题词聚合、基准 CPC、`trending_keyword_evidence`。
- **调用工具**：`build_keyword_tiers`。
- **输出结构**：`keyword_levels`（core ≥2 / long_tail ≥4 / blue_ocean ≥2）、
  `layout_rules`（3–6 条，位置限标题/正文/标签）、`level_budget_split`（合计为 1）、
  `trending_monitor`（机制 / 跟进标准 / 数据源状态）、`human_review_items`。
- **注意**：
  - 关键词重复会被整体拒绝并列出重复词；
  - 缺基准 CPC 时各词 `bid_range_cny` 为 null，只保留倍率带文字说明；
  - 无合规实时热搜源时 `data_source_status` 必须是「待接入数据源」，
    此时任何「实时热搜」结论都不可采信。

---

## 4. 模型配置与切换

### 4.1 三个环境变量

Analyzer 通道（模块 Agent 决策 + 可选报告润色）：

```bash
export AGENT_ANALYZER_API_KEY=...
export AGENT_ANALYZER_BASE_URL=...
export AGENT_ANALYZER_MODEL=...
```

未设置时依次回退到 `AGENT_OPENAI_API_KEY` / `AGENT_OPENAI_BASE_URL` / `AGENT_OPENAI_MODEL`，
再回退到硅基流动默认值（`https://api.siliconflow.cn/v1` + `Qwen/Qwen3-8B`）。
另外 `model_config.load_dotenv_files()` 会读取**本项目目录**内的 `.env` 或 `course.env`
（见 `.env.example`），且**不覆盖**已经 export 的值；不依赖上级课程仓。

Embedding 通道（`AGENT_EMBEDDING_*`）已接入混合检索：分词关键字召回 + 向量召回。
配置 Key 后走远程 Embedding；未配置时自动降级本地向量，仍可完成混合排序。

### 4.2 切到 DeepSeek

```bash
export AGENT_ANALYZER_API_KEY=sk-...
export AGENT_ANALYZER_BASE_URL=https://api.deepseek.com
export AGENT_ANALYZER_MODEL=deepseek-chat
```

`deepseek-chat` / `deepseek-reasoner` 已被官方弃用，`_normalize_chat_model()` 会自动
归一化到 `deepseek-v4-flash` / `deepseek-v4-pro`，所以上面这样写不会 400。
另外 `chat_request_extras()` 会为 DeepSeek 自动附加 `thinking={"type":"disabled"}`——
V4 默认开启 thinking，多轮工具调用若不回传 `reasoning_content` 会 400，
关掉后 function calling 才稳定。

### 4.3 用 Qwen（硅基流动）

```bash
export AGENT_ANALYZER_API_KEY=sk-...
export AGENT_ANALYZER_BASE_URL=https://api.siliconflow.cn/v1
export AGENT_ANALYZER_MODEL=Qwen/Qwen3-8B
```

模型名含 `qwen` 或 base_url 含 `siliconflow` 时，`chat_request_extras()` 自动附加
`enable_thinking=false`。不关思考链会拖慢多轮工具调用，也更容易出现工具参数格式问题。
实测 Qwen3-8B 能跑通全链路，但策略文本质量不如 DeepSeek 稳定，
详见[测试报告的模型对比](./TEST_REPORT.md)。

### 4.4 Docker 下的配置

`docker-compose.yml` 已透传全部变量。运行前 export 即可：

```bash
export AGENT_ANALYZER_API_KEY=sk-...
export AGENT_ANALYZER_BASE_URL=https://api.deepseek.com
export AGENT_ANALYZER_MODEL=deepseek-chat
docker compose up -d agent
```

配置项里允许写行内注释（`MODEL=deepseek-chat # 说明文字`），
`_strip_inline_comment()` 会把 `#` 之后的内容剥掉，但会保留 URL 里的 `#`。

---

## 5. 容错行为说明

### 5.1 缺输入时的默认值

| 缺什么 | 系统怎么做 |
| --- | --- |
| 没给 `spotlight_budget_cny` | 先调 `compute_budget_split` 按目标默认档推导付费预算 |
| 没给 `organic_ratio` | 落到目标对应默认档（转化/客资/直播 0.30、曝光/互动 0.50、搜索增长 0.40） |
| 没给 `campaign_days` / `analysis_days` | 各取默认 30 天 |
| 没给基准 CPC | 出价、关键词出价区间、ROI 全部返回 null + 「待补数据」，并给出「用聚光账户实时建议价做首轮小预算测试」的替代动作 |
| 没给 CVR | 目标 CPA 用保守占位（CPC × 25，约 4% 点击转化假设），且**不输出 ROI** |
| 没给 CTR 或 CVR 任一档 | `forecast_status` 写明缺哪档，只给测试带宽与止损 |

### 5.2 证据缺口标注

`engine._evidence_gaps()` 逐项检查证据字段，产出 `evidence_gaps` 列表（字段 / 影响 / 建议来源），
并据此定 `data_confidence`：

- 无缺口且无 Mock 注入 → `high`
- 恰好 1 项缺口且无 Mock → `medium`
- 其余（含任何 Mock 注入）→ `low`

**Mock 补足不会抬高可信度**。报告首屏显示缺口数量，看板 KPI 有「证据缺口」一项。

### 5.3 Agent 失败与降级

降级链条：`LLM Agent 决策 → 确定性模块输出 → 证据缺口标注`。

| 情况 | 表现 |
| --- | --- |
| `use_agent_modules=true` 但 Key 缺失或为占位值 | trace 记 `{"stage":"agent_modules","status":"skipped","reason":"model_key_missing"}`，全部模块用确定性输出 |
| 单个模块 Agent 抛异常（超步数 / 修复轮用尽 / 网关失败） | trace 记 `{"stage":"agent_moduleN","status":"fallback","reason":...}`，**该模块**回退确定性输出，其它模块不受影响 |
| 模块 Agent 成功但溯源未过 | `decision_source=llm_agent_ungrounded`，报告显示「⚠️ 数字未溯源模块：N」，结果仍展示但需人工复核 |
| 网关瞬时故障（断连 / 超时 / 429 / 502-504） | 自动指数退避重试最多 3 次；仍失败才算模块失败 |
| `use_model=true` 但润色失败 | 返回确定性 Markdown，trace 记 `{"stage":"model_polish","status":"fallback"}` |

排查时优先看响应里的 `trace` 数组，它按阶段记录了每一步的状态与降级原因。

### 5.4 Mock 边界

开启 `allow_mock=true` 后，缺失字段由子 Agent 按种子补足，但必须满足：

1. 每个 Mock 对象带 `is_mock=true` / `evidence_grade=M` / `mock_seed` / 警告文案；
2. Mock 达人标记 `is_recommendation=false`，禁止当作真实推荐名单；
3. Mock 热搜标明「非实时热搜」，拒审台账标明「需替换真实导出」；
4. `data_confidence` 不会因 Mock 被抬到 `high`；
5. 真实证据始终优先，不会被 Mock 覆盖；
6. Mock 报告回填的案例被强制标记为 `demo_case`。

相同请求 + 相同 `mock_seed` 得到相同的模拟结果，便于复现与对比。
关闭 `allow_mock` 后恢复为空值 + 硬缺口。

**Mock 数据不得用于真实预算决策、达人下单或对外汇报。**

---

## 6. 加分项功能怎么用

四个加分项能力全部已接线，下面按代码实际行为描述。

### 6.1 多模态内容审核

- **自动执行**：每次 `/analyze` 都会由 `bonus_modules.build_bonus_modules()` 调用一次，
  输入取产品名（作标题）、卖点（作正文）与 `competitor_candidates`，
  结果落在 `modules.bonus_content_audit`。
- **单独调用**：

  ```bash
  curl -X POST http://127.0.0.1:8010/bonus/content-audit \
    -H 'Content-Type: application/json' \
    -d '{"title":"最好吃的曲奇","body":"全国第一蝴蝶酥","selling_points":["牛油香浓"],
         "image_urls":["https://example.com/a.jpg"],"competitor_names":["珍妮曲奇"]}'
  ```

- **LLM 也可调用**：工具名 `audit_note_content`，已注册在 `DEFAULT_REGISTRY`。
- **检测内容**：绝对化用语（最好/第一/顶级/100%/唯一…）、功效或医疗暗示
  （减肥/降脂/治疗/药用/抗癌/速效）、竞品提及。命中 high 即 `passed=false`。
- **边界**：图片/视频只返回 `pending_ocr` / `pending_frame_scan` 状态，
  **不做也不伪造视觉识别**。`evidence_boundary` 字段会原样说明这一点。

### 6.2 A/B 测试方案

- **自动执行**：从模块2 的内容方向（缺省用「场景痛点 / 产品证据 / 对比决策」）
  与模块4 的探测预算生成，结果落在 `modules.bonus_ab_test`。
- **单独调用**：

  ```bash
  curl -X POST http://127.0.0.1:8010/bonus/ab-test \
    -H 'Content-Type: application/json' \
    -d '{"directions":["场景痛点","产品证据","对比决策"],
         "title_variants_per_direction":2,"cover_variants_per_direction":2,
         "probe_budget_cny":1200,"min_clicks_per_cell":50}'
  ```

- **LLM 工具名**：`build_ab_test_matrix`。
- **输出**：正交矩阵（方向 × 标题变体 × 封面变体，示例 3×2×2 = 12 格）、
  每格 `scenario_ratio`、单格最小点击、每格预算、成功判定标准与决策规则。
- **注意**：`scenario_ratio` **仅用于情景比较，不进入正式预算汇总**；
  未达最小点击前禁止按单日波动宣布胜负；每个变体只能改标题或封面一个变量。

### 6.3 竞品投放监控

- **自动执行**：每次 `/analyze` 从模块1 的竞品结果构造当前快照，
  与状态库缓存的上次快照（key = `competitor_monitor` / `brand:<品牌名>`，TTL 7 天）对比，
  结果落在 `modules.bonus_competitor_monitor`，本次快照写回缓存。
- **LLM 工具名**：`monitor_competitor_ads`。
- **两种状态**：
  - `baseline`：无历史快照，做一次基线扫描（有广告标识笔记 → medium 预警；
    无竞品样本 → low 提示补 3–5 个对标账号；否则 → 基线就绪提示）；
  - `diff`：有历史快照，输出增量预警（广告标识笔记 +2 及以上 → high「疑似加大投放」；
    +1 → medium；出现新对标账号 → medium；无突变 → low「维持既定节奏」）。
- **边界**：**不是实时爬虫**，基于本次导入/知识库快照对比；
  广告标识与投放时长必须人工打开原笔记核验。

### 6.4 数据看板（在「附加工具」页签内）

- **网页**：生成报告后点「附加工具」→「数据看板集成」。
- **接口**：`GET /board/{report_id}`（报告需已保存在状态库中，否则 404）。
- **内容**：KPI（数据可信度 / 总预算 / 聚光预算 / 证据缺口数 / 本周唯一动作）、
  自然趋势曲线、搜索-信息流预算环图、预警列表（含内容审核风险与竞品监控预警）、
  动作表、A/B 矩阵前 12 格、各章节的「可执行/需复核」徽章；同页还有内容审核、A/B 方案与竞品监控。
- **注意**：看板是 `report_view` 的**投影，不新增任何事实**，也不接实时平台数据；
  导出以 Markdown / JSON 为准。`tools/dashboard.py` 不是 LLM 工具，是纯渲染函数。

---

## 7. 进阶功能

四项进阶能力都是**显式开启、失败降级**：不开就完全不影响原有行为，开了之后出问题
也只是少一块信息，不会阻断分析。落地背景与未实现子项见
[优化方向](./OPTIMIZATION_ROADMAP.md)。

### 7.1 Critic 二审：让强模型审策略文本

模块 Agent 产出通过契约校验之后，再交给一个（可以更强的）模型做一次**只审文本、
不审数字**的二审。数字已经由 `grounding_check` 溯源，Critic 被明令禁止质疑数字大小。

**两个环境变量**

```bash
export AGENT_CRITIC_ENABLED=1     # 取 1 / true / yes / on 才开启，默认关闭（成本考虑）
export AGENT_CRITIC_MODEL=...     # 可选：二审用的强模型名；不填就沿用 Analyzer 主模型
```

api_key 与 base_url **直接复用 Analyzer 通道**（`AGENT_ANALYZER_*`，可回退
`AGENT_OPENAI_*`），不需要配第三套 Key。模型名同样支持行内注释与废弃别名归一化。

**命令行试跑**

```bash
python demo_agent_loop.py --module4 --critic     # 单模块
python demo_agent_loop.py --pipeline --critic    # 全流程，逐模块打印 verdict
```

**API 里在哪看**：开启 `use_agent_modules=true` 且 `AGENT_CRITIC_ENABLED` 已开时，
二审结果挂在

```text
modules.<engine_key>.agent_decision.critic_review
```

同级还有布尔 `critic_rewritten`（本模块有没有因二审被重写过）。
`trace` 里多一条 `{"stage": "critic_moduleN", "status": "ok" | "degraded", "rewritten": bool}`；
未开启时既不调用也不写 trace。

**读懂返回**

```json
{
  "status": "ok",
  "report": {
    "verdict": "revise",
    "dimension_scores": {
      "evidence_citation": 7, "executability": 6,
      "compliance_wording": 8, "consistency": 9
    },
    "issues": [
      {"path": "account_structure.campaigns.0.placement",
       "severity": "high", "problem": "...", "suggestion": "..."}
    ],
    "summary": "一句话总评"
  }
}
```

- 四个维度各 1–10 分（10 最好）：**证据引用**（结论有没有指到具体证据，
  还是只写「结合市场情况」）、**可执行性**（有没有主体/条件/阈值/动作）、
  **合规措辞**（假设有没有被说成事实、有无绝对化宣称）、**一致性**
  （与输入目标、证据、上游模块结论是否自洽）；
- 除四个通用维度外，二审 prompt 还会带上**该模块专属的检查清单**
  （`MODULE_CRITIC_CHECKLISTS`，每个模块 3–5 条），
  比如模块4 会被专门问「campaigns 是不是被当成了投放阶段」
  「daily_schedule 是投放时段还是值班表」「调价用没用百分比」；
- `verdict` 只有 `pass` / `revise` 两种，`issues` 最多 10 条按严重度排序；
- `path` 用输出 JSON 的点路径定位问题字段。

**issues 会怎么影响输出**（`/analyze` 链路）

| 情况 | 系统怎么做 |
| --- | --- |
| 有 **high** severity | 触发**一轮定向重写**：把 high 问题作为「只修这些、别动已溯源数字」的上下文重跑该模块；成功则用新输出替换 `agent_decision`、重算 `decision_source`，剩余 medium/low 写进 `human_review_items`，trace 记 `critic_rewrite_moduleN / success`，`critic_rewritten=true` |
| 重写本身失败 | **回退原输出**，把全部 issues 写进 `human_review_items`，trace 记 `critic_rewrite_moduleN / fallback`，`critic_rewritten=false` |
| 只有 medium / low | 不重写，issues 以 `[Critic/<严重度>] <路径>: <问题> → <建议>` 追加进 `human_review_items`（去重，超 6 条时保留末尾以满足契约上限） |

所以开启二审后，`human_review_items` 里出现 `[Critic/...]` 开头的条目是正常的，
它们就是二审留给你的人工复核清单。

**成本提醒**：一次分析六个模块 = 六次二审；命中 high 的模块还会**再跑一遍模块 Agent**。
开之前先估算好 token 与耗时，这也是它默认关闭的原因。

**degraded 是什么意思**

```json
{"status": "degraded", "reason": "..."}
```

表示这次二审**没跑成**——缺 Key、网络异常、模型返回非法 JSON、契约校验两轮仍不过
等等都会走到这里。此时：

- 模块的 `agent_decision.output` **照常可用**，二审不是闸门，失败不阻断产出；
- `reason` 里是截断到 300 字的原因，按它排查（最常见是没配 Analyzer Key）；
- 不要把 degraded 读成「二审通过」——它是「没有二审结论」，
  也不会触发重写、不会往 `human_review_items` 里加任何东西。

### 7.2 全流程编排：模块之间开始传结论

**怎么跑**

```bash
python demo_agent_loop.py --pipeline
```

或走 API：`POST /analyze?use_agent_modules=true`——HTTP 链路上
`engine._attach_agent_modules()` 用的是同一套顺序与摘要函数。

**依赖顺序与理由**

```text
M1 赛道与竞品 → M2 人群与内容 → M6 关键词策略 → M3 达人匹配 → M4 聚光决策 → M5 预算统筹
```

不是数字顺序，是业务顺序：先判读赛道格局，才谈得上定人群与选题；
有了选题方向才好定关键词词库；有了词库和人群才能匹配达人；
达人和词库定了才能设计聚光账户结构与出价；最后由模块5 统筹全案预算与节奏。
只跑子集时仍按这个顺序重排。

**上游摘要机制**

- 每个模块跑完，编排层把它的结论压成一段 **≤600 字**的中文摘要
  （只取下游用得上的字段，例如给模块4 的是模块1 的竞品定向假设）；
- 摘要拼进下游模块的 user prompt 末尾，**只带最近 3 段**，避免 prompt 无限膨胀、
  上游细节稀释模型对本模块证据的注意力；
- **模块6 → 模块3 是例外**：词表必须逐词一致，摘要不够用，
  所以模块6 额外传一段 `【模块6共享词表】` 开头、上限 4000 字的**完整词表 JSON**
  （`keyword_levels` + `level_budget_split`），并明文要求模块3 直接复用、
  不要再调 `build_keyword_tiers` 另起一套；trace 记一条 `shared_keyword_handoff`；
- **上游失败不断链**：某模块抛异常时记一条 `failed` trace 后继续跑后续模块，
  下游只是少一段上游摘要，等价于改造前各模块独立执行的行为。

**在哪看效果**：`trace` 里每条 `agent_moduleN` 都带 `upstream_digest_chars`
（本模块收到多少字上游摘要）；`--pipeline` 的 `pipeline_trace` 还会打印
`digest_chars`（本模块产出的摘要长度）。

### 7.3 实时数据源：合规同构接口（当前为模拟源）

**先说边界。** 当前挂的是**模拟数据源**，不是真实热搜或真实竞品动态：

- 每一条 feed 数据都强制带 `is_mock=true`、`evidence_grade="M"`，
  `source_name` 带「模拟实时数据源」前缀；
- `M` 不属于 A–E 任何真实证据等级，因此**永远不会抬高 `data_confidence`**；
- 合并时同名热搜词、同名竞品**一律不覆盖**已有的真实证据；
- **不得**用它做真实预算决策、达人下单或对外汇报；没有真实合规趋势源时，
  模块6 的 `data_source_status` 仍应是「待接入数据源」。

这样设计的意义是接口先行：`FeedAdapter` 协议只有一个 `pull` 方法，
将来接官方开放能力或品牌授权 API 时只换 adapter，下面这些用法一行都不用改。

**三个端点**

```bash
# 1) 拉一批并落库（参数都可选；同 seed 生成同一批次序列，热度随批次升温）
curl -X POST 'http://127.0.0.1:8010/feeds/pull?seed=demo-2026&category=香港蝴蝶酥伴手礼&brand=曲奇四重奏&product_name=经典蝴蝶酥礼盒'

# 2) 看库存与数据源政策声明
curl 'http://127.0.0.1:8010/feeds/status'

# 3) 看最近的批次原文（limit 1–50，默认 5）
curl 'http://127.0.0.1:8010/feeds/latest?limit=3'
```

**持续拉取的守护脚本**

```bash
# 默认每 10 秒一批、共 6 批
python scripts/feed_daemon.py

python scripts/feed_daemon.py --interval 3 --count 20 --seed demo-2026
python scripts/feed_daemon.py --base-url http://127.0.0.1:8010 --category 香港蝴蝶酥伴手礼
```

它是纯客户端脚本（只用 httpx 打本地 HTTP，不 import 项目模块），
跑完会打印累计的 `/feeds/status`。

**把数据用起来**

```bash
curl -X POST 'http://127.0.0.1:8010/analyze?use_model=false&use_realtime_feed=true' \
  -H 'Content-Type: application/json' \
  --data @examples/cookie_quartet_full_case.json
```

合并发生在本地知识库检索**之前**，最多补 6 个热搜词 + 4 条竞品事件。
`trace` 里会多一条：

```json
{"step": "realtime_feed_merge", "merged_trending": 6, "merged_competitors": 2, "is_mock": true}
```

数据源出问题时这条 trace 带 `"status": "failed"` 与 `error_type`，本次分析
**退回「不合并」继续跑**，不会失败。数据库位置默认 `data/realtime_feed.db`，
可用环境变量 `XHS_FEED_DB` 覆盖。

### 7.4 评测跑分：改动前后有没有变好

`bench/` 是一套独立于主链路的回归评分工具（只依赖标准库，不 import engine）。

**两种跑法**

```bash
# 回放存档：离线，不需要模型 Key —— 日常回归用这个
python3 bench/run_bench.py --replay bench/fixtures/regression_outputs.json

# 真跑：调六模块流水线后立即评分，需要 Analyzer Key
python3 bench/run_bench.py --live --label "deepseek/prompt-2026-07"

# 评测矩阵：三个案例各真跑一次并各写一份报告，最后打印总表
python3 bench/run_bench.py --matrix

# 只打印不落盘
python3 bench/run_bench.py --replay bench/fixtures/regression_outputs.json --no-write
```

`--replay` / `--live` / `--matrix` 三选一。`--matrix` 的三个案例是
`full_evidence`（`cookie_quartet_full_case.json`，满证据）、
`workbook_partial`（`cookie_quartet_with_workbook_data.json`，有历史基准无笔记）、
`minimal`（`cookie_quartet.json`，极简）——用来看**证据越少时诚实分掉不掉**。

`--label` 会写进报告 `meta`，用来标记这次跑的是哪个模型 / 哪版 prompt。
`--request` 可换评测用的请求（默认 `examples/cookie_quartet_full_case.json`），
不变量需要它来核对预算与证据口径。

**四个维度怎么算（满分 100）**

| 维度 | 满分 | 判据 |
| --- | --- | --- |
| 溯源 grounding | 40 | `grounding_check.passed` 为 true 得 40，否则 0——没有中间态 |
| 诚实 honesty | 25 | 诚实标记命中率 × 25。每条标记给一组同义措辞，命中任一即算通过，避免评分退化成措辞考试 |
| 不变量 invariants | 25 | 无违规得 25，**每条违规扣 5 分**，扣到 0 为止 |
| 结构 structure | 10 | 关键路径命中率 × 10 |

总分是六个模块的算术平均。缺席的模块会被点名进 `missing_modules` 但不拉低平均；
不在断言集里的模块进 `unknown_modules`，同样不计入平均。

还有两项**只减分或只记录、不新增满分**的附加项：

- **文本分 text**（上限 15）：存档里带 `critic_review` 且 `status=ok` 时，
  按 high × 5 / medium × 1.5 从总分扣，扣满 15 为止。
  没有 Critic 记 `skipped`、二审降级记 `degraded`——**两种情况都不扣分**，
  所以离线回放基线依然是 100。
- **收敛 convergence**：按修复轮数记进 `detail`，**不改总分**，
  免得「合法满分」参照存档因为一次修复轮就掉分。

**报告在哪**：每次跑分写一个带 UTC 时间戳的目录

```text
bench/reports/<YYYYMMDDTHHMMSSZ>/report.json
bench/reports/<YYYYMMDDTHHMMSSZ>/report.md
```

markdown 里除了评分表还有「违规与缺口明细」（逐条点名是哪个不变量、
缺哪条诚实标记、缺哪条关键路径），以及与**上一份报告**的「较上次」分差列。

**怎么把真实跑的输出存档后 replay**

存档格式就是 `{module_name: result}`，`result` 是 `run_module_agent` 的返回；
也接受 `{"request": {...}, "modules": {...}}` 这种带请求的包装格式。

```python
import json
from models import CampaignRequest
from module_agents.orchestrator import run_pipeline

req = CampaignRequest.model_validate(
    json.load(open("examples/cookie_quartet_full_case.json", encoding="utf-8"))
)
outcome = run_pipeline(req)          # {"modules": {...}, "pipeline_trace": [...]}
json.dump(
    {"request": req.model_dump(mode="json"), "modules": outcome["modules"]},
    open("bench/fixtures/run_20260726.json", "w", encoding="utf-8"),
    ensure_ascii=False, indent=2, default=str,
)
```

之后就可以离线反复评分：

```bash
python3 bench/run_bench.py --replay bench/fixtures/run_20260726.json
```

`demo_agent_loop.py` 与 `/analyze?use_agent_modules=true` 响应里的
`modules.*.agent_decision` 是同构结构，同样可以存下来回放。

**典型用法**：改 prompt / 改契约 / 换模型之前跑一次基线，改完再跑一次，
把「较上次」那一列贴进变更记录。

---

## 8. 常见问题

**Q：勾了「启用六模块 LLM Agent 决策」，但报告里看不到 Agent 卡片？**
先看响应 `trace`：若有 `agent_modules / skipped / model_key_missing`，说明 Analyzer Key 没配；
若有 `agent_moduleN / fallback`，看 `reason` 与 `detail` 字段定位是超步数、修复轮用尽还是网关问题。

**Q：某个模块显示「存在未溯源数字，需人工复核」，能用吗？**
可以看，但要人工核对被标记的数字。`grounding_check.mismatches` 会给出具体路径与数值。
这通常意味着模型把工具算出来的数字改写了，或者写了一个工具没算过的数字。

**Q：为什么 `matched_creators` 少于 20 个？**
候选不足时系统**不补名单**，只在 `open_slots` 里说明每层还缺几个。导入更多达人证据即可。

**Q：报告里的 CPC 有两个不同的值？**
看报告的「基准指标 SSOT」小节：多来源同类指标会被标 `conflict` 并列出全部候选，
选用规则是「账户实测 / 数据需求来源优先，同优先级取采集时间最新」。
下游模块引用时必须注明来源。

**Q：能不能直接拿报告去投？**
不能。所有标注「需投手确认」的数字必须用聚光账户实时数据校准；
预算放量、达人下单、素材发布均需人工拍板。
