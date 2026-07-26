# Real, Public, and Mock Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the Xiaohongshu decision report with the existing 205 real notes, verified public references, and clearly labeled Mock scenarios for fields that cannot be observed.

**Architecture:** Keep real note retrieval unchanged and add a field-level fallback layer in the strategy engine. Every returned metric carries a Chinese data-type label and provenance metadata; the API controls fallback with `allow_mock`, while the browser renders visible badges and never counts Mock data as real evidence.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, SQLite, pytest/unittest-compatible tests, vanilla JavaScript/HTML/CSS.

## Global Constraints

- Data priority is `真实样本 > 公开资料 > 模拟数据（Mock）`.
- Every Mock item has `data_type="模拟数据（Mock）"`, `is_mock=true`, `evidence_grade="M"`, `mock_basis`, and the exact warning from the design.
- Mock cannot assert named comments, orders, ad evidence, real targeting, real Spotlight accounts, or named creator performance.
- Mock rows do not enter note trend calculations or the overall evidence-confidence score.
- All user-facing field names, badges, and warnings are Chinese.

---

### Task 1: Mock Provenance Contract and Scenario Factory

**Files:**
- Create: `xiaohongshu-strategy-agent/mock_scenarios.py`
- Test: `xiaohongshu-strategy-agent/tests/test_mock_scenarios.py`

**Interfaces:**
- Consumes: `CampaignRequest.total_budget_cny`, `CampaignRequest.goal`, and an optional real metric dictionary.
- Produces: `evidence_meta(data_type, ...) -> dict[str, Any]`, `metric_or_mock(...) -> dict[str, Any]`, and `build_mock_market_scenarios(req) -> dict[str, Any]`.

- [ ] **Step 1: Write failing contract tests**

```python
def test_mock_metric_has_visible_provenance():
    row = metric_or_mock({}, "cpc", label="CPC", mock_value=2.8, unit="元/点击", basis="首轮测试中位情景")
    assert row["data_type"] == "模拟数据（Mock）"
    assert row["is_mock"] is True
    assert row["evidence_grade"] == "M"
    assert "不代表真实平台" in row["warning"]

def test_real_metric_wins_over_mock():
    row = metric_or_mock({"cpc": {"value": 1.9, "unit": "元/点击", "source": "品牌聚光报表", "collected_at": "2026-07-01"}}, "cpc", label="CPC", mock_value=2.8, unit="元/点击", basis="模拟")
    assert row["value"] == 1.9
    assert row["is_mock"] is False
```

- [ ] **Step 2: Run tests and confirm missing-module failure**

Run: `cd xiaohongshu-strategy-agent && ../.venv/bin/python -m unittest tests.test_mock_scenarios -v`

Expected: FAIL because `mock_scenarios` does not exist.

- [ ] **Step 3: Implement deterministic scenario metadata**

Use fixed, explainable scenario values rather than random numbers. Return low/base/high bands for CPC, CPM, conversion cost, search/feed budget share, budget range, targeting hypotheses, and duration hypotheses. All rows must include the provenance contract.

- [ ] **Step 4: Run focused tests**

Run: `cd xiaohongshu-strategy-agent && ../.venv/bin/python -m unittest tests.test_mock_scenarios -v`

Expected: PASS.

### Task 2: Engine and API Field-Level Fallback

**Files:**
- Modify: `xiaohongshu-strategy-agent/models.py`
- Modify: `xiaohongshu-strategy-agent/engine.py`
- Modify: `xiaohongshu-strategy-agent/main.py`
- Modify: `xiaohongshu-strategy-agent/tests/test_engine.py`

**Interfaces:**
- Consumes: `run_strategy(req, use_model=False, allow_mock=False)`.
- Produces: module outputs with per-field provenance and `trace[].allow_mock`.

- [ ] **Step 1: Add failing engine tests**

```python
def test_allow_mock_completes_missing_spotlight_metrics(self):
    result = run_strategy(self.request, use_model=False, allow_mock=True)
    cpc = result.modules["module_1_market_competitor"]["spotlight_market"]["average_cpc"]
    self.assertTrue(cpc["is_mock"])
    self.assertEqual(cpc["data_type"], "模拟数据（Mock）")

def test_disallow_mock_preserves_gap(self):
    result = run_strategy(self.request, use_model=False, allow_mock=False)
    self.assertIsNone(result.modules["module_1_market_competitor"]["spotlight_market"]["average_cpc"]["value"])

def test_real_benchmark_replaces_mock(self):
    request = self.request.model_copy(update={"benchmark_evidence": [real_cpc]})
    result = run_strategy(request, use_model=False, allow_mock=True)
    self.assertFalse(result.modules["module_1_market_competitor"]["spotlight_market"]["average_cpc"]["is_mock"])
```

- [ ] **Step 2: Run the focused engine tests**

Run: `cd xiaohongshu-strategy-agent && ../.venv/bin/python -m unittest tests.test_engine -v`

Expected: FAIL because `allow_mock` is not accepted.

- [ ] **Step 3: Thread `allow_mock` through the engine**

Update `run_strategy`, `_spotlight_market_summary`, and `_competitor_market_summary`. Add provenance to the real organic sample summary. Replace only missing values with factory output; do not add Mock notes to `category_note_evidence`.

- [ ] **Step 4: Add API query control**

Expose `allow_mock: bool = Query(default=True, description="是否用明确标识的模拟数据补足缺失指标")` in `/analyze`, pass it to `run_strategy`, and append it to trace metadata.

- [ ] **Step 5: Run focused tests**

Run: `cd xiaohongshu-strategy-agent && ../.venv/bin/python -m unittest tests.test_engine -v`

Expected: PASS.

### Task 3: Chinese Mock Badges and Browser Control

**Files:**
- Modify: `xiaohongshu-strategy-agent/web/index.html`
- Modify: `xiaohongshu-strategy-agent/web/app.js`
- Modify: `xiaohongshu-strategy-agent/web/style.css`

**Interfaces:**
- Consumes: objects containing `data_type` and `is_mock`, plus form checkbox `#allowMock`.
- Produces: `/analyze?...&allow_mock=true|false` and an inline Chinese badge beside every Mock object/table row.

- [ ] **Step 1: Add the form switch**

Add a checked checkbox labeled `允许使用明确标识的模拟数据补足缺失指标` and explanatory copy that Mock is not a real platform or account fact.

- [ ] **Step 2: Send the query flag**

Build the request URL as:

```javascript
const allowMock = $("#allowMock").checked;
const response = await fetch(`/analyze?use_model=${useModel}&use_knowledge=${useKnowledge}&allow_mock=${allowMock}`, options);
```

- [ ] **Step 3: Render inline badges**

Add `数据类型`, `是否模拟`, `模拟依据`, `证据等级`, and `适用日期` to `fieldNames`. In `tree()` and `table()`, render `<span class="data-badge mock">模拟数据（Mock）</span>` whenever the current object or row has `is_mock === true`; add separate real/public badge styles.

- [ ] **Step 4: Add accessible styles**

Use high-contrast orange for Mock, green for real samples, and blue for public sources. Preserve text labels so color is not the only indicator.

- [ ] **Step 5: Perform static validation**

Run: `grep -n "allowMock\|模拟数据（Mock）\|data-badge" xiaohongshu-strategy-agent/web/{index.html,app.js,style.css}`

Expected: switch, query flag, renderer, and styles are all present.

### Task 4: End-to-End Analysis and Regression Verification

**Files:**
- Modify: `xiaohongshu-strategy-agent/tests/test_engine.py`
- Modify: `xiaohongshu-strategy-agent/docs/TEST_REPORT.md`

**Interfaces:**
- Consumes: SQLite knowledge base with 205 real notes and the `/analyze` endpoint.
- Produces: a verified complete report where real sample calculations remain real and only absent metrics are Mock.

- [ ] **Step 1: Add regression assertions**

Assert that organic market `sample_size > 0`, organic market is not Mock, missing CPC is Mock when enabled, and the same CPC is null when disabled. Assert no Mock item uses factual phrases such as `竞品正在投放` or `真实定向`.

- [ ] **Step 2: Run all tests**

Run: `cd xiaohongshu-strategy-agent && ../.venv/bin/python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 3: Exercise the API locally without model calls**

Use FastAPI TestClient or direct `analyze()` invocation with the full-case payload and `use_model=False`. Confirm the report contains all modules, the retrieved real-note sample count, visible Mock metadata, and no network collection.

- [ ] **Step 4: Update the test report**

Record test count, commands, real-note count, fields supplied by Mock, and the explicit statement that no Xiaohongshu collection request was made.

- [ ] **Step 5: Commit implementation**

```bash
git add xiaohongshu-strategy-agent/mock_scenarios.py xiaohongshu-strategy-agent/models.py xiaohongshu-strategy-agent/engine.py xiaohongshu-strategy-agent/main.py xiaohongshu-strategy-agent/web xiaohongshu-strategy-agent/tests xiaohongshu-strategy-agent/docs/TEST_REPORT.md xiaohongshu-strategy-agent/docs/superpowers/plans/2026-07-24-real-public-mock-analysis.md
git commit -m "feat: label mock fallbacks in strategy analysis"
```
