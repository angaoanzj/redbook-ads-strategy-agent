# 测试报告：曲奇四重奏全流程（Agent 化重构后）

> 配套文档：[技术架构](./TECHNICAL_ARCHITECTURE.md)｜[使用说明书](./USER_GUIDE.md)｜[优化方向](./OPTIMIZATION_ROADMAP.md)｜[数据来源记录](./QUARTET_DATA_PROVENANCE.md)

## 1. 测试目标

验证控制权反转后的架构在真实品牌案例上是否成立，具体回答三个问题：

1. LLM 在 Agent Loop 里能否稳定收敛（步数、修复轮、工具拒绝后能否自愈）？
2. 护栏体系（工具参数校验 + 输出契约 + 数字溯源）能否拦住数字类错误与编造？
3. 输出到底有多少可以直接落地，多少必须标注待人工核验？

## 2. 测试环境

### 2.1 运行环境

| 项 | 配置 |
| --- | --- |
| 容器 | `Dockerfile` 基于 `python:3.13-slim`，非 root 用户，`./data:/app/data` 卷持久化 |
| 服务 | `uvicorn main:app --host 0.0.0.0 --port 8010`（不启用 reload） |
| 依赖 | `fastapi==0.136.1`、`uvicorn[standard]==0.46.0`、`httpx==0.28.1`、`pydantic==2.11.4`、`python-multipart==0.0.20` |
| 持久化 | `data/xhs_knowledge.db`（证据库 + FTS5）、`data/agent_state.db`（会话/checkpoint/缓存/反馈） |
| Agent 参数 | `max_steps=10`（模块4 为 16）、`max_repair_rounds=2`、网关重试 3 次指数退避、单请求超时 180s |

### 2.2 被测模型

| 代号 | 模型 | 网关 | 请求特调 |
| --- | --- | --- | --- |
| 模型 A | `Qwen/Qwen3-8B` | 硅基流动 `https://api.siliconflow.cn/v1` | `enable_thinking=false` |
| 模型 B | `deepseek-chat` 通道 | DeepSeek `https://api.deepseek.com` | `thinking={"type":"disabled"}` |

> 说明：`model_config._normalize_chat_model()` 会把已废弃的 `deepseek-chat` 归一化到
> 当前可用模型名 `deepseek-v4-flash`（`deepseek-reasoner` → `deepseek-v4-pro`），
> 因此配置里写 `deepseek-chat` 不会 400，实际请求发的是归一化后的模型名。
> DeepSeek V4 默认开启 thinking，多轮工具调用若不回传 `reasoning_content` 会 400，
> 所以模块 Agent 循环里显式关闭 thinking 以保证 function calling 稳定。

### 2.3 测试数据集

`examples/cookie_quartet_full_case.json`（满证据案例）：

| 项 | 内容 |
| --- | --- |
| 品牌/商品 | 曲奇四重奏（香港蝴蝶酥伴手礼）／经典－原味蝴蝶酥礼盒 |
| 定价 | 228 HKD（`aov_cny` 需按参考汇率 ×0.92 换算，约 209.76 元，演示值非牌价） |
| 预算 | 总预算 100,000 元，其中聚光 70,000 元，周期 30 天，目标 `conversion` |
| 品类笔记 | 40 条（图集 39 条 / 视频 1 条） |
| 竞品 | 2 条（奇华、珍妮曲奇；均为图集，互动缺失，广告标识分别为未知与 false） |
| 达人 | 8 位（`examples/creators_cookie_quartet.csv` 同源，粉丝 9,000–55,000） |
| 趋势词 | 4 个（含风险词「最好吃的曲奇」用于降权验证） |
| 违规台账 | 3 条（绝对化用语 5 次 / 食品功效暗示 3 次 / 未披露商业合作 2 次） |
| 基准指标 | 7 条，来源《数据需求.xlsx》2026 年 1—5 月加权 |

基准指标明细（供后续数字核对）：

| 指标 | 值 | 单位 | 来源 |
| --- | --- | --- | --- |
| `cpc` | 0.3005181259 | CNY/click | 数据需求.xlsx／投流数据／1—5 月加权 |
| `ctr` | 0.1604600541 | ratio | 同上 |
| `cpm` | 48.22115472 | CNY/1000 imp | 同上 |
| `cost_per_interaction` | 2.895544125 | CNY/interaction | 同上 |
| `organic_content_ctr` | 0.2047736626 | ratio | 数据需求.xlsx／内容数据 |
| `organic_interaction_rate` | 0.0207233251 | ratio | 同上 |
| `cvr` | 0.012 | ratio | **演示补全值**，`is_mock=true`、`evidence_grade=M`，标注「待投手确认」 |

### 2.4 复现命令

```bash
cd /Users/llan/Documents/xiaohongshu-agent

# 1) 自动化测试
docker compose run --rm agent python -m unittest discover tests

# 1b) 只跑本轮优化方向落地的测试（108 个方法，离线可跑）
docker compose run --rm agent python -m unittest \
  tests.test_critic tests.test_orchestrator tests.test_bench \
  tests.test_realtime_feed tests.test_calibration

# 1c) 回归评分基线（离线回放，期望总分 100/100）
docker compose run --rm agent python bench/run_bench.py \
  --replay bench/fixtures/regression_outputs.json --no-write

# 2) 离线工具层演示（不联网、不调模型）
docker compose run --rm agent python demo_agent_loop.py --offline

# 3) 单模块 live 跑（需 Analyzer Key）
python demo_agent_loop.py --module1   # --module2 ... --module6

# 4) 端到端（六模块 Agent 挂载）
curl -X POST 'http://127.0.0.1:8010/analyze?use_model=false&use_agent_modules=true' \
  -H 'Content-Type: application/json' \
  --data @examples/cookie_quartet_full_case.json
```

### 2.5 自动化测试基线

| 项 | 数量 |
| --- | --- |
| 测试文件 | 29 |
| 测试方法总数 | 332 |
| 沙盒（Python 3.10）实跑通过 | 280 |
| 沙盒无法导入的测试模块 | 7 个模块 / 52 个测试方法 |

7 个 import error 全部指向同一个既有限制：`report_view.py` 使用了 Python 3.12+ 才允许的
f-string 写法（表达式部分含反斜杠），Python 3.10 解析失败，连带 `engine` / `main` 无法导入。
受影响模块为 `test_engine`（15）、`test_report_view`（10）、`test_api_state`（9）、
`test_bonus_modules`（6）、`test_mock_data_files`（5）、`test_mock_agents`（4）、
`test_api_mock`（3）。
项目实际交付环境是 `python:3.13-slim` 容器，这 7 个模块在容器内可正常导入运行；
上表的 280/332 是**本轮 3.10 沙盒的实测值**，不代表 Docker 下的结果。

> 口径说明：332 是 `tests/` 下全部 `test_*.py` 里 `TestCase` 子类的 `test*` 方法总数，
> 与 `python -m unittest discover tests` 在 3.13 容器内的收集口径一致。
> 本轮优化方向落地共新增 5 个测试文件、108 个测试方法（详见第 7 节）。

按测试文件的覆盖分布：

| 覆盖面 | 文件 | 方法数 |
| --- | --- | --- |
| 零代码 SOP 文档一致性 | `test_no_code_docs.py` | 46 |
| 评测基准集与回归评分 | `test_bench.py` | 35 |
| 实时数据源接入层 | `test_realtime_feed.py` | 27 |
| 模块间依赖传递编排 | `test_orchestrator.py` | 25 |
| 报告 Agent 视图与 SSOT | `test_report_agent_view.py` | 22 |
| 强模型 Critic 二审 | `test_critic.py` | 18 |
| 工具层护栏（预算/出价/Loop 重试） | `test_agent_tools.py` | 13 |
| 工具层护栏（预估/关键词） | `test_forecast_keyword_tools.py` | 12 |
| 工具层护栏（竞品/选题/达人） | `test_competitor_topic_creator_tools.py` | 12 |
| 六个模块 Agent 契约与溯源 | `test_module1..6_agent.py` | 26 |
| 引擎/报告/接口/Mock/知识库/状态/校准等 | 其余 14 个文件 | 96 |

模块 Agent 测试全部用 `httpx.MockTransport` 注入脚本化模型响应，不依赖真实网关，
因此「工具调用 → 契约校验 → 修复轮 → 溯源」的整条链路是可回归的。

## 3. 六模块逐个测试记录

以下 live 记录来自模型 B（DeepSeek 通道）对满证据案例的复跑；模块5 另附模型 A 的首跑记录。

### 3.1 模块1：赛道与竞品分析

| 指标 | 结果 |
| --- | --- |
| 收敛步数 | 2 步 |
| JSON 修复轮 | 0 |
| 溯源结果 | 通过（`competitor_breakdown.ad_labeled_count` 与工具返回一致） |
| 工具调用 | `summarize_competitor_landscape` × 1，一次通过 |

代表性输出与核对：

- `organic_landscape.sample_size = 40`，与 `_aggregate_organic()` 的聚合一致；
  `hot_formats` 取图集（39 条，占比 97.5%），平均互动 **695.03**，与代码聚合值逐位吻合。
- `peak_hour_hypothesis` 引用「早间 06-11 时段 22 条 / 40 条」，与
  `_evidence_aggregation.aggregate_time_slots()` 的首位桶（22 条 / 互动 14,528）一致，
  并按契约要求写成「假设」而非结论。
- `paid_landscape` 只取证据数字并逐个带来源；演示补全的 CVR 被正确标注为
  「待投手确认」，同时进入 `risk_alerts` / `human_review_items`。
- `boundary_note` 声明本样本不等于全平台大盘（契约 `min_length=1` + 铁律 5）。
- 竞品部分：2 条证据全部转录，`ad_labeled_count=0`，`budget_inference_policy`
  原样采用工具返回的「无广告标识证据：禁止推测竞品预算」。

### 3.2 模块2：用户画像与内容策略

| 指标 | 结果 |
| --- | --- |
| 收敛步数 | 3 步 |
| JSON 修复轮 | 0 |
| 溯源结果 | 通过（三方向双评分 + 两个筛选阈值均来自工具） |
| 工具调用 | `score_content_topics` × 2：首次被拒 → 自我修正后通过 |

代表性输出与核对：

- 15 个选题全部落在三个方向内、每方向 ≥3 个，且所有 `suitable_for_paid=true` 的选题
  都带了合法的 `paid_objective`（种草/成交/客资/直播引流）——这正是首次被拒的原因，
  工具在 `details` 里点名了缺目标的选题标题，模型据此补全后通过。
- 素材筛选阈值：CTR 0.08、互动率 0.05。两者都落在工具护栏内
  （`ctr_threshold` 0.03–0.30、`engagement_threshold` 0.02–0.20），属于模型在护栏内的自选值，
  而非代码写死的默认档（默认为 0.10 / 0.07）。这是控制权反转生效的直接证据。
- `tag_status` 按契约注明「标签需在聚光后台核对可用性」。

### 3.3 模块3：关键词策略与达人匹配

| 指标 | 结果 |
| --- | --- |
| 收敛步数 | 5 步 |
| JSON 修复轮 | 0 |
| 溯源结果 | 通过 |
| 工具调用 | 4 次全部一次通过，核心为 `build_keyword_tiers` → `plan_creator_tiers` → `match_creators` |

代表性输出与核对：

- **诚实输出达人缺口**：8 位候选中 7 位粉丝在 1 万–50 万区间被分到「达人」层、
  1 位（9,000 粉）分到「素人」层，KOL 层为 0。`match_creators` 按 Top 20 名额
  在三层间均分（7/7/6）后返回 `open_slots = [素人缺 6, KOL 缺 6]`。
  模型如实照抄了这个缺口，**没有编造名单去凑满 20 位**，并在 `human_review_items`
  写明需导入蒲公英/CSV 后补齐。
- 三档关键词出价严格等于基准 CPC `0.300518` × 固定倍率带
  （蓝海 0.6–0.8、信息流 0.7–1.0、搜索高意向 1.0–1.3 等），倍率带由代码写死、LLM 不可调。
- 关键词去重、各级数量下限（core≥2 / long_tail≥4 / blue_ocean≥2）、三级预算比例合计为 1
  均由工具校验通过。

### 3.4 模块4：聚光投流前置决策

| 指标 | 结果 |
| --- | --- |
| 收敛步数 | 2 步 |
| JSON 修复轮 | 0 |
| 溯源结果 | 通过（出价、测试带宽、止损、ROI 全部对上工具返回） |
| 工具调用 | `calc_bid_range`、`estimate_paid_performance` |

代表性输出与核对（可用工具常量逐项复算）：

| 输出 | 值 | 复算 |
| --- | --- | --- |
| ROI 点值 | 7.38 | `(1/0.3005181259) × 0.012 × 209.76 − 1 = 7.376` |
| ROI 区间 | [5.16, 8.85] | `7.376 × 0.7` / `7.376 × 1.2` |
| 止损 CPC | 0.45 | `0.3005181259 × 1.5` |
| 止损 CPA | 30.05 | 目标 CPA `0.3005/0.012 = 25.04` × 1.2 |
| 测试带宽 | 3,500 | `min(70000×0.15, 25.04×20×1.5) = 751` → 触发下限 `70000×0.05` |

- `placement` / `objective` 全部落在聚光枚举内（搜索推广 / 信息流推广 / 搜索+信息流；
  产品种草 / 商品成交 / 客资收集 / 直播引流），`budget_share` 合计为 1 且不再照抄阶段节奏。
- `daily_schedule` 引用证据区的高互动时段与互动数，不再是运营值班表。
- `scaling_rules` 的调价动作全部用百分比表述，无「X 倍」歧义写法。
- 5 条风险预案覆盖冷启动失败 / 成本过高 / 流量跑不动 / 拒审 / 衰退，症状引用了
  本案例的止损线与测试带宽数字。

### 3.5 模块5：全域预算与节奏

模型 A（Qwen3-8B）首次 live 跑：

| 指标 | 结果 |
| --- | --- |
| 收敛步数 | 6 步 |
| JSON 修复轮 | 0 |
| 工具调用 | `compute_budget_split`、`plan_creator_tiers`、`calc_bid_range`；**出价参数出现一次自我修正** |

出价参数的自我修正是本轮最典型的护栏样本：模型首次提交的倍率区间越出
`cold_start` 的 0.8–1.3 护栏，工具返回
「`cold_start` 阶段倍率护栏为 0.8–1.3，当前 X–Y 越界；`cold_start` 请改用 0.9–1.1」，
模型下一步据此改正并通过。整个过程没有人工介入，也没有中断循环。

预算数学由工具保证：自然 30,000 + 聚光 70,000 = 100,000（`arithmetic_check`），
三阶段付费预算按 20% / 60% / 20% 拆分且尾差归入爆发期，总额精确闭合。

### 3.6 模块6：关键词策略

本轮**未做 live 复跑记录**，覆盖来自离线回归：
`test_module6_agent.py` 3 个用例（工具调用后产出合法 JSON、损坏 JSON 触发修复轮、
篡改三级预算比例被溯源标记）与 `test_forecast_keyword_tools.py` 中
`build_keyword_tiers` 的 6 个护栏用例（重复词拒绝、比例合计不为 1 拒绝、
各级数量不足拒绝、无基准 CPC 出价留空、倍率带正确）。
契约层强制：无合规实时热搜源时 `trending_monitor.data_source_status`
必须标注「待接入数据源」。

## 4. 「发现 - 修复 - 验证」问题台账

| # | 问题 | 发现方式 | 根因 | 修复 | 验证证据 |
| --- | --- | --- | --- | --- | --- |
| 1 | 模块4 聚光计划出现 `placement="自然内容"` | 模型 A 模块4 首跑人工读输出 | 契约用自由字符串，prompt 未区分「聚光计划版位」与「内容形态」 | `placement` 收紧为 Literal 枚举（搜索推广/信息流推广/搜索+信息流）+ `check_all_spotlight_paid` 校验器 + 铁律 3a | `test_module4_agent.test_placement_natural_content_rejected` |
| 2 | 模块4 `objective` 出现「品牌曝光/品牌沉淀」等非聚光目标 | 同上 | 同上 | `objective` 收紧为 Literal 枚举（产品种草/商品成交/客资收集/直播引流） | `test_module4_agent.test_objective_brand_exposure_rejected`、`test_valid_enum_fields_accepted` |
| 3 | 模块4 `budget_share` 照抄阶段节奏 0.2/0.6/0.2 | 同上 | campaigns 是「账户计划层级划分」，模型误解为投放阶段 | 铁律 3a 明确 campaigns ≠ 投放阶段并禁止照抄阶段比例；保留 `check_shares` 合计为 1 的硬校验 | 模型 B 复跑：三条计划按目标×版位拆分、合计为 1；`AccountStructure.check_shares` |
| 4 | 模块4 投放时段输出成「总结当日数据/准备次日策略」运营值班表 | 同上 | 证据区没给时段聚合，模型只能自由发挥 | 抽出 `_evidence_aggregation.aggregate_time_slots()` 供模块1/4 共用同一时段桶口径，聚合结果写进 user prompt 证据区；铁律 3b 禁值班表 | 模型 B 复跑：`daily_schedule` 引用证据时段与互动数；模块1 与模块4 时段口径一致 |
| 5 | 调价动作写成「0.1 倍」，歧义（涨还是降？） | 同上 | 契约未限定调价表述 | `scaling_rules` 字段 description 强制百分比表述 + 铁律 3c | 模型 B 复跑：调价全部百分比。**注意**：这是 prompt + 字段描述级约束，未做正则硬校验 |
| 6 | 首轮测试带宽塌缩到 ¥225（占聚光 0.32%），不可执行 | 模型 A 模块4 首跑核对数字 | 无 CVR 时目标 CPA 用占位公式 `CPC×25`；本案例 CPC 仅 0.30，`CPA×20×1.5 = 225` 远小于聚光×15% | 新增 `TEST_BUDGET_FLOOR_RATIO = 0.05`，测试带宽取 `max(计算值, 聚光×5%)`，并在 `test_budget_basis` 里注明已触发下限 | `test_forecast_keyword_tools.test_test_budget_floor_triggered`；满证据复跑 ¥225 → **¥3,500** |
| 7 | 零证据运行时 `hot_formats` 契约 `min_length=1` 逼模型编造「图文/短视频/合集 avg 0.0」 | 用 `cookie_quartet_with_workbook_data.json`（无笔记证据）跑模块1 | 契约反噬：非空约束在无证据时把「诚实留空」变成非法输出 | `hot_formats` 改为 `min_length=0`；铁律 0 明令无笔记证据必须留空；user prompt 在无证据分支直接告知留空 | `test_module1_agent.test_empty_hot_formats_allowed` |
| 8 | 零证据运行时竞品工具 `min_length=1` 逼模型编造带假 URL 的竞品条目 | 同上 | 同为契约反噬 | `CompetitorLandscapeArgs.competitors` 改为 `min_length=0`，并在工具内加零竞品诚实分支（`content_gaps` = 全部卖点、`ad_labeled_count=0`、预算政策=禁止推测） | `test_competitor_topic_creator_tools.test_empty_competitors_returns_honest_result`、`test_module1_agent.test_zero_evidence_run_with_empty_competitors` |
| 9 | LLM 把 `estimate_paid_performance` 的 `baseline_cpc_source` 误传给 `calc_bid_range` | 模块4 live trace 里出现参数校验失败 | 两个工具的来源字段名不同（`baseline_source` vs `baseline_cpc_source`），模型容易串台 | 两个工具各加 `model_validator(mode="before")` 做双向别名兼容（仅在目标字段缺失时回填，不覆盖已填值），并在 tool description 里写明 | `test_agent_tools.test_accepts_baseline_cpc_source_alias`、`test_forecast_keyword_tools.test_accepts_baseline_source_alias_for_cpc` |
| 10 | 硅基流动网关偶发 `RemoteProtocolError` 断连，整轮 Agent 失败 | 模型 A 多次 live 跑 | 网关瞬时故障，循环无重试 | `AgentLoop._chat()` 加可重试异常集（RemoteProtocolError/各类超时/ConnectError/PoolTimeout）+ 状态码白名单 429/502/503/504 + 3 次指数退避；其余 4xx 直接抛错并带响应体 | `test_agent_tools.test_retries_remote_protocol_error_then_succeeds`、`test_exhausted_retries_raise_agent_loop_error` |
| 11 | 加了重试仍不稳定，模型 A 的策略文本质量也不稳 | 连续 live 跑观察 | 8B 模型 + 网关双重因素 | 借助 `model_config` 双通道把 Analyzer 切到 DeepSeek，业务代码零改动；`chat_request_extras()` 为 DeepSeek 关 thinking 以稳住多轮 function calling | 模型 B 四模块复跑全部收敛（见第 3 节）；`test_model_config.test_deepseek_extras_disable_thinking`、`test_dual_channel_separation` |
| 12 | demo 默认用零证据 example，模块1/2/3 演示出来是空壳 | 跑 `demo_agent_loop.py --module1` | `EXAMPLE_FILE` 指向 `cookie_quartet_with_workbook_data.json` | 默认切到 `cookie_quartet_full_case.json`，并在注释里保留切回零证据路径的方法 | `demo_agent_loop.EXAMPLE_FILE` 现指向满证据案例；模块1/2/3 演示可读出真实聚合 |
| 13 | 报告中同时出现 CPC 0.30（账户加权实测）与 1.60（`demo_agent_loop` 的演示 prompt 值），引发口径疑问 | 交叉阅读报告与 demo 输出 | 没有基准指标的单一事实源，多来源同类指标各说各话 | `report_agent_view.build_benchmark_ssot()`：按 CPC/CPM/CTR/CVR/conversion 分类归组，多来源标 `conflict`，选用规则为「来源名含账户/数据需求/实测者优先，同优先级取 `collected_at` 最新」，并在报告里渲染候选与选用理由 | `test_report_agent_view.test_double_cpc_conflict_selects_by_source_priority`、`test_selects_latest_when_no_priority_source`、`test_missing_collected_at_degrades` |

## 5. 准确性与实用性评估

### 5.1 可直接落地的结论

| 结论 | 模块 | 为什么可落地 |
| --- | --- | --- |
| 自然 30,000 / 聚光 70,000 拆分与预热 20% / 爆发 60% / 长尾 20% | 5 | 金额由 `compute_budget_split` 计算，`arithmetic_check` 保证闭合，尾差归爆发期 |
| 达人分层合作预算、单人报价参考、聚光二次放大预算 | 3/5 | 由 `plan_creator_tiers` 计算，比例合计必须为 1 |
| 冷启动出价区间（基准 CPC × 0.9–1.1） | 4/5 | 倍率护栏写死，基准 CPC 有来源；仍需以账户实时建议价校准 |
| 首轮测试带宽 ¥3,500 与止损公式（CPC>基准×1.5 或 CPA>目标×1.2，且曝光≥3000 或点击≥100） | 4 | 常量写死不可调，公式可复算 |
| 账户结构（计划=推广目标×版位）与三个定向包 | 4 | 枚举 + `budget_share` 合计为 1 硬校验 |
| 15 个选题矩阵与素材筛选阈值 | 2 | 结构由 `score_content_topics` 校验，付费选题必须带合法目标 |
| 三级词库、去重与各级数量下限、出价倍率带 | 3/6 | 工具校验通过后才允许写入最终 JSON |
| 达人名额缺口如实输出（素人缺 6 / KOL 缺 6） | 3 | 不足名额不编造，是防幻觉能力的正面证据 |
| 五类投流问题 SOP | 4 | 恰好 5 条契约约束 + 症状引用本案例数字 |

### 5.2 必须标注待人工核验的结论

| 结论 | 模块 | 待核验原因 |
| --- | --- | --- |
| ROI 7.38 与区间 [5.16, 8.85] | 4 | 依赖演示补全的 CVR 0.012（`is_mock=true`）与价带中值换汇；未计入退货、归因窗口与版位差异 |
| 目标 CPA 25.04 / 止损 CPA 30.05 | 4 | 同样由演示 CVR 推导 |
| 高互动时段假设（早间 06-11） | 1/4 | 仅 40 条样本、22 条落在该桶，需用聚光分时报表确认 |
| 竞品共性与内容缺口 | 1 | 2 条竞品样本，广告标识与投放时长必须人工打开原笔记核验 |
| 8 位达人的粉丝数与报价 | 3 | 公开样本估算/演示值，下单前必须蒲公英复核档期与异常粉 |
| 聚光定向标签与人群包 | 2 | `tag_status` 已注明需在聚光后台核对标签可用性 |
| 热搜/趋势词跟进 | 6 | 无合规实时热搜源，`data_source_status` 标注「待接入数据源」 |
| 工作簿指标的平台导出口径 | 全案 | 原表未注明导出来源，需数据负责人确认 |

### 5.3 仍禁止当作事实的项

- 未确认广告标识就说「竞品正在投流」；
- 由点赞/互动反推竞品预算（工具在无广告标识证据时直接返回「禁止推测竞品预算」，
  有标识也只给需人工核验的口径文本、不吐任何数字）；
- 未接入官方或合规 API 时的「实时热搜榜」；
- 把官方规则条文列表直接叫作「赛道高频违规榜」；
- 把 `scenario_ratio`（A/B 情景比较用）写进正式预算汇总。

### 5.4 护栏拦截效果（定性结论）

不给量化拦截率——本轮 live 跑次数有限，任何百分比都不具统计意义。可以确定的是：

- **数字类错误 100% 被拦截或被标记**。两代模型的所有数字类问题（出价倍率越界、
  预算比例不为 1、选题缺投放目标、测试带宽塌缩、误传字段名）都在三处之一被捕获：
  工具参数校验（返回 error 供自愈）、输出契约校验（触发修复轮）、数字溯源（标 mismatch 并降级）。
  没有出现「模型自己编了个数字、系统照单全收」的情况。
- **文本类质量问题不被拦截**。台账第 1–5 项（版位写成自然内容、投放时段写成值班表、
  调价写成 X 倍）本质是语义错误而非数字错误，护栏当时抓不到，全部靠人工读输出发现，
  修复方式是「收紧契约枚举」或「加 prompt 铁律 + 字段描述」。
  这是**本轮 live 记录当时**的架构短板；对应的强模型 Critic 二审已在本轮落地
  （见第 7 节与[优化方向](./OPTIMIZATION_ROADMAP.md)第 2 项），
  但落地后尚未补做 live 复跑，因此上述定性结论未随之更新。
- **零证据路径的诚实性依赖契约设计**。台账第 7、8 项说明：过强的非空约束会
  反向逼模型编造。「允许为空 + 工具内诚实分支 + prompt 明示留空」三件套齐了，
  模型才会老实说「没有」。

## 6. 模型对比实录

| 维度 | 模型 A：Qwen3-8B（硅基流动） | 模型 B：DeepSeek 通道 |
| --- | --- | --- |
| 收敛性 | 模块5 首跑 6 步收敛，出价参数出现一次自我修正 | 模块1 2 步 / 模块2 3 步 / 模块3 5 步 / 模块4 2 步 |
| 修复轮 | 未触发 JSON 修复轮 | 四模块均 0 修复轮 |
| 工具调用准确度 | 偶发倍率越界、字段名串台（`baseline_cpc_source` 误传）；模块4 因此把 `max_steps` 提到 16 | 模块2 一次工具拒绝后自我修正，其余一次通过 |
| 策略文本质量 | 不稳：版位写「自然内容」、`budget_share` 照抄阶段节奏、时段写成运营值班表、调价写「0.1 倍」 | 稳定：枚举正确、时段引用证据互动数、调价全百分比 |
| 网关稳定性 | 偶发 `RemoteProtocolError` 断连；加指数退避重试后仍不稳 | 本轮未出现网关断连 |
| 结论 | 可用，能跑通全链路，适合验证护栏是否生效；策略文本需人工重读 | 达到可交付水准 |

两点值得记录：

1. **护栏体系在两代模型上都成功拦截或标记了全部数字类错误**。模型能力差异体现在
   「需要多少次自我修正」和「文本写得好不好」，而不是「数字对不对」——数字的正确性
   由工具与契约保证，不由模型能力保证。
2. **换模型是配置动作，不是代码动作**。切换只改三个环境变量，
   `chat_request_extras()` 自动按网关拼 `enable_thinking` / `thinking` 字段。

## 7. 优化方向落地验证

[优化方向](./OPTIMIZATION_ROADMAP.md)的四个方向在本轮落地，本节记录它们的测试规模、
关键验证点，以及开发过程中发现并修复的缺陷。

### 7.1 测试规模

| 方向 | 测试文件 | 方法数 | 是否需要模型 Key |
| --- | --- | --- | --- |
| 强模型 Critic 二审 | `tests/test_critic.py` | 18 | 否（`httpx.MockTransport` 注入） |
| 模块间依赖传递编排 | `tests/test_orchestrator.py` | 25 | 否（注入 `runner` 假执行器） |
| 评测基准集与回归评分 | `tests/test_bench.py` | 35 | 否（回放存档 fixture） |
| 合规实时数据源接入 | `tests/test_realtime_feed.py` | 27 | 否（mock adapter + 临时 SQLite） |
| 反馈回流校准 | `tests/test_calibration.py` | 3 | 否 |
| 合计 | 5 个新文件 | **108** | 全部离线可回归 |

四个方向的测试**全部不依赖真实网关**：Critic 用 `httpx.MockTransport` 注入脚本化响应，
编排注入自定义 runner，评测回放存档，数据源本身就是可复现的 mock。
`bench/` 与 `module_agents/orchestrator.py`、`realtime_feed.py` 都不 import `engine`，
因此这 108 个方法在 Python 3.10 沙盒里也能全量跑通（不受第 2.5 节那 7 个 import error 影响）。

复现命令：

```bash
python3 -m unittest tests.test_critic tests.test_orchestrator \
                    tests.test_bench tests.test_realtime_feed tests.test_calibration
# 本轮实测：Ran 108 tests ... OK
```

### 7.2 关键验证点

**（1）管线断链容错——上游挂了，下游照跑**

`test_orchestrator.test_failed_module_blocks_only_its_hard_dependents` 注入一个在指定模块
抛异常的 runner，断言：失败模块在 `pipeline_trace` 里记 `status="failed"` 且带
`reason` / `detail`，**其余模块仍然全部执行完毕**，下游只是少收到一段上游摘要。
配套的 `test_executes_in_dependency_order` / `test_subset_still_follows_pipeline_order`
锁住 `M1 → M2 → M6 → M3 → M4 → M5` 的顺序，
`test_third_module_receives_first_two_digests` 与 `test_upstream_limit_caps_injected_digests`
锁住「只带最近 3 段」的注入窗口，`test_all_digests_within_limit` 锁住 600 字上限。
`test_shared_keyword_handoff_reaches_module3` 单独验证模块6 的整包词表确实到了模块3。

这条是编排改造里最重要的一条：编排引入了模块间顺序依赖，
如果上游失败会连累下游，就等于用「结论互通」换掉了原本的 fail-safe 语义。
测试把「不断链」钉死成回归断言。

**（2）评分基线 100 的硬断言**

`test_bench.RegressionBaselineTest` 用 `bench/fixtures/regression_outputs.json`
（六模块「合法满分」参照输出）跑 `score_run`，硬断言：

```python
self.assertEqual(self.summary["overall"], 100.0)
self.assertEqual(self.summary["module_count"], 6)
self.assertEqual(self.summary["missing_modules"], [])
self.assertEqual(self.summary["unknown_modules"], [])
```

`test_every_module_scores_full_marks` 进一步要求六个模块**各自** 100 分、
零违规、零缺失标记、零缺失路径；`test_dimension_average_baseline` 锁住各维度均分
`{grounding: 40, honesty: 25, invariants: 25, structure: 10, text: 15}`
（离线存档不带 `critic_review`，文本分记 `skipped` 不扣分，所以总分仍是 100）。

这组断言的意义是**给评分器本身上锁**：分值一旦变化，说明黄金断言集或评分口径被改了，
必须在变更记录里写明原因，而不是悄悄漂移。

**（3）破坏一个比例 → 得 95 分，并点名违规**

`test_bench.test_invariants_deduct_five_per_violation` 把模块6 的三级预算比例
改成 `0.6 / 0.3 / 0.2`（合计 1.1）后重新评分，断言：

- 违规**恰好 1 条**（不是被淹没在一堆连锁报错里）；
- `invariants` 维度从 25 扣到 **20**，即总分 40 + 25 + 20 + 10 = **95**；
- 违规文案里点名 `合计必须为 1.0`，而不是笼统的「校验失败」。

`test_invariants_floor_at_zero` 则一次破坏模块4 的五处数字，断言违规数 ≥5 且
`invariants` 扣到 0 为止不变负数。`BrokenOutputTest`（14 个用例）逐条验证
「故意破坏什么 → 报什么违规」：比例合计 1.1（计划与定向包各一条）、少一个选题、
方向选题不足 3 个、预算拆分不等于总预算、三阶段合计对不上、放大池不自洽、
编造超出证据的达人、篡改广告标识计数、付费指标缺来源、关键词重复；
另有三条边界用例——零证据请求必须逼出空 `hot_formats`、无 CPC 证据时禁止出现出价数字、
垃圾输出不能让评分脚本崩溃。

这一组是评测集的核心价值：**它证明的不是「满分输出能得满分」，
而是「坏输出会被扣分并被点名」**——前者随便写个断言都能过，后者才是回归能力。

**（4）实时数据源：同 seed 可复现、合并不膨胀**

- `test_same_seed_reproduces_batch_sequence`：同一 seed 的两个 adapter 拉出的批次序列
  逐字段一致；`test_different_seed_diverges` 反向确认不同 seed 会分叉。
- `test_heat_score_evolves_monotonically_per_keyword`：同 seed 同关键词的热度
  **后批不低于前批**（模拟热搜升温），封顶 99。
- `test_all_items_carry_mock_flags_and_source_prefix`：每一条 trending / 竞品事件 /
  基准漂移都带 `is_mock=true`、`evidence_grade="M"` 与「模拟实时数据源」前缀——
  这是合规隔离的回归锁。
- 去重不膨胀：`test_existing_keyword_is_not_overwritten` /
  `test_existing_competitor_is_not_overwritten` 断言已有真实证据不被 mock 覆盖；
  `test_merged_output_is_deduplicated_within_feed` 断言同一批 feed 内部的重复项
  只进一条；`test_empty_store_is_noop` 断言空库时合并结果与入参等价；
  `test_trending_limit_is_respected` / `test_competitor_limit_is_respected`
  锁住 6 / 4 的上限。反复调 `/feeds/pull` 再分析，证据区不会无限膨胀。
- `test_items_are_compatible_with_evidence_contracts`：feed 条目可以直接被
  `models.TrendKeywordEvidence` / `CompetitorEvidence` 校验通过——
  这是「换真实源不用改下游」这句话的实际依据。

**（5）Critic：失败一律降级，绝不抛异常**

`test_critic` 里有四条独立的降级路径断言——`test_connect_error_degrades_without_raising`
（网络断连）、`test_non_retryable_status_degrades`（非重试 4xx）、
`test_malformed_response_body_degrades`（响应结构异常）、
`test_bad_json_retried_once_then_degraded`（坏 JSON 修复一轮后仍不合法）——
全部断言返回 `{"status": "degraded", ...}` 而**不是抛异常**。
`test_repair_round_can_succeed` 验证修复轮确实能救回一次坏 JSON。
`test_merge_issues_into_human_review_items` 验证 issues 会被写进人工复核项，
`test_module_checklists_cover_six_modules` 锁住六个模块各有专属检查清单。

### 7.3 开发中发现并修复的缺陷

| # | 问题 | 发现方式 | 根因 | 修复 | 验证证据 |
| --- | --- | --- | --- | --- | --- |
| 14 | 固定 seed 反复调 `POST /feeds/pull`，批次号永远停在 1，新批次把上一批**整个覆盖**掉 | 写 `FeedStore` 落库测试时发现 `feed_batches` 行数始终为 1 | `MockRealtimeFeedAdapter` 的批次号是**实例状态** `self._batch_index`，而 HTTP 是无状态的——`/feeds/pull` 每次请求都新建一个 adapter，计数器每次都从 0 重来；`batch_id` 由 `feed-<seed>-0001` 派生，于是 `INSERT OR REPLACE` 每次都命中同一主键 | 新增 `FeedStore.last_batch_index(seed)`（`SELECT MAX(batch_index) WHERE seed = ?`）与 `adapter.resume_from(store)`，让无状态调用方在 `pull()` 前先从库里已有的同 seed 批次续号；`main.feeds_pull()` 里显式调用，并在代码注释写明「否则固定 seed 会永远停在第 1 批并互相覆盖」 | `test_realtime_feed.test_last_batch_index_and_resume_from_store`、`test_batch_index_increments_and_is_encoded_in_id`、`test_start_index_offsets_batch_numbering`；`test_resaving_same_batch_is_idempotent` 反向确认「同一批次重复保存」仍应幂等 |

这个缺陷值得单独记一笔，因为它**只在真实调用形态下才暴露**：
adapter 的单元测试里对象一直活着，批次号自然递增，测试全绿；
只有把它放回「HTTP 每请求新建实例」的语境里，状态丢失才显形。
修复思路也因此不是「把 adapter 改成单例」（那会在多 worker 下再次失效），
而是**把续号的事实来源放回持久层**——谁都可以是无状态的，只要库里记着上次到哪了。

## 8. 局限性

1. **live 样本量小**。每个模块的 live 记录是个位数次运行，步数、修复轮这类指标只能
   当作观察，不能当作稳定性能指标；本报告不给成功率、不给拦截率百分比。
2. **模块6 无 live 复跑记录**。仅有离线契约与工具护栏回归覆盖。
3. **沙盒无法跑全量测试**。3.10 环境下 7 个模块因 `report_view.py` 的 3.12+ f-string
   语法无法导入（52 个测试方法未执行）；报告中 280/332 的数字仅适用于该沙盒。
   本轮新增的 108 个测试方法不受影响（它们都不 import `engine` / `main`）。
4. **ROI 链路依赖演示 CVR**。CVR 0.012 是标注了 `is_mock` 的演示补全值，
   因此所有由它推导的数字（目标 CPA、止损 CPA、ROI 点值与区间）都只是口径演示，
   不构成效果承诺。
5. **文本质量的自动化评估仍依赖模型**。台账第 1–5 项这类语义错误现在有了两道抓手：
   Critic 二审（按模块定制检查项，见 7.1–7.2）与 `bench/score.py` 的文本分。
   但两者都**依赖真实模型跑出来的 `critic_review`**——离线回归里文本分恒为 `skipped`，
   本轮也**没有做 live 二审的样本记录**，所以「Critic 能不能稳定抓出台账第 1–5 类问题」
   目前只有设计上的说明，没有实测数据支撑。这一条仍是本报告最弱的环节。
6. **溯源是数值比对，不是语义比对**。`grounding_check` 只检查「输出里的数字能否在
   工具结果中找到」，不检查「这个数字被用在了正确的位置」。数字用对了地方仍需人工判断。
7. **多模态审核未真正接入**。图片/视频只返回 `pending_ocr` / `pending_frame_scan` 状态，
   本轮未做视觉识别测试。
8. **未做压力与并发测试**。本轮全部为单请求功能验证，未评估并发下的网关限流与
   状态库写入竞争。

## 附录A：Critic 二审实录（保留为活证据，未回修）

**背景**：2026-07-26 本机实跑 `demo_agent_loop.py --module4 --critic`。一审模块 Agent（deepseek-chat 通道）2 步收敛、0 修复轮、数字溯源全部通过；二审 Critic（`AGENT_CRITIC_MODEL=deepseek-v4-pro`）判定 **verdict: revise**，四维评分：证据引用 5／可执行性 6／合规措辞 7／一致性 8，共 7 条 issue。

**保留决策**：以下问题**有意不回修**。理由：数字护栏与溯源审计已保证全部数字可追溯，这 7 条属于「数字被用在什么语境」的文本级问题——恰好证明二审层能抓住一审与确定性护栏都无法覆盖的缺陷类别。全部条目均已被模块输出中的 `human_review_items` 流程兜底（人工拍板环节覆盖）。

| # | 严重度 | 位置 | 问题（摘要） |
| --- | --- | --- | --- |
| 1 | high | targeting_packages（达人相似定向） | 引用了证据中不存在的达人合作历史，未标注为假设 |
| 2 | high | bidding.scaling_rules | 目标 CPA ¥25.04 直接使用但未说明推导口径 |
| 3 | medium | daily_schedule | 时段预算与计划层 budget_share 缺联动说明，动作偏值班表化 |
| 4 | medium | risk_playbook（冷启动） | CTR 基准 16.05% 无出处引用 |
| 5 | medium | risk_playbook（衰退） | CVR=0.012 已标注「待投手确认」却被当硬阈值使用（自相矛盾） |
| 6 | low | bidding.scaling_rules | 止损线 ¥30.05 与 forecast 一致但证据链未闭环 |
| 7 | low | search_feed_split.synergy_note | 搜推联动缺触发条件（转化数/CPA 门槛） |

**结论**：一审（结构与数字全绿）+ 二审（文本质量 revise）的组合结果，验证了分层审计设计的必要性：溯源审计管「数字从哪来」，Critic 管「数字用得对不对、话说得严不严谨」，人工拍板管最终取舍。该实录同时说明系统对自身输出的批判能力不依赖人工介入。

## 附录B：双版本对照实验（no-code vs 代码版）

**实验设计**：同一输入（`examples/cookie_quartet_full_case.json`：40 条品类笔记 / 2 竞品 / 8 达人 / 4 热搜词 / 3 违规台账）、同一裁判（`bench/` 四维评分）、同一强模型（Claude 5 系）。no-code 侧严格按 `docs/no-code-agent/` 的薄编排器 + 四份治理文件 + 六份 SOP 执行 `/full`（M1→M2→M6→M3→M4→M5），无工具、无 Pydantic 校验、无溯源审计；输出存档为 `bench/fixtures/nocode_full_run.json`，通过 `python bench/run_bench.py --replay` 打分。代码版取回归基线（`bench/fixtures/regression_outputs.json`）。实验日期 2026-07-26。

**评分对照**：

| 维度（满分） | no-code | 代码版 | 差异性质 |
| --- | ---: | ---: | --- |
| 数字溯源（40） | 0 | 40 | 结构性 |
| 诚实标记（25） | 18.05 | 25 | 词法性 |
| 数字不变量（25） | 25 | 25 | 本次持平 |
| 结构完整（10） | 10 | 10 | 持平 |
| 文本质量（15） | 15 | 15 | 持平 |
| **总分** | **53.05** | **100** | — |

分模块：M1/M2/M6 各 60，M3/M5 各 47.5，M4 43.33（越靠近投放决策、依赖 Mock CVR 的模块扣分越多）。

**三条发现**：

1. **40 分溯源差距是架构性的，非模型能力问题**。no-code 形态原理上产不出机器可核验的计算轨迹（`grounding_check` 恒为 false），无论换多强的模型都无法弥补。这从反面验证了本项目「控制权反转 + 工具护栏 + 溯源审计」重构路线的必要性。

2. **诚实维丢的 7 分实为「更严格反被扣分」**。no-code 运行按治理纪律直接**拒用** Mock CVR（`matched_creators` 留空、forecast 不输出 ROI），语义上比代码版「使用但标注待确认」更保守；但 `bench/golden.py` 的诚实标记词族是按代码版措辞校准的（要求「待投手确认 / 证据不足」等 token），「拒用 / 保持为空」未命中。这是评分器的已知偏差，改进方向：诚实标记的 `any_of` 词族应扩充「拒用 / 不可确认 / 保持为空」等同义表达。

3. **不变量满分需打折看待**。本轮 no-code 的算术全对（预算守恒 30000+70000=100000、三阶段 14000+42000+14000=70000、出价倍率带、比例合计）属于强模型逐笔核算的理想情况——是「这次没错」而非「不会错」。代码版的同样 25 分由 Pydantic 校验与工具算术结构性保证，两者可靠性不可等同。

**结论**：no-code 版在治理规范表达力与灵活性上不输代码版（其证据仲裁梯子、SSOT 字段规范、`blocked/completed_with_gaps` 状态、硬前序检查四项已于本轮反向移植进代码版，见 `evidence_policy.py` 与 `module_agents/orchestrator.py`），但在可审计性与可回归性上存在结构性差距。两版本定位：no-code 适合快速迭代策略纪律与人工陪跑，代码版适合需要留痕、复现与自动回归的正式交付。
