# 第一阶段：证据驱动分析设计

## 目标

将小红书投放策略 Agent 的第一阶段从“确定性模板脚手架”提升为“证据驱动的可审计分析器”，优先修复模块1、3、4、6。第一阶段不绕过平台登录、验证码或访问控制，不把缺失数据伪装成事实。

## 范围

### 包含

- 模块1：赛道与竞品深度分析
- 模块3：关键词与达人
- 模块4：聚光前置决策
- 模块6：关键词策略
- 本地 Excel/CSV/JSON 导入
- 可替换的合规 API 适配器接口
- 证据来源、样本量、时间范围、置信度和缺口输出
- 真实数据优先策略
- 竞品聚光账户模拟数据的独立边界设计，但不把模拟数据当作真实数据

### 不包含

- 绕过登录、验证码、访问控制或设备风控的采集
- 竞品聚光后台真实账户数据的非法获取
- 真实成交额、ROAS、CPA 的推断性补齐
- 第一阶段全面重写前端
- 与当前任务无关的数据库迁移或 Docker 重构

## 数据接入原则

数据来源分为三类：

1. `real_authorized`：品牌自有聚光/电商/内容后台导出，或品牌授权 API。
2. `public_observation`：公开笔记和公开品牌资料，保存 URL、采集时间和字段范围。
3. `mock_competitor_spotlight`：仅用于开发和演示的竞品聚光账户结构模拟，必须显式标记 `is_mock=1`，不进入真实效果计算。

数据优先级：

```text
real_authorized > public_observation > mock_competitor_spotlight
```

Mock 只能填补目标字段没有任何真实记录的展示或测试场景，不能覆盖已有真实记录，也不能参与“真实市场结论”的置信度计算。

## 统一证据结构

新增或统一的数据记录至少包含：

```text
source_type
source_name
source_url
collected_at
as_of
metric_name
value
unit
dimensions
sample_size
evidence_grade
is_mock
```

每个分析结论至少包含：

```text
finding
evidence_refs
sample_size
as_of
confidence
limitations
next_collection_action
```

## 分析器边界

### MarketCompetitorAnalyzer（模块1）

回答：赛道内容发生了什么、竞品公开内容做了什么、哪些内容存在空白、哪些结论不能推出。

输入：公开笔记、品牌资料、用户导入的竞品链接、广告标识人工核验记录、平台/品牌投放报表。

输出：

- 品类样本趋势；若没有逐篇发布时间，只输出样本分布，不输出流量高峰
- 内容主题、形式、互动和收藏结构
- 竞品自然内容共性和空白
- 广告标识、投放时间、预算和定向的证据状态
- 风险项及对应处理方案

### KeywordCreatorAnalyzer（模块3）

回答：哪些关键词有证据支持、哪些达人值得进入候选池、下一步需要采集什么。

输入：真实关键词数据、搜索热度、竞品笔记、授权达人导出、历史合作效果。

输出：

- 关键词的搜索量、竞争度、意向和证据等级
- 真实达人候选；无真实达人数据时只输出筛选规则和空缺字段，不输出虚构名单
- 出价建议仅基于实际 CPC 或明确标注为测试区间

### SpotlightDecisionAnalyzer（模块4）

回答：应该如何设计最小测试、什么条件下放量、什么条件下停止或回滚。

输入：真实历史投放、目标、素材、词包、人群、预算和成交归因。

输出：

- 测试单元：素材 × 词包 × 人群 × 搜推位
- 最小测试预算和观察窗口
- CTR、CPC、搜索组件转化率、互动成本等前置触发器
- 有成交归因时才计算 ROAS/CPA；没有时输出“不可计算”
- 风险问题、处理方案、触发条件和回滚动作

### KeywordStrategyAnalyzer（模块6）

回答：如何管理品牌词、品类词、场景词、竞品词和热搜词，以及如何监控变化。

输入：关键词历史表现、热搜导入、搜索组件数据和内容样本。

输出：

- 关键词分层和模块职责
- 搜索词变化、词包表现和风险词
- 热搜监控接口状态
- 与模块3的分工：模块3负责发现和候选，模块6负责投放布局和持续监控

## 合规 API 适配器

定义适配器协议，不绑定某个平台 SDK：

```python
class AuthorizedDataSource(Protocol):
    def fetch(self, query: SourceQuery) -> SourceBatch: ...
```

第一阶段先实现：

- `WorkbookSource`：Excel/CSV/JSON
- `PublicObservationSource`：已人工核验的公开笔记记录
- `AuthorizedApiSource`：接口骨架、权限状态和错误状态，不在没有凭证时假装可用

适配器必须记录授权范围、请求时间、返回条数和失败原因。

## 多 Agent 编排

第一阶段不引入重量级 LangChain/CrewAI 依赖，先使用清晰的 Agent 接口实现可测试分工：

```text
EvidenceIngestionAgent
        ↓
DataQualityAgent
        ↓
MarketCompetitorAgent ─┐
KeywordCreatorAgent    ├─→ EvidenceMergerAgent → ReportAgent
SpotlightDecisionAgent ┤
KeywordStrategyAgent ──┘
```

每个 Agent 只消费标准化证据，不能直接读取未审计的原始数据并生成事实结论。

## 失败和缺口处理

- 数据源缺失：返回缺口、影响、推荐来源和最小补充字段。
- 指标定义冲突：保留原始字段，标记口径冲突，不自动合并。
- API 无权限：返回 `authorization_required`，不回退到绕过采集。
- 真实数据不足：允许输出测试方法，不输出虚构的市场结论。
- Mock 数据存在：默认过滤；只有显式 `allow_mock=true` 的开发/演示请求才可使用。

## 验收标准

- 模块1没有逐篇发布时间时不输出真实流量高峰。
- 模块3没有真实达人证据时不输出“待筛选达人01—20”作为推荐名单。
- 模块4没有成交额和订单时不输出 ROAS、真实 CPA 或成交预测。
- 模块4风险项包含问题、证据、应对方案、触发条件和回滚动作。
- 模块6的热搜监控区分“未接入”“人工导入”和“API 导入”。
- 所有关键结论带来源、样本量、时间和置信度。
- 真实数据优先，Mock 不覆盖真实记录。
- 现有测试保持通过，并新增针对上述行为的失败优先测试。

