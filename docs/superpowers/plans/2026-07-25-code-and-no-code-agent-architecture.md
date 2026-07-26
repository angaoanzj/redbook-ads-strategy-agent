# Code and No-Code Xiaohongshu Agent Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the current code architecture documentation and derive a Claude Project/Custom GPT no-code package from the six implemented modules without claiming capabilities the code does not provide.

**Architecture:** Treat the current Python implementation as the authoritative source. First document the running architecture and current-versus-target distinctions, then create platform-neutral governance and six module SOPs, with thin Claude/GPT entry prompts referencing the shared files. Validate all artifacts with automated text-contract tests and a worked Cookie Quartet `/full` example.

**Tech Stack:** Markdown, Mermaid, FastAPI/Pydantic architecture references, SQLite/FTS5, OpenAI-compatible Analyzer configuration, configured-but-not-yet-wired Embedding channel, Docker Compose, Python standard-library unittest.

## Global Constraints

- The codebase is authoritative; planned capabilities must be labeled as planned.
- Full-case business dependency is `M1 → M2 → M6 → M3 → M4 → M5`.
- Analyzer is active for module decisions and optional report polishing; Embedding is configuration-ready but not currently called by retrieval.
- `mock_agents.py` and `mock_scenarios.py` are a data simulation service, not real evidence.
- Real/account, public observation, user-imported, industry benchmark, strategic assumption and Mock evidence remain distinct.
- Claude and GPT entry prompts share one set of business SOP files.
- Preserve unrelated changes in the dirty worktree.

---

## File Structure

**Modify**

- `docs/TECHNICAL_ARCHITECTURE.md` — authoritative current architecture, diagrams, runtime and deployment status.

**Create**

- `docs/DUAL_VERSION_CAPABILITY_MAPPING.md` — code/no-code mapping, gaps and controls.
- `docs/no-code-agent/README_使用说明.md` — setup, upload order and commands.
- `docs/no-code-agent/Claude_Project_System_Prompt.md` — Claude router.
- `docs/no-code-agent/Custom_GPT_Instructions.md` — GPT router.
- `docs/no-code-agent/01_全局证据与数据纪律.md` — evidence hierarchy and Mock isolation.
- `docs/no-code-agent/02_模块状态输出契约.md` — `module_state` schema.
- `docs/no-code-agent/03_跨模块依赖与冲突处理.md` — dependency and conflict rules.
- `docs/no-code-agent/04_指标单一事实源规范.md` — `benchmark_registry`.
- `docs/no-code-agent/模块1_赛道竞品分析SOP.md` through `模块6_关键词策略SOP.md` — six SOPs.
- `docs/no-code-agent/示例_曲奇四重奏_FULL.md` — worked example.
- `tests/test_no_code_docs.py` — document contract tests.

---

### Task 1: Lock the Current-Code Inventory

**Files:**
- Inspect: `main.py`, `models.py`, `knowledge_base.py`, `agent_state.py`, `engine.py`, `model_config.py`
- Inspect: `module_agents/*.py`, `tools/*.py`
- Inspect: `report_agent_view.py`, `report_view.py`, `mock_agents.py`, `mock_scenarios.py`
- Inspect: `Dockerfile`, `docker-compose.yml`

**Interfaces:**
- Consumes: current repository state.
- Produces: verified component names, links and current/planned status used by later tasks.

- [ ] **Step 1: Enumerate implementation files**

Run:

```bash
find . -maxdepth 2 -type f | sort | grep -E '(main.py|models.py|knowledge_base.py|agent_state.py|engine.py|model_config.py|module_agents/|tools/|report_agent_view.py|report_view.py|mock_agents.py|mock_scenarios.py|Dockerfile|docker-compose.yml)'
```

Expected: every named component exists, including Module 1–6 implementations.

- [ ] **Step 2: Verify model-channel usage**

Run:

```bash
grep -RIn 'load_analyzer_config\|load_embedding_config' . --exclude-dir=__pycache__ --exclude='*.db'
```

Expected: Analyzer has runtime callers; Embedding appears only in configuration/tests.

- [ ] **Step 3: Verify Agent/report flow**

Run:

```bash
grep -RIn '_attach_agent_modules\|agent_decision\|build_agent_decision_view\|build_report_view' engine.py report_view.py report_agent_view.py
```

Expected: actual module-decision and report-construction order is visible and recorded for Task 2.

- [ ] **Step 4: Verify persistence boundaries**

Run:

```bash
grep -RIn 'xhs_knowledge.db\|agent_state.db\|checkpoint\|Idempotency' knowledge_base.py agent_state.py main.py README.md
```

Expected: evidence storage and workflow/session storage are separately attributable.

---

### Task 2: Rewrite Technical Architecture and Mermaid Diagrams

**Files:**
- Modify: `docs/TECHNICAL_ARCHITECTURE.md`
- Create: `tests/test_no_code_docs.py`

**Interfaces:**
- Consumes: inventory from Task 1.
- Produces: authoritative vocabulary and status used by mapping and no-code docs.

- [ ] **Step 1: Write the failing test**

Create:

```python
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TechnicalArchitectureDocsTest(unittest.TestCase):
    def test_current_architecture_names_real_components(self):
        text = (ROOT / "docs/TECHNICAL_ARCHITECTURE.md").read_text(encoding="utf-8")
        for required in (
            "tools/", "model_config.py", "Analyzer", "Embedding",
            "report_agent_view.py", "数据模拟服务", "Docker Compose",
            "xhs_knowledge.db", "agent_state.db", "Grounding Check",
        ):
            self.assertIn(required, text)

    def test_embedding_is_not_claimed_as_active_retrieval(self):
        text = (ROOT / "docs/TECHNICAL_ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertIn("配置就绪、向量检索待接入", text)
        self.assertNotIn("大模型只做报告表达与归纳", text)
```

- [ ] **Step 2: Verify RED**

Run: `../.venv/bin/python -m unittest tests.test_no_code_docs.TechnicalArchitectureDocsTest -v`

Expected: FAIL because the old document omits current components and retains historical wording.

- [ ] **Step 3: Rewrite the document**

Use these sections:

```markdown
# 技术架构与实现原理
## 1. 当前系统定位
## 2. 当前代码总体架构图
## 3. 端到端分析数据流
## 4. 六模块业务依赖与当前执行方式
## 5. 组件职责与代码映射
## 6. Analyzer/Embedding 双通道
## 7. Agent 决策、Grounding 与确定性回退
## 8. 数据、证据等级与 Mock 隔离
## 9. 双 SQLite 持久化
## 10. 本机与 Docker Compose 部署
## 11. 安全边界
## 12. 当前实现与演进项
```

Include four Mermaid diagrams: overall architecture, data flow, `M1→M2→M6→M3→M4→M5`, and Docker deployment. Label Embedding `配置就绪、向量检索待接入`. Describe `mock_agents.py` as `数据模拟服务（显式启用）`. State that Analyzer participates in module decisions and optional polishing, while deterministic modules provide the baseline and fallback.

- [ ] **Step 4: Verify GREEN**

Run: `../.venv/bin/python -m unittest tests.test_no_code_docs.TechnicalArchitectureDocsTest -v`

Expected: PASS.

- [ ] **Step 5: Check and commit**

```bash
git diff --check -- docs/TECHNICAL_ARCHITECTURE.md tests/test_no_code_docs.py
git add docs/TECHNICAL_ARCHITECTURE.md tests/test_no_code_docs.py
git commit -m "docs: update current strategy agent architecture"
```

---

### Task 3: Add Dual-Version Capability Mapping

**Files:**
- Create: `docs/DUAL_VERSION_CAPABILITY_MAPPING.md`
- Modify: `tests/test_no_code_docs.py`

**Interfaces:**
- Consumes: Task 2 component/status vocabulary.
- Produces: canonical code/no-code mapping.

- [ ] **Step 1: Add the failing test**

```python
class DualVersionMappingTest(unittest.TestCase):
    def test_mapping_covers_required_capabilities_and_gaps(self):
        text = (ROOT / "docs/DUAL_VERSION_CAPABILITY_MAPPING.md").read_text(encoding="utf-8")
        for required in (
            "主控路由", "六模块执行", "知识检索", "状态管理", "数据接入",
            "证据审计", "确定性计算", "指标统一", "数字溯源", "Mock 隔离",
            "降级", "报告生成", "持久化", "人工审批", "差距与补偿",
        ):
            self.assertIn(required, text)
```

- [ ] **Step 2: Verify RED**

Run: `../.venv/bin/python -m unittest tests.test_no_code_docs.DualVersionMappingTest -v`

Expected: ERROR because the mapping file is absent.

- [ ] **Step 3: Create the mapping**

Use:

```markdown
| 能力 | 代码版实现与文件 | Claude/GPT 零代码实现 | 零代码差距与补偿 | 当前状态 |
```

Add every tested capability. Mark programmatic validation, cross-session persistence, automatic fallback and Mock enforcement as weaker in no-code. Mark Embedding configuration-ready but inactive.

- [ ] **Step 4: Verify GREEN and commit**

```bash
../.venv/bin/python -m unittest tests.test_no_code_docs.DualVersionMappingTest -v
git add docs/DUAL_VERSION_CAPABILITY_MAPPING.md tests/test_no_code_docs.py
git commit -m "docs: map code and no-code agent capabilities"
```

---

### Task 4: Create Shared Governance Files

**Files:**
- Create: `docs/no-code-agent/01_全局证据与数据纪律.md`
- Create: `docs/no-code-agent/02_模块状态输出契约.md`
- Create: `docs/no-code-agent/03_跨模块依赖与冲突处理.md`
- Create: `docs/no-code-agent/04_指标单一事实源规范.md`
- Modify: `tests/test_no_code_docs.py`

**Interfaces:**
- Consumes: evidence and SSOT behavior verified from code.
- Produces: `module_state` and `benchmark_registry` used by both prompts and all SOPs.

- [ ] **Step 1: Add failing tests**

```python
class NoCodeGovernanceTest(unittest.TestCase):
    def test_governance_files_define_shared_contracts(self):
        folder = ROOT / "docs/no-code-agent"
        evidence = (folder / "01_全局证据与数据纪律.md").read_text(encoding="utf-8")
        state = (folder / "02_模块状态输出契约.md").read_text(encoding="utf-8")
        dependency = (folder / "03_跨模块依赖与冲突处理.md").read_text(encoding="utf-8")
        ssot = (folder / "04_指标单一事实源规范.md").read_text(encoding="utf-8")
        for grade in ("A_官方或授权", "B_公开观察", "C_用户导入", "D_行业基准", "E_策略假设", "Mock"):
            self.assertIn(grade, evidence)
        for key in ("run_id", "module", "status", "evidence_ids", "confirmed_facts", "assumptions", "decisions", "unresolved_gaps", "human_review_items"):
            self.assertIn(key, state)
        self.assertIn("M1 → M2 → M6 → M3 → M4 → M5", dependency)
        for key in ("candidates", "selected_value", "selected_source", "selection_reason", "recommended_ratio", "scenario_ratio"):
            self.assertIn(key, ssot)
```

- [ ] **Step 2: Verify RED**

Run: `../.venv/bin/python -m unittest tests.test_no_code_docs.NoCodeGovernanceTest -v`

Expected: ERROR because the governance files are absent.

- [ ] **Step 3: Write the governance files**

Define allowed conclusions per evidence level, forbidden substitutions, Mock prohibition, the exact YAML `module_state` fields tested above, missing-predecessor behavior, conflict precedence, budget-conservation failure, and `benchmark_registry` candidate selection. Historical facts preserve exact values; forecasts and recommendations use ranges.

- [ ] **Step 4: Verify GREEN and commit**

```bash
../.venv/bin/python -m unittest tests.test_no_code_docs.NoCodeGovernanceTest -v
git add docs/no-code-agent/0*.md tests/test_no_code_docs.py
git commit -m "docs: define no-code evidence and state contracts"
```

---

### Task 5: Create Claude and GPT Entry Prompts

**Files:**
- Create: `docs/no-code-agent/Claude_Project_System_Prompt.md`
- Create: `docs/no-code-agent/Custom_GPT_Instructions.md`
- Modify: `tests/test_no_code_docs.py`

**Interfaces:**
- Consumes: governance files from Task 4.
- Produces: shared routes `/m1`–`/m6`, `/full`, `/ab`, `/board`.

- [ ] **Step 1: Add failing tests**

```python
class NoCodeEntryPromptTest(unittest.TestCase):
    def test_both_platform_prompts_share_routes_and_governance(self):
        folder = ROOT / "docs/no-code-agent"
        texts = [
            (folder / "Claude_Project_System_Prompt.md").read_text(encoding="utf-8"),
            (folder / "Custom_GPT_Instructions.md").read_text(encoding="utf-8"),
        ]
        for text in texts:
            for route in ("/m1", "/m2", "/m3", "/m4", "/m5", "/m6", "/full", "/ab", "/board"):
                self.assertIn(route, text)
            self.assertIn("M1 → M2 → M6 → M3 → M4 → M5", text)
            self.assertIn("benchmark_registry", text)
            self.assertIn("module_state", text)
```

- [ ] **Step 2: Verify RED**

Run: `../.venv/bin/python -m unittest tests.test_no_code_docs.NoCodeEntryPromptTest -v`

Expected: ERROR because entry files are absent.

- [ ] **Step 3: Write both prompts**

Keep business rules in shared files. Claude explicitly consults Project Knowledge; GPT explicitly names the SOP file for each route to compensate for retrieval-style knowledge selection. Both require evidence labels, unresolved gaps, `module_state`, `benchmark_registry`, and final conflict checks.

- [ ] **Step 4: Verify GREEN and commit**

```bash
../.venv/bin/python -m unittest tests.test_no_code_docs.NoCodeEntryPromptTest -v
git add docs/no-code-agent/Claude_Project_System_Prompt.md docs/no-code-agent/Custom_GPT_Instructions.md tests/test_no_code_docs.py
git commit -m "docs: add Claude and GPT orchestrator prompts"
```

---

### Task 6: Derive Upstream SOPs M1, M2 and M6

**Files:**
- Create: `docs/no-code-agent/模块1_赛道竞品分析SOP.md`
- Create: `docs/no-code-agent/模块2_用户画像选题SOP.md`
- Create: `docs/no-code-agent/模块6_关键词策略SOP.md`
- Inspect: corresponding `module_agents/` and `tools/competitors.py`, `topics.py`, `keywords.py`
- Modify: `tests/test_no_code_docs.py`

**Interfaces:**
- Consumes: current module outputs and shared governance.
- Produces: upstream module states consumed by M3–M5.

- [ ] **Step 1: Add failing SOP tests**

```python
class NoCodeModuleSopTest(unittest.TestCase):
    REQUIRED = ("职责与边界", "输入", "前序依赖", "证据", "执行步骤", "输出契约", "module_state", "Grounding", "降级", "人工拍板")

    def _assert_sop(self, filename):
        text = (ROOT / "docs/no-code-agent" / filename).read_text(encoding="utf-8")
        for section in self.REQUIRED:
            self.assertIn(section, text)

    def test_upstream_sops_have_uniform_contract(self):
        for filename in ("模块1_赛道竞品分析SOP.md", "模块2_用户画像选题SOP.md", "模块6_关键词策略SOP.md"):
            self._assert_sop(filename)
```

- [ ] **Step 2: Verify RED**

Run: `../.venv/bin/python -m unittest tests.test_no_code_docs.NoCodeModuleSopTest.test_upstream_sops_have_uniform_contract -v`

Expected: ERROR because SOPs are absent.

- [ ] **Step 3: Write M1**

Cover organic/paid landscape, competitor breakdown, risk alerts and review items. Limit public evidence to sample conclusions; prohibit competitor budget/targeting claims without evidence.

- [ ] **Step 4: Write M2**

Cover persona, content directions, topics and material screening. Label unsupported scores as test hypotheses.

- [ ] **Step 5: Write M6**

Own the canonical keyword library, three levels, layout, budget split and trend monitor. Require search-volume/note-count evidence before “blue ocean” or “trending” claims.

- [ ] **Step 6: Verify GREEN and commit**

```bash
../.venv/bin/python -m unittest tests.test_no_code_docs.NoCodeModuleSopTest.test_upstream_sops_have_uniform_contract -v
git add docs/no-code-agent/模块1_赛道竞品分析SOP.md docs/no-code-agent/模块2_用户画像选题SOP.md docs/no-code-agent/模块6_关键词策略SOP.md tests/test_no_code_docs.py
git commit -m "docs: derive upstream no-code module SOPs"
```

---

### Task 7: Derive Downstream SOPs M3, M4 and M5

**Files:**
- Create: `docs/no-code-agent/模块3_达人匹配SOP.md`
- Create: `docs/no-code-agent/模块4_聚光投流决策SOP.md`
- Create: `docs/no-code-agent/模块5_全域预算节奏SOP.md`
- Inspect: corresponding `module_agents/` and `tools/creator_match.py`, `bidding.py`, `forecast.py`, `budget.py`
- Modify: `tests/test_no_code_docs.py`

**Interfaces:**
- Consumes: M2, M6, M3/M4 predecessor state and `benchmark_registry`.
- Produces: creator, Spotlight and full-budget decisions.

- [ ] **Step 1: Extend the failing SOP test**

```python
    def test_downstream_sops_have_uniform_contract(self):
        for filename in ("模块3_达人匹配SOP.md", "模块4_聚光投流决策SOP.md", "模块5_全域预算节奏SOP.md"):
            self._assert_sop(filename)
```

- [ ] **Step 2: Verify RED**

Run: `../.venv/bin/python -m unittest tests.test_no_code_docs.NoCodeModuleSopTest.test_downstream_sops_have_uniform_contract -v`

Expected: ERROR because SOPs are absent.

- [ ] **Step 3: Write M3**

Consume M2 audience/content and M6 canonical keywords. Cover creator tiers, matched creators, open slots, evidence and purchase review. Never present generated placeholders as recommendations.

- [ ] **Step 4: Write M4**

Cover account structure, targeting, bidding, search/feed split, schedule, forecast and risk playbook. Cite `benchmark_registry`; separate `recommended_ratio` from `scenario_ratio`; include response actions for every risk.

- [ ] **Step 5: Write M5**

Cover total split, phases, creator tiers, bids, organic-paid synergy and contingency. Enforce budget conservation. Historical metrics may be exact; future recommendations are ranges.

- [ ] **Step 6: Verify GREEN and commit**

```bash
../.venv/bin/python -m unittest tests.test_no_code_docs.NoCodeModuleSopTest.test_downstream_sops_have_uniform_contract -v
git add docs/no-code-agent/模块3_达人匹配SOP.md docs/no-code-agent/模块4_聚光投流决策SOP.md docs/no-code-agent/模块5_全域预算节奏SOP.md tests/test_no_code_docs.py
git commit -m "docs: derive downstream no-code module SOPs"
```

---

### Task 8: Add Package Guide and Cookie Quartet Full Example

**Files:**
- Create: `docs/no-code-agent/README_使用说明.md`
- Create: `docs/no-code-agent/示例_曲奇四重奏_FULL.md`
- Inspect: `examples/cookie_quartet_full_case.json`, `examples/cookie_quartet_with_workbook_data.json`, `docs/QUARTET_DATA_PROVENANCE.md`
- Modify: `tests/test_no_code_docs.py`

**Interfaces:**
- Consumes: all governance, prompts and SOPs.
- Produces: user-operable package and traceable example.

- [ ] **Step 1: Add failing package tests**

```python
class NoCodePackageTest(unittest.TestCase):
    def test_readme_lists_upload_order_and_routes(self):
        text = (ROOT / "docs/no-code-agent/README_使用说明.md").read_text(encoding="utf-8")
        for required in ("上传顺序", "Claude Project", "自定义 GPT", "/full"):
            self.assertIn(required, text)

    def test_example_preserves_evidence_boundaries(self):
        text = (ROOT / "docs/no-code-agent/示例_曲奇四重奏_FULL.md").read_text(encoding="utf-8")
        for required in ("曲奇四重奏", "数据需求.xlsx", "公开观察", "不可确认", "Mock", "M1 → M2 → M6 → M3 → M4 → M5", "人工拍板"):
            self.assertIn(required, text)
```

- [ ] **Step 2: Verify RED**

Run: `../.venv/bin/python -m unittest tests.test_no_code_docs.NoCodePackageTest -v`

Expected: ERROR because package files are absent.

- [ ] **Step 3: Write README**

Document platform setup, upload order (governance, SOPs, optional data/example), routes, cross-conversation state handoff, Web Search boundaries, and no-code persistence/arithmetic limits.

- [ ] **Step 4: Write example**

Use existing Cookie Quartet facts and workbook provenance. Show inputs, evidence registry, module states in required order, benchmark selection, unresolved competitor-account gaps, budget check, Mock status and human decisions. Do not invent competitor Spotlight details, orders or targeting.

- [ ] **Step 5: Verify GREEN and commit**

```bash
../.venv/bin/python -m unittest tests.test_no_code_docs.NoCodePackageTest -v
git add docs/no-code-agent/README_使用说明.md docs/no-code-agent/示例_曲奇四重奏_FULL.md tests/test_no_code_docs.py
git commit -m "docs: add no-code package guide and full example"
```

---

### Task 9: Completion Audit and Regression Verification

**Files:**
- Verify: `docs/TECHNICAL_ARCHITECTURE.md`
- Verify: `docs/DUAL_VERSION_CAPABILITY_MAPPING.md`
- Verify: `docs/no-code-agent/*.md`
- Verify: `tests/test_no_code_docs.py`

**Interfaces:**
- Consumes: all Tasks 1–8.
- Produces: verified package with no missing artifacts, placeholders or obsolete claims.

- [ ] **Step 1: Run document tests**

Run: `../.venv/bin/python -m unittest tests.test_no_code_docs -v`

Expected: all PASS.

- [ ] **Step 2: Run project regression suite**

Run: `../.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`

Expected: exit code 0 with no new failures/errors.

- [ ] **Step 3: Scan forbidden placeholders/claims**

```bash
grep -RInE 'TBD|TODO|PLACEHOLDER|大模型只做报告表达与归纳' docs/TECHNICAL_ARCHITECTURE.md docs/DUAL_VERSION_CAPABILITY_MAPPING.md docs/no-code-agent || true
```

Expected: no matches.

- [ ] **Step 4: Verify file set and Markdown whitespace**

```bash
find docs/no-code-agent -maxdepth 1 -type f -name '*.md' -print | sort
git diff --check -- docs/TECHNICAL_ARCHITECTURE.md docs/DUAL_VERSION_CAPABILITY_MAPPING.md docs/no-code-agent tests/test_no_code_docs.py
```

Expected: README, two prompts, four governance files, six SOPs and example are present; diff check is clean.

- [ ] **Step 5: Review scope and commit corrections**

```bash
git status --short
git diff --stat -- docs/TECHNICAL_ARCHITECTURE.md docs/DUAL_VERSION_CAPABILITY_MAPPING.md docs/no-code-agent tests/test_no_code_docs.py
```

If corrections were needed:

```bash
git add docs/TECHNICAL_ARCHITECTURE.md docs/DUAL_VERSION_CAPABILITY_MAPPING.md docs/no-code-agent tests/test_no_code_docs.py
git commit -m "docs: finalize code and no-code architecture package"
```

