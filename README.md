# 小红书投放策略决策 AI Agent

独立可运行的本地原型：下载或克隆本仓库后，在**仓库根目录**按下方「如何运行」操作即可。  
把品牌输入、合规证据与预算约束编排为 **6 个策略模块 + 附加工具**，输出结构化 JSON、可执行 Markdown 与网页看板。

## 作业交付物

| # | 交付项 | 入口 |
| --- | --- | --- |
| 1 | 可运行的 Agent 原型 | 本 README「[如何运行](#如何运行必读)」+ `web/` |
| 2 | 使用说明书 | [docs/USER_GUIDE.md](docs/USER_GUIDE.md) |
| 3 | 测试报告（曲奇四重奏） | [docs/TEST_REPORT.md](docs/TEST_REPORT.md) |
| 4 | 技术架构图 | [docs/TECHNICAL_ARCHITECTURE.md](docs/TECHNICAL_ARCHITECTURE.md) |
| 5 | 后续优化方向（3–5 项） | [docs/OPTIMIZATION_ROADMAP.md](docs/OPTIMIZATION_ROADMAP.md) |

文档索引：[docs/README.md](docs/README.md)（标明主交付 vs 支撑材料）

## 核心原则

**架构原则（控制权反转）**

- 大模型是决策者，不是润色器：六个模块各自跑一个 Agent Loop，由 LLM 在循环中调用工具，
  决定选哪档预算比例、用什么出价倍率、达人怎么分层、选题与关键词怎么写。
- 工具负责算术与护栏：金额、比例、出价、效果预估一律由 `tools/` 下的确定性函数计算，
  参数用 Pydantic 强校验；校验失败不抛异常，而是把错误回传给 LLM 自我修正。
- 输出过契约与溯源两道关：最终 JSON 必须通过模块契约校验（最多 2 轮修复），
  再由 `grounding_check` 逐个核对数字是否有工具依据；未溯源的模块被标记为
  `llm_agent_ungrounded` 并提示人工复核，而不是静默采纳。
- 始终可降级：任一模块 Agent 失败只回退该模块的确定性输出并记录 trace，不影响其它模块；
  未配置模型 Key 时全案仍可用确定性引擎生成。
- 换模型是配置动作：Analyzer 通道的三个环境变量即可在硅基流动 Qwen 与 DeepSeek 之间切换，
  业务代码零改动。

**数据合规原则**

- 不把大模型记忆当成实时平台数据。
- CPC、CPM、达人报价、热搜和竞品投放等结论必须绑定输入证据。
- 缺少证据时明确标记 `待接入数据源`，不会生成虚假达人名单或伪实时数字。
- 数据可信度不会被 Mock 补足抬高；最终投放上线、预算放量与达人下单均由人工拍板。

详见上述四份文档：说明书 · 测试报告 · 技术架构 · 后续优化方向。

## 如何运行（必读）

> 以下命令默认已进入**本仓库根目录**（含 `docker-compose.yml`、`main.py`、`web/` 的那一层）。  
> 若本机 8010 已被其它容器占用，先 `docker ps` 查看并停掉占用端口的容器。

### 你需要准备什么

| 方式 | 前置 | 能否不配模型 Key |
| --- | --- | --- |
| **Docker（推荐）** | 已安装 Docker Desktop / Docker Engine，并已启动 | **可以**：确定性引擎照常出全案 |
| **本机 Python** | Python 3.11+（3.10 一般也可）、能建 venv | **可以**：同上 |

模型 Key **不是启动门槛**。没有 Key 时：网页生成、六模块确定性输出、离线测试都能跑。  
只有勾选「大模型润色」或「六模块 LLM Agent」时，才需要在本地 `.env` 填 Key。

### 1. 配置环境变量（首次必做一次）

仓库只提交**空占位**模板 `.env.example`，**不提交**真实 Key。

```bash
# 已在仓库根目录时：
cp -n .env.example .env
```

然后二选一：

1. **先跑通（推荐）**：保持 `.env` 里所有 `*_API_KEY=` 为空即可启动。  
2. **要用 LLM**：只在本机编辑 `.env`，填入例如：

```env
AGENT_ANALYZER_API_KEY=你的密钥
AGENT_ANALYZER_BASE_URL=https://api.deepseek.com
AGENT_ANALYZER_MODEL=deepseek-v4-flash
```

红线：

- `.env` 已在 `.gitignore`，**不要** `git add .env`。  
- 提交/分享仓库时只保留 `.env.example`（Key 字段保持空）。  
- 不要把本地真实 Key 写进 example、文档或示例 JSON。

可选变量说明见 `.env.example`（Embedding、Critic、5118 热度等均可空）。

### 2A. Docker 启动（推荐）

```bash
docker compose up -d --build
```

验收：

```bash
curl --noproxy '*' http://127.0.0.1:8010/health
# 期望：{"status":"ok","agent":"xiaohongshu-strategy"}
```

浏览器打开 http://127.0.0.1:8010/ 。

常用命令：

```bash
docker compose ps                 # 看是否 healthy
docker compose logs -f agent      # 看日志
docker compose restart            # 改代码后重启（本仓挂载 .:/app）
docker compose down               # 停止
```

离线自检（不调大模型）：

```bash
docker compose run --rm agent python -m unittest discover tests
docker compose run --rm agent python demo_agent_loop.py --offline
docker compose run --rm agent python bench/run_bench.py \
  --replay bench/fixtures/regression_outputs.json --no-write
```

说明：Compose 项目名 / 容器名 / 镜像均为 `xiaohongshu-agent`；端口 `8010:8010`。

### 2B. 本机 Python 启动

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt

# 已按上一节准备好 .env 后：
python -m uvicorn main:app --host 127.0.0.1 --port 8010
```

看到 `Uvicorn running on http://127.0.0.1:8010` 即成功；停止用 `Control + C`。

不建议直接 `python main.py`（默认开 reload，部分 macOS 环境会报
`[Errno 1] Operation not permitted`）。

### 3. 网页上怎么第一次跑出报告

1. 打开 http://127.0.0.1:8010/  
2. 点 **「载入填满全案示例」**（品牌、卖点、约 40 条示例笔记、对标证据一次填齐）  
3. 保持「使用大模型润色 / 六模块 LLM Agent」关闭即可（无 Key 路径）  
4. 点生成，查看「赛道与竞品深度分析」等页签  

没有示例时：手动填任务书；可选上传 `category_notes.json`（写入本地知识库）、达人 CSV、竞品链接。

优先用 `127.0.0.1`。若本机开了 HTTP/SOCKS 代理，`localhost` 有时会被错误代理成 `502`。

入口汇总：

| 地址 | 用途 |
| --- | --- |
| http://127.0.0.1:8010/ | 用户界面 |
| http://127.0.0.1:8010/docs | API 文档 |
| http://127.0.0.1:8010/health | 健康检查 |

## 调用

```bash
curl -X POST 'http://127.0.0.1:8010/analyze?use_model=false' \
  -H 'Content-Type: application/json' \
  -H 'X-Session-ID: demo-session-001' \
  -H 'Idempotency-Key: demo-analysis-001' \
  --data @examples/cookie_quartet.json
```

响应中的 `report_markdown` 是可直接复制到文档中的投放全案；`modules` 保存六个模块的结构化结果；`report_id` 与 `session_state` 用于追踪本次报告和当前会话。

### 启用六模块 LLM Agent 决策（`use_agent_modules`）

```bash
curl -X POST 'http://127.0.0.1:8010/analyze?use_model=false&use_agent_modules=true' \
  -H 'Content-Type: application/json' \
  -H 'X-Session-ID: demo-session-001' \
  -H 'Idempotency-Key: demo-analysis-002' \
  --data @examples/cookie_quartet_full_case.json
```

`use_agent_modules` 默认 `false`。置为 `true` 且 Analyzer Key 可用时，六个模块会各自进入
Agent Loop 由 LLM 调用工具做决策，结果挂在 `modules.<模块键>.agent_decision`：

- `agent_decision.output`：通过模块契约校验的结构化决策；
- `agent_decision.grounding_check`：数字溯源结果（`passed` 与 `mismatches`）；
- `agent_decision.steps_used`：本模块收敛用了几步；
- 同级的 `decision_source`：`llm_agent`（溯源通过）或 `llm_agent_ungrounded`（需人工复核）。

未配置 Key 时 `trace` 记 `agent_modules / skipped / model_key_missing`；单个模块失败时记
`agent_moduleN / fallback` 并保留该模块的确定性输出，其余模块不受影响。
网页端对应勾选项为「启用六模块 LLM Agent 决策」。

`/analyze` 的全部查询参数与各模块的输入输出说明见 [使用说明书](docs/USER_GUIDE.md)。

普通用户使用首页表单即可，不需要进入 Swagger。首页支持：

- 一键载入《数据需求.xlsx》历史数据案例；
- 填写品牌、产品、人群、预算、周期和竞品链接；
- 选择是否使用历史基准及大模型润色；
- 分模块查看结果并下载 Markdown/JSON。
- 显示当前 `Mock种子`；同一种子可复现同一组模拟结果，点击「换一组 Mock」会生成新种子并重新分析。
- 生成结果默认进入「赛道与竞品深度分析」（有对标证据时）；其余模块页签与「附加工具」「证据附录」按需切换。
- 模拟结论、达人候选和异常情景会显示 `Mock`、种子与证据边界，不能当作真实平台或账户事实。

接口也支持可复现 Mock：

```text
POST /analyze?use_model=false&allow_mock=true&mock_seed=demo-001
```

相同请求与相同 `mock_seed` 会得到相同的 Mock 模块；真实或已导入的证据始终优先，不会被 Mock 覆盖。

### 实时数据源（`use_realtime_feed`）

`POST /analyze?use_realtime_feed=true` 会把 `POST /feeds/pull` 已落库的实时数据源条目
合并进本次请求的证据区（`trace` 记 `realtime_feed_merge`）；**当前接的是模拟源**，
条目一律 `is_mock=true` / `evidence_grade=M`，同名热搜词与同名竞品不覆盖真实证据，
不能当作真实趋势或竞品事实。

配套端点：`POST /feeds/pull`（拉一批并落库，同 seed 可复现）、
`GET /feeds/status`（库存与数据源政策声明）、`GET /feeds/latest`（最近批次原文）；
`scripts/feed_daemon.py` 可周期性调用 `/feeds/pull` 做持续拉取演示。
接口与真实源同构（`FeedAdapter` 协议），换真实源只需替换 adapter，下游不用改。

模块6 会在运行时直接从该库实时取值（`module_agents/module6._load_live_trending`
→ `FeedStore.latest_trending_with_previous`，同词取最近两批热度），把候选词交给
`evaluate_trending_keywords` 工具按固定规则判定趋势（rising/flat/cooling/unknown）
与是否跟进（跟进/观察/不跟进），结果落在 `trending_monitor.rising_keywords`；
库为空或读取失败时该数组留空并标注「待接入数据源」，绝不编造热搜结论。
`python demo_agent_loop.py --module6` 会在库为空时自动注入 2 批模拟数据，
演示「mock API 接口 → 数据库 → 模块运行时实时取值」完整链路。

### 命令行 demo

```bash
python demo_agent_loop.py --offline            # 离线：演示工具层校验与自我修正
python demo_agent_loop.py --module1            # 单模块端到端（--module1 … --module6）
python demo_agent_loop.py --pipeline           # 全流程：M1→M2→M6→M3→M4→M5，上游摘要注入下游
python demo_agent_loop.py --module4 --critic   # 叠加强模型 Critic 二审（只审文本不审数字）
python demo_agent_loop.py --pipeline --critic  # 全流程 + 逐模块二审
```

`--critic` 是可叠加 flag；除 `--offline` 外都需要 Analyzer Key。
详见 [使用说明书第 7 章「进阶功能」](docs/USER_GUIDE.md)。

## 会话状态与任务追踪

网页会在浏览器 `localStorage` 中生成一个会话 UUID，每次分析自动发送：

- `X-Session-ID`：同一浏览器会话的稳定标识；
- `Idempotency-Key`：单次提交的唯一标识，避免重复点击导致重复分析和重复计数。

分析成功后，接口响应以及网页下载的「小红书投放全案.json」都包含：

```json
{
  "report_id": "rpt_...",
  "session_state": {
    "session_id": "...",
    "analysis_count": 1,
    "last_report_id": "rpt_...",
    "last_brand_name": "曲奇四重奏",
    "last_product_name": "经典蝴蝶酥礼盒"
  }
}
```

状态保存在独立的本地 SQLite 文件中：

```text
xiaohongshu-agent/data/agent_state.db
```

该数据库记录会话摘要、分析记录、工作流 checkpoint、反馈、案例回填、公共缓存和幂等记录。它不会保存 Cookie、Authorization、API Key、Token、代理地址或完整 traceback。Mock 报告回填的案例会被强制标记为 `demo_case`。

状态查询接口：

- `GET /sessions/{session_id}`：会话摘要与累计成功分析次数；
- `GET /sessions/{session_id}/runs`：该会话最近的分析报告；
- `GET /workflows/{session_id}/{report_id}`：任务阶段和失败状态；
- `GET /state/status`：状态库各类记录数量；
- `POST /feedback`：保存报告反馈，支持 `Idempotency-Key`；
- `POST /backfilled-cases`：人工确认后沉淀案例；
- `POST /sessions/{session_id}/reset`：清除指定会话，保留公共缓存。

网页右上角会显示当前会话短 ID、成功分析次数和最近报告 ID；点击「新建会话」会换一个 UUID。旧会话仍保存在本地状态库中，除非显式调用 reset 接口。

仓库中有三个示例：

- `examples/cookie_quartet.json`：演示没有历史数据时的证据缺口处理。
- `examples/cookie_quartet_with_workbook_data.json`：已接入《数据需求.xlsx》的产品信息及 2026 年 1—5 月加权历史指标。
- `examples/cookie_quartet_full_case.json`：填满版（历史指标 + 品类笔记 + 达人 CSV + 热搜词 + 拒审台账）；配套 `examples/creators_cookie_quartet.csv`。

首页可一键「载入填满全案示例」。也支持上传达人 CSV、粘贴热搜词后生成方案。

原始工作簿的规范化只读快照保存在 `examples/data_requirements_normalized.json`，便于核对月度数据和派生指标。

## 模型配置

本项目**独立**读取目录内 `.env` 或 `course.env`（见 `.env.example`），不读取上级课程仓。
已在 shell 里 `export` 的变量优先，文件不会覆盖它们。

```env
AGENT_ANALYZER_API_KEY=...
AGENT_ANALYZER_BASE_URL=https://api.deepseek.com
AGENT_ANALYZER_MODEL=deepseek-v4-flash

# 或兼容旧变量
AGENT_OPENAI_API_KEY=...
AGENT_OPENAI_BASE_URL=https://api.siliconflow.cn/v1
AGENT_OPENAI_MODEL=Qwen/Qwen3-8B
```

模型不可用时，Agent 仍会生成确定性策略报告，并在 `trace` 中标记降级原因。

## 数据接入

原型接受人工导入或合规工具导出的证据。生产版可在 `data_sources` 中接入：

- 小红书官方公开页面、聚光平台自有账户报表；
- 品牌授权的历史投放 CSV/API；
- 获得合法授权的第三方数据分析工具；
- 人工核验的竞品笔记和达人资料。

禁止绕过登录、验证码、访问控制或平台条款进行抓取。

## 本地知识库

Agent 使用本机 SQLite 文件持久保存品类笔记：

```text
xiaohongshu-agent/data/xhs_knowledge.db
```

数据库文件属于本地运行数据，已加入 `.gitignore`，不会提交到 Git。知识库提供：

- 按 `note_id` 去重；重复导入会更新互动数据，不新增重复笔记；
- 保存采集关键词、标题、正文、标签、互动量、时间和证据来源；
- SQLite FTS5 全文索引，并使用标题、标签、关键词、正文和互动量做混合排序；
- 记录每次导入批次、导入时间、新增数和更新数；
- 生成方案时自动使用“品类 + 产品 + 核心卖点”检索最多 30 条相关证据；
- 在响应 `trace` 的 `local_knowledge_retrieval` 中记录检索词和命中数量。

网页中选择 `category_notes.json` 后会自动写入知识库。以后刷新页面无需重复上传，只要
勾选“自动检索本地知识库”，生成策略时就会自动召回相关笔记。

也可以在终端管理知识库：

```bash
# 在仓库根目录、已激活 venv 时：

# 导入（换成你本机上的规范化笔记 JSON 相对/绝对路径均可）
python knowledge_base.py import ./examples/your_category_notes.json

# 查看状态
python knowledge_base.py status

# 检索
python knowledge_base.py search "香港伴手礼" --limit 5
```

对应接口：

- `GET /knowledge/status`：知识库规模与最近导入时间；
- `POST /knowledge/import`：导入规范化笔记数组；
- `GET /knowledge/search?q=香港伴手礼&limit=10`：搜索证据；
- `POST /analyze?use_knowledge=true`：检索知识库后生成策略。

### 自动识别竞品

在页面“待识别竞品品牌”中填写候选品牌，每行一个。系统从本地知识库计算品牌提及笔记数、
独立作者数、品类相关笔记数、对比语境数和累计互动量：

- 至少 2 条笔记提及，且至少 1 条与当前品类相关：`可能竞品`，进入模块 1；
- 仅 1 条笔记提及：`待人工复核`；
- 没有相关笔记：`证据不足`。

识别过程记录在响应 `trace.competitor_identification`。广告/赞助标识不会自动猜测，必须打开
原笔记人工核验。
