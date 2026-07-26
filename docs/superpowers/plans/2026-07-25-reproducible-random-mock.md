# Reproducible Random Mock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fixed demonstration Mock values with complete, reproducible random scenarios controlled by a visible seed and a “换一组 Mock” action.

**Architecture:** Add namespace-derived `random.Random` streams in `mock_scenarios.py` so each module is stable for a given seed and independent of which other fields are missing. Thread `mock_seed` through FastAPI and the strategy engine, attach it to every Mock object and report export, and let the browser generate or replace the seed without any network dependency.

**Tech Stack:** Python 3.13 standard library (`random`, `hashlib`, `secrets`), FastAPI, Pydantic, vanilla JavaScript, unittest.

## Global Constraints

- Real and verified public evidence always overrides Mock.
- Same request plus same seed produces identical Mock output; a different seed changes at least one Mock value.
- Every Mock object carries `data_type`, `is_mock`, `evidence_grade`, `source_name`, `mock_seed`, `mock_basis`, and `warning`.
- Search/feed shares sum to `1.0`; low `<` base `<` high; `CPA ≈ CPC / CVR`; all values are non-negative.
- Mock competitors and creators are anonymous and cannot claim real platform facts.
- No external request or Xiaohongshu collection is used in generation or tests.

---

### Task 1: Seeded Random Foundation

**Files:**
- Modify: `xiaohongshu-strategy-agent/mock_scenarios.py`
- Test: `xiaohongshu-strategy-agent/tests/test_mock_scenarios.py`

**Interfaces:**
- Produces `normalize_mock_seed(seed: str | None) -> str` and `rng_for(seed: str, namespace: str) -> random.Random`.
- All `build_mock_*` functions accept keyword-only `mock_seed: str`.

- [x] **Step 1: Write failing reproducibility tests**

```python
def test_same_seed_reproduces_market_scenarios(self):
    first = build_mock_market_scenarios(100000, "conversion", mock_seed="seed-a")
    second = build_mock_market_scenarios(100000, "conversion", mock_seed="seed-a")
    self.assertEqual(first, second)

def test_different_seed_changes_market_scenarios(self):
    first = build_mock_market_scenarios(100000, "conversion", mock_seed="seed-a")
    second = build_mock_market_scenarios(100000, "conversion", mock_seed="seed-b")
    self.assertNotEqual(first["cpc"], second["cpc"])
```

- [x] **Step 2: Run tests and confirm signature failure**

Run: `cd xiaohongshu-strategy-agent && ../.venv/bin/python -m unittest tests.test_mock_scenarios -v`

- [x] **Step 3: Implement namespace-derived random streams**

Hash `f"{seed}:{namespace}"` with SHA-256 and construct `random.Random(int(digest[:16], 16))`. Use `secrets.token_hex(8)` only when no seed is supplied.

- [x] **Step 4: Generate correlated market values**

Generate base CPC, CPM, CTR and CVR within declared ranges; calculate base CPA from `CPC / CVR` with at most ±5% seeded noise. Derive low/high bands from the base and normalize budget shares.

- [x] **Step 5: Run focused tests**

Expected: reproducibility and numeric-invariant tests pass.

### Task 2: Full Random Mock Evidence

**Files:**
- Modify: `xiaohongshu-strategy-agent/mock_scenarios.py`
- Modify: `xiaohongshu-strategy-agent/models.py`
- Modify: `xiaohongshu-strategy-agent/engine.py`
- Test: `xiaohongshu-strategy-agent/tests/test_mock_scenarios.py`
- Test: `xiaohongshu-strategy-agent/tests/test_engine.py`

**Interfaces:**
- `apply_demo_mock_evidence(req, mock_seed=...) -> tuple[CampaignRequest, dict[str, Any]]`.
- `run_strategy(..., allow_mock=False, mock_seed: str | None = None) -> StrategyResponse`.

- [x] **Step 1: Write failing all-module tests**

Assert 20 anonymous creators, 3–5 anonymous competitors, randomized trend words, 30 daily Mock notes, Mock risk frequencies, and complete metadata with the same seed.

- [x] **Step 2: Run tests and verify fixed-size/fixed-value failures**

Run focused mock and engine tests.

- [x] **Step 3: Randomize generators independently**

Use separate namespaces for market, notes, creators, competitors, trends, violations and paid-risk scenarios. Generate summaries from their detail rows rather than separate random calls.

- [x] **Step 4: Preserve real evidence precedence**

Inject competitors, creators, trends, risk rows and benchmarks only when the corresponding real collection is empty; supplement missing benchmark metric names without replacing existing names.

- [x] **Step 5: Add platform-Mock separation**

Keep the real `organic_market` result and expose a separate `simulated_platform_market` object with 30-day series and Mock metadata when enabled.

- [x] **Step 6: Run focused tests**

Expected: same-seed equality, different-seed variation, metadata and real-precedence tests pass.

### Task 3: API, Report, and Browser Seed Controls

**Files:**
- Modify: `xiaohongshu-strategy-agent/main.py`
- Modify: `xiaohongshu-strategy-agent/web/index.html`
- Modify: `xiaohongshu-strategy-agent/web/app.js`
- Modify: `xiaohongshu-strategy-agent/web/style.css`
- Test: `xiaohongshu-strategy-agent/tests/test_api_mock.py`
- Test: `xiaohongshu-strategy-agent/tests/test_web_mock.py`

**Interfaces:**
- `/analyze?...&allow_mock=true&mock_seed=<seed>`.
- Frontend stores `currentMockSeed`, displays `#mockSeedValue`, and handles `#regenerateMock`.

- [x] **Step 1: Write failing API and static browser tests**

Verify the API trace includes `mock_seed`, response Mock values reproduce for the same seed, and HTML/JS contain the visible seed plus regeneration control.

- [x] **Step 2: Run tests and confirm missing controls**

Run: `cd xiaohongshu-strategy-agent && ../.venv/bin/python -m unittest tests.test_api_mock tests.test_web_mock -v`

- [x] **Step 3: Thread seed through API and engine**

Accept `mock_seed: str | None`, normalize it only when Mock is enabled, and include it in trace and Markdown's Mock inventory heading.

- [x] **Step 4: Add browser controls**

Generate a seed with `crypto.getRandomValues`, submit it as a query parameter, show it in the result, and make “换一组 Mock” replace the seed then call `form.requestSubmit()`.

- [x] **Step 5: Run focused tests and JavaScript syntax check**

Run: `node --check xiaohongshu-strategy-agent/web/app.js` plus the two focused test modules.

### Task 4: Full Regression and Documentation

**Files:**
- Modify: `xiaohongshu-strategy-agent/docs/TEST_REPORT.md`

- [x] **Step 1: Run all tests**

Run: `cd xiaohongshu-strategy-agent && ../.venv/bin/python -m unittest discover -s tests -v`

- [x] **Step 2: Audit every Mock object**

Recursively assert required metadata, matching seed, numeric invariants, 20 Mock creators, 3–5 Mock competitors, and a 30-day simulated platform series.

- [x] **Step 3: Update the report**

Record test count, seed reproduction evidence, changed-seed evidence and confirmation that no external collection occurred.

- [ ] **Step 4: Commit only scoped files**

Stage the plan and files modified for this feature without staging unrelated pre-existing workspace changes.
