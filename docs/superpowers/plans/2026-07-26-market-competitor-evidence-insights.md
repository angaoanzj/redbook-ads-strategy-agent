# Market & Competitor Evidence Insights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing「赛道与竞品深度分析」so deterministic and Agent-assisted paths produce evidence-backed, confidence-labelled competitor insights without breaking the current API or page structure.

**Architecture:** Add a pure deterministic module that converts `CompetitorEvidence[]` into structured insight rows and staged content-gap assessments. The engine, benchmark board, web view, and Module 1 prompt consume this evidence layer; the LLM may add actions but may not replace deterministic facts.

**Tech Stack:** Python 3, Pydantic v2, `unittest`, FastAPI report pipeline, vanilla JavaScript, Docker Compose.

## Global Constraints

- Keep the existing `dimension` and `observation` fields and the current「赛道与竞品深度分析」entry/chapter.
- Add only backward-compatible fields: `evidence`, `sample_count`, `total_samples`, `coverage`, `conclusion_type`, `confidence`, and `missing_evidence`.
- Keep evidence-insufficient rows visible.
- Fewer than 5 competitor samples caps cross-sample confidence at `low`.
- Uncovered selling points remain `sample_uncovered` until demand or validation evidence exists.
- The deterministic path must remain useful without an LLM key.
- Do not infer competitor budgets from engagement counts.
- Preserve the user’s dirty `README.md` and unrelated untracked example files.

## File Structure

- Create `competitor_insight_analysis.py`: evidence extraction, aggregation, confidence gates, and gap staging.
- Create `tests/test_competitor_insight_analysis.py`: focused evidence-boundary tests.
- Modify `engine.py` and `tools/competitors.py`: use honest gap semantics.
- Modify `competitor_benchmark_board.py` and `web/app.js`: integrate evidence rows into the existing deep-analysis section.
- Modify `module_agents/module1.py`: ground model actions in deterministic facts.
- Modify focused integration tests and only stale architecture/SOP copy.

---

### Task 1: Deterministic competitor insight analysis

**Files:**
- Create: `competitor_insight_analysis.py`
- Create: `tests/test_competitor_insight_analysis.py`

**Interfaces:**
- Produces: `assess_content_gaps(selling_points, evidence, *, demand_signals=(), validated_points=()) -> dict[str, Any]`.
- Produces: `build_competitor_insight_rows(evidence, *, content_gap_analysis=None, observed_formats=()) -> list[dict[str, Any]]`.

- [ ] **Step 1: Write the failing Jenny contract test**

```python
def test_jenny_rows_are_compatible_and_evidence_backed(self):
    payload = json.loads(BENCH.read_text(encoding="utf-8"))
    evidence = [CompetitorEvidence.model_validate(row) for row in payload["competitor_evidence"]]
    gaps = assess_content_gaps(
        ["招牌经典款", "采用日本小麦粉与新西兰牛油", "适合作为香港伴手礼"],
        evidence,
    )
    rows = build_competitor_insight_rows(
        evidence,
        content_gap_analysis=gaps,
        observed_formats=[{"format": "图集", "sample_count": 3}],
    )
    by_dimension = {row["dimension"]: row for row in rows}
    self.assertIn("observation", by_dimension["选题"])
    self.assertEqual(by_dimension["选题"]["total_samples"], 3)
    self.assertEqual(by_dimension["选题"]["confidence"], "low")
    self.assertTrue(by_dimension["选题"]["evidence"])
    self.assertIn("评论", by_dimension["互动引擎"]["observation"])
```

- [ ] **Step 2: Write failing classification-boundary tests**

```python
def test_cash_alone_is_not_trust(self):
    rows = build_competitor_insight_rows([
        CompetitorEvidence(
            account_name="A",
            profile_or_note_url="https://www.xiaohongshu.com/explore/cash-only",
            title="只收现金",
            content_themes=["只收现金"],
        )
    ])
    trust = next(row for row in rows if row["dimension"] == "信任机制")
    self.assertEqual(trust["conclusion_type"], "evidence_insufficient")
    self.assertNotIn("现金", trust["observation"])

def test_fake_shop_word_alone_is_not_spread_risk(self):
    rows = build_competitor_insight_rows([
        CompetitorEvidence(
            account_name="A",
            profile_or_note_url="https://www.xiaohongshu.com/explore/fake-shop",
            title="避坑假店",
            content_themes=["避坑假店"],
        )
    ])
    risk = next(row for row in rows if row["dimension"] == "扩散风险")
    self.assertEqual(risk["conclusion_type"], "evidence_insufficient")

def test_no_comment_signal_keeps_insufficient_interaction_row(self):
    rows = build_competitor_insight_rows([
        CompetitorEvidence(
            account_name="A",
            profile_or_note_url="https://www.xiaohongshu.com/explore/unboxing",
            title="伴手礼开箱",
            content_themes=["伴手礼"],
        )
    ])
    row = next(row for row in rows if row["dimension"] == "互动引擎")
    self.assertEqual(row["conclusion_type"], "evidence_insufficient")
    self.assertTrue(row["missing_evidence"])
```

- [ ] **Step 3: Run tests and verify red state**

Run: `docker compose run --rm agent python -m unittest tests.test_competitor_insight_analysis -v`

Expected: FAIL with `ModuleNotFoundError: competitor_insight_analysis`.

- [ ] **Step 4: Implement the public builders and stable row shape**

```python
def assess_content_gaps(
    selling_points: Sequence[str],
    evidence: Sequence[CompetitorEvidence],
    *,
    demand_signals: Sequence[str] = (),
    validated_points: Sequence[str] = (),
) -> dict[str, Any]:
    """Return covered points and staged candidates."""


def build_competitor_insight_rows(
    evidence: Sequence[CompetitorEvidence],
    *,
    content_gap_analysis: Mapping[str, Any] | None = None,
    observed_formats: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Return the seven compatible rows used by the deep-analysis board."""
```

Every row uses:

```python
{
    "dimension": dimension,
    "observation": observation,
    "evidence": evidence_refs,
    "sample_count": support_n,
    "total_samples": len(evidence),
    "coverage": round(support_n / len(evidence), 3) if evidence else 0.0,
    "conclusion_type": conclusion_type,
    "confidence": confidence,
    "missing_evidence": missing_evidence,
}
```

Use separate named signal maps for topics, decision information, trust, interaction, and risk. Require `评论`, `咨询`, or `问` before treating notes as interaction evidence. Require controversy/redirect terms such as `导流`, `质疑`, `香精`, `人造奶油`, or `更好吃` for risk; `假店` alone is insufficient.

- [ ] **Step 5: Run tests and verify green state**

Run the Step 3 command. Expected: all Task 1 tests PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add competitor_insight_analysis.py tests/test_competitor_insight_analysis.py
git commit -m "feat: add evidence-based competitor insight analysis"
```

---

### Task 2: Stage content gaps in the engine and competitor tool

**Files:**
- Modify: `engine.py:1643-1770`
- Modify: `tools/competitors.py:55-130`
- Modify: `tests/test_competitor_input.py`
- Modify: `tests/test_competitor_topic_creator_tools.py`

**Interfaces:**
- Consumes Task 1 `assess_content_gaps(...)`.
- Engine produces `covered_points`, `candidates`, `opportunities`, `decision_conclusion`, `status`, and `missing_evidence`.
- Tool keeps `content_gaps` for compatibility and adds `content_gap_stage` and `content_gap_policy`.

- [ ] **Step 1: Add failing engine assertions**

```python
gaps = result.modules["module_1_market_competitor"]["competitor_full_funnel"]["content_gaps"]
self.assertIn("样本内未覆盖候选", gaps["decision_conclusion"])
self.assertNotIn("可规模化空白机会", gaps["decision_conclusion"])
self.assertTrue(all(row["stage"] == "sample_uncovered" for row in gaps["candidates"]))
self.assertIn("用户需求", " ".join(gaps["missing_evidence"]))
```

- [ ] **Step 2: Add failing tool assertions**

```python
self.assertEqual(result["content_gaps"], ["低糖健康", "送礼体面"])
self.assertEqual(result["content_gap_stage"], "sample_uncovered")
self.assertIn("样本内未覆盖", result["content_gap_policy"])
self.assertNotIn("市场空白", result["content_gap_policy"])
```

- [ ] **Step 3: Run focused tests and verify failure**

Run:

```bash
docker compose run --rm agent python -m unittest \
  tests.test_competitor_input.CompetitorInputTests.test_auto_board_uses_local_engine_competitor_section \
  tests.test_competitor_topic_creator_tools.CompetitorToolTest -v
```

Expected: FAIL because stages/policies do not exist and old copy says `可规模化空白机会`.

- [ ] **Step 4: Use shared gap assessment in `engine.py`**

```python
gap_assessment = assess_content_gaps(req.selling_points, req.competitor_evidence)
gap_opportunities = [
    {
        "opportunity": f"测试卖点「{row['point']}」的对比/体验内容",
        "reason": "当前对标样本未覆盖；尚缺用户需求与效果证据",
        "evidence_basis": row["evidence_basis"],
        "stage": row["stage"],
        "conclusion_type": row["conclusion_type"],
        "validation_required": row["validation_required"],
    }
    for row in gap_assessment["candidates"][:5]
]
```

Return the shared conclusion plus candidate and missing-evidence fields. Remove old `可规模化空白机会` copy.

- [ ] **Step 5: Add compatibility metadata in `tools/competitors.py`**

```python
"content_gap_stage": "sample_uncovered",
"content_gap_policy": "自身卖点未命中当前竞品主题，只能视为样本内未覆盖候选；需用户需求与效果测试后升级。",
```

For zero competitors use `evidence_insufficient` and state that sample coverage itself is unknown.

- [ ] **Step 6: Rerun focused tests and verify PASS**

- [ ] **Step 7: Commit Task 2**

```bash
git add engine.py tools/competitors.py tests/test_competitor_input.py tests/test_competitor_topic_creator_tools.py
git commit -m "fix: stage competitor content gaps by evidence"
```

---

### Task 3: Integrate insights into the existing deep-analysis board

**Files:**
- Modify: `competitor_benchmark_board.py:360-487`
- Modify: `web/app.js:800-870`
- Modify: `tests/test_competitor_input.py`
- Modify: `tests/test_web_mock.py`

**Interfaces:**
- Consumes Task 1 `build_competitor_insight_rows(...)` and Task 2 engine gaps.
- Produces existing `section_competitor.commonality_rows` with new evidence metadata.
- Renders new metadata in the same「赛道与竞品深度分析」table.

- [ ] **Step 1: Add failing board assertions**

```python
rows = {row["dimension"]: row for row in comp["commonality_rows"]}
self.assertEqual(rows["选题"]["total_samples"], 3)
self.assertEqual(rows["选题"]["confidence"], "low")
self.assertTrue(rows["选题"]["evidence"])
self.assertNotIn("现金", rows["信任机制"]["observation"])
self.assertIn("样本内未覆盖", rows["内容空白"]["observation"])
```

- [ ] **Step 2: Add failing web assertions**

```python
self.assertIn('label: "证据/样本"', app_js)
self.assertIn('label: "结论类型"', app_js)
self.assertIn('label: "置信度"', app_js)
```

- [ ] **Step 3: Run focused tests and verify failure**

Run:

```bash
docker compose run --rm agent python -m unittest \
  tests.test_competitor_input.CompetitorInputTests.test_auto_board_uses_local_engine_competitor_section \
  tests.test_web_mock -v
```

- [ ] **Step 4: Replace keyword row construction**

```python
commonality_rows = build_competitor_insight_rows(
    evidence,
    content_gap_analysis=gaps,
    observed_formats=formats,
)
```

Keep paid-note, targeting, budget, and risk safeguards unchanged. Remove only helpers that become unused.

- [ ] **Step 5: Render the added fields in `web/app.js`**

```javascript
const insightSample = row => {
  const n = row.sample_count ?? 0;
  const total = row.total_samples ?? 0;
  const pct = row.coverage == null ? "—" : `${Math.round(Number(row.coverage) * 100)}%`;
  const signals = (row.evidence || []).slice(0, 2).map(item => item.signal).filter(Boolean);
  return `${n}/${total} (${pct})${signals.length ? ` · ${signals.join("；")}` : ""}`;
};
const conclusionLabel = row => ({
  fact: "事实", inference: "推断", hypothesis: "待验证假设",
  sample_observation: "单篇观察", evidence_insufficient: "证据不足",
}[row.conclusion_type] || row.conclusion_type || "—");
```

Add `证据/样本`, `结论类型`, and `置信度` columns to the existing commonality table.

- [ ] **Step 6: Rerun focused tests and verify PASS**

- [ ] **Step 7: Commit Task 3**

```bash
git add competitor_benchmark_board.py web/app.js tests/test_competitor_input.py tests/test_web_mock.py
git commit -m "feat: show evidence quality in competitor deep analysis"
```

---

### Task 4: Ground Module 1 actions and preserve deterministic facts

**Files:**
- Modify: `module_agents/module1.py:70-285`
- Modify: `competitor_benchmark_board.py:211-356`
- Modify: `tests/test_module1_agent.py`
- Modify: `tests/test_agent_board_overlay.py`

**Interfaces:**
- Prompt receives a JSON `确定性竞品事实层` built without importing `engine`.
- Automatic boards retain local fact rows; Agent output supplements actions, hypotheses, risks, and review items.

- [ ] **Step 1: Add failing prompt assertions**

```python
prompt = build_user_prompt(_sample_request())
self.assertIn("确定性竞品事实层", prompt)
self.assertIn('"conclusion_type"', prompt)
self.assertIn("不得覆盖事实层", SYSTEM_PROMPT)
self.assertIn("样本内未覆盖", SYSTEM_PROMPT)
```

- [ ] **Step 2: Strengthen the overlay preservation test**

```python
local_rows = [{
    "dimension": "内容空白",
    "observation": "样本内未覆盖候选：低糖；尚缺需求证据",
    "conclusion_type": "hypothesis",
    "confidence": "low",
}]
board["section_competitor"]["commonality_rows"] = local_rows
apply_module1_agent_overlay(board, modules, overlay_competitor_section=False, overlay_organic_copy=False)
self.assertEqual(board["section_competitor"]["commonality_rows"], local_rows)
```

- [ ] **Step 3: Run Agent tests and verify failure**

Run: `docker compose run --rm agent python -m unittest tests.test_module1_agent tests.test_agent_board_overlay -v`

- [ ] **Step 4: Inject deterministic facts into `build_user_prompt`**

```python
gap_assessment = assess_content_gaps(req.selling_points, req.competitor_evidence)
fact_rows = build_competitor_insight_rows(req.competitor_evidence, content_gap_analysis=gap_assessment)
evidence.append(
    "确定性竞品事实层（不得覆盖，只能据此写测试动作）：\n"
    + json.dumps(fact_rows, ensure_ascii=False)
)
```

Import only the pure analysis module, not `engine`.

- [ ] **Step 5: Tighten System Prompt wording**

Add these exact rules:

```text
确定性竞品事实层由代码计算，禁止改写其事实、覆盖率、结论类型和置信度。
content_gaps 只能把 sample_uncovered 改写成“待验证切口”，不得写成已验证市场空白。
common_patterns 只用于生成行动解读；网页第03章事实表由本地引擎保留。
```

- [ ] **Step 6: Rerun Agent tests and verify PASS**

- [ ] **Step 7: Commit Task 4**

```bash
git add module_agents/module1.py competitor_benchmark_board.py tests/test_module1_agent.py tests/test_agent_board_overlay.py
git commit -m "fix: ground module1 actions in deterministic competitor facts"
```

---

### Task 5: End-to-end regression and documentation alignment

**Files:**
- Modify: `tests/test_competitor_input.py`
- Modify only if stale: `docs/ARCHITECTURE_OVERVIEW.md`
- Modify only if stale: `docs/no-code-agent/模块1_赛道竞品分析SOP.md`

**Interfaces:**
- Produces a stable automatic Jenny report inside the existing deep-analysis section.

- [ ] **Step 1: Add final automatic-Jenny assertions**

```python
rows = {
    row["dimension"]: row
    for row in result.report_view["competitor_benchmark_board"]["section_competitor"]["commonality_rows"]
}
self.assertEqual(set(rows), {"选题", "信息密度", "信任机制", "互动引擎", "扩散风险", "内容形式", "内容空白"})
self.assertIn("门店", rows["信息密度"]["observation"])
self.assertIn("支付", rows["信息密度"]["observation"])
self.assertIn("正版", rows["信任机制"]["observation"])
self.assertIn("价格", rows["互动引擎"]["observation"])
self.assertIn("导流", rows["扩散风险"]["observation"])
self.assertIn("样本内未覆盖", rows["内容空白"]["observation"])
self.assertTrue(all(row["confidence"] == "low" for row in rows.values()))
```

- [ ] **Step 2: Run focused market/competitor tests**

```bash
docker compose run --rm agent python -m unittest \
  tests.test_competitor_insight_analysis tests.test_competitor_input \
  tests.test_competitor_topic_creator_tools.CompetitorToolTest \
  tests.test_module1_agent tests.test_agent_board_overlay tests.test_web_mock -v
```

Expected: PASS.

- [ ] **Step 3: Run the complete suite**

Run: `docker compose run --rm agent python -m unittest discover tests -v`

Expected: PASS. Record exact unrelated pre-existing failures rather than weakening new tests.

- [ ] **Step 4: Inspect an offline automatic Jenny payload**

Generate `competitor_benchmark_brief=None`, `use_model=False`, `allow_mock=False`, and print `competitor_benchmark_board.section_competitor`. Verify all seven dimensions, visible evidence gaps, and no unvalidated scalable-market claim.

- [ ] **Step 5: Align only stale docs**

Required copy:

```text
竞品共性由确定性证据层计算；每行显示样本覆盖、结论类型和置信度。
自有卖点未命中竞品主题只能标记为“样本内未覆盖候选”。
LLM 只补充测试动作，不覆盖第03章事实表。
```

- [ ] **Step 6: Commit final regression/docs changes**

```bash
git add tests/test_competitor_input.py docs/ARCHITECTURE_OVERVIEW.md docs/no-code-agent/模块1_赛道竞品分析SOP.md
git commit -m "test: lock competitor deep analysis evidence contract"
```

- [ ] **Step 7: Verify no unintended files are staged**

Run:

```bash
git status --short
git diff --check
```

Expected: the user’s pre-existing `README.md` modification and unrelated untracked files may remain, but no unintended file is staged and no whitespace errors are reported.
