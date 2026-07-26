# Human-Readable Analysis Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the default evidence-tree result with a human-readable Xiaohongshu strategy report that combines executive decisions, lightweight charts, operator actions, and a collapsible evidence appendix.

**Architecture:** Add a focused `report_view.py` layer that consumes the existing six-module output and deterministically produces an executive summary, four required analysis sections, and prioritized actions. Add the view model to `StrategyResponse`, generate Markdown from the same model, and update the vanilla-JavaScript frontend to render the report by default while preserving the existing tree renderer for evidence only.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, vanilla JavaScript, native SVG/CSS, unittest.

## Global Constraints

- The report defaults to Chinese and must be readable without expanding evidence objects.
- The four chapters are natural traffic, Spotlight advertising, competitor full-funnel, and risk/compliance.
- Every chapter contains conclusion, data explanation, analysis, actions, success metrics, and evidence boundary.
- Real/authorized evidence always overrides Mock; Mock labels and `mock_seed` remain visible.
- Missing values remain missing and are never rendered as zero.
- The same request and Mock seed produce the same view model and Markdown.
- The LLM may polish controlled prose only; deterministic output remains complete when the LLM is disabled or unavailable.
- No external request, Xiaohongshu collection, heavy chart dependency, PDF, or PPT work is in scope.

---

### Task 1: Deterministic Report View Model

**Files:**
- Create: `xiaohongshu-strategy-agent/report_view.py`
- Modify: `xiaohongshu-strategy-agent/models.py`
- Create: `xiaohongshu-strategy-agent/tests/test_report_view.py`

**Interfaces:**
- Consumes: `build_report_view(req: CampaignRequest, modules: dict[str, Any], gaps: list[EvidenceGap], data_confidence: str) -> dict[str, Any]`.
- Produces: a dictionary with `executive_summary`, `report_sections`, `action_plan`, and `evidence_appendix`.
- Produces: `render_report_markdown(req: CampaignRequest, report_view: dict[str, Any]) -> str`.

- [ ] **Step 1: Write failing view-model contract tests**

```python
class ReportViewTests(unittest.TestCase):
    def test_report_contains_four_human_readable_sections(self):
        result = run_strategy(sample_request(), use_model=False, allow_mock=True, mock_seed="report-ui-a")
        view = result.report_view
        self.assertEqual(
            [row["key"] for row in view["report_sections"]],
            ["organic", "spotlight", "competitor", "risk"],
        )
        for section in view["report_sections"]:
            for field in ("decision", "analysis", "actions", "success_metrics", "evidence_boundary"):
                self.assertTrue(section[field])

    def test_executive_summary_is_decision_oriented(self):
        result = run_strategy(sample_request(), use_model=False, allow_mock=True, mock_seed="report-ui-a")
        summary = result.report_view["executive_summary"]
        self.assertTrue(summary["strategic_thesis"])
        self.assertGreaterEqual(len(summary["key_findings"]), 3)
        self.assertEqual(len(summary["priority_actions"]), 3)
```

- [ ] **Step 2: Run tests and confirm the missing `report_view` failure**

Run: `cd xiaohongshu-strategy-agent && ../.venv/bin/python -m unittest tests.test_report_view -v`

Expected: FAIL because `StrategyResponse` has no `report_view` and the builder does not exist.

- [ ] **Step 3: Add the response field**

Add to `StrategyResponse`:

```python
report_view: dict[str, Any]
```

- [ ] **Step 4: Implement small report builder helpers**

Create these functions in `report_view.py`:

```python
def build_executive_summary(req, modules, gaps, data_confidence) -> dict[str, Any]: ...
def build_organic_section(req, module1) -> dict[str, Any]: ...
def build_spotlight_section(req, module1) -> dict[str, Any]: ...
def build_competitor_section(req, module1) -> dict[str, Any]: ...
def build_risk_section(req, module1) -> dict[str, Any]: ...
def build_action_plan(req, modules) -> list[dict[str, Any]]: ...
def build_report_view(req, modules, gaps, data_confidence) -> dict[str, Any]: ...
```

Each section returns:

```python
{
    "key": "organic",
    "chapter_number": 1,
    "title": "自然流量大盘分析",
    "decision": "...",
    "data_explanation": ["..."],
    "analysis": ["...", "..."],
    "actions": ["..."],
    "success_metrics": ["..."],
    "evidence_boundary": "...",
    "is_mock": False,
    "mock_seed": None,
    "visuals": {"metric_cards": [], "trend_series": [], "tables": []},
}
```

Use existing `decision_conclusion`, `status`, series, budget shares, competitor rows, and risk rows. Do not invent new facts. When a list is empty, provide a data-acquisition or controlled-test action instead of a number.

- [ ] **Step 5: Implement prioritized actions**

Each action has the exact shape:

```python
{
    "priority": "P1",
    "title": "验证高意向搜索承接",
    "why": "...",
    "steps": ["..."],
    "budget_cny": 12345,
    "owner": "优化师",
    "timeline": "第1–3天",
    "success_metrics": ["达到最小点击样本", "CPA不高于止损线"],
    "stop_condition": "达到最小样本后仍超过止损线则暂停",
    "evidence_dependency": "账户实时建议价与转化回传",
}
```

Build exactly three headline actions for the executive summary and a complete P1/P2/P3 action plan from modules 2–6.

- [ ] **Step 6: Run focused tests**

Run: `cd xiaohongshu-strategy-agent && ../.venv/bin/python -m unittest tests.test_report_view -v`

Expected: PASS.

---

### Task 2: Engine Integration and Shared Markdown

**Files:**
- Modify: `xiaohongshu-strategy-agent/engine.py`
- Modify: `xiaohongshu-strategy-agent/report_view.py`
- Modify: `xiaohongshu-strategy-agent/tests/test_engine.py`
- Modify: `xiaohongshu-strategy-agent/tests/test_api_mock.py`

**Interfaces:**
- Consumes: Task 1 `build_report_view` and `render_report_markdown`.
- Produces: `StrategyResponse.report_view` and a matching `report_markdown`.

- [ ] **Step 1: Write failing integration tests**

```python
def test_markdown_uses_human_readable_report_sections(self):
    result = run_strategy(sample_request(), use_model=False, allow_mock=True, mock_seed="report-ui-a")
    self.assertIn("## 管理层决策摘要", result.report_markdown)
    self.assertIn("## 第一章｜自然流量大盘分析", result.report_markdown)
    self.assertIn("### 决策结论", result.report_markdown)
    self.assertIn("### 建议动作", result.report_markdown)
    self.assertIn("## 证据附录说明", result.report_markdown)

def test_api_returns_report_view(self):
    payload = client.post(
        "/analyze?use_model=false&use_knowledge=false&allow_mock=true&mock_seed=api-report",
        json=sample_request().model_dump(mode="json"),
    ).json()
    self.assertEqual(len(payload["report_view"]["report_sections"]), 4)
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `cd xiaohongshu-strategy-agent && ../.venv/bin/python -m unittest tests.test_engine tests.test_api_mock -v`

Expected: FAIL because the engine still calls `_markdown` and does not attach the view model.

- [ ] **Step 3: Integrate the builder after confidence calculation**

Reorder the end of `run_strategy` so confidence is calculated before the report:

```python
report_view = build_report_view(effective_req, modules, gaps, confidence)
deterministic_report = render_report_markdown(effective_req, report_view)
```

Return:

```python
StrategyResponse(
    ...,
    modules=modules,
    report_view=report_view,
    report_markdown=report,
    trace=trace,
)
```

- [ ] **Step 4: Render Markdown from the same view model**

`render_report_markdown` must render:

1. management summary;
2. four chapter headings;
3. conclusion, data explanation, analysis, actions, success metrics, and evidence boundary for each chapter;
4. P1/P2/P3 execution plan;
5. evidence appendix explanation and gaps.

Do not duplicate analytical logic in `_markdown`; remove or stop calling the old implementation.

- [ ] **Step 5: Preserve model-polish boundaries**

Update the `_model_polish` system message to explicitly preserve chapter coverage, numbers, data labels, evidence boundaries, and Mock seed. The deterministic `report_view` remains unchanged even if polished Markdown is returned.

- [ ] **Step 6: Verify same-seed behavior and real-data precedence**

Run:

```bash
cd xiaohongshu-strategy-agent
../.venv/bin/python -m unittest \
  tests.test_report_view \
  tests.test_engine.StrategyEngineTests.test_seed_reproduces_all_mock_modules \
  tests.test_engine.StrategyEngineTests.test_real_benchmark_replaces_mock \
  tests.test_api_mock -v
```

Expected: PASS.

---

### Task 3: Report-First Frontend with Native Charts

**Files:**
- Modify: `xiaohongshu-strategy-agent/web/index.html`
- Modify: `xiaohongshu-strategy-agent/web/app.js`
- Modify: `xiaohongshu-strategy-agent/web/style.css`
- Modify: `xiaohongshu-strategy-agent/tests/test_web_mock.py`

**Interfaces:**
- Consumes: `result.report_view` from Task 2.
- Produces: `renderReportView(view)`, `renderActionPlan(actions)`, `renderEvidenceAppendix(modules)`, `lineChart(series)`, and `donutChart(searchRatio, feedRatio)`.

- [ ] **Step 1: Write failing static frontend tests**

```python
def test_result_defaults_to_analysis_report(self):
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "app.js").read_text(encoding="utf-8")
    self.assertIn('data-view="report"', html)
    self.assertIn("分析报告", html)
    self.assertIn("执行方案", html)
    self.assertIn("证据附录", html)
    self.assertIn("renderReportView", script)
    self.assertIn("renderEvidenceAppendix", script)

def test_native_charts_are_present(self):
    script = (ROOT / "app.js").read_text(encoding="utf-8")
    self.assertIn("function lineChart", script)
    self.assertIn("function donutChart", script)
    self.assertNotIn("chart.js", script.casefold())
```

- [ ] **Step 2: Run tests and confirm missing report navigation**

Run: `cd xiaohongshu-strategy-agent && ../.venv/bin/python -m unittest tests.test_web_mock -v`

Expected: FAIL because only six module tabs and the evidence tree exist.

- [ ] **Step 3: Replace the result navigation shell**

Add three buttons in `index.html`:

```html
<nav id="resultViews" class="result-views">
  <button type="button" data-view="report" class="active">分析报告</button>
  <button type="button" data-view="actions">执行方案</button>
  <button type="button" data-view="evidence">证据附录</button>
</nav>
```

Keep one `<article id="module">` render target. The default active view is `report`.

- [ ] **Step 4: Implement report renderers**

`renderReportView` renders:

- strategic thesis hero;
- key finding cards;
- priority actions;
- four chapter `<section>` blocks;
- metric cards, report prose, actions, success metrics, and evidence boundary.

`renderActionPlan` renders P1/P2/P3 cards with owner, timeline, budget, steps, success metrics, and stop condition.

`renderEvidenceAppendix` renders evidence gaps followed by the existing six-module tab/tree interface. The recursive `tree` function is not used in the default report view.

- [ ] **Step 5: Implement native SVG/CSS charts**

`lineChart(series)` returns an accessible SVG with two normalized polylines for `note_count` and `interactions`, date range text, legend, and a no-data panel when series is empty.

`donutChart(searchRatio, feedRatio)` returns a CSS conic-gradient chart only when both ratios are numeric; otherwise it renders “待接入版位消耗数据”.

- [ ] **Step 6: Add report visual hierarchy**

Add focused styles for:

- `.report-hero`, `.finding-grid`, `.report-chapter`;
- `.metric-card-grid`, `.report-chart`, `.donut-chart`;
- `.report-prose`, `.decision-callout`, `.boundary-note`;
- `.action-card`, `.priority-p1`, `.priority-p2`, `.priority-p3`;
- responsive behavior below 850px.

Use the existing red/dark/paper palette and maintain readable contrast.

- [ ] **Step 7: Run frontend checks**

Run:

```bash
cd xiaohongshu-strategy-agent
../.venv/bin/python -m unittest tests.test_web_mock -v
node --check web/app.js
```

Expected: PASS.

---

### Task 4: Regression, Documentation, and Live Browser Verification

**Files:**
- Modify: `xiaohongshu-strategy-agent/README.md`
- Modify: `xiaohongshu-strategy-agent/docs/TEST_REPORT.md`

**Interfaces:**
- Consumes: completed API and frontend.
- Produces: verified localhost report-first application and updated usage documentation.

- [ ] **Step 1: Add a recursive report-contract audit**

Verify all four chapters have non-empty human-readable fields, any chapter marked Mock exposes a seed and warning, and visual series contain no fabricated zero for missing values.

- [ ] **Step 2: Run the complete suite**

Run:

```bash
cd xiaohongshu-strategy-agent
../.venv/bin/python -m unittest discover -s tests -v
node --check web/app.js
```

Expected: all tests pass with zero failures and JavaScript exits 0.

- [ ] **Step 3: Update documentation**

Document that the default result is now “分析报告”, explain the three views, clarify that the evidence appendix preserves provenance, and record the final test count in `docs/TEST_REPORT.md`.

- [ ] **Step 4: Restart the local server**

Run from `xiaohongshu-strategy-agent`:

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  ../.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8010
```

- [ ] **Step 5: Verify in the browser**

Reload `http://127.0.0.1:8010/`, load the full-case example, generate with Mock enabled and model disabled, and verify:

- “分析报告” opens by default;
- management summary and all four chapters are readable;
- trend and budget charts render;
- “执行方案” shows P1/P2/P3;
- “证据附录” still exposes all six modules;
- Mock seed and badges remain visible;
- browser console has no errors.

- [ ] **Step 6: Commit only feature-scoped changes when safe**

Do not stage unrelated pre-existing workspace changes. If feature files already contain inseparable user edits, leave implementation uncommitted and report that boundary rather than committing them as if they were solely produced by this feature.
