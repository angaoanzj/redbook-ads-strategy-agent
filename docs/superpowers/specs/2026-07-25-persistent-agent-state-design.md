# 小红书策略 Agent 持久化状态设计

## 目标

为当前小红书投放策略 Agent 增加课程中六类运行状态能力，并将课程级全局内存对象升级为本地 SQLite 持久化实现。系统应能够跨服务重启保留会话和运行轨迹，同时避免把 Cookie、密钥、代理配置、完整采集数据或大段报告写入状态库。

本期覆盖：

1. 会话状态；
2. 用户反馈；
3. 回填案例；
4. 公共命中缓存；
5. 工作流 checkpoint；
6. 幂等提交记录；
7. 轻量分析历史。

本期不实现多用户账号体系、分布式锁、自动从 checkpoint 恢复、Redis、消息队列或云数据库。

## 设计原则

- 状态编排和策略计算分离：`run_strategy()` 保持确定性计算职责，状态读写由编排层完成。
- SQLite 六类业务表分开存储，使用数据库唯一约束保证关键一致性。
- 前端无需用户填写会话 ID；浏览器生成 UUID 并保存在 `localStorage`。
- 真实证据优先于 Mock；Mock 回填案例必须保留演示标识，不能变成真实业务案例。
- 状态只保存轻量摘要和引用，不复制知识库笔记正文或完整报告。
- 所有时间使用带时区的 ISO 8601 UTC 字符串。
- 状态库中禁止出现 Cookie、Authorization、API Key、代理地址或完整异常堆栈。

## 架构

新增 `AgentStateStore` 作为状态存储边界，FastAPI `/analyze` 作为第一阶段编排入口：

```text
浏览器 / API
    ↓ X-Session-ID + Idempotency-Key
FastAPI /analyze
    ↓
Agent 编排层
    ├── 校验幂等键
    ├── 创建/更新 session
    ├── 查询公共命中缓存
    ├── 写入 workflow checkpoint
    ├── 调用现有 run_strategy()
    ├── 写入 analysis run 与会话摘要
    └── 完成幂等记录
            ↓
      AgentStateStore
            ↓
          SQLite
```

`AgentStateStore` 提供明确的方法，而不是让 API 路由直接拼 SQL。状态库使用独立 SQLite 文件，和现有品类知识库逻辑隔离。

## 数据模型

### `agent_sessions`

- `session_id`：主键，UUID 字符串。
- `analysis_count`：成功分析次数。
- `last_report_id`：最近报告引用。
- `last_brand_name`、`last_product_name`、`last_category`、`last_goal`。
- `last_mock_seed`：最近 Mock 种子，可为空。
- `last_summary_json`：最近管理层摘要的受控 JSON。
- `created_at`、`updated_at`。

### `analysis_runs`

- `report_id`：主键。
- `session_id`：关联会话。
- `brand_name`、`product_name`、`category`、`goal`。
- `mock_seed`、`data_confidence`。
- `summary_json`：管理层摘要。
- `source_counts_json`：知识库、规则、指标等数量摘要。
- `created_at`。

每个会话接口默认只返回最近 10 次记录。第一版不自动删除更早记录，但不在默认查询中返回。

### `feedback_records`

- `feedback_id`：主键。
- `session_id`、`report_id`。
- `rating`：`满意`、`一般` 或 `不满意`。
- `comment`：可选文字意见。
- `sections_json`：需要修改的章节列表。
- `idempotency_key`：唯一键。
- `created_at`。

反馈不会自动改写正式报告。

### `backfilled_cases`

- `case_id`：主键。
- `session_id`、`report_id`。
- `brand_name`、`category`、`problem_summary`、`strategy_summary`。
- `evidence_grade`。
- `case_type`：`verified_case` 或 `demo_case`。
- `is_mock`。
- `created_at`、`updated_at`。

只有用户明确确认采用的人工修正版才能写入。只要来源报告包含 Mock，该案例默认只能成为 `demo_case`。

### `common_hit_cache`

- `cache_key`：主键，由功能名、输入摘要和数据版本计算。
- `namespace`。
- `payload_json`。
- `source_version`。
- `expires_at`、`created_at`、`updated_at`。

只缓存不含用户隐私的稳定公共结果。默认 TTL 为 24 小时；官方规则类缓存可以使用 7 天。过期记录不再命中。

### `workflow_checkpoints`

- 复合唯一键：`session_id + report_id + stage`。
- `stage`：`received`、`evidence_ready`、`strategy_generated`、`report_generated`、`completed` 或 `failed`。
- `status`。
- `context_json`：轻量上下文。
- `error_summary`：脱敏错误摘要。
- `created_at`、`updated_at`。

第一版 checkpoint 用于观察、审计和定位，不从中间阶段自动恢复执行。

### `submitted_actions`

- `idempotency_key`：主键。
- `action_type`：如 `analyze`、`feedback`。
- `request_hash`。
- `session_id`、`report_id`。
- `status`：`processing`、`completed` 或 `failed`。
- `response_summary_json`。
- `expires_at`、`created_at`、`updated_at`。

相同键和相同请求摘要返回原结果引用；相同键配不同请求摘要返回 HTTP 409。默认保留 24 小时。

## API 设计

### 分析接口

现有请求体保持不变，增加可选请求头：

```http
X-Session-ID: <uuid>
Idempotency-Key: <unique-key>
```

未提供 `X-Session-ID` 时由后端创建。未提供幂等键时仍允许分析，但不能获得重复提交保护。

`StrategyResponse` 增加：

```json
{
  "report_id": "rpt_xxx",
  "session_state": {
    "session_id": "uuid",
    "analysis_count": 3,
    "last_report_id": "rpt_xxx",
    "last_brand_name": "曲奇四重奏",
    "last_product_name": "经典蝴蝶酥礼盒",
    "updated_at": "2026-07-25T00:00:00+00:00"
  }
}
```

### 状态接口

- `GET /sessions/{session_id}`：读取会话摘要。
- `GET /sessions/{session_id}/runs?limit=10`：读取最近分析记录。
- `POST /feedback`：提交报告评分、意见和关联章节，支持幂等。
- `POST /backfilled-cases`：明确确认后写入回填案例。
- `GET /workflows/{session_id}/{report_id}`：读取 checkpoint 时间线。
- `GET /state/status`：返回各状态表计数及有效/过期缓存数量。
- `POST /sessions/{session_id}/reset`：重置该会话运行状态，不影响知识库。

`reset` 删除目标会话的 session、analysis run、feedback、checkpoint 和相关幂等记录；不删除全局公共缓存和品类知识库。前端“新建会话”只切换 UUID，不调用 `reset`。

## 分析状态流转

一次成功分析按以下顺序执行：

1. 规范化或创建 `session_id`。
2. 根据请求内容计算稳定 `request_hash`。
3. 校验 `Idempotency-Key`。
4. 创建 `report_id` 和 `received` checkpoint。
5. 检索知识库与公共缓存。
6. 写入 `evidence_ready` checkpoint。
7. 调用现有 `run_strategy()`。
8. 写入 `strategy_generated` 和 `report_generated` checkpoint。
9. 在一个数据库事务中写入 `analysis_runs`、更新 `agent_sessions.analysis_count`、完成幂等记录。
10. 写入 `completed` checkpoint并返回响应。

失败时写入 `failed` checkpoint 和脱敏错误摘要。失败分析不增加 `analysis_count`。

## 前端交互

- 首次加载读取 `localStorage.xhs_agent_session_id`；不存在时生成 UUID。
- `/analyze` 请求发送 `X-Session-ID` 和新生成的 `Idempotency-Key`。
- 页面显示短会话 ID、成功分析次数和最近报告 ID。
- “新建会话”生成并保存新 UUID，清空当前页面结果，但不删除旧会话。
- 下载 JSON 和 Markdown 的现有行为不变。
- 前端不显示或存储 Cookie、API Key、代理信息。

## 并发与错误处理

- SQLite 连接启用 WAL 和合理的 busy timeout。
- 会话计数使用单条原子 SQL 更新或事务，不能在 Python 中先读后写。
- 唯一约束处理反馈和幂等竞争；重复写入转换为可解释的既有结果或 409。
- JSON 反序列化失败视为内部状态损坏，接口返回安全错误，不输出数据库行或堆栈。
- 状态接口找不到对象时返回 404。
- 无效 session ID、过长幂等键和非法评分返回 422。

## 安全与数据边界

写入前对状态 payload 做递归键名检查，拒绝或剔除以下字段及常见变体：

- `cookie`；
- `authorization`；
- `api_key`、`token`、`secret`；
- `proxy`；
- 完整异常 traceback。

缓存不接受达人私有数据、账户级指标原表或用户上传文件原文。状态库只保存策略摘要、计数、引用和必要操作上下文。

## 测试与验收

采用测试驱动实现，至少覆盖：

1. 同一会话成功分析后计数累加。
2. 重新创建 `AgentStateStore` 后仍能读取会话。
3. 不同 session 互不污染。
4. 重复幂等请求不重复增加计数。
5. 相同幂等键配不同请求返回 409。
6. 正常路径 checkpoint 顺序完整。
7. 失败路径存在 `failed` checkpoint，且计数不增加。
8. Mock 报告回填只能成为 `demo_case`。
9. 公共缓存命中、过期和版本变化行为正确。
10. 重复反馈只保存一次。
11. 敏感键不能进入任一 JSON 状态字段。
12. 前端生成并复用 session ID，可主动新建会话。
13. 现有全部策略、API 和网页回归测试继续通过。

完成标准是 API、SQLite 和前端共同表现出可观察、可持久化且可审计的六类状态；关闭并重新启动服务后，会话状态仍可查询。
