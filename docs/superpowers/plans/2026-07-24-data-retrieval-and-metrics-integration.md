# 数据检索与真实指标接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `/analyze` 自动使用知识库中的真实投放/内容数据，并修正公开笔记采集、去重、时间窗口、证据过滤和字段完整性问题。

**Architecture:** 保留现有 FastAPI + SQLite + 确定性引擎结构，新增知识库查询方法和标准化指标转换层。请求参数控制分析窗口和是否允许 Mock；默认只返回真实/公开证据。采集端继续只处理合规导入或已人工核验的公开数据，不增加绕过登录、验证码或访问控制的逻辑。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、SQLite/FTS5、unittest。

## Global Constraints

- 真实授权数据优先于公开观察数据；Mock 默认不参与分析。
- 没有订单/成交额时禁止输出真实 ROAS、CPA、CAC 或成交预测。
- 没有逐篇发布时间时禁止输出真实流量高峰。
- 不绕过平台登录、验证码、访问控制或设备风控。
- 任何新增字段必须保留来源、采集时间、分析时间范围和证据等级。

---

### Task 1: 增加真实指标查询与标准化转换

**Files:**
- Modify: `knowledge_base.py`
- Modify: `models.py`
- Test: `tests/test_knowledge_base.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Add `KnowledgeBase.get_brand_metrics(brand_name, start_period, end_period, metric_kind) -> dict`.
- Add `KnowledgeBase.get_brand_products(brand_name) -> list[dict]`.
- Add `KnowledgeBase.get_organic_periods(brand_name, start_period, end_period) -> list[dict]`.
- Add `KnowledgeBase.metric_evidence_for_campaign(brand_name, analysis_days) -> list[MetricEvidence]`.

- [ ] **Step 1: Write failing tests** for retrieving 2026-01 to 2026-05 `paid_metrics`, converting `消费/曝光量/点击量/平均点击成本/平均千次展现费用` into `MetricEvidence`, and excluding any table whose evidence grade is `MOCK_*`.
- [ ] **Step 2: Run the focused tests** with `../.venv/bin/python -m unittest tests.test_knowledge_base tests.test_engine -v`; confirm failure because the query methods do not exist.
- [ ] **Step 3: Implement the smallest query layer** that reads the existing JSON rows, filters year/month by the requested window, validates numeric fields, and attaches `source_name`, `collected_at`, `evidence_grade`, `sample_size`, and `is_mock` metadata.
- [ ] **Step 4: Run focused tests** and confirm the real workbook rows are returned with `is_mock=0`.
- [ ] **Step 5: Run the full Python test suite** and keep all existing tests green.

### Task 2: Connect real metrics to `/analyze`

**Files:**
- Modify: `main.py`
- Modify: `engine.py`
- Modify: `models.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Add `use_knowledge` retrieval trace fields: `paid_metric_count`, `organic_period_count`, `metric_sources`, `analysis_window`.
- `run_strategy()` receives normalized `benchmark_evidence` derived from the knowledge base only when the request did not provide an explicit evidence item for the same metric.

- [ ] **Step 1: Write failing tests** asserting that an analysis request with no manual benchmark evidence receives real CPC/CPM evidence from the local database, while an explicit request metric wins for the same metric.
- [ ] **Step 2: Run the focused engine tests** and confirm failure because `/analyze` currently retrieves notes/rules only.
- [ ] **Step 3: Implement merge precedence**: request-supplied authorized evidence > local real evidence > no evidence; append provenance to the trace without replacing raw request data.
- [ ] **Step 4: Update the module 1/4 outputs** to expose source, period, sample size, and evidence grade for CPC/CPM/search metrics.
- [ ] **Step 5: Run the full suite** and inspect a real `cookie_quartet` response for the expected evidence trace.

### Task 3: Make note retrieval time-aware, evidence-aware, and diverse

**Files:**
- Modify: `knowledge_base.py`
- Modify: `main.py`
- Modify: `models.py`
- Test: `tests/test_knowledge_base.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Extend `KnowledgeBase.search(terms, limit=30, analysis_days=None, as_of=None, source_names=None, evidence_grades=None, allow_mock=False, diversify_by_author=True)`.
- `CategoryNoteEvidence` gains optional `platform`, `author_id`, `author_followers_snapshot`, `views`, `ad_label_status`, `ad_evidence_url`, and `metric_snapshot_at` fields.

- [ ] **Step 1: Write failing tests** for date-window filtering, Mock exclusion, source/evidence filtering, and per-author diversity.
- [ ] **Step 2: Run the tests** and confirm the existing search signature cannot enforce those constraints.
- [ ] **Step 3: Add schema columns with backward-compatible defaults** and update import/row conversion logic.
- [ ] **Step 4: Implement filtered ranking**: exact phrase/title/tag matches first, then field match strength, then interaction quality; apply date/source/evidence filters before ranking and cap repeated authors.
- [ ] **Step 5: Update `/analyze`** to pass `analysis_days` and to report filtered vs total retrieval counts.
- [ ] **Step 6: Run the full test suite** and verify the existing 205-note database still opens without migration errors.

### Task 4: Harden competitor identification and source provenance

**Files:**
- Modify: `knowledge_base.py`
- Modify: `models.py`
- Test: `tests/test_knowledge_base.py`

**Interfaces:**
- Add optional competitor aliases and normalized entity fields to `CompetitorEvidence`.
- Add `KnowledgeBase.identify_competitors(..., analysis_days=None, as_of=None, allow_mock=False)`.

- [ ] **Step 1: Write failing tests** for alias matching, false-positive avoidance, time filtering, and evidence-grade filtering.
- [ ] **Step 2: Run the tests** and confirm the current raw substring matching fails the cases.
- [ ] **Step 3: Implement normalized candidate entities** using exact brand/alias tokens, comparison context, independent author count, and category relevance.
- [ ] **Step 4: Return evidence references** including note IDs, URLs, source, snapshot date, and ad-label status; never infer real budget or targeting.
- [ ] **Step 5: Run all tests** and inspect competitor results for the current knowledge base.

### Task 5: Audit and document collection fields and import validation

**Files:**
- Modify: `scripts/import_brand_workbook.py`
- Modify: `docs/DATA_RETRIEVAL_AUDIT.md`
- Create: `docs/DATA_COLLECTION_SCHEMA.md`
- Test: `tests/test_knowledge_base.py`

**Interfaces:**
- Import validation returns `accepted_fields`, `missing_fields`, `type_warnings`, `source_metadata`, and `mock_rows_rejected`.
- Add explicit column mappings for workbook products, monthly paid metrics, and monthly organic metrics.

- [ ] **Step 1: Write failing tests** for missing source metadata, numeric parse warnings, period normalization, and rejection of Mock rows in real imports.
- [ ] **Step 2: Run focused import tests** and confirm the current importer has no validation report.
- [ ] **Step 3: Implement validation and a schema document** covering note, product, paid, organic, account, campaign, creative, audience, order attribution, and violation fields.
- [ ] **Step 4: Re-run the existing workbook import into a temporary database** and compare row counts and representative values with the current database.
- [ ] **Step 5: Run the full suite and record the final audit output**.

