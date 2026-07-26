# Persistent Agent State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent SQLite-backed session, feedback, backfill, cache, checkpoint, idempotency, and lightweight analysis-run state to the Xiaohongshu strategy Agent.

**Architecture:** A focused `AgentStateStore` owns all state SQL and sensitive-key filtering. FastAPI remains the orchestration boundary around the existing deterministic `run_strategy()` function, while the frontend generates and persists a browser session UUID and displays returned session state.

**Tech Stack:** Python 3.13, SQLite, FastAPI, Pydantic, vanilla JavaScript, unittest.

## Global Constraints

- Keep `run_strategy()` deterministic and free of state-store dependencies.
- Persist state in a SQLite file separate from the category knowledge base.
- Store only summaries, counts, references, and safe workflow context; never persist Cookie, authorization, API keys, tokens, secrets, proxy values, or tracebacks.
- Use UTC ISO 8601 timestamps and SQLite WAL plus busy timeout.
- Real evidence always overrides Mock; any backfill from a Mock report is a `demo_case`.
- A failed analysis does not increment `analysis_count`.
- Existing request bodies and report outputs remain backward compatible apart from additive `report_id` and `session_state` fields.
- Do not access Xiaohongshu or start any collector during implementation or verification.

---

### Task 1: SQLite State Store Core

**Files:**
- Create: `agent_state.py`
- Create: `tests/test_agent_state.py`

**Interfaces:**
- Produces: `AgentStateStore(path: str | Path)`.
- Produces: `new_report_id() -> str`.
- Produces: `get_or_create_session(session_id: str | None) -> dict[str, Any]`.
- Produces: `complete_analysis(session_id: str, report_id: str, summary: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]`.
- Produces: `get_session(session_id: str) -> dict[str, Any] | None`.
- Produces: `list_runs(session_id: str, limit: int = 10) -> list[dict[str, Any]]`.
- Produces: `save_checkpoint(...)` and `list_checkpoints(...)`.

- [ ] **Step 1: Write failing persistence and isolation tests**

```python
def test_session_persists_and_success_count_is_atomic(self):
    store = AgentStateStore(self.db_path)
    session = store.get_or_create_session("session-a")
    store.complete_analysis("session-a", "rpt_one", {"strategic_thesis": "先搜索"}, self.metadata)
    reopened = AgentStateStore(self.db_path)
    self.assertEqual(reopened.get_session("session-a")["analysis_count"], 1)
    self.assertIsNone(reopened.get_session("session-b"))

def test_checkpoint_timeline_is_ordered(self):
    store.save_checkpoint("session-a", "rpt_one", "received", status="success", context={})
    store.save_checkpoint("session-a", "rpt_one", "completed", status="success", context={})
    self.assertEqual([x["stage"] for x in store.list_checkpoints("session-a", "rpt_one")], ["received", "completed"])
```

- [ ] **Step 2: Run the focused tests and confirm import failure**

Run: `../.venv/bin/python -m unittest tests.test_agent_state -v`

Expected: FAIL because `agent_state` does not exist.

- [ ] **Step 3: Implement schema creation and connection settings**

`AgentStateStore.__init__` creates these tables with `CREATE TABLE IF NOT EXISTS`: `agent_sessions`, `analysis_runs`, `feedback_records`, `backfilled_cases`, `common_hit_cache`, `workflow_checkpoints`, and `submitted_actions`. Every connection executes:

```python
connection.execute("PRAGMA journal_mode=WAL")
connection.execute("PRAGMA busy_timeout=5000")
connection.row_factory = sqlite3.Row
```

- [ ] **Step 4: Implement session, run, and checkpoint methods**

Use `BEGIN IMMEDIATE` and one SQL upsert for `analysis_count = analysis_count + 1`. Serialize safe JSON with `ensure_ascii=False` and stable key ordering.

- [ ] **Step 5: Run focused tests**

Run: `../.venv/bin/python -m unittest tests.test_agent_state -v`

Expected: PASS.

---

### Task 2: Sensitive Filtering, Cache, Feedback, Backfill, and Idempotency

**Files:**
- Modify: `agent_state.py`
- Modify: `tests/test_agent_state.py`

**Interfaces:**
- Produces: `sanitize_state_payload(value: Any) -> Any`.
- Produces: `get_cache`, `set_cache`.
- Produces: `begin_action`, `complete_action`, `fail_action`, `get_action`.
- Produces: `save_feedback`, `save_backfilled_case`, `state_status`, and `reset_session`.

- [ ] **Step 1: Write failing behavior tests**

```python
def test_sensitive_keys_never_persist(self):
    store.set_cache("rules", "cache-a", {"safe": 1, "Cookie": "secret", "proxy_url": "http://127.0.0.1"}, ttl_seconds=60)
    self.assertEqual(store.get_cache("rules", "cache-a"), {"safe": 1})

def test_idempotency_distinguishes_replay_and_conflict(self):
    self.assertEqual(store.begin_action("key-a", "analyze", "hash-a", "session-a")["result"], "started")
    store.complete_action("key-a", "rpt_one", {"session_id": "session-a"})
    self.assertEqual(store.begin_action("key-a", "analyze", "hash-a", "session-a")["result"], "replayed")
    self.assertEqual(store.begin_action("key-a", "analyze", "hash-b", "session-a")["result"], "conflict")

def test_mock_backfill_is_forced_to_demo(self):
    row = store.save_backfilled_case(..., requested_case_type="verified_case", is_mock=True)
    self.assertEqual(row["case_type"], "demo_case")
```

- [ ] **Step 2: Run tests and confirm missing-method failures**

Run: `../.venv/bin/python -m unittest tests.test_agent_state -v`

Expected: FAIL on the newly specified methods.

- [ ] **Step 3: Implement recursive sensitive-key removal**

Normalize keys with lowercase alphanumeric characters and reject names containing `cookie`, `authorization`, `api_key`, `apikey`, `token`, `secret`, `proxy`, or `traceback`. Apply sanitization before every JSON write.

- [ ] **Step 4: Implement TTL cache and idempotency state machine**

Expired cache entries return `None`. `begin_action` returns one of `started`, `replayed`, `processing`, or `conflict`; only `replayed` includes the saved response summary.

- [ ] **Step 5: Implement feedback, backfill, status, and reset methods**

Feedback uses a unique `idempotency_key`. Backfill forces Mock reports to `demo_case`. Reset deletes only rows scoped to the session and preserves common cache.

- [ ] **Step 6: Run focused tests**

Run: `../.venv/bin/python -m unittest tests.test_agent_state -v`

Expected: PASS.

---

### Task 3: API Models and Analyze Orchestration

**Files:**
- Modify: `models.py`
- Modify: `main.py`
- Create: `tests/test_api_state.py`

**Interfaces:**
- Adds `report_id: str` and `session_state: dict[str, Any]` to `StrategyResponse`.
- Adds optional `x_session_id: str | None = Header(...)` and `idempotency_key: str | None = Header(...)` to `/analyze`.
- Uses module-level `STATE = AgentStateStore(...)` with a test override helper or monkeypatchable binding.

- [ ] **Step 1: Write failing API tests**

```python
def test_analyze_returns_persistent_session_state(self):
    first = client.post(self.url, headers={"X-Session-ID": "session-a", "Idempotency-Key": "analysis-a"}, json=self.payload)
    second = client.post(self.url, headers={"X-Session-ID": "session-a", "Idempotency-Key": "analysis-b"}, json=self.payload)
    self.assertEqual(first.json()["session_state"]["analysis_count"], 1)
    self.assertEqual(second.json()["session_state"]["analysis_count"], 2)
    self.assertTrue(second.json()["report_id"].startswith("rpt_"))

def test_repeated_idempotency_key_does_not_increment(self):
    first = client.post(self.url, headers=self.headers, json=self.payload)
    second = client.post(self.url, headers=self.headers, json=self.payload)
    self.assertEqual(second.json()["session_state"]["analysis_count"], 1)
    self.assertEqual(first.json()["report_id"], second.json()["report_id"])
```

- [ ] **Step 2: Run tests and confirm response-contract failure**

Run: `../.venv/bin/python -m unittest tests.test_api_state -v`

Expected: FAIL because `report_id` and `session_state` are absent.

- [ ] **Step 3: Add additive response fields**

Add the two required fields to `StrategyResponse`; engine unit tests that construct responses continue to receive values from `run_strategy`, using a temporary run ID as `report_id` and an empty state object until orchestration overwrites them.

- [ ] **Step 4: Wrap analyze flow with checkpoints and idempotency**

Compute `request_hash` from canonical JSON covering request body and all behavior-changing query parameters. For a replay, load the stored `analysis_runs.response_json` or reconstruct the saved lightweight response reference; the implementation must preserve full API replay behavior without rerunning `run_strategy`.

Store stages in order: `received`, `evidence_ready`, `strategy_generated`, `report_generated`, `completed`. On exception, write `failed`, call `fail_action`, and re-raise without incrementing the session count.

- [ ] **Step 5: Run API and engine tests**

Run: `../.venv/bin/python -m unittest tests.test_api_state tests.test_api_mock tests.test_engine -v`

Expected: PASS.

---

### Task 4: State Management Endpoints

**Files:**
- Modify: `models.py`
- Modify: `main.py`
- Modify: `tests/test_api_state.py`

**Interfaces:**
- Produces `GET /sessions/{session_id}`.
- Produces `GET /sessions/{session_id}/runs?limit=10`.
- Produces `POST /feedback`.
- Produces `POST /backfilled-cases`.
- Produces `GET /workflows/{session_id}/{report_id}`.
- Produces `GET /state/status`.
- Produces `POST /sessions/{session_id}/reset`.

- [ ] **Step 1: Add failing endpoint tests**

Cover 404 session lookup, run listing, feedback replay, Mock backfill coercion, checkpoint lookup, state counts, and session reset preserving cache.

- [ ] **Step 2: Run tests and confirm 404 route failures**

Run: `../.venv/bin/python -m unittest tests.test_api_state -v`

Expected: FAIL because routes do not exist.

- [ ] **Step 3: Add Pydantic input models**

Define `FeedbackRequest` with constrained rating and `BackfilledCaseRequest` with report/session linkage and explicit confirmation boolean. Reject a backfill request unless `confirmed=True`.

- [ ] **Step 4: Implement thin API routes**

Routes validate input, call one `AgentStateStore` method, and translate missing rows to HTTP 404 and idempotency conflicts to HTTP 409. They contain no SQL.

- [ ] **Step 5: Run endpoint tests**

Run: `../.venv/bin/python -m unittest tests.test_api_state -v`

Expected: PASS.

---

### Task 5: Browser Session State and Visible Status

**Files:**
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/style.css`
- Modify: `tests/test_web_mock.py`

**Interfaces:**
- Produces `getOrCreateSessionId() -> string`.
- Produces `newSession() -> void`.
- Adds `X-Session-ID` and `Idempotency-Key` headers to `/analyze`.
- Renders returned session short ID, analysis count, and recent report ID.

- [ ] **Step 1: Write failing static frontend tests**

```python
def test_frontend_persists_and_sends_session(self):
    self.assertIn("xhs_agent_session_id", script)
    self.assertIn('"X-Session-ID"', script)
    self.assertIn('"Idempotency-Key"', script)
    self.assertIn("新建会话", html)
    self.assertIn("analysis_count", script)
```

- [ ] **Step 2: Run tests and confirm missing session UI**

Run: `../.venv/bin/python -m unittest tests.test_web_mock -v`

Expected: FAIL.

- [ ] **Step 3: Implement session UUID lifecycle**

Use `crypto.randomUUID()` with a deterministic fallback based on timestamp and random bytes only for browsers lacking the API. Persist to `localStorage`. A new analysis generates a fresh idempotency UUID.

- [ ] **Step 4: Add compact session UI**

Show `会话 <first 8 chars>`, `已完成 N 次分析`, and recent report ID. “新建会话” replaces local storage, clears the current result area, and updates the badge without deleting server history.

- [ ] **Step 5: Run frontend tests and syntax check**

Run:

```bash
../.venv/bin/python -m unittest tests.test_web_mock -v
node --check web/app.js
```

Expected: PASS.

---

### Task 6: Documentation, Migration-Safe Startup, and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/TEST_REPORT.md`
- Modify: `docs/superpowers/plans/2026-07-25-persistent-agent-state.md`

**Interfaces:**
- Documents state database path, response fields, endpoints, session lifecycle, reset semantics, and inspection commands.

- [ ] **Step 1: Document state behavior and API examples**

Include a curl example with `X-Session-ID` and `Idempotency-Key`, plus a Python command to print `report_id`, `session_state`, and the `model_polish` trace.

- [ ] **Step 2: Run the complete local test suite**

Run:

```bash
../.venv/bin/python -m unittest discover -s tests -v
node --check web/app.js
```

Expected: all tests pass with zero failures and JavaScript exits 0.

- [ ] **Step 3: Restart the local launchd service**

Run `launchctl remove codex.xhs-strategy-agent` if present, then resubmit the existing `uvicorn` launchd job on `127.0.0.1:8010` using the project virtual environment.

- [ ] **Step 4: Perform local API and browser verification**

Verify health, analyze twice under one session, replay one idempotency key, query session/runs/checkpoints/status, reload the browser, and confirm the persisted count remains visible. Confirm no console errors and no external Xiaohongshu request.

- [ ] **Step 5: Record verification evidence**

Update `docs/TEST_REPORT.md` with the final test count, endpoint checks, persistence proof, and sensitive-field filtering result.
