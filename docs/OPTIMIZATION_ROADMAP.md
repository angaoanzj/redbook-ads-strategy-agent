# 后续优化方向

> 配套文档：[技术架构](./TECHNICAL_ARCHITECTURE.md)｜[测试报告](./TEST_REPORT.md)｜[使用说明书](./USER_GUIDE.md)｜[交付索引](./DELIVERABLES.md)

## 作业交付：可继续提升的 5 个方向

下列方向面向**下一阶段**，每项均可单独立项；不依赖改作业主链路即可演示价值。

### 1. 用合规真实数据源替换 Mock 实时 Feed

- **现状**：`realtime_feed.py` 已是同构接口，但当前只有可复现的 Mock 热搜/竞品事件；模块6 热点仍常停在「待接入数据源」。
- **方案**：优先接官方开放能力或品牌授权第三方；实现同一个 `FeedAdapter.pull()`，强制带来源与采集时间；竞品监控改为按周守护进程刷新快照并推送 high/medium 预警。
- **预期收益**：热点监控与竞品加码预警从「点一次看一眼」变成可持续观察；不降低证据成色。

### 2. 落地真正的多模态内容审核（OCR / 视频抽帧）

- **现状**：`content_audit` 对图片/视频只返回 `pending_ocr` / `pending_frame_scan`，文本规则预审已可用。
- **方案**：接入合规 OCR 与关键帧扫描服务；把视觉命中写回 `findings`，并继续驱动付费选题/创意门禁；无视觉结果时保持 pending，禁止伪造。
- **预期收益**：封面绝对化用语、竞品 Logo、功效暗示等「图上的违规」能在投前拦住。

### 3. 对标看板「本地引擎 × Agent」双轨评测集

- **现状**：赛道看板已用本地引擎拼共性/空白/高峰（北京时间），DeepSeek Agent 可写人话但默认不覆盖第 03 章。
- **方案**：固化珍妮/曲奇四重奏等金样用例；对摘要、共性五条、空白五条、高峰分桶做自动打分；每次改 prompt 或换模型跑回归。
- **预期收益**：换模型时能量化「像不像投手 briefing」，避免只靠肉眼。

### 4. 投放后效果回流，自动校准出价与预算档位

- **现状**：`calibration` / feedback 已有最小读路径，但真实投放结果样本少，校准增益有限。
- **方案**：定义周级回流表（计划 ID、花费、CPC、CTR、转化）；用后验分布微调探测预算与止损线；校准结果进报告「相对历史」栏目。
- **预期收益**：同一品牌第二轮投放少踩「首轮拍脑袋出价」的坑。

### 5. 多品牌租户化与权限隔离（演示级 SaaS）

- **现状**：单机 SQLite + 会话 ID，适合原型，不适合多品牌并行运营。
- **方案**：按 `brand_id` 隔离知识库与 `agent_state`；API Key / 会话绑定品牌；看板与导出带租户前缀；保留 deterministic 离线模式便于售前演示。
- **预期收益**：可把原型推进到「代运营多客户」试用，而不混数据。

---

## 附录：本轮已落地的能力（供对照，非作业必读）

以下五项在仓库中**已经实现骨架或完整能力**（第 1 项真实源仍待接入）。详细文件位置与验证命令见后文各节。

| # | 方向 | 状态 |
| --- | --- | --- |
| A | 合规实时数据源接入（mock 同构） | 已落地接口 |
| B | 强模型 Critic 二审 | 已落地 |
| C | 模块间依赖传递编排 | 已落地 |
| D | 反馈回流校准（最小读路径） | 已落地 |
| E | 评测基准集与回归评分 | 已落地 |

---

## 1. 合规实时数据源接入（热搜与竞品监控自动化）｜**已落地（mock 同构接口）**

### 现状短板

- **热搜/趋势词是人工粘贴的**。`trending_keyword_evidence` 靠首页文本框或 JSON 导入；
  模块6 的 `trending_monitor.data_source_status` 在无合规源时被契约强制标注为
  「待接入数据源」。这个标注是诚实的，但也意味着「热点监控机制」目前只是一份流程文档，
  没有真实数据在跑。
- **竞品监控是被动的**。`tools/competitor_monitor.py` 的能力已经完整：无历史快照时做
  `baseline` 基线扫描，有快照时做 `diff` 增量预警（广告标识笔记 +2 以上报 high
  「疑似加大投放」、新增对标账号报 medium）。快照通过 `agent_state` 的
  `competitor_monitor` / `brand:<品牌名>` 缓存保存，TTL 7 天。
  但**快照只有在用户主动发起一次 `/analyze` 时才会更新**——没人点，就没有对比，
  预警也就永远不会触发。TTL 到期后甚至会退回 `baseline` 状态重新开始。
- 竞品的广告标识与投放时长仍必须人工打开原笔记核验，工具的 `evidence_boundary`
  字段一直在申明这件事。

### 方案

1. **接入合规趋势源**：优先级依次是官方开放能力 > 品牌授权的第三方数据服务 >
   自有账户后台导出。接入层统一产出 `TrendKeywordEvidence`（带 `source_name` /
   `collected_at` / `heat_score`），复用现有契约，模块6 无需改动即可从
   「待接入数据源」切到真实源状态。
2. **给竞品监控加定时器**：新增一个按品牌维度的周期任务（建议按周），
   独立于用户请求触发 `monitor_competitor_ads`，把快照写回同一缓存键，
   并把 TTL 从 7 天延长到与扫描周期匹配，避免快照过期导致 `diff` 退化成 `baseline`。
3. **预警出口**：把 high/medium 预警从「报告里的一段文字」升级为可订阅的事件
   （落状态库 + 看板置顶），让「竞品加码投放」这件事在用户不主动跑分析时也能被看到。
4. **红线不动**：不绕过登录、验证码、robots 或平台条款采集；无授权的数据一律不接入，
   宁可继续标注「待接入数据源」。

### 预期收益

- 模块6 的热点监控从流程文档变成有数据的机制，蓝海词的判定不再只是「待验证种子词」；
- 竞品监控从「用户点一次看一眼」变成「持续观察 + 变化时告警」，
  这是 `diff` 分支真正的设计意图；
- 减少一类人工操作（粘贴热搜），同时不降低证据成色——所有接入源仍带来源与采集时间。

### 落地实现

本项按「**接口先行、mock 实现**」落地：接入层与真实源同构，当前挂的是模拟数据源。
换真实源时只需新写一个实现 `FeedAdapter` 协议的 adapter，下游一行不用改。

**文件位置**

| 文件 | 内容 |
| --- | --- |
| `realtime_feed.py` | `FeedAdapter` 协议（唯一方法 `pull(since_ts) -> FeedBatch`）、`MockRealtimeFeedAdapter`、`FeedStore`（SQLite）、`merge_feed_into_request()` / `feed_merge_counts()` |
| `main.py` | `POST /feeds/pull`、`GET /feeds/status`、`GET /feeds/latest`，以及 `/analyze` 的 `use_realtime_feed` 参数与 `realtime_feed_merge` trace |
| `scripts/feed_daemon.py` | 纯客户端演示守护脚本，周期性打 `/feeds/pull`（不 import 项目模块） |
| `tests/test_realtime_feed.py` | 27 个用例：协议一致性、同 seed 复现、热度单调、mock 标记、去重合并、批次续号 |

**开关方式**

- 拉数据：`POST /feeds/pull?seed=&category=&brand=&product_name=`，落库后返回批次摘要；
- 用数据：`POST /analyze?use_realtime_feed=true`，把库里最新条目合并进本次请求证据
  （默认 6 个热搜词 + 4 个竞品事件；同名词/同竞品**不覆盖**已有真实证据）；
  该参数已计入 `_analysis_request_hash()`，开关不同视为不同请求，幂等键不会串用；
- 换库位置：环境变量 `XHS_FEED_DB`（默认 `data/realtime_feed.db`）。

**红线（代码强制，不是文档约定）**

- 所有条目固定 `is_mock=true`、`evidence_grade="M"`、`source_name` 带「模拟实时数据源」前缀；
- `M` 不在 A–E 真实证据等级内，因此永远不会抬高 `data_confidence`；
- `/feeds/status` 的 `source_policy` 字段把这条边界直接写在接口响应里。

**验证命令**

```bash
python3 -m unittest tests.test_realtime_feed

# 起服务后：拉三批 → 看状态 → 合并进分析
curl -X POST 'http://127.0.0.1:8010/feeds/pull?seed=demo-2026&category=香港蝴蝶酥伴手礼'
curl 'http://127.0.0.1:8010/feeds/status'
python3 scripts/feed_daemon.py --interval 3 --count 5 --seed demo-2026
```

**方案里尚未实现的子项（如实标注）**

- 方案 1 的「真实合规源」未接入，当前只有 mock adapter，模块6 的
  `data_source_status` 在没有真实趋势源时仍应标注「待接入数据源」。

**本轮补齐（竞品定时器 + 预警出口）**

| 文件 / 接口 | 内容 |
| --- | --- |
| `main.py` | `POST /competitors/scan`、`GET /alerts`；`/analyze` 后 high/medium 预警落 `alert_events` |
| `agent_state.py` | `alert_events` 表、`save_alert` / `list_alerts` |
| `scripts/competitor_scan_daemon.py` | 周期调用 `/competitors/scan` 的纯客户端守护脚本 |
| TTL | 环境变量 `XHS_COMPETITOR_CACHE_TTL_DAYS`（默认 **14** 天，与周扫描匹配） |

```bash
# 起服务后：对已有分析品牌做一次独立扫描，再查预警
curl -X POST 'http://127.0.0.1:8010/competitors/scan?brand_name=曲奇四重奏'
curl 'http://127.0.0.1:8010/alerts?brand_name=曲奇四重奏&severity=high'
python3 scripts/competitor_scan_daemon.py --brand 曲奇四重奏 --count 1
```

---

## 2. 强模型 Critic 二审策略文本｜**已落地**

### 现状短板

护栏体系目前是**数字导向**的：工具参数校验、输出契约校验、`grounding_check` 数值溯源。
[测试报告的问题台账](./TEST_REPORT.md)第 1–5 项暴露了一个明确空档——
**语义错误不触发任何护栏**：

- 聚光计划的 `placement` 写成「自然内容」；
- `objective` 写成「品牌曝光」这类非聚光目标；
- `budget_share` 照抄预热/爆发/长尾的 0.2/0.6/0.2；
- 投放时段写成「总结当日数据 / 准备次日策略」的运营值班表；
- 调价写成「0.1 倍」这种分不清涨降的表述。

这五项全部是**人工读输出才发现的**。修复手段分两类：能枚举的收紧成 Literal + 校验器
（`objective` / `placement` 现在是硬校验），不能枚举的只能加 system prompt 铁律 +
字段 description（调价百分比、禁值班表目前就属于这一类，没有正则硬校验）。
后一类无法保证换模型或改 prompt 后不复发。

### 方案

1. **加一层 Critic**：模块 Agent 产出并通过契约校验后，把
   `{证据摘要, 工具调用轨迹, 最终 JSON}` 交给一个**更强的模型**做二审，
   只审策略文本质量，不审数字（数字已有溯源）。审查清单按模块定制，例如模块4：
   「campaigns 是否被误解为投放阶段」「daily_schedule 是否是投放时段而非值班表」
   「调价是否用百分比」「风险预案是否引用了本案例数字」。
2. **输出结构化裁决**：`{passed, issues: [{field_path, severity, problem, suggestion}]}`。
   high severity 触发一轮定向重写（复用现有的 `continue_run` 修复轮机制，
   把 Critic 的 issues 当作新的 user 消息），medium/low 只写进报告的人工复核项。
3. **成本控制**：Critic 只在 `use_agent_modules=true` 且显式开启时运行；
   一次分析六个模块 = 六次二审，建议做成独立开关与独立模型通道
   （`model_config` 的双通道模式可直接扩成三通道）。
4. **与降级链条对齐**：Critic 调用失败不阻断主流程，按现有 fail-safe 惯例记 trace 并跳过。

### 预期收益

- 补上「数字有溯源、文本无质检」的空档，把台账第 1–5 类问题从「人工读出来」
  变成「系统标出来」；
- 弱模型（如 Qwen3-8B）的可用性提升——测试记录显示它的问题集中在文本质量而非数字，
  二审正好补这一块，让低成本模型 + 强模型二审成为可行组合；
- 为第 5 项的回归评分提供打分器：Critic 的 issues 数量与严重度可以直接当作质量指标。

### 落地实现

**文件位置**

| 文件 | 内容 |
| --- | --- |
| `module_agents/critic.py` | `critic_enabled()` / `load_critic_config()` / `run_critic()`、`CriticReport` 契约、system prompt（含「不得质疑数字」铁律） |
| `engine.py` | `_attach_agent_modules()` 在模块 Agent 成功挂载后追加一次二审 |
| `demo_agent_loop.py` | `--critic` 叠加 flag，打印 verdict / 四维分 / issues |
| `tests/test_critic.py` | 16 个用例：契约边界、单次成功、模型覆盖、坏 JSON 修复轮、各类降级 |

**输出契约**（`CriticReport`）：`verdict` 为 `pass` / `revise`；
`dimension_scores` 四维各 1–10 分——`evidence_citation`（证据引用）、
`executability`（可执行性）、`compliance_wording`（合规措辞）、`consistency`（一致性）；
`issues` 最多 10 条，每条含 `path` / `severity`（high|medium|low）/ `problem` / `suggestion`；
外加一句 `summary` 总评。

**开关方式**（两个环境变量，默认关闭以控成本）

```bash
export AGENT_CRITIC_ENABLED=1        # 1 / true / yes / on 才开启
export AGENT_CRITIC_MODEL=...        # 可选；缺省沿用 Analyzer 主模型
```

`load_critic_config()` 直接复用 `load_analyzer_config()` 的 api_key / base_url，
**不新增第三条通道变量**，只把模型名换掉；模型名同样过 `_normalize_chat_model()`
归一化与 `_strip_inline_comment()` 行内注释剥离，与 Analyzer 口径完全一致。

**挂载位置与降级语义**

- API 响应里挂在 `modules.<engine_key>.agent_decision.critic_review`；
  trace 另记一条 `{"stage": "critic_<模块名>", "status": ...}`；
- 成功：`{"status": "ok", "report": {...}}`；
- 任何失败（缺 Key、网络异常、非重试 4xx、坏 JSON、契约不过、修复轮用尽）一律返回
  `{"status": "degraded", "reason": ...}`，`run_critic()` **绝不抛异常**，
  模块产出照常挂载；Critic 模块本身 import 失败时按「未开启」处理。

**验证命令**

```bash
python3 -m unittest tests.test_critic

AGENT_CRITIC_ENABLED=1 python3 demo_agent_loop.py --module4 --critic
AGENT_CRITIC_ENABLED=1 python3 demo_agent_loop.py --pipeline --critic
```

**方案里尚未实现的子项（如实标注）**

- 无。本轮已补齐：high severity 触发一轮定向重写（复用模块 `run_fn` 再跑一遍，
  把 Critic issues 写入上游上下文）；medium/low 写入 `human_review_items`；
  `MODULE_CRITIC_CHECKLISTS` 按模块定制检查项并注入 `build_critic_prompt`。
  重写失败只记 `critic_rewrite_*` fallback，不阻塞模块挂载。

---

## 3. 模块间依赖传递编排｜**已落地**

### 现状短板

目标业务依赖是 `M1 → M2 → M6 → M3 → M4 → M5`，但当前运行时是
`engine._attach_agent_modules()` 按 `module1 → module6` 的数字顺序**逐个独立执行**，
每个模块直接读同一份 `CampaignRequest` 证据上下文，模块之间不传递任何结论。
后果是：

- 模块1 判读出的「爆款共性」「内容缺口」「高互动时段」不会进入模块2 的选题 prompt，
  模块2 只能自己再从笔记主题词重新聚合一遍；
- 模块1 的竞品定向假设不会传给模块4 的定向包设计；
- 模块6 的三级词库与模块3 的关键词赛道各自独立调用 `build_keyword_tiers`，
  可能给出两套不完全一致的词表；
- 唯一已经共享的是时段口径——`module_agents/_evidence_aggregation.py` 被模块1 与模块4
  共用，避免两套时段定义。这恰好说明依赖共享是有效的，只是目前只做了一处。

### 方案

1. **定义模块间交接契约**：为每个上游模块声明一个「可被下游消费的结论子集」
   （如模块1 输出 `hot_formats` / `content_gaps` / `peak_slot` / `targeting_hypotheses`），
   用独立的 Pydantic 模型固化，避免下游直接吃上游的完整 JSON 造成耦合。
2. **改执行顺序 + 上下文注入**：`_attach_agent_modules` 从固定数字顺序改为按依赖图
   拓扑执行，并把上游交接结构渲染进下游的 user prompt 证据区
   （沿用现有 `build_user_prompt` 的「证据区」段落格式，无需改契约）。
3. **上游失败时的降级**：上游模块 fallback 时，下游按「无上游结论」路径运行
   （等价于现在的行为），并在 `human_review_items` 注明缺少上游输入。
   这保持了现有的 fail-safe 语义：一个模块挂掉不能连累全案。
4. **词表统一**：模块3 与模块6 共享一次 `build_keyword_tiers` 的结果，
   模块3 只做「从词库里挑搜索词/信息流词并配 bid_note」。

### 预期收益

- 消除跨模块结论冲突（两套词表、两套时段、两套竞品判断）；
- 下游模块 prompt 里有了上游的具体结论，选题与定向的针对性提高，
  减少「每个模块各自泛泛而谈」的观感；
- 减少重复工具调用与重复聚合，降低 token 与步数消耗。

### 落地实现

**文件位置**

| 文件 | 内容 |
| --- | --- |
| `module_agents/orchestrator.py` | `PIPELINE_ORDER`、六个 `_digest_moduleN()`、`build_upstream_digest()`、`run_pipeline()` |
| `module_agents/base.py` | `run_module_agent(..., upstream_context="")` 参数与 `UPSTREAM_CONTEXT_HEADER`，非空时拼到 user prompt 末尾 |
| `engine.py` | `_attach_agent_modules()` 改为按 `PIPELINE_ORDER` 排序执行并逐级注入摘要 |
| `demo_agent_loop.py` | `--pipeline` 跑全流程并打印 `pipeline_trace` |
| `tests/test_orchestrator.py` | 24 个用例：各模块摘要提取与字段缺失容错、依赖顺序、注入条数、断链容错 |

**依赖顺序**：`PIPELINE_ORDER = M1 → M2 → M6 → M3 → M4 → M5`
（先赛道判读 → 人群与选题 → 关键词词库 → 达人匹配 → 聚光决策 → 预算统筹）。
`module_names` 传子集时仍按该顺序重排；不在顺序表里的名字记一条
`{"status": "skipped", "reason": "unknown_module"}`。

**摘要机制**：每个模块跑完由 `build_upstream_digest()` 压成一段
**≤600 字**（`DIGEST_MAX_CHARS`，超长截断加省略号）的中文纯文本，
只提取下游真正要用的结论；下游只注入最近 `upstream_limit` 段（默认 **3**，
`engine` 侧同为最近 3 段），避免 prompt 无限膨胀。
所有摘要函数对字段缺失一律容错，不抛异常。

**断链语义**：`run_pipeline()` 对单模块 try/except，失败记
`{"status": "failed", "reason": ..., "detail": ...}` 后**继续跑后续模块**，
下游只是少一段上游摘要——等价于改造前的独立执行行为，fail-safe 语义不变。
`runner` 参数可注入自定义执行器 `(module_name, req, upstream_context) -> result`，
测试据此完全离线覆盖编排逻辑。

**验证命令**

```bash
python3 -m unittest tests.test_orchestrator

python3 demo_agent_loop.py --pipeline
curl -X POST 'http://127.0.0.1:8010/analyze?use_model=false&use_agent_modules=true' \
  -H 'Content-Type: application/json' --data @examples/cookie_quartet_full_case.json
# trace 里每个 agent_moduleN 都带 upstream_digest_chars
```

**方案里尚未实现的子项（如实标注）**

- 方案 1 的「独立 Pydantic 交接模型」未做：交接物仍是**纯文本摘要** + 共享词表 JSON
  段落，好处是模块契约零改动；若需强校验可再抽 `Handoff*` 模型。

**本轮补齐（词表统一）**

- `orchestrator.build_shared_keyword_handoff()`：模块6 成功后注入
  `【模块6共享词表】` + `keyword_levels` / `level_budget_split` 完整 JSON；
- `engine` / `run_pipeline` 注入窗口优先保留该 handoff；
- 模块3 system prompt：有共享词表时禁止再调 `build_keyword_tiers`，只挑广告词配
  `bid_note`。

---

## 4. 反馈回流校准｜**已落地（最小读路径）**

### 现状短板

`POST /feedback` 与 `agent_state.db` 的 `feedback_records` 表已经落地：
存 `rating`（满意/一般/不满意）、`comment`、`sections`（用户指出有问题的章节）、
`report_id`、`session_id`、幂等键。`POST /backfilled-cases` 还能沉淀人工确认后的案例。

问题曾是**这些数据只进不出**：没有任何代码读取 `feedback_records` 去影响后续生成。
与此同时，系统里有一批「拍脑袋定的默认值」正等着被真实数据校准：

- 素材筛选阈值默认 CTR 0.10 / 互动率 0.07（模型可在 0.03–0.30 / 0.02–0.20 内自选）；
- 出价倍率护栏 `cold_start` 0.80–1.30、`scaling` 0.90–1.60；
- 预算默认档（转化 0.30 / 曝光 0.50 / 搜索增长 0.40）；
- 无 CVR 时的目标 CPA 占位倍数 25、测试带宽比例 15% 与下限 5%、
  止损倍率 CPC×1.5 / CPA×1.2。

这些常量在[技术架构第 3.2 节](./TECHNICAL_ARCHITECTURE.md)有完整清单，
它们目前全部来自作业基准与经验值，没有一个是从本品牌历史数据回归出来的。

### 方案

1. **补齐反馈结构**：现有 `sections` 只标「哪一章有问题」，建议扩展为
   「哪个字段 / 建议值 / 实际执行值」，让反馈可计算而不只是可阅读。
2. **接执行结果回流**：真正的校准依赖投后数据（实际 CPC、CTR、CVR、CPA），
   建议通过 `/backfilled-cases` 或新增的投后回填接口收集，
   并强制标注 `evidence_grade` 与来源（沿用现有证据契约）。
3. **按品牌维度校准**：积累到最小样本量后，为该品牌生成一份
   「校准后的默认档」（默认预算比例、CTR/互动率阈值、测试带宽比例），
   作为 `benchmark_evidence` 的一类特殊来源注入 prompt，
   **优先级低于账户实测值、高于全局默认档**——正好复用
   `report_agent_view.build_benchmark_ssot()` 现有的来源优先级机制。
4. **护栏不自动放宽**：出价倍率、止损倍率这类安全护栏**不参与自动校准**，
   只产出「建议调整」进人工复核项。自动放宽护栏等于取消护栏。

### 预期收益

- 让阈值与默认档从「作业基准」变成「本品牌基准」，第二次、第三次投放的建议
  比第一次更贴合实际；
- 把已经存在的 `feedback` / `backfilled_cases` 两张表从「审计记录」升级成「学习信号」，
  不需要新建持久化层；
- 为「这个 Agent 用得越久越准」提供可验证的说法，而不是宣传话术。

### 落地实现

| 文件 / 接口 | 内容 |
| --- | --- |
| `models.FieldCorrection` / `FeedbackRequest.field_corrections` | 字段级「建议值/实际值」 |
| `agent_state.save_feedback` | 持久化 `field_corrections_json`；`list_feedback_for_brand` |
| `calibration.py` | `load_brand_calibration()`：样本 ≥3 出 `ready` 默认档；护栏只进 suggestions |
| `GET /calibration/{brand_name}` | 查询校准结果 |
| `engine` / `/analyze` | 校准 `ready` 时注入上游摘要；trace 记 `brand_calibration` |

**红线**：出价/止损倍率等护栏字段永不写入 `defaults`，只进
`guardrail_suggestions` 供人工复核。

```bash
python3 -m unittest tests.test_calibration
curl 'http://127.0.0.1:8010/calibration/曲奇四重奏'
```

**方案里尚未实现的子项（如实标注）**

- 尚未把校准档写成正式的 `benchmark_evidence` SSOT 条目（当前是 Agent 上游文本摘要）；
- 投后 CPC/CTR/CVR 专用回填接口未单独建模，仍依赖 `field_corrections` + 回填案例。

---

## 5. 评测基准集与回归评分｜**已落地**

### 现状短板

当前的自动化测试（24 个文件 / 224 个测试方法，均为本项落地前的口径）覆盖的是**确定性行为**：
工具护栏是否拒绝非法参数、契约是否拒绝非法结构、溯源是否标出篡改数字、
修复轮是否能救回损坏 JSON。模块 Agent 测试全部用 `httpx.MockTransport`
注入脚本化模型响应，因此可回归、可复现。

但**没有任何东西在评估真实模型输出的质量**。测试报告里的模型对比
（Qwen3-8B 文本不稳、DeepSeek 达到可交付水准）是人工读若干次 live 输出得出的定性结论，
样本量是个位数。这带来两个具体问题：

- 改一句 system prompt 铁律，无法知道它是修好了一类问题还是引入了新问题；
- 换模型时无法量化对比，只能重新人工通读。

### 方案

1. **建 golden set**：以 `examples/cookie_quartet_full_case.json` 为满证据基准，
   再补三类边界案例——零证据（`cookie_quartet_with_workbook_data.json` 已可用）、
   部分证据（有 CPC 无 CVR）、冲突证据（同一指标多来源不同值）。
   每个案例 × 六个模块，形成固定的评测矩阵。
2. **定义评分维度**（每个模块一份 checklist）：
   - **结构分**：契约一次通过 / 修复轮数 / 收敛步数；
   - **溯源分**：`grounding_check.passed`、mismatch 数量；
   - **诚实分**：零证据案例下是否留空而非编造（`hot_formats` 是否为空、
     竞品是否为空列表、`matched_creators` 是否如实为空、`open_slots` 是否给出）；
   - **文本分**：由第 2 项的 Critic 打分（枚举正确性、时段语义、调价表述、
     风险预案是否引用本案例数字）。
3. **跑分脚本**：单独的评测入口（不进 `unittest`，因为它需要真实模型 Key 且耗时），
   输出一份可比对的 JSON 报表，包含每个模块每个维度的得分与与上次的差值。
4. **纳入变更流程**：改 prompt、改契约、换模型之前跑一次基线，改完再跑一次，
   把差值贴进变更记录。测试报告里那张模型对比表就可以由脚本自动生成，
   而不是靠人工通读。

### 预期收益

- 把「这次改动有没有变好」从主观判断变成可对比的数字；
- 换模型的决策成本大幅下降——现在换一次模型要人工重读六个模块的输出；
- 零证据案例的诚实分是本项目最核心的防幻觉能力
  （[测试报告台账](./TEST_REPORT.md)第 7、8 项），必须有回归手段防止它在后续改动中被破坏。

### 落地实现

**文件位置**

| 文件 | 内容 |
| --- | --- |
| `bench/golden.py` | 六模块黄金断言集（代码即数据）：`honesty_markers` 14 条、`numeric_invariants` 20 个函数、`required_structure` 64 条关键路径；顶部集中镜像 `tools/` 的护栏常量并注明来源文件 |
| `bench/score.py` | 四维加权评分 + Critic 文本惩罚 + `render_markdown()` |
| `bench/run_bench.py` | CLI：`--replay` / `--live` / `--matrix`，写报告并与上一份比分差 |
| `bench/fixtures/regression_outputs.json` | 六模块「合法满分」参照存档（回归基线） |
| `tests/test_bench.py` | 四维满分/扣分、文本分、基线硬断言、故意破坏用例 |

**评分口径**（满分 100，`score.py` 顶部常量）

| 维度 | 满分 | 判据 |
| --- | --- | --- |
| grounding 溯源 | **40** | `grounding_check.passed is True` 得满分，否则 0（无中间态） |
| honesty 诚实 | **25** | 诚实标记命中率 × 25；每条标记给一组 `any_of` 同义措辞，任一命中即通过，避免评分退化成措辞考试 |
| invariants 不变量 | **25** | 无违规得满分，每条违规扣 5 分，扣到 0 为止 |
| structure 结构 | **10** | 关键路径命中率 × 10 |
| text 文本（附加） | **15**（展示） | 有 `critic_review.status=ok` 时按 high/medium issues 从 total 扣分；无 Critic 不扣分 |

运行级 `overall` 是**已知模块的算术平均**；缺席模块记进 `missing_modules`（点名但不拉低平均），
未知模块记 `unknown_modules` 且不计入平均。

**三种跑法**

```bash
# 回放存档：离线、无需模型 Key，用于回归
python3 bench/run_bench.py --replay bench/fixtures/regression_outputs.json

# 真跑：调 orchestrator.run_pipeline，需要 Analyzer Key
python3 bench/run_bench.py --live --label "deepseek-v4-flash/prompt-2026-07"

# 评测矩阵：满证据 / 工作簿弱证据 / 极简请求（需 Key，耗时约为单次×3）
python3 bench/run_bench.py --matrix --label "matrix-baseline"
```

存档格式就是 `{module_name: result}`（`run_module_agent` 的返回），
也接受 `{"request": {...}, "modules": {...}}` 包装格式；
`demo_agent_loop.py` 与 `/analyze?use_agent_modules=true` 的 `agent_decision`
是同构结构，因此**真跑一次 → 存下 JSON → 以后 `--replay` 反复评分**是可行的工作流
（具体存档代码见 `bench/run_bench.py` 模块 docstring）。

**报告位置**：每次跑分写 `bench/reports/<UTC时间戳>/report.json` 与 `report.md`；
markdown 自动带上与上一份报告的「较上次」分差列（总分与每模块各一列）。
`--no-write` 只打印不落盘。

**验证命令**

```bash
python3 -m unittest tests.test_bench
python3 bench/run_bench.py --replay bench/fixtures/regression_outputs.json --no-write
# 期望：总分 100 / 100，六模块全满分、零违规
```

**方案里尚未实现的子项（如实标注）**

- 冲突证据专用 fixture 尚未单独沉淀（矩阵目前覆盖满证据 / 工作簿 / 极简三档）；
- 修复轮数记入 `detail.convergence` 信息项，默认**不改 total**（避免合法满分夹具掉分）。

---

## 附：本轮已完成的事项（存档）

1. 控制权反转重构：六模块全部 Agent 化，LLM 在 Agent Loop 内调用工具决策，
   工具管算术与护栏。
2. 四道护栏落地：工具参数 Pydantic 校验（错误回传自愈）、输出契约强校验
   （修复轮 ≤2）、数字溯源审计、未溯源降级为 `llm_agent_ungrounded`。
3. 网关容错：可重试异常集 + 429/5xx 白名单 + 3 次指数退避；模型双通道可插拔。
4. engine 集成 fail-safe：单模块失败独立回退确定性输出，互不影响。
5. 零证据诚实路径：`hot_formats` 允许为空、竞品工具允许空列表、达人不足只报缺口。
6. 模块4 契约收紧：`objective` / `placement` Literal 枚举 + 全聚光计划校验器；
   投放时段聚合进证据区；调价百分比表述。
7. 效果预估修正：测试带宽下限 `max(计算值, 聚光×5%)`，避免低 CPC 场景下带宽塌缩。
8. 基准指标 SSOT：`build_benchmark_ssot()` 多来源对比、冲突标记与选用规则。
9. 加分项接线：内容审核 / A-B 矩阵 / 竞品监控三个工具双入口（LLM 可调 + 确定性执行），
   看板投影 `report_view.dashboard` 与 `GET /board/{report_id}`。
10. **强模型 Critic 二审**（本文档第 2 项）：含按模块检查清单、high→定向重写、
    medium/low→`human_review_items`。
11. **模块间依赖传递编排**（第 3 项）：`M1→M2→M6→M3→M4→M5` + 摘要注入 +
    **M6→M3 共享词表 handoff**。
12. **评测基准集与回归评分**（第 5 项）：四维加权 + Critic 文本扣分 + `--matrix`。
13. **合规实时数据源接入层**（第 1 项）：mock feed + **竞品定时扫描** +
    **`GET /alerts` 预警订阅** + 可配置 TTL。
14. **反馈回流校准**（第 4 项）：`field_corrections` + `calibration.py` 读路径 +
    `GET /calibration/{brand}`；护栏不自动放宽。

上述 10–14 项的详细文件位置、开关方式与验证命令见本文档对应方向的「落地实现」小节；
配套的测试规模与关键验证点见[测试报告第 7 节](./TEST_REPORT.md)。
