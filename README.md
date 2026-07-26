# 小红书投放策略决策 AI Agent

独立可运行的本地原型（仓库路径：`/Users/llan/Documents/xiaohongshu-agent`）。  
把品牌输入、合规证据与预算约束编排为 **6 个策略模块 + 附加工具**，输出结构化 JSON、可执行 Markdown 与网页看板。

## 作业交付物（五份）

| # | 交付项 | 入口 |
| --- | --- | --- |
| 1 | 可运行的 Agent 原型 | 本 README「启动」+ `web/` 网页输入参数生成 |
| 2 | 使用说明书 | [docs/USER_GUIDE.md](docs/USER_GUIDE.md) |
| 3 | 测试报告（曲奇四重奏） | [docs/TEST_REPORT.md](docs/TEST_REPORT.md) |
| 4 | 技术架构图 | [docs/ARCHITECTURE_OVERVIEW.md](docs/ARCHITECTURE_OVERVIEW.md) |
| 5 | 后续优化方向 | [docs/OPTIMIZATION_ROADMAP.md](docs/OPTIMIZATION_ROADMAP.md) |

完整索引：[docs/DELIVERABLES.md](docs/DELIVERABLES.md)

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

详见 [架构总览](docs/ARCHITECTURE_OVERVIEW.md)、[技术架构详述](docs/TECHNICAL_ARCHITECTURE.md)、
[测试报告](docs/TEST_REPORT.md)、[使用说明书](docs/USER_GUIDE.md)、[优化方向](docs/OPTIMIZATION_ROADMAP.md)。  
需求逐条覆盖对照见 [REQUIREMENTS_COVERAGE.md](docs/REQUIREMENTS_COVERAGE.md)。

## 启动（本目录独立运行）

```bash
cd /Users/llan/Documents/xiaohongshu-agent

# 1. 虚拟环境 + 依赖
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt

# 2. 模型 Key（任选其一）
cp .env.example .env               # 编辑填入 AGENT_ANALYZER_API_KEY 等
# 或：export AGENT_ANALYZER_API_KEY=... ; export AGENT_ANALYZER_BASE_URL=...

# 3. 启动 API（保持终端打开）
python -m uvicorn main:app --host 127.0.0.1 --port 8010
```

看到下面的信息表示启动成功：

```text
Uvicorn running on http://127.0.0.1:8010
```

需要停止时，在该终端按 `Control + C`。

不建议直接运行 `python main.py`（默认开启 Uvicorn reload；部分 macOS / 受限环境可能报
`[Errno 1] Operation not permitted`）。上面的命令不启用自动重载，更适合日常演示。

可以在另一个终端检查服务：

```bash
curl --noproxy '*' http://127.0.0.1:8010/health
```

正常返回：

```json
{"status":"ok","agent":"xiaohongshu-strategy"}
```

打开：

- 用户操作界面：http://127.0.0.1:8010/
- API 文档：http://127.0.0.1:8010/docs
- 健康检查：http://127.0.0.1:8010/health

优先使用 `127.0.0.1`。如果电脑配置了 HTTP/SOCKS 代理，`localhost` 有时可能被错误地
发送给代理而出现 `502` 或连接失败。

## Docker 运行

无需在本机安装 Python 依赖，用 Docker 即可构建并运行。以下命令在本项目目录
（`xiaohongshu-agent/`）执行。

```bash
# 1. 构建镜像
docker compose build

# 2. 跑全部单元测试（29 个文件 / 332 个方法）
docker compose run --rm agent python -m unittest discover tests

# 3. 跑离线 Agent Loop 演示（不联网、不调用大模型）
docker compose run --rm agent python demo_agent_loop.py --offline

# 3b. 跑离线回归评分（不联网，期望总分 100/100）
docker compose run --rm agent python bench/run_bench.py \
  --replay bench/fixtures/regression_outputs.json --no-write

# 4. 起 API 服务（后台常驻），访问 http://127.0.0.1:8010/
docker compose up -d agent
```

说明：

- 服务监听容器内 8010 端口并映射到宿主机 `8010:8010`，启动方式为
  `uvicorn main:app --host 0.0.0.0 --port 8010`（不启用 reload）。
- 模型 Key 通过环境变量传入。可在运行前 `export AGENT_OPENAI_API_KEY=...`，
  compose 会自动透传；同理可覆盖 `AGENT_OPENAI_BASE_URL`
  （默认 `https://api.siliconflow.cn/v1`）和 `AGENT_OPENAI_MODEL`
  （默认 `Qwen/Qwen3-8B`）。未配置 Key 时 Agent 仍会生成确定性报告并标记降级。
- SQLite 数据通过 `./data:/app/data` 卷持久化，容器重建后
  `xhs_knowledge.db`、`agent_state.db` 等数据仍保留在宿主机 `data/` 目录。

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
cd xiaohongshu-agent
source .venv/bin/activate

# 导入（路径换成你本地的规范化笔记 JSON）
python knowledge_base.py import path/to/category_notes.json

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
