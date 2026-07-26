import json
import re
import unittest
from pathlib import Path
from typing import get_args, get_origin

from pydantic import BaseModel

from models import CampaignRequest
from module_agents.module1 import Module1Output
from module_agents.module2 import Module2Output
from module_agents.module3 import Module3Output
from module_agents.module4 import Module4Output
from module_agents.module5 import Module5Output
from module_agents.module6 import Module6Output
from tools.bidding import STAGE_GUARDRAILS
from tools.budget import (
    DEFAULT_ORGANIC_RATIO,
    PHASE_RATIOS,
    BudgetSplitArgs,
    compute_budget_split,
)
from tools.creator_match import (
    BASE_MATCH_SCORE,
    MAX_MATCH_SCORE,
    PER_TAG_BONUS,
    TIER_AMATEUR_MAX,
    TIER_KOC_MAX,
    TOP_N,
)
from tools.creators import CreatorTierPlanArgs, TierAllocation, plan_creator_tiers
from tools.forecast import (
    MIN_CLICKS,
    MIN_IMPRESSIONS,
    NO_CVR_CPA_MULTIPLIER,
    ROI_BAND_HIGH,
    ROI_BAND_LOW,
    SAMPLE_SAFETY,
    STOP_CPA_MULTIPLIER,
    STOP_CPC_MULTIPLIER,
    TEST_BUDGET_FLOOR_RATIO,
    TEST_BUDGET_RATIO,
    TEST_BUDGET_RATIO_NO_CPA,
)
from tools.keywords import (
    BLUE_OCEAN_BAND,
    FEED_BAND,
    MIN_BLUE_OCEAN,
    MIN_CORE,
    MIN_LONG_TAIL,
    SEARCH_HIGH_BAND,
    SEARCH_LOW_BAND,
    SEARCH_MID_BAND,
)


ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE_PATH = ROOT / "docs" / "TECHNICAL_ARCHITECTURE.md"


class TechnicalArchitectureDocsTest(unittest.TestCase):
    EVIDENCE_LEVELS = (
        "A_官方或授权",
        "B_公开观察",
        "C_用户导入",
        "D_行业基准",
        "E_策略假设",
        "Mock",
    )
    METRIC_SSOT = ("CPC", "CPM", "CPA", "CTR", "CVR", "ROAS")

    def _assert_architecture_semantics(self, architecture):
        mermaid_blocks = re.findall(
            r"```mermaid\n(.*?)\n```", architecture, flags=re.DOTALL
        )
        self.assertGreaterEqual(len(mermaid_blocks), 4)
        self.assertTrue(
            any("人工审批" in block for block in mermaid_blocks),
            "At least one architecture flow must contain an explicit human-approval node",
        )

        for level in self.EVIDENCE_LEVELS:
            self.assertIn(level, architecture, f"Missing evidence level: {level}")
        for metric in self.METRIC_SSOT:
            self.assertRegex(
                architecture,
                rf"(?<![A-Z]){metric}(?![A-Z])",
                f"Missing SSOT metric: {metric}",
            )

        self.assertIn("recommended_ratio", architecture)
        self.assertIn("scenario_ratio", architecture)
        self.assertRegex(
            architecture,
            r"recommended_ratio[^\n]*(?:正式预算|待审批正式建议)",
        )
        self.assertRegex(
            architecture,
            r"scenario_ratio[^\n]*(?:情景|不得进入正式预算)",
        )

        deployment = next(
            (block for block in mermaid_blocks if "Docker Compose" in block),
            None,
        )
        self.assertIsNotNone(deployment, "Missing deployment Mermaid block")
        for path_marker in ("本机", ".venv", "Dockerfile", "Docker Compose"):
            self.assertIn(
                path_marker, deployment, f"Missing deployment path: {path_marker}"
            )

    def test_architecture_documents_current_no_code_boundaries(self):
        """Removing a required current-system boundary must fail this documentation contract."""
        architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

        for required_term in (
            "tools/",
            "model_config.py",
            "Analyzer",
            "Embedding",
            "report_agent_view.py",
            "数据模拟服务",
            "Docker Compose",
            "xhs_knowledge.db",
            "agent_state.db",
            "Grounding Check",
        ):
            with self.subTest(required_term=required_term):
                self.assertIn(required_term, architecture)

        self.assertIn("hybrid_search", architecture)
        self.assertIn("向量 RAG", architecture)
        self.assertNotIn("大模型只做报告表达与归纳", architecture)
        self._assert_architecture_semantics(architecture)

    def test_architecture_semantic_guard_rejects_missing_approval_or_deployment_path(self):
        """Removing a control node or one supported runtime path must fail the contract."""
        original = ARCHITECTURE_PATH.read_text(encoding="utf-8")
        mutations = (
            original.replace("人工审批", "人工复核", 100),
            original.replace("Dockerfile", "容器镜像文件", 100),
            original.replace(".venv", "虚拟环境", 100),
            original.replace("scenario_ratio", "ratio_scenario", 100),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation[-120:]):
                with self.assertRaises(AssertionError):
                    self._assert_architecture_semantics(mutation)


class DualVersionMappingTest(unittest.TestCase):
    def _mapping_rows(self, text):
        table_lines = [line for line in text.splitlines() if line.startswith("|")]
        rows = {}
        for line in table_lines[2:]:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) == 5:
                rows[cells[0]] = cells
        return rows

    def _assert_partial_enforcement_is_honest(self, text):
        rows = self._mapping_rows(text)
        evidence = " ".join(rows["证据审计"])
        self.assertIn("当前只做**部分**证据审计", evidence)
        self.assertRegex(evidence, r"(?:未|不).*A.?E.*(?:优先级|等级)")

        ssot = " ".join(rows["指标统一"])
        self.assertIn("当前是**部分** SSOT", ssot)
        for limitation in ("CPA", "ROAS", "来源名", "采集日期"):
            self.assertIn(limitation, ssot, f"Missing partial-SSOT limit: {limitation}")

    def test_mapping_covers_required_capabilities_and_gaps(self):
        text = (ROOT / "docs" / "DUAL_VERSION_CAPABILITY_MAPPING.md").read_text(
            encoding="utf-8"
        )

        table_lines = [line for line in text.splitlines() if line.startswith("|")]
        expected_header = (
            "| 能力 | 代码版实现与文件 | Claude/GPT 零代码实现 | "
            "零代码差距与补偿 | 当前状态 |"
        )
        self.assertGreaterEqual(len(table_lines), 3)
        self.assertEqual(table_lines[0], expected_header)
        self.assertEqual(
            table_lines[1],
            "| --- | --- | --- | --- | --- |",
        )

        rows = {}
        for line in table_lines[2:]:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            self.assertEqual(
                len(cells),
                5,
                msg=f"Mapping row must have exactly five columns: {line}",
            )
            rows[cells[0]] = cells

        for required in (
            "主控路由",
            "六模块执行",
            "知识检索",
            "状态管理",
            "数据接入",
            "证据审计",
            "确定性计算",
            "指标统一",
            "数字溯源",
            "Mock 隔离",
            "降级",
            "报告生成",
            "持久化",
            "人工审批",
            "差距与补偿",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)
                self.assertIn(required, rows)

        for required_row in ("Analyzer", "Embedding", "Docker 部署"):
            with self.subTest(required_row=required_row):
                self.assertIn(required_row, rows)

        six_modules = rows["六模块执行"]
        self.assertIn("M1 → M2 → M6 → M3 → M4 → M5", six_modules[3])
        self.assertIn("计划", six_modules[3])
        self.assertIn("当前运行时按数值顺序", six_modules[1])
        self.assertIn("M1 → M2 → M3 → M4 → M5 → M6", text)

        embedding = rows["Embedding"]
        self.assertIn("hybrid_search", embedding[1])
        self.assertIn("混合检索", embedding[4])
        self.assertIn("向量", embedding[3])

        weaker_controls = rows["差距与补偿"][3]
        for control in ("持久化", "程序校验", "Mock 强制隔离"):
            with self.subTest(control=control):
                self.assertIn(control, weaker_controls)
        self.assertIn("较弱", weaker_controls)
        self._assert_partial_enforcement_is_honest(text)

    def test_mapping_rejects_full_enforcement_claims_for_partial_code_paths(self):
        """The mapping must not promote presence/Mock checks or heuristic SSOT to full policy."""
        original = (ROOT / "docs" / "DUAL_VERSION_CAPABILITY_MAPPING.md").read_text(
            encoding="utf-8"
        )
        mutations = (
            original.replace("当前只做**部分**证据审计", "当前执行完整证据审计", 1),
            original.replace("当前是**部分** SSOT", "当前是完整 SSOT", 1),
            original.replace("来源名", "来源等级", 1),
            original.replace("采集日期", "口径可比性", 1),
            original.replace("未执行", "已执行", 1),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation[-120:]):
                with self.assertRaises(AssertionError):
                    self._assert_partial_enforcement_is_honest(mutation)


class NoCodeGovernanceTest(unittest.TestCase):
    """Protect the shared safety contracts consumed by every no-code module."""

    FOLDER = ROOT / "docs" / "no-code-agent"

    def _read(self, filename):
        return (self.FOLDER / filename).read_text(encoding="utf-8")

    def _section(self, text, heading):
        match = re.search(
            rf"^{re.escape(heading)}\n(.*?)(?=^## |\Z)", text, flags=re.MULTILINE | re.DOTALL
        )
        self.assertIsNotNone(match, f"Missing section: {heading}")
        return match.group(1)

    def _fenced_yaml(self, text, heading):
        section = self._section(text, heading)
        match = re.search(r"```yaml\n(.*?)\n```", section, flags=re.DOTALL)
        self.assertIsNotNone(match, f"Missing YAML contract in {heading}")
        return match.group(1)

    def _fenced_json(self, text, heading):
        section = self._section(text, heading)
        match = re.search(r"```json\n(.*?)\n```", section, flags=re.DOTALL)
        self.assertIsNotNone(match, f"Missing JSON contract in {heading}")
        return json.loads(match.group(1))

    def _yaml_mapping(self, yaml_block, key, indent):
        match = re.search(
            rf"^ {{{indent}}}{re.escape(key)}:\n(.*?)(?=^ {{{indent}}}[^ \n][^\n]*:|\Z)",
            yaml_block,
            flags=re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match, f"Missing YAML mapping: {key}")
        return match.group(0)

    def _ratio_pairs_with_provenance(self, ratio_block):
        pattern = re.compile(
            r'- search: (?P<search>\d+)%\n'
            r'\s+feed: (?P<feed>\d+)%\n'
            r'\s+evidence_id: "(?P<evidence_id>[^"]+)"\n'
            r'\s+evidence_level: "(?P<evidence_level>[^"]+)"\n'
            r'\s+source: "(?P<source>[^"]+)"\n'
            r'\s+period: "(?P<period>[^"]+)"\n'
            r'\s+formula: "(?P<formula>[^"]+)"\n'
            r'\s+selection_reason: "(?P<selection_reason>[^"]+)"'
        )
        pairs = [match.groupdict() for match in pattern.finditer(ratio_block)]
        self.assertEqual(len(pairs), 2, "Every declared pair must carry provenance")
        for pair in pairs:
            self.assertEqual(int(pair["search"]) + int(pair["feed"]), 100)
            self.assertTrue(pair["evidence_id"].startswith("E-"))
            self.assertEqual(pair["evidence_level"], "E_策略假设")
            self.assertTrue(pair["source"])
            self.assertTrue(pair["period"])
            self.assertEqual(pair["formula"], "search + feed = 100%")
            self.assertTrue(pair["selection_reason"])
        return pairs

    def test_evidence_discipline_keeps_mock_out_of_formal_actions(self):
        """Mock must be prohibited from—not merely mentioned near—formal actions."""
        evidence = self._read("01_全局证据与数据纪律.md")

        for label in (
            "A_官方或授权",
            "B_公开观察",
            "C_用户导入",
            "D_行业基准",
            "E_策略假设",
            "Mock",
        ):
            with self.subTest(label=label):
                self.assertIn(label, self._section(evidence, "## 1. 证据等级与允许结论"))

        discipline = self._section(evidence, "## 2. 禁止替代与数字纪律")
        self.assertRegex(
            discipline,
            r"`Mock`.*(?:永不|不得).*采购.*下单.*正式预算",
        )
        self.assertNotRegex(
            evidence,
            r"`Mock`[^\n]*(?:可|可以|允许)[^\n]*(?:采购|下单|正式预算)",
        )
        search_limits = self._section(evidence, "## 3. Web Search 使用边界")
        self.assertIn("不可确认", search_limits)
        self.assertIn("内部小红书", search_limits)

    def _assert_evidence_registry_schema(self, registry):
        self.assertEqual(
            set(registry),
            {"version", "run_id", "evidence", "claims", "competitor_subjects"},
        )
        self.assertGreaterEqual(len(registry["evidence"]), 1)
        self.assertGreaterEqual(len(registry["claims"]), 1)
        evidence_fields = {
            "id",
            "evidence_level",
            "source_type",
            "source_name",
            "source_url",
            "collected_at",
            "period",
            "status",
            "is_mock",
            "allowed_use",
            "prohibited_use",
        }
        claim_fields = {
            "id",
            "subject",
            "claim_type",
            "status",
            "value",
            "unit",
            "evidence_ids",
            "formal_use",
            "required_evidence",
        }
        subject_fields = {"name", "evidence_ids", "status"}
        for item in registry["evidence"]:
            self.assertEqual(set(item), evidence_fields)
        for item in registry["claims"]:
            self.assertEqual(set(item), claim_fields)
        for item in registry["competitor_subjects"]:
            self.assertEqual(set(item), subject_fields)

        ids = [item["id"] for item in registry["evidence"]]
        self.assertEqual(len(ids), len(set(ids)))
        known_ids = set(ids)
        for claim in registry["claims"]:
            self.assertLessEqual(set(claim["evidence_ids"]), known_ids)
        for subject in registry["competitor_subjects"]:
            self.assertLessEqual(set(subject["evidence_ids"]), known_ids)

    def test_evidence_registry_has_one_stable_machine_contract(self):
        """All SOP handoffs must share the same named evidence registry and field schema."""
        evidence = self._read("01_全局证据与数据纪律.md")
        payload = self._fenced_json(evidence, "## 1.1 规范 `evidence_registry`")
        self.assertEqual(set(payload), {"evidence_registry"})
        self._assert_evidence_registry_schema(payload["evidence_registry"])
        self.assertNotIn("claim_evidence_registry", evidence)

    def test_evidence_registry_schema_rejects_legacy_name_and_missing_provenance(self):
        """Legacy root names and partial evidence rows cannot satisfy the handoff contract."""
        evidence = self._read("01_全局证据与数据纪律.md")
        registry = self._fenced_json(
            evidence, "## 1.1 规范 `evidence_registry`"
        )["evidence_registry"]
        mutations = []
        missing_url = json.loads(json.dumps(registry))
        missing_url["evidence"][0].pop("source_url")
        mutations.append(missing_url)
        unknown_reference = json.loads(json.dumps(registry))
        unknown_reference["claims"][0]["evidence_ids"] = ["UNKNOWN-001"]
        mutations.append(unknown_reference)
        missing_value = json.loads(json.dumps(registry))
        missing_value["claims"][0].pop("value")
        mutations.append(missing_value)
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.assertRaises(AssertionError):
                    self._assert_evidence_registry_schema(mutation)

    def test_module_state_fields_are_root_fields_inside_its_fenced_yaml_contract(self):
        """A prose field list cannot substitute for the portable module_state payload."""
        state = self._read("02_模块状态输出契约.md")
        state_yaml = self._fenced_yaml(state, "## 1. 有效 `module_state`")
        self.assertTrue(state_yaml.startswith("module_state:\n"))

        for field in (
            "run_id:",
            "module:",
            "status:",
            "evidence_ids:",
            "confirmed_facts:",
            "assumptions:",
            "decisions:",
            "unresolved_gaps:",
            "human_review_items:",
            "confidence:",
            "decision_source:",
        ):
            with self.subTest(field=field):
                self.assertRegex(state_yaml, rf"(?m)^  {re.escape(field)}")
        self.assertIn("跨会话", state)
        self.assertIn("handoff", state)

    def test_dependency_conflict_precedence_is_ordered_and_mock_cannot_win(self):
        """A reversed source hierarchy would let weak or simulated evidence control decisions."""
        dependency = self._read("03_跨模块依赖与冲突处理.md")
        self.assertIn("M1 → M2 → M6 → M3 → M4 → M5", dependency)
        conflict = self._section(dependency, "## 2. 冲突优先级")
        ranked_labels = re.findall(r"^\d+\. .*?`([^`]+)`", conflict, flags=re.MULTILINE)
        self.assertEqual(
            ranked_labels,
            [
                "A_官方或授权",
                "C_用户导入",
                "B_公开观察",
                "D_行业基准",
                "E_策略假设",
                "Mock",
            ],
        )
        self.assertRegex(conflict, r"`Mock`.*不能参与正式选择")

    def test_dependency_sections_define_predecessors_defaults_gaps_and_full_run_stops(self):
        """Each /full dependency control must live in its operational section, not nearby prose."""
        dependency = self._read("03_跨模块依赖与冲突处理.md")
        predecessors = self._section(dependency, "## 1. 前序要求与缺口处理")
        table_rows = {}
        for line in predecessors.splitlines():
            if not line.startswith("|") or line.startswith("| ---"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if cells[0] != "模块":
                table_rows[cells[0]] = cells

        self.assertEqual(set(table_rows), {"M1", "M2", "M3", "M4", "M5", "M6"})
        expected_predecessors = {
            "M1": "品牌范围、目标期、可用证据",
            "M2": "M1 的赛道/观察边界",
            "M6": "M1、M2 的主题边界",
            "M3": "M2 人群、M6 关键词、达人输入",
            "M4": "M3 候选、指标登记和审批边界",
            "M5": "M4 测试方案及所有选定指标",
        }
        for module, expected in expected_predecessors.items():
            with self.subTest(module=module):
                self.assertEqual(table_rows[module][1], expected)
                self.assertTrue(table_rows[module][2])
                self.assertTrue(table_rows[module][3])
        self.assertIn("安全默认值只允许建立待验证方案", predecessors)
        self.assertIn("不能把不可推断的缺口写成事实", predecessors)

        conservation_failure = self._section(dependency, "## 3. 预算守恒失败")
        self.assertRegex(
            conservation_failure,
            r"发生预算守恒失败时，禁止输出正式预算、采购或下单结论",
        )
        self.assertIn("human_review_items", conservation_failure)

        final_checks = self._section(dependency, "## 4. 全案结束检查")
        for required_check in (
            "每个前序状态可追溯",
            "证据 ID、期间、来源、公式或假设标签",
            "不可推断缺口、冲突或低置信度项",
            "Mock` 是否完全隔离",
            "同一版 `benchmark_registry`",
            "预算是否守恒",
            "人工审批项",
        ):
            with self.subTest(required_check=required_check):
                self.assertIn(required_check, final_checks)

    def test_ssot_ratios_are_complementary_and_keep_formal_and_scenario_uses_distinct(self):
        """Ratio pairs must conserve budget and prevent scenarios from becoming formal plans."""
        ssot = self._read("04_指标单一事实源规范.md")
        registry = self._fenced_yaml(ssot, "## 1. 有效 `benchmark_registry`")
        ratios = self._yaml_mapping(registry, "ratios", 2)
        recommended = self._yaml_mapping(ratios, "recommended_ratio", 4)
        scenario = self._yaml_mapping(ratios, "scenario_ratio", 4)

        for ratio_block in (recommended, scenario):
            self._ratio_pairs_with_provenance(ratio_block)
            self.assertIn("search + feed = 100%", ratio_block)

        self.assertRegex(recommended, r'purpose: ".*正式预算计算.*"')
        self.assertRegex(scenario, r'purpose: ".*仅用于 A/B 情景比较.*不进入正式预算.*"')

    def test_ssot_ratio_provenance_guard_rejects_unlabeled_numeric_pairs(self):
        """Every numeric search/feed pair must remain an explicit E-level hypothesis."""
        ssot = self._read("04_指标单一事实源规范.md")
        registry = self._fenced_yaml(ssot, "## 1. 有效 `benchmark_registry`")
        ratios = self._yaml_mapping(registry, "ratios", 2)
        recommended = self._yaml_mapping(ratios, "recommended_ratio", 4)
        mutations = (
            recommended.replace('evidence_level: "E_策略假设"\n', "", 1),
            recommended.replace('evidence_id: "E-', 'evidence_id: "B-', 1),
            recommended.replace('formula: "search + feed = 100%"', 'formula: "模型建议"', 1),
            recommended.replace('selection_reason: "', 'selection_reason: "" # ', 1),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation[-160:]):
                with self.assertRaises(AssertionError):
                    self._ratio_pairs_with_provenance(mutation)

    def test_ssot_registry_fields_and_metric_scope_are_inside_the_fenced_contract(self):
        """Every metric entry—not just the registry—must carry provenance and selection fields."""
        ssot = self._read("04_指标单一事实源规范.md")
        registry = self._fenced_yaml(ssot, "## 1. 有效 `benchmark_registry`")
        self.assertTrue(registry.startswith("benchmark_registry:\n"))
        metrics = self._yaml_mapping(registry, "metrics", 2)
        required_fields = (
            "candidates:",
            "selected_value:",
            "selected_source:",
            "selection_reason:",
            "period:",
            "formula:",
            "evidence_level:",
        )
        for metric in ("CPC", "CPM", "CPA", "CTR", "CVR", "ROAS"):
            with self.subTest(metric=metric):
                metric_entry = self._yaml_mapping(metrics, metric, 4)
                for field in required_fields:
                    self.assertRegex(metric_entry, rf"(?m)^      {re.escape(field)}")

    def test_ssot_binds_exact_historical_values_and_ranged_future_recommendations_to_fields(self):
        """History must remain exact while future recommendations remain explicit ranges."""
        ssot = self._read("04_指标单一事实源规范.md")
        registry = self._fenced_yaml(ssot, "## 1. 有效 `benchmark_registry`")
        metrics = self._yaml_mapping(registry, "metrics", 2)
        cpc = self._yaml_mapping(metrics, "CPC", 4)
        self.assertRegex(cpc, r'(?m)^      selected_value: 2\.83$')
        self.assertRegex(cpc, r'(?m)^      value_kind: "historical_fact"$')
        self.assertRegex(cpc, r'(?m)^      value_precision: "exact"$')

        ratios = self._yaml_mapping(registry, "ratios", 2)
        for ratio_name in ("recommended_ratio", "scenario_ratio"):
            with self.subTest(ratio_name=ratio_name):
                ratio = self._yaml_mapping(ratios, ratio_name, 4)
                self.assertRegex(ratio, r'(?m)^      value_kind: "future_recommendation"$')
                self.assertRegex(
                    ratio,
                    r'(?m)^      range_representation: "complementary_pairs"$',
                )
                self.assertRegex(ratio, r"(?m)^        - search: \d+%$")
                self.assertRegex(ratio, r"(?m)^          feed: \d+%$")

        selection_rules = self._section(ssot, "## 2. 选择规则")
        self.assertIn("历史事实", selection_rules)
        self.assertIn("精确值", selection_rules)
        self.assertIn("未来建议", selection_rules)
        self.assertIn("范围", selection_rules)


class NoCodeEntryPromptTest(unittest.TestCase):
    """Keep the two no-code entry prompts thin, governed, and platform-aware."""

    FOLDER = ROOT / "docs" / "no-code-agent"
    PROMPTS = (
        "Claude_Project_System_Prompt.md",
        "Custom_GPT_Instructions.md",
    )
    SOP_ROUTES = {
        "/m1": "模块1_赛道竞品分析SOP.md",
        "/m2": "模块2_用户画像选题SOP.md",
        "/m3": "模块3_达人匹配SOP.md",
        "/m4": "模块4_聚光投流决策SOP.md",
        "/m5": "模块5_全域预算节奏SOP.md",
        "/m6": "模块6_关键词策略SOP.md",
    }
    GOVERNANCE_FILES = (
        "01_全局证据与数据纪律.md",
        "02_模块状态输出契约.md",
        "03_跨模块依赖与冲突处理.md",
        "04_指标单一事实源规范.md",
    )

    def _read(self, filename):
        return (self.FOLDER / filename).read_text(encoding="utf-8")

    def _routing_rows(self, text):
        """Return exact command/instruction cells from the prompt's routing table."""
        table_match = re.search(
            r"(?m)^## 命令路由[^\n]*\n\n(?P<table>(?:^\|[^\n]*\|\n?)+)", text
        )
        self.assertIsNotNone(table_match, "Missing command routing table")

        rows = []
        for line in table_match.group("table").splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            self.assertEqual(len(cells), 2, f"Routing row must have two cells: {line}")
            if cells[0] == "命令" or set(cells[0]) <= {"-", " ", ":"}:
                continue
            rows.append((cells[0].strip("`"), cells[1]))

        commands = [command for command, _ in rows]
        self.assertEqual(len(commands), len(set(commands)), "Routing commands must be unique")
        return dict(rows)

    def _assert_exact_route_rows(self, rows):
        for route, sop_filename in self.SOP_ROUTES.items():
            self.assertEqual(rows.get(route), f"`{sop_filename}`")
        self.assertIn("/full", rows)
        self.assertIn("M1 → M2 → M6 → M3 → M4 → M5", rows["/full"])

    def _assert_postprocess_route_rows(self, rows):
        for route in ("/ab", "/board"):
            self.assertIn(route, rows)
            self.assertIn("已完成的结构化状态", rows[route])
            self.assertRegex(rows[route], r"不得(?:补造|补充|虚构|编造)证据")

    def _replace_route_instruction(self, text, route, instruction):
        mutated, replacements = re.subn(
            rf"(?m)^(\| `{re.escape(route)}` \| )[^|]*(\|)$",
            rf"\1{instruction}\2",
            text,
        )
        self.assertEqual(replacements, 1, f"Expected one routing row for {route}")
        return mutated

    def test_both_prompts_expose_routes_and_exact_sop_routes(self):
        """Changing a command route or silently routing it to another SOP is a bug."""
        for filename in self.PROMPTS:
            text = self._read(filename)
            with self.subTest(prompt=filename):
                self._assert_exact_route_rows(self._routing_rows(text))

    def test_both_prompts_require_shared_governance_and_structured_state(self):
        """Removing a shared control would permit unsupported cross-module decisions."""
        required_controls = (
            "module_state",
            "benchmark_registry",
            "证据标签",
            "未解决缺口",
            "Grounding 自检",
            "预算守恒",
            "Mock 隔离",
            "人工审批",
            "安全默认值",
            "仅用于测试的假设",
            "不可推断缺口",
        )
        for filename in self.PROMPTS:
            text = self._read(filename)
            with self.subTest(prompt=filename):
                for governance_file in self.GOVERNANCE_FILES:
                    self.assertIn(governance_file, text)
                for control in required_controls:
                    self.assertIn(control, text)

    def test_prompts_preserve_evidence_boundaries_and_thin_orchestration(self):
        """A prompt must not invent private XHS facts or become a copied business SOP."""
        copied_sop_headings = (
            "## 职责与边界",
            "## 输入",
            "## 前序依赖",
            "## 证据",
            "## 执行步骤",
            "## 输出契约",
        )
        for filename in self.PROMPTS:
            text = self._read(filename)
            with self.subTest(prompt=filename):
                self.assertIn("不得声称拥有内部小红书访问", text)
                self.assertIn("不得虚构竞品账户", text)
                self.assertIn("不得补造证据", text)
                self.assertLess(
                    len(text),
                    7000,
                    "Entry prompt must stay a thin orchestrator; keep business SOP logic external.",
                )
                for heading in copied_sop_headings:
                    self.assertNotIn(heading, text)

    def test_ab_and_board_only_transform_completed_structured_state(self):
        """A/B and board commands may summarize state but must never create evidence."""
        for filename in self.PROMPTS:
            text = self._read(filename)
            with self.subTest(prompt=filename):
                self._assert_postprocess_route_rows(self._routing_rows(text))

    def test_postprocess_route_contract_rejects_row_local_mutations(self):
        """A prior routing row must not satisfy a damaged /ab or /board row."""
        original = self._read("Claude_Project_System_Prompt.md")
        for route in ("/ab", "/board"):
            with self.subTest(route=route):
                mutated = self._replace_route_instruction(
                    original, route, "仅生成展示内容。"
                )
                with self.assertRaises(AssertionError):
                    self._assert_postprocess_route_rows(self._routing_rows(mutated))

    def test_exact_route_contract_rejects_row_local_mutations(self):
        """The exact SOP mapping and /full order must live in their own table cells."""
        original = self._read("Claude_Project_System_Prompt.md")
        mutations = {
            "/m1": "`模块2_用户画像选题SOP.md`",
            "/full": "依次按模块编号运行。",
        }
        for route, instruction in mutations.items():
            with self.subTest(route=route):
                mutated = self._replace_route_instruction(original, route, instruction)
                with self.assertRaises(AssertionError):
                    self._assert_exact_route_rows(self._routing_rows(mutated))

    def test_platform_specific_retrieval_rules_are_explicit(self):
        """Claude and GPT use different knowledge-retrieval safeguards by design."""
        claude = self._read("Claude_Project_System_Prompt.md")
        gpt = self._read("Custom_GPT_Instructions.md")

        self.assertIn("Project Knowledge", claude)
        self.assertIn("Web Search 仅可用于公开且当前可复查的来源", claude)
        self.assertIn("选择性", gpt)
        self.assertIn("明确检索并读取", gpt)
        for sop_filename in self.SOP_ROUTES.values():
            self.assertIn(sop_filename, gpt)


class NoCodeModuleSopTest(unittest.TestCase):
    """Keep every module SOP aligned with current contracts and governance."""

    FOLDER = ROOT / "docs" / "no-code-agent"
    NORMATIVE_POLICY_MARKER = (
        '> 规范性声明：本节操作约束仅以“控制规则表”为准；'
        "表外文字只作解释、状态描述或示例，不授予例外。"
    )
    DOCUMENT_POLICY_MARKER = (
        '> 文档级规范性声明：本 SOP 的全部十个业务章节（职责与边界、输入、前序依赖、证据、'
        '执行步骤、输出契约、module_state、Grounding 自检、降级、人工拍板）均为强制执行契约；'
        '控制规则表是禁止与必须规则的唯一增删入口，任何表外文字、代码块或示例不得取消、替代或覆盖这些契约。'
    )
    NON_NORMATIVE_START = "<!-- NON-NORMATIVE:START -->"
    NON_NORMATIVE_END = "<!-- NON-NORMATIVE:END -->"
    DOWNSTREAM_SOPS = {
        "模块3_达人匹配SOP.md",
        "模块4_聚光投流决策SOP.md",
        "模块5_全域预算节奏SOP.md",
    }
    REQUIRED_SECTIONS = (
        "职责与边界",
        "输入",
        "前序依赖",
        "证据",
        "执行步骤",
        "输出契约",
        "module_state",
        "Grounding 自检",
        "降级",
        "人工拍板",
    )
    SOP_CONTRACTS = {
        "模块1_赛道竞品分析SOP.md": {
            "module": "M1",
            "output_model": Module1Output,
            "input_contract": {
                "campaign_request": {
                    "brand_name",
                    "category",
                    "product_name",
                    "selling_points",
                    "initial_audience",
                    "goal",
                    "constraints",
                    "category_note_evidence",
                    "competitor_evidence",
                    "benchmark_evidence",
                    "account_violation_evidence",
                    "official_rule_evidence",
                },
                "workflow": {"run_id", "benchmark_registry", "evidence_registry"},
                "upstream_module_states": set(),
            },
        },
        "模块2_用户画像选题SOP.md": {
            "module": "M2",
            "output_model": Module2Output,
            "input_contract": {
                "campaign_request": {
                    "brand_name",
                    "category",
                    "product_name",
                    "selling_points",
                    "price_min",
                    "price_max",
                    "currency",
                    "initial_audience",
                    "goal",
                    "constraints",
                    "category_note_evidence",
                },
                "workflow": {"run_id", "benchmark_registry", "evidence_registry"},
                "upstream_module_states": {"M1"},
            },
        },
        "模块6_关键词策略SOP.md": {
            "module": "M6",
            "output_model": Module6Output,
            "input_contract": {
                "campaign_request": {
                    "brand_name",
                    "category",
                    "product_name",
                    "selling_points",
                    "initial_audience",
                    "goal",
                    "constraints",
                    "category_note_evidence",
                    "benchmark_evidence",
                    "trending_keyword_evidence",
                },
                "workflow": {"run_id", "benchmark_registry", "evidence_registry"},
                "upstream_module_states": {"M1", "M2"},
            },
        },
        "模块3_达人匹配SOP.md": {
            "module": "M3",
            "output_model": Module3Output,
            "input_contract": {
                "campaign_request": {
                    "brand_name",
                    "category",
                    "product_name",
                    "selling_points",
                    "initial_audience",
                    "total_budget_cny",
                    "spotlight_budget_cny",
                    "campaign_days",
                    "goal",
                    "constraints",
                    "category_note_evidence",
                    "benchmark_evidence",
                    "creator_evidence",
                },
                "workflow": {"run_id", "benchmark_registry", "evidence_registry"},
                "upstream_module_states": {"M2", "M6"},
            },
        },
        "模块4_聚光投流决策SOP.md": {
            "module": "M4",
            "output_model": Module4Output,
            "input_contract": {
                "campaign_request": {
                    "brand_name",
                    "category",
                    "product_name",
                    "selling_points",
                    "price_min",
                    "price_max",
                    "currency",
                    "initial_audience",
                    "total_budget_cny",
                    "spotlight_budget_cny",
                    "campaign_days",
                    "goal",
                    "constraints",
                    "category_note_evidence",
                    "benchmark_evidence",
                    "paid_risk_demo_scenarios",
                },
                "workflow": {"run_id", "benchmark_registry", "evidence_registry"},
                "upstream_module_states": {"M1", "M2", "M6", "M3"},
            },
        },
        "模块5_全域预算节奏SOP.md": {
            "module": "M5",
            "output_model": Module5Output,
            "input_contract": {
                "campaign_request": {
                    "brand_name",
                    "category",
                    "product_name",
                    "selling_points",
                    "price_min",
                    "price_max",
                    "currency",
                    "initial_audience",
                    "total_budget_cny",
                    "spotlight_budget_cny",
                    "campaign_days",
                    "goal",
                    "constraints",
                    "benchmark_evidence",
                    "creator_evidence",
                    "owned_history_summary",
                    "owned_content_history",
                },
                "workflow": {"run_id", "benchmark_registry", "evidence_registry"},
                "upstream_module_states": {"M1", "M2", "M6", "M3", "M4"},
            },
        },
    }
    POLICY_CONTRACTS = {
        "模块1_赛道竞品分析SOP.md": {
            "证据": {
                "M1-SAMPLE-EXTRAPOLATION": (
                    "禁止",
                    "B_公开观察样本",
                    "外推为平台大盘或样本外事实",
                ),
                "M1-SSOT-BYPASS": (
                    "禁止",
                    "CPC、CPM、转化成本",
                    "绕过 benchmark_registry 读取或生成数值",
                ),
                "M1-COMPETITOR-PRIVATE-FACTS": (
                    "禁止",
                    "公开竞品观察",
                    "推断竞品真实预算、真实定向或账户事实",
                ),
                "M1-RULE-FREQUENCY": (
                    "禁止",
                    "官方规则",
                    "替代 account_violation_evidence 证明观察到的违规频次",
                ),
            },
        },
        "模块2_用户画像选题SOP.md": {
            "前序依赖": {
                "M2-M1-DEPENDENCY": (
                    "必须",
                    "M2",
                    "消费同一 run_id 的 M1 module_state",
                ),
            },
            "证据": {
                "M2-UNSUPPORTED-SCORING": (
                    "禁止",
                    "无证据的 organic_score、paid_score 与筛选阈值",
                    "表述为已验证分数；必须标记为 E_策略假设",
                ),
                "M2-UNVALIDATED-TARGETING": (
                    "禁止",
                    "未经平台和账户验证的定向标签",
                    "表述为可用定向；只能作为候选",
                ),
            },
        },
        "模块6_关键词策略SOP.md": {
            "职责与边界": {
                "M6-CANONICAL-OWNERSHIP": (
                    "必须",
                    "M6",
                    "作为零代码流程唯一规范关键词库所有者",
                ),
                "M6-M3-NO-REGENERATION": (
                    "禁止",
                    "M3",
                    "脱离 M6 module_state 重新生成关键词",
                ),
            },
            "前序依赖": {
                "M6-M1-DEPENDENCY": (
                    "必须",
                    "M6",
                    "消费同一 run_id 的 M1 module_state",
                ),
                "M6-M2-DEPENDENCY": (
                    "必须",
                    "M6",
                    "消费同一 run_id 的 M2 module_state",
                ),
            },
            "证据": {
                "M6-UNSUPPORTED-MARKET-CLAIMS": (
                    "禁止",
                    "缺少搜索量、笔记数量或当前来源证据的关键词",
                    "声称蓝海、趋势、热搜或实时热度",
                ),
            },
        },
        "模块3_达人匹配SOP.md": {
            "职责与边界": {
                "M3-M6-CANONICAL-KEYWORDS": (
                    "必须",
                    "M3 keyword_tracks",
                    "只转换同一 run_id 的 M6 规范词库，不重新生成、另建或扩充关键词",
                ),
            },
            "前序依赖": {
                "M3-M2-DEPENDENCY": (
                    "必须",
                    "M3",
                    "消费同一 run_id 的 M2 persona 与 content 状态",
                ),
                "M3-M6-DEPENDENCY": (
                    "必须",
                    "M3",
                    "消费同一 run_id 的 M6 规范关键词状态",
                ),
            },
            "证据": {
                "M3-CREATOR-EVIDENCE": (
                    "必须",
                    "每个达人候选",
                    "绑定可复核身份、报价、过往结果、受众匹配证据与名额状态",
                ),
                "M3-NO-FAKE-RECOMMENDATION": (
                    "禁止",
                    "placeholder 或 Mock 达人",
                    "描述为真实推荐或写入 matched_creators",
                ),
                "M3-NO-PREVERIFICATION-PURCHASE": (
                    "禁止",
                    "未人工核验的达人候选",
                    "进入采购、下单或合作承诺",
                ),
            },
        },
        "模块4_聚光投流决策SOP.md": {
            "前序依赖": {
                "M4-M1-DEPENDENCY": (
                    "必须",
                    "M4",
                    "消费同一 run_id 的 M1 benchmark 与赛道边界状态",
                ),
                "M4-M2-DEPENDENCY": (
                    "必须",
                    "M4",
                    "消费同一 run_id 的 M2 material 与 persona 状态",
                ),
                "M4-M6-DEPENDENCY": (
                    "必须",
                    "M4",
                    "消费同一 run_id 的 M6 规范关键词状态",
                ),
                "M4-M3-DEPENDENCY": (
                    "必须",
                    "M4",
                    "消费同一 run_id 的 M3 达人候选与名额状态",
                ),
            },
            "证据": {
                "M4-BENCHMARK-CITATION": (
                    "必须",
                    "出价、测试带宽与止损线",
                    "引用同版 benchmark_registry 的 selected_source、period 与公式",
                ),
                "M4-NO-INTERNAL-ACCOUNT-FACTS": (
                    "禁止",
                    "公开观察、策略假设或 Mock 情景",
                    "表述为内部账户定向、竞价、转化或事故事实",
                ),
            },
            "执行步骤": {
                "M4-RATIO-SEPARATION": (
                    "禁止",
                    "scenario_ratio",
                    "替代 recommended_ratio 或进入正式预算计算",
                ),
                "M4-RATIO-CONSERVATION": (
                    "必须",
                    "recommended_ratio 与 scenario_ratio 的每个 search/feed 配对",
                    "各自满足 search + feed = 1.0（100%）",
                ),
                "M4-RISK-COMPONENTS": (
                    "必须",
                    "每个 risk_playbook 项",
                    "在 symptom/response 中包含诊断、动作、停止或升级条件与 owner",
                ),
            },
        },
        "模块5_全域预算节奏SOP.md": {
            "前序依赖": {
                "M5-M1-DEPENDENCY": (
                    "必须",
                    "M5",
                    "消费同一 run_id 的 M1 状态",
                ),
                "M5-M2-DEPENDENCY": (
                    "必须",
                    "M5",
                    "消费同一 run_id 的 M2 状态",
                ),
                "M5-M6-DEPENDENCY": (
                    "必须",
                    "M5",
                    "消费同一 run_id 的 M6 状态",
                ),
                "M5-M3-DEPENDENCY": (
                    "必须",
                    "M5",
                    "消费同一 run_id 的 M3 状态",
                ),
                "M5-M4-DEPENDENCY": (
                    "必须",
                    "M5",
                    "消费同一 run_id 的 M4 状态",
                ),
            },
            "证据": {
                "M5-HISTORY-FUTURE-PRECISION": (
                    "必须",
                    "历史事实与未来建议",
                    "历史保留来源精确值，未来未批准建议使用范围",
                ),
                "M5-NO-UNRESOLVED-FORMAL-OUTPUT": (
                    "禁止",
                    "存在未解决同优先级冲突或 Mock 污染的 M5",
                    "输出正式预算、采购、下单或放量结论",
                ),
            },
            "执行步骤": {
                "M5-TOTAL-BUDGET-CONSERVATION": (
                    "必须",
                    "budget_split",
                    "organic_budget_cny + paid_budget_cny = normalized_total_budget_cny",
                ),
                "M5-PHASE-BUDGET-CONSERVATION": (
                    "必须",
                    "phases",
                    "sum(phases[].paid_budget_cny) = budget_split.paid_budget_cny",
                ),
                "M5-COMPLETE-ACTION-PLAN": (
                    "必须",
                    "M5 正式业务输出",
                    "同时包含预算、阶段、达人分层、出价、联动规则与应急动作",
                ),
                "M5-PHASE-REMAINDER": (
                    "必须",
                    "阶段整数尾差",
                    "归入 phases[1]（爆发期）后执行阶段守恒检查",
                ),
                "M5-CREATOR-TIER-ROUNDING": (
                    "必须",
                    "达人层级金额",
                    "按 plan_creator_tiers 对每层独立 round，不重分配整数尾差",
                ),
            },
        },
    }
    VALIDATION_CONTRACTS = {
        "模块4_聚光投流决策SOP.md": {
            "ratio_contract": {
                "recommended_ratio": {
                    "source": "benchmark_registry.ratios.recommended_ratio.pairs",
                    "use": "formal_budget",
                    "equation": "search + feed = 1.0",
                },
                "scenario_ratio": {
                    "source": "benchmark_registry.ratios.scenario_ratio.pairs",
                    "use": "scenario_only",
                    "equation": "search + feed = 1.0",
                },
            }
        },
        "模块5_全域预算节奏SOP.md": {
            "normalization": {
                "raw_field": "campaign_request.total_budget_cny",
                "normalized_field": "normalized_total_budget_cny",
                "formula": "int(round(total_budget_cny))",
                "rounding_semantics": "Python round; ties-to-even",
                "rounding_delta_formula": (
                    "normalized_total_budget_cny - total_budget_cny"
                ),
                "module_state_record": {
                    "location": "assumptions/decisions",
                    "fields": [
                        "raw_total_budget_cny",
                        "normalized_total_budget_cny",
                        "rounding_delta",
                    ],
                },
                "examples": [
                    {
                        "raw_total_budget_cny": 100000.4,
                        "normalized_total_budget_cny": 100000,
                        "rounding_delta": -0.4,
                    },
                    {
                        "raw_total_budget_cny": 100000.5,
                        "normalized_total_budget_cny": 100000,
                        "rounding_delta": -0.5,
                    },
                    {
                        "raw_total_budget_cny": 100000.6,
                        "normalized_total_budget_cny": 100001,
                        "rounding_delta": 0.4,
                    },
                ],
            },
            "budget_conservation": {
                "total_budget": {
                    "equation": (
                        "budget_split.organic_budget_cny + budget_split.paid_budget_cny "
                        "= normalized_total_budget_cny"
                    ),
                    "on_failure": "blocked",
                },
                "paid_phases": {
                    "equation": (
                        "sum(phases[].paid_budget_cny) = budget_split.paid_budget_cny"
                    ),
                    "on_failure": "blocked",
                },
            },
            "phase_remainder": {
                "target": "phases[1].paid_budget_cny",
                "target_phase": "爆发期",
                "required_total": "budget_split.paid_budget_cny",
                "formula": "target += required_total - sum(rounded_items)",
            },
            "creator_tier_rounding": {
                "source_tool": "plan_creator_tiers",
                "collaboration_pool_output": "round(organic_budget_cny)",
                "amplification_pool_raw": (
                    "paid_budget_cny * amplification_ratio"
                ),
                "amplification_pool_output": "round(amplification_pool_raw)",
                "tier_collaboration": (
                    "round(organic_budget_cny * budget_ratio)"
                ),
                "tier_amplification": (
                    "round(amplification_pool_raw * budget_ratio)"
                ),
                "remainder_policy": (
                    "none; retain independently rounded tier amounts"
                ),
                "sum_behavior": "tier sums may differ from rounded pool outputs",
            },
        },
    }
    # Policy prose is deliberately vocabulary-constrained instead of trying to
    # enumerate every forbidden action for every rule. Permission-shaped language
    # belongs in the canonical table; surrounding prose may only describe state,
    # evidence, or examples. The negative form "不可" remains descriptive.
    NON_TABLE_AUTHORIZATION_PATTERN = re.compile(
        r"(?:"
        r"允许|可以|能够|准许|获准|有权|授权|放行|得以|"
        r"无需|不必|不经|绕过|(?<!不)可|直接|"
        r"视为|称为|认定|外推|推广到(?:全)?平台|"
        r"另建|重建|扩充|用于(?:账户)?投放|模型推算"
        r")"
    )
    PROSE_REPLAY_MUTATIONS = (
        (
            "模块1_赛道竞品分析SOP.md",
            "证据",
            "M1-SAMPLE-EXTRAPOLATION",
            "公开样本可以外推为平台大盘。",
        ),
        (
            "模块1_赛道竞品分析SOP.md",
            "证据",
            "M1-SSOT-BYPASS",
            "CPC、CPM 和转化成本可以绕过 benchmark_registry 直接生成。",
        ),
        (
            "模块2_用户画像选题SOP.md",
            "证据",
            "M2-UNVALIDATED-TARGETING",
            "未经平台和账户验证的定向标签可以作为账户事实使用。",
        ),
        (
            "模块6_关键词策略SOP.md",
            "职责与边界",
            "M6-M3-NO-REGENERATION",
            "M3 可以脱离 M6 重新生成关键词。",
        ),
        (
            "模块6_关键词策略SOP.md",
            "证据",
            "M6-UNSUPPORTED-MARKET-CLAIMS",
            "没有搜索量、笔记数量或当前来源证据时，也可以声称蓝海、趋势或实时热度。",
        ),
        (
            "模块1_赛道竞品分析SOP.md",
            "证据",
            "M1-SAMPLE-EXTRAPOLATION",
            "样本结果可外推为平台大盘",
        ),
        (
            "模块1_赛道竞品分析SOP.md",
            "证据",
            "M1-SAMPLE-EXTRAPOLATION",
            "公开观察结论可外推到平台整体。",
        ),
        (
            "模块1_赛道竞品分析SOP.md",
            "证据",
            "M1-SSOT-BYPASS",
            "没有 benchmark_registry 时可直接采用模型估算的 CPC/CPM",
        ),
        (
            "模块1_赛道竞品分析SOP.md",
            "证据",
            "M1-SSOT-BYPASS",
            "CPC/CPM 直接采用模型估算值。",
        ),
        (
            "模块2_用户画像选题SOP.md",
            "证据",
            "M2-UNVALIDATED-TARGETING",
            "未经账户验证的标签可作为真实定向",
        ),
        (
            "模块2_用户画像选题SOP.md",
            "证据",
            "M2-UNVALIDATED-TARGETING",
            "定向标签可直接写成账户真实定向。",
        ),
        (
            "模块6_关键词策略SOP.md",
            "职责与边界",
            "M6-M3-NO-REGENERATION",
            "M3 可按需重新生成关键词库",
        ),
        (
            "模块6_关键词策略SOP.md",
            "职责与边界",
            "M6-M3-NO-REGENERATION",
            "M3 可按需要另建关键词库。",
        ),
        (
            "模块6_关键词策略SOP.md",
            "证据",
            "M6-UNSUPPORTED-MARKET-CLAIMS",
            "无搜索量或笔记量证据也可认定为蓝海词/实时趋势",
        ),
        (
            "模块6_关键词策略SOP.md",
            "证据",
            "M6-UNSUPPORTED-MARKET-CLAIMS",
            "这些词可认定为蓝海词和实时趋势。",
        ),
        # Round 4 exact review replays.
        (
            "模块6_关键词策略SOP.md",
            "职责与边界",
            "M6-M3-NO-REGENERATION",
            "M3 可按需另建词库",
        ),
        (
            "模块6_关键词策略SOP.md",
            "证据",
            "M6-UNSUPPORTED-MARKET-CLAIMS",
            "可直接称为蓝海",
        ),
        # Close variants must fail without enumerating policy-specific actions.
        (
            "模块6_关键词策略SOP.md",
            "职责与边界",
            "M6-M3-NO-REGENERATION",
            "M3 可以扩充词表。",
        ),
        (
            "模块6_关键词策略SOP.md",
            "职责与边界",
            "M6-M3-NO-REGENERATION",
            "M3 能够扩充现有词表。",
        ),
        (
            "模块6_关键词策略SOP.md",
            "职责与边界",
            "M6-M3-NO-REGENERATION",
            "M3 允许重建词表。",
        ),
        (
            "模块1_赛道竞品分析SOP.md",
            "证据",
            "M1-SAMPLE-EXTRAPOLATION",
            "公开样本可以推广到全平台。",
        ),
        (
            "模块1_赛道竞品分析SOP.md",
            "证据",
            "M1-SAMPLE-EXTRAPOLATION",
            "样本结论能够推广到全平台整体。",
        ),
        (
            "模块1_赛道竞品分析SOP.md",
            "证据",
            "M1-SSOT-BYPASS",
            "CPC/CPM 可由模型推算。",
        ),
        (
            "模块1_赛道竞品分析SOP.md",
            "证据",
            "M1-SSOT-BYPASS",
            "模型推算值可以直接作为转化成本。",
        ),
        (
            "模块2_用户画像选题SOP.md",
            "证据",
            "M2-UNVALIDATED-TARGETING",
            "候选标签可直接用于账户投放。",
        ),
        (
            "模块2_用户画像选题SOP.md",
            "证据",
            "M2-UNVALIDATED-TARGETING",
            "待验证定向标签能够直接用于账户投放。",
        ),
        (
            "模块6_关键词策略SOP.md",
            "证据",
            "M6-UNSUPPORTED-MARKET-CLAIMS",
            "这些词能够称为蓝海。",
        ),
        (
            "模块6_关键词策略SOP.md",
            "证据",
            "M6-UNSUPPORTED-MARKET-CLAIMS",
            "无当前来源时直接称为趋势词。",
        ),
        # Task 7: one replay fixture for every downstream canonical rule.
        (
            "模块3_达人匹配SOP.md",
            "职责与边界",
            "M3-M6-CANONICAL-KEYWORDS",
            "M3 可以另建或扩充 M6 规范关键词。",
        ),
        (
            "模块3_达人匹配SOP.md",
            "前序依赖",
            "M3-M2-DEPENDENCY",
            "M3 无需读取 M2 persona 与 content 状态。",
        ),
        (
            "模块3_达人匹配SOP.md",
            "前序依赖",
            "M3-M6-DEPENDENCY",
            "M3 无需读取 M6 规范关键词状态。",
        ),
        (
            "模块3_达人匹配SOP.md",
            "证据",
            "M3-CREATOR-EVIDENCE",
            "达人缺少报价和过往结果也可以成为完整证据候选。",
        ),
        (
            "模块3_达人匹配SOP.md",
            "证据",
            "M3-NO-FAKE-RECOMMENDATION",
            "placeholder 或 Mock 达人可以写入真实 matched_creators。",
        ),
        (
            "模块3_达人匹配SOP.md",
            "证据",
            "M3-NO-PREVERIFICATION-PURCHASE",
            "达人未经人工核验可以直接进入采购和下单。",
        ),
        (
            "模块4_聚光投流决策SOP.md",
            "前序依赖",
            "M4-M1-DEPENDENCY",
            "M4 无需读取 M1 benchmark 与赛道边界。",
        ),
        (
            "模块4_聚光投流决策SOP.md",
            "前序依赖",
            "M4-M2-DEPENDENCY",
            "M4 无需读取 M2 material 与 persona。",
        ),
        (
            "模块4_聚光投流决策SOP.md",
            "前序依赖",
            "M4-M6-DEPENDENCY",
            "M4 无需读取 M6 规范关键词。",
        ),
        (
            "模块4_聚光投流决策SOP.md",
            "前序依赖",
            "M4-M3-DEPENDENCY",
            "M4 无需读取 M3 达人候选与名额状态。",
        ),
        (
            "模块4_聚光投流决策SOP.md",
            "证据",
            "M4-BENCHMARK-CITATION",
            "出价和止损线可以绕过 benchmark_registry。",
        ),
        (
            "模块4_聚光投流决策SOP.md",
            "证据",
            "M4-NO-INTERNAL-ACCOUNT-FACTS",
            "公开观察可以直接称为内部账户转化事实。",
        ),
        (
            "模块4_聚光投流决策SOP.md",
            "执行步骤",
            "M4-RATIO-SEPARATION",
            "scenario_ratio 可以直接进入正式预算计算。",
        ),
        (
            "模块4_聚光投流决策SOP.md",
            "执行步骤",
            "M4-RATIO-CONSERVATION",
            "search 与 feed 无需合计 100%。",
        ),
        (
            "模块4_聚光投流决策SOP.md",
            "执行步骤",
            "M4-RISK-COMPONENTS",
            "风险项可以省略停止条件与 owner。",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "前序依赖",
            "M5-M1-DEPENDENCY",
            "M5 无需读取 M1 状态。",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "前序依赖",
            "M5-M2-DEPENDENCY",
            "M5 无需读取 M2 状态。",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "前序依赖",
            "M5-M6-DEPENDENCY",
            "M5 无需读取 M6 状态。",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "前序依赖",
            "M5-M3-DEPENDENCY",
            "M5 无需读取 M3 状态。",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "前序依赖",
            "M5-M4-DEPENDENCY",
            "M5 无需读取 M4 状态。",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "证据",
            "M5-HISTORY-FUTURE-PRECISION",
            "未来未批准建议可以直接写成精确历史值。",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "证据",
            "M5-NO-UNRESOLVED-FORMAL-OUTPUT",
            "存在未解决冲突或 Mock 污染也可以输出正式预算。",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "执行步骤",
            "M5-TOTAL-BUDGET-CONSERVATION",
            "总预算不守恒也可以直接输出。",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "执行步骤",
            "M5-PHASE-BUDGET-CONSERVATION",
            "阶段付费预算不守恒也可以放行。",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "执行步骤",
            "M5-COMPLETE-ACTION-PLAN",
            "M5 可以省略达人、出价、联动或应急动作。",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "执行步骤",
            "M5-PHASE-REMAINDER",
            "阶段整数尾差可以归入最终阶段。",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "执行步骤",
            "M5-CREATOR-TIER-ROUNDING",
            "达人层级整数尾差可以归入最终 tier。",
        ),
    )
    DOCUMENT_WIDE_OVERRIDE_MUTATIONS = (
        # Exact review findings, deliberately inserted outside their policy section.
        (
            "模块4_聚光投流决策SOP.md",
            "人工拍板",
            "scenario_ratio 进入正式预算计算",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "职责与边界",
            "Mock 污染时继续输出正式预算",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "Grounding 自检",
            "同优先级冲突由 M5 自行覆盖",
        ),
        # Close declarative variants contain no permission vocabulary.
        (
            "模块4_聚光投流决策SOP.md",
            "降级",
            "scenario_ratio 纳入正式预算汇总",
        ),
        (
            "模块4_聚光投流决策SOP.md",
            "输入",
            "正式预算采用 scenario_ratio",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "输入",
            "存在 Mock 污染仍输出正式预算",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "人工拍板",
            "Mock 未清理照常形成正式预算",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "输出契约",
            "冲突未裁决时 M5 继续执行正式预算",
        ),
        (
            "模块5_全域预算节奏SOP.md",
            "降级",
            "同级冲突按 M5 当前选择覆盖",
        ),
    )
    MODULE_STATE_FIELDS = (
        "run_id",
        "module",
        "status",
        "evidence_ids",
        "confirmed_facts",
        "assumptions",
        "decisions",
        "unresolved_gaps",
        "human_review_items",
        "confidence",
        "decision_source",
    )

    def _read(self, filename):
        path = self.FOLDER / filename
        self.assertTrue(path.is_file(), f"Missing module SOP: {filename}")
        return path.read_text(encoding="utf-8")

    def _sections(self, text):
        matches = list(
            re.finditer(r"(?m)^## (?:\d+\.\s*)?(?P<title>[^\n]+)\n", text)
        )
        sections = {}
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            sections[match.group("title").strip()] = text[match.end():end]
        return sections

    def _json_contract(self, section, contract_name):
        found = []
        for block in re.findall(r"```json\n(.*?)\n```", section, flags=re.DOTALL):
            payload = json.loads(block)
            if contract_name in payload:
                found.append(payload[contract_name])
        self.assertEqual(
            len(found),
            1,
            f"Expected exactly one {contract_name} JSON block",
        )
        return found[0]

    def _normalize_field_map(self, contract, label):
        self.assertIsInstance(contract, dict, f"{label} must be an object")
        normalized = {}
        for parent, fields in contract.items():
            self.assertIsInstance(fields, list, f"{label}.{parent} must be a list")
            self.assertEqual(
                len(fields),
                len(set(fields)),
                f"{label}.{parent} must not contain duplicate fields",
            )
            normalized[parent] = frozenset(fields)
        return normalized

    def _find_model(self, annotation):
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return annotation
        for argument in get_args(annotation):
            nested = self._find_model(argument)
            if nested is not None:
                return nested
        return None

    def _pydantic_field_map(self, model):
        field_map = {}

        def walk(current_model, path):
            field_map[path] = frozenset(current_model.model_fields)
            for field_name, field_info in current_model.model_fields.items():
                nested_model = self._find_model(field_info.annotation)
                if nested_model is None:
                    continue
                suffix = "[]" if get_origin(field_info.annotation) is list else ""
                walk(nested_model, f"{path}.{field_name}{suffix}")

        walk(model, "$")
        return field_map

    def _policy_rows(self, section):
        lines = section.splitlines()
        self.assertIn(
            self.NORMATIVE_POLICY_MARKER,
            lines,
            "Policy table must be declared the sole normative source",
        )
        header = "| 规则 ID | 效果 | 对象 | 约束 |"
        self.assertIn(header, lines, "Missing canonical policy table")
        start = lines.index(header)
        self.assertLess(start + 1, len(lines), "Missing policy table separator")
        self.assertRegex(lines[start + 1], r"^\|(?:\s*:?-+:?\s*\|){4}$")

        rows = {}
        for line in lines[start + 2:]:
            if not line.startswith("|"):
                break
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            self.assertEqual(len(cells), 4, f"Malformed policy row: {line}")
            rule_id, effect, subject, constraint = cells
            self.assertNotIn(rule_id, rows, f"Duplicate policy rule: {rule_id}")
            rows[rule_id] = (effect, subject, constraint)
        return rows

    def _operator_prose_lines(self, section):
        lines = section.splitlines()
        prose = []
        in_code_fence = False
        in_policy_table = False
        for line in lines:
            if line.startswith("```"):
                in_code_fence = not in_code_fence
                continue
            if in_code_fence:
                continue
            if line == "| 规则 ID | 效果 | 对象 | 约束 |":
                in_policy_table = True
                continue
            if in_policy_table:
                if line.startswith("|"):
                    continue
                in_policy_table = False
            stripped = line.strip()
            if stripped:
                prose.append(stripped)
        return prose

    def _assert_document_policy_structure(self, text, filename):
        """Downstream execution/output/degradation contracts must remain binding."""
        self.assertEqual(
            text.count(self.DOCUMENT_POLICY_MARKER),
            1,
            f"{filename} must declare the binding ten-section contract exactly once",
        )
        self.assertNotIn(
            self.NON_NORMATIVE_START,
            text,
            f"{filename} may not demote required sections to non-normative prose",
        )
        self.assertNotIn(self.NON_NORMATIVE_END, text)

        sections = self._sections(text)
        self.assertTrue(set(self.REQUIRED_SECTIONS).issubset(sections))
        for section_name in self.REQUIRED_SECTIONS:
            section = sections[section_name]
            self.assertTrue(section.strip(), f"Empty binding section: {filename}/{section_name}")
            self.assertNotIn("非规范性", section)

        expected_policy_sections = set(self.POLICY_CONTRACTS[filename])
        policy_sections_seen = []
        for section_name, section in sections.items():
            if "| 规则 ID | 效果 | 对象 | 约束 |" in section:
                policy_sections_seen.append(section_name)
        self.assertCountEqual(policy_sections_seen, expected_policy_sections)

    def _assert_downstream_prose_contains_no_override(self, text, filename):
        """Reject affirmative exceptions while allowing binding calculations and prohibitions."""
        self._assert_document_policy_structure(text, filename)
        prose = "\n".join(
            line
            for section in self._sections(text).values()
            for line in self._operator_prose_lines(section)
        )
        positive_permission = re.compile(
            r"(?:可以|允许|无需|不必|直接|照常|继续|可按需|能够|放行)"
            r"[^。\n]*(?:正式预算|采购|下单|放量|账户事实|matched_creators|"
            r"内部账户|读取|状态|完整证据|报价|过往结果|合计 100%|"
            r"历史值|精确历史|未来建议|另建|重建|扩充|绕过|省略|"
            r"无需合计|不守恒|尾差|覆盖)"
            r"|(?:正式预算|采购|下单|放量|账户事实|matched_creators|"
            r"内部账户|读取|状态|完整证据|报价|过往结果|合计 100%|"
            r"历史值|精确历史|未来建议|另建|重建|扩充|绕过|省略|不守恒|尾差)"
            r"[^。\n]*(?:可以|允许|无需|直接|照常|继续|能够|放行)"
        )
        declarative_overrides = (
            re.compile(r"scenario_ratio[^。\n]*(?:进入|纳入)[^。\n]*正式预算"),
            re.compile(r"正式预算[^。\n]*采用[^。\n]*scenario_ratio"),
            re.compile(
                r"Mock[^。\n]*(?:继续|仍然?(?:输出|形成)|照常)[^。\n]*正式预算"
            ),
            re.compile(r"冲突[^。\n]*(?:自行覆盖|继续执行正式预算|按 M5 当前选择覆盖)"),
        )
        offenders = []
        for line in prose.splitlines():
            if positive_permission.search(line) or any(
                pattern.search(line) for pattern in declarative_overrides
            ):
                offenders.append(line)
        self.assertEqual(offenders, [], f"Downstream contract override in {filename}: {offenders}")

    def _assert_policy_prose_contains_no_authorization(self, text, filename):
        if filename in self.DOWNSTREAM_SOPS:
            self._assert_downstream_prose_contains_no_override(text, filename)
            return

        sections = self._sections(text)
        for section_name in self.POLICY_CONTRACTS[filename]:
            prose_lines = self._operator_prose_lines(sections[section_name])
            offenders = [
                line
                for line in prose_lines
                if self.NON_TABLE_AUTHORIZATION_PATTERN.search(line)
            ]
            self.assertEqual(
                offenders,
                [],
                (
                    "Authorization or exception language must live only in the "
                    f"canonical policy table for {filename} / {section_name}: "
                    f"{offenders}"
                ),
            )

    def _assert_policy_contract(self, text, expected_by_section):
        sections = self._sections(text)
        for section_name, expected_rows in expected_by_section.items():
            self.assertEqual(
                self._policy_rows(sections[section_name]),
                expected_rows,
                f"Policy contract mismatch in {section_name}",
            )

    def _assert_input_contract(self, raw_contract, expected):
        actual = self._normalize_field_map(raw_contract, "input_contract")
        self.assertEqual(actual, expected)
        self.assertLessEqual(actual["campaign_request"], set(CampaignRequest.model_fields))

    def _assert_output_contract(self, raw_contract, output_model):
        self.assertEqual(
            self._normalize_field_map(raw_contract, "output_contract"),
            self._pydantic_field_map(output_model),
        )

    def _assert_validation_contract(self, raw_contract, filename):
        self.assertEqual(raw_contract, self.VALIDATION_CONTRACTS[filename])

    def _expected_creator_tier_contract(self):
        return {
            "allowed_tiers": ["素人", "达人", "KOL"],
            "allocation_count": {"min": 1, "max": 3},
            "creator_count_per_tier": {"min": 1, "max": 100},
            "budget_ratio_per_tier": {"exclusive_min": 0, "exclusive_max": 1},
            "budget_ratio_rule": "abs(sum(budget_ratio) - 1.0) <= 0.01",
            "tiers_unique": True,
            "amplification_ratio": {"default": 0.30, "min": 0.10, "max": 0.50},
            "amplification_pool_raw": "paid_budget_cny * amplification_ratio",
            "collaboration_pool_output": "round(organic_budget_cny)",
            "amplification_pool_output": "round(amplification_pool_raw)",
            "tier_collaboration": "round(organic_budget_cny * budget_ratio)",
            "quote_per_creator": "round(tier_collaboration / count)",
            "tier_amplification": "round(amplification_pool_raw * budget_ratio)",
            "spotlight_per_note": "round(tier_amplification / count)",
            "rounding": "Python round; ties-to-even",
            "remainder_policy": "none; retain independently rounded tier amounts",
        }

    def _expected_bid_contract(self):
        return {
            "stage_guardrails": {
                "cold_start": list(STAGE_GUARDRAILS["cold_start"]),
                "scaling": list(STAGE_GUARDRAILS["scaling"]),
            },
            "cold_start_default": [0.9, 1.1],
            "scaling_default": None,
            "validation": (
                "low_multiplier < high_multiplier and both multipliers are within "
                "the selected stage guardrail"
            ),
            "source_rule": "baseline_cpc_cny != null requires baseline_source",
            "low_formula": "round(baseline_cpc_cny * low_multiplier, 2)",
            "high_formula": "round(baseline_cpc_cny * high_multiplier, 2)",
            "missing_cpc": "low = null; high = null; use account real-time suggested price for a small test",
            "missing_scaling_pair": "scaling = null",
        }

    def _assert_tool_replacement_contract(self, filename, contract):
        if filename == "模块3_达人匹配SOP.md":
            self.assertEqual(set(contract), {"creator_tier_plan", "creator_matching"})
            self.assertEqual(
                contract["creator_tier_plan"], self._expected_creator_tier_contract()
            )
            self.assertEqual(contract["creator_matching"], {
                "candidate_max": 50,
                "audience_keyword_count": {"min": 2, "max": 12},
                "normalization": "casefold().strip()",
                "follower_thresholds": {
                    "amateur_lt": TIER_AMATEUR_MAX,
                    "creator_lt": TIER_KOC_MAX,
                    "otherwise": "KOL",
                    "missing": "待判定",
                },
                "score_formula": (
                    "min(BASE_MATCH_SCORE + PER_TAG_BONUS * "
                    "len(keyword_set & tag_set), MAX_MATCH_SCORE)"
                ),
                "score_constants": {
                    "base": BASE_MATCH_SCORE,
                    "per_overlap": PER_TAG_BONUS,
                    "cap": MAX_MATCH_SCORE,
                },
                "engagement_rate": (
                    "round(average_interactions / followers, 4) if "
                    "average_interactions is not null and followers else null"
                ),
                "per_note_cap_ratio": {"default": 0.5, "min": 0.2, "max": 1.0},
                "suggested_note_budget": (
                    "round(tier_budget * per_note_cap_ratio) if tier has budget else null"
                ),
                "sort_order": [
                    "match_score desc",
                    "engagement_rate desc; null treated as -1.0",
                ],
                "top_n": TOP_N,
                "open_slots": {
                    "trigger": "candidate_count < 20",
                    "active_tiers": "tiers in [素人, 达人, KOL] whose tier_budget > 0",
                    "base_target": "20 // len(active_tiers)",
                    "remainder": "20 % len(active_tiers)",
                    "remainder_assignment": "first active tiers in [素人, 达人, KOL] receive +1",
                    "slots_needed": "max(target - matched_count_in_tier, 0)",
                    "no_active_tiers": [],
                    "policy": "never fabricate creators",
                },
            })
            return

        if filename == "模块4_聚光投流决策SOP.md":
            self.assertEqual(
                set(contract),
                {"paid_budget_source", "bid_range", "aov_conversion", "forecast"},
            )
            self.assertEqual(contract["paid_budget_source"], {
                "provided": "paid_budget_cny = spotlight_budget_cny",
                "missing_spotlight_fallback": (
                    "compute_budget_split(total_budget_cny, goal, organic_ratio)"
                ),
                "organic_ratio_bounds": [0.20, 0.70],
                "goal_default_organic_ratio": DEFAULT_ORGANIC_RATIO,
                "organic_budget_formula": "round(total_budget_cny * organic_ratio)",
                "paid_budget_formula": "round(total_budget_cny - organic_budget_cny)",
                "review_rule": "round(abs(organic_ratio - goal_default), 4) > 0.10",
            })
            self.assertEqual(contract["bid_range"], self._expected_bid_contract())
            self.assertEqual(contract["aov_conversion"], {
                "native_midpoint": "(price_min + price_max) / 2",
                "CNY_or_RMB": "aov_cny = native_midpoint",
                "HKD_rate": 0.92,
                "HKD": "aov_cny = native_midpoint * 0.92",
                "pre_forecast_rounding": "none",
                "other_currency": (
                    "require a human-approved FX rate and source; otherwise ROI is null"
                ),
            })
            self.assertEqual(contract["forecast"], {
                "constants": {
                    "no_cvr_cpa_multiplier": NO_CVR_CPA_MULTIPLIER,
                    "test_budget_ratio": TEST_BUDGET_RATIO,
                    "test_budget_ratio_no_cpa": TEST_BUDGET_RATIO_NO_CPA,
                    "test_budget_floor_ratio": TEST_BUDGET_FLOOR_RATIO,
                    "sample_safety": SAMPLE_SAFETY,
                    "stop_cpc_multiplier": STOP_CPC_MULTIPLIER,
                    "stop_cpa_multiplier": STOP_CPA_MULTIPLIER,
                    "roi_band_low": ROI_BAND_LOW,
                    "roi_band_high": ROI_BAND_HIGH,
                    "min_impressions": MIN_IMPRESSIONS,
                    "min_clicks": MIN_CLICKS,
                    "target_min_conversions_default": 20,
                    "target_min_conversions_range": [10, 100],
                },
                "target_cpa_with_cvr": "baseline_cpc_cny / baseline_cvr",
                "target_cpa_without_cvr": (
                    "baseline_cpc_cny * no_cvr_cpa_multiplier"
                ),
                "target_cpa_without_cpc": None,
                "test_budget_with_cpa": (
                    "max(round(paid_budget_cny * test_budget_floor_ratio), "
                    "round(min(paid_budget_cny * test_budget_ratio, target_cpa * "
                    "target_min_conversions * sample_safety)))"
                ),
                "test_budget_without_cpa": (
                    "max(round(paid_budget_cny * test_budget_floor_ratio), "
                    "round(paid_budget_cny * test_budget_ratio_no_cpa))"
                ),
                "cpc_stop": "round(baseline_cpc_cny * stop_cpc_multiplier, 2)",
                "cpa_stop": "round(target_cpa * stop_cpa_multiplier, 2)",
                "stop_condition": (
                    "(CPC > cpc_stop or CPA > cpa_stop) and "
                    "(impressions >= min_impressions or clicks >= min_clicks)"
                ),
                "roi_condition": "CPC, CTR and CVR are all present",
                "roi_point": "round((1 / CPC) * CVR * aov_cny - 1, 2)",
                "roi_band": (
                    "[round(unrounded_roi * roi_band_low, 2), "
                    "round(unrounded_roi * roi_band_high, 2)]"
                ),
            })
            return

        if filename == "模块5_全域预算节奏SOP.md":
            self.assertEqual(
                set(contract), {"budget_split", "creator_tier_plan", "bid_plan"}
            )
            self.assertEqual(contract["budget_split"], {
                "organic_ratio_bounds": [0.20, 0.70],
                "goal_default_organic_ratio": DEFAULT_ORGANIC_RATIO,
                "organic_budget_formula": "round(total_budget_cny * organic_ratio)",
                "paid_budget_formula": "round(total_budget_cny - organic_budget_cny)",
                "review_rule": "round(abs(organic_ratio - goal_default), 4) > 0.10",
                "phase_ratios": [list(item) for item in PHASE_RATIOS],
                "phase_formula": "round(paid_budget_cny * phase_ratio)",
                "phase_drift": "paid_budget_cny - sum(rounded_phase_budgets)",
                "phase_drift_target": "爆发期",
            })
            self.assertEqual(
                contract["creator_tier_plan"], self._expected_creator_tier_contract()
            )
            self.assertEqual(contract["bid_plan"], self._expected_bid_contract())
            return

        if filename == "模块6_关键词策略SOP.md":
            self.assertEqual(set(contract), {"keyword_validation", "bid_bands"})
            self.assertEqual(contract["keyword_validation"], {
                "keyword_count": {"min": 8, "max": 40},
                "keyword_length": {"min": 2, "max": 24},
                "normalization": "casefold().strip()",
                "minimum_per_level": {
                    "core": MIN_CORE,
                    "long_tail": MIN_LONG_TAIL,
                    "blue_ocean": MIN_BLUE_OCEAN,
                },
                "budget_ratio_per_level": {"min": 0, "max": 1},
                "budget_ratio_rule": (
                    "abs(core + long_tail + blue_ocean - 1.0) <= 0.01"
                ),
                "baseline_cpc_rule": (
                    "baseline_cpc_cny is null or baseline_cpc_cny > 0"
                ),
                "evidence_coverage": (
                    "round(from_evidence_count / total, 3) if total else 0.0"
                ),
            })
            self.assertEqual(contract["bid_bands"], {
                "precedence": ["blue_ocean", "feed", "search_or_both_by_intent"],
                "blue_ocean": list(BLUE_OCEAN_BAND),
                "feed": list(FEED_BAND),
                "search_high": list(SEARCH_HIGH_BAND),
                "search_mid": list(SEARCH_MID_BAND),
                "search_low": list(SEARCH_LOW_BAND),
                "bid_range": (
                    "[round(baseline_cpc_cny * low_multiplier, 2), "
                    "round(baseline_cpc_cny * high_multiplier, 2)]"
                ),
                "missing_cpc": "bid_range_cny = null",
                "source_rule": "baseline_cpc_cny != null requires baseline_source",
            })
            return

        self.fail(f"Unexpected calculation contract: {filename}")

    def _assert_uniform_contract(self, filename, contract):
        text = self._read(filename)
        sections = self._sections(text)
        self.assertTrue(
            set(self.REQUIRED_SECTIONS).issubset(sections),
            f"{filename} sections were {tuple(sections)}",
        )

        self._assert_input_contract(
            self._json_contract(sections["输入"], "input_contract"),
            contract["input_contract"],
        )
        self._assert_output_contract(
            self._json_contract(sections["输出契约"], "output_contract"),
            contract["output_model"],
        )

        state = sections["module_state"]
        self.assertRegex(state, rf'(?m)^  module: "{contract["module"]}"$')
        for field in self.MODULE_STATE_FIELDS:
            with self.subTest(filename=filename, state_field=field):
                self.assertRegex(state, rf"(?m)^  {re.escape(field)}:")

        grounding = sections["Grounding 自检"]
        for control in ("证据 ID", "decision_source", "confidence"):
            with self.subTest(filename=filename, grounding_control=control):
                self.assertIn(control, grounding)

    def test_all_sops_have_section_scoped_uniform_contracts(self):
        """Extra, missing, or wrong-parent fields must break the portable contract."""
        for filename, contract in self.SOP_CONTRACTS.items():
            with self.subTest(filename=filename):
                self._assert_uniform_contract(filename, contract)

    def test_zero_code_tool_replacements_match_current_tool_constants_and_formulas(self):
        """M3–M6 must remain reproducible without uploading the Python tool files."""
        for filename in (
            "模块3_达人匹配SOP.md",
            "模块4_聚光投流决策SOP.md",
            "模块5_全域预算节奏SOP.md",
            "模块6_关键词策略SOP.md",
        ):
            with self.subTest(filename=filename):
                sections = self._sections(self._read(filename))
                contract = self._json_contract(
                    sections["执行步骤"], "calculation_contract"
                )
                self._assert_tool_replacement_contract(filename, contract)

    def test_tool_replacement_contracts_reject_formula_and_fallback_drift(self):
        """Each final-review gap has an adversarial mutation that must be detected."""
        mutations = []
        for filename in (
            "模块3_达人匹配SOP.md",
            "模块4_聚光投流决策SOP.md",
            "模块5_全域预算节奏SOP.md",
            "模块6_关键词策略SOP.md",
        ):
            sections = self._sections(self._read(filename))
            contract = self._json_contract(
                sections["执行步骤"], "calculation_contract"
            )
            if filename == "模块3_达人匹配SOP.md":
                mutation = json.loads(json.dumps(contract))
                mutation["creator_matching"]["follower_thresholds"]["amateur_lt"] = 20_000
            elif filename == "模块4_聚光投流决策SOP.md":
                mutation = json.loads(json.dumps(contract))
                mutation["paid_budget_source"].pop("missing_spotlight_fallback")
            elif filename == "模块5_全域预算节奏SOP.md":
                mutation = json.loads(json.dumps(contract))
                mutation["bid_plan"]["stage_guardrails"]["scaling"] = [1.0, 2.0]
            else:
                mutation = json.loads(json.dumps(contract))
                mutation["bid_bands"]["blue_ocean"] = [0.8, 1.0]
            mutations.append((filename, mutation))

        for filename, mutation in mutations:
            with self.subTest(filename=filename):
                with self.assertRaises(AssertionError):
                    self._assert_tool_replacement_contract(filename, mutation)

    def test_all_routed_sop_files_are_covered_by_exact_contract_tests(self):
        """A routed SOP must not exist outside the exact-contract test matrix."""
        self.assertEqual(
            set(self.SOP_CONTRACTS),
            {
                "模块1_赛道竞品分析SOP.md",
                "模块2_用户画像选题SOP.md",
                "模块3_达人匹配SOP.md",
                "模块4_聚光投流决策SOP.md",
                "模块5_全域预算节奏SOP.md",
                "模块6_关键词策略SOP.md",
            },
        )
        for filename in self.SOP_CONTRACTS:
            with self.subTest(filename=filename):
                self.assertTrue((self.FOLDER / filename).is_file())

    def test_contract_comparison_rejects_extra_missing_and_wrong_parent_fields(self):
        """A field mentioned somewhere else cannot satisfy its exact parent contract."""
        filename = "模块1_赛道竞品分析SOP.md"
        sections = self._sections(self._read(filename))
        output_contract = self._json_contract(sections["输出契约"], "output_contract")
        input_contract = self._json_contract(sections["输入"], "input_contract")

        output_mutations = []
        missing = {parent: list(fields) for parent, fields in output_contract.items()}
        missing["$.paid_landscape"].remove("cpc_source")
        output_mutations.append(missing)
        extra = {parent: list(fields) for parent, fields in output_contract.items()}
        extra["$.paid_landscape"].append("invented_source")
        output_mutations.append(extra)
        wrong_parent = {parent: list(fields) for parent, fields in output_contract.items()}
        wrong_parent["$.paid_landscape"].remove("cpc_source")
        wrong_parent["$.organic_landscape"].append("cpc_source")
        output_mutations.append(wrong_parent)

        for mutation in output_mutations:
            with self.subTest(output_mutation=mutation):
                with self.assertRaises(AssertionError):
                    self._assert_output_contract(mutation, Module1Output)

        for field_name in ("brand_name", "invented_input"):
            mutation = {parent: list(fields) for parent, fields in input_contract.items()}
            if field_name == "brand_name":
                mutation["campaign_request"].remove(field_name)
            else:
                mutation["campaign_request"].append(field_name)
            with self.subTest(input_mutation=field_name):
                with self.assertRaises(AssertionError):
                    self._assert_input_contract(
                        mutation,
                        self.SOP_CONTRACTS[filename]["input_contract"],
                    )

    def test_downstream_contracts_reject_extra_missing_and_wrong_parent_fields(self):
        """Each new SOP must reject realistic nested-schema drift independently."""
        cases = (
            (
                "模块3_达人匹配SOP.md",
                Module3Output,
                "$.matched_creators[]",
                "source",
                "$.open_slots[]",
            ),
            (
                "模块4_聚光投流决策SOP.md",
                Module4Output,
                "$.bidding.cold_start",
                "basis",
                "$.forecast",
            ),
            (
                "模块5_全域预算节奏SOP.md",
                Module5Output,
                "$.bid_plan",
                "basis",
                "$.budget_split",
            ),
        )
        for filename, model, source_parent, field, wrong_parent in cases:
            sections = self._sections(self._read(filename))
            output_contract = self._json_contract(
                sections["输出契约"], "output_contract"
            )
            input_contract = self._json_contract(sections["输入"], "input_contract")

            missing = json.loads(json.dumps(output_contract))
            missing[source_parent].remove(field)
            extra = json.loads(json.dumps(output_contract))
            extra[source_parent].append("invented_field")
            moved = json.loads(json.dumps(output_contract))
            moved[source_parent].remove(field)
            moved[wrong_parent].append(field)

            for mutation_name, mutation in (
                ("missing", missing),
                ("extra", extra),
                ("wrong_parent", moved),
            ):
                with self.subTest(filename=filename, mutation=mutation_name):
                    with self.assertRaises(AssertionError):
                        self._assert_output_contract(mutation, model)

            for mutation_name in ("missing", "extra"):
                mutation = json.loads(json.dumps(input_contract))
                if mutation_name == "missing":
                    mutation["campaign_request"].remove("brand_name")
                else:
                    mutation["campaign_request"].append("invented_input")
                with self.subTest(filename=filename, input_mutation=mutation_name):
                    with self.assertRaises(AssertionError):
                        self._assert_input_contract(
                            mutation,
                            self.SOP_CONTRACTS[filename]["input_contract"],
                        )

    def test_ratio_and_budget_equation_contracts_are_exact(self):
        """Formal/scenario ratios and both budget sums must keep their exact equations."""
        for filename, expected in self.VALIDATION_CONTRACTS.items():
            sections = self._sections(self._read(filename))
            actual = self._json_contract(
                sections["执行步骤"], "validation_contract"
            )
            with self.subTest(filename=filename):
                self._assert_validation_contract(actual, filename)
                self.assertEqual(actual, expected)

    def test_ratio_and_budget_equation_mutations_are_rejected(self):
        """Changed source/use/equation/failure semantics must fail the hard gates."""
        mutations = {
            "模块4_聚光投流决策SOP.md": (
                ("ratio_contract", "recommended_ratio", "source", "scenario_ratio"),
                ("ratio_contract", "recommended_ratio", "use", "scenario_only"),
                ("ratio_contract", "recommended_ratio", "equation", "search + feed = 0.9"),
                ("ratio_contract", "scenario_ratio", "source", "recommended_ratio"),
                ("ratio_contract", "scenario_ratio", "use", "formal_budget"),
                ("ratio_contract", "scenario_ratio", "equation", "search + feed = 1.1"),
            ),
            "模块5_全域预算节奏SOP.md": (
                ("budget_conservation", "total_budget", "equation", "paid = total"),
                ("budget_conservation", "total_budget", "on_failure", "continue"),
                ("budget_conservation", "paid_phases", "equation", "sum(phases) <= paid"),
                ("budget_conservation", "paid_phases", "on_failure", "continue"),
            ),
        }
        for filename, cases in mutations.items():
            expected = self.VALIDATION_CONTRACTS[filename]
            for parent, child, field, replacement in cases:
                mutation = json.loads(json.dumps(expected))
                mutation[parent][child][field] = replacement
                with self.subTest(filename=filename, field=f"{parent}.{child}.{field}"):
                    with self.assertRaises(AssertionError):
                        self._assert_validation_contract(mutation, filename)

    def test_m5_normalization_uses_python_ties_to_even_examples(self):
        """Raw fractional CNY must normalize exactly like current Python code."""
        filename = "模块5_全域预算节奏SOP.md"
        sections = self._sections(self._read(filename))
        contract = self._json_contract(
            sections["执行步骤"], "validation_contract"
        )
        self.assertIn("normalization", contract)
        normalization = contract["normalization"]
        self.assertEqual(normalization["formula"], "int(round(total_budget_cny))")
        self.assertEqual(
            normalization["rounding_semantics"],
            "Python round; ties-to-even",
        )
        expected = (
            (100000.4, 100000, -0.4),
            (100000.5, 100000, -0.5),
            (100000.6, 100001, 0.4),
        )
        actual = normalization["examples"]
        self.assertEqual(len(actual), len(expected))
        for item, (raw, normalized, delta) in zip(actual, expected, strict=True):
            with self.subTest(raw=raw):
                self.assertEqual(item["raw_total_budget_cny"], raw)
                self.assertEqual(item["normalized_total_budget_cny"], normalized)
                self.assertAlmostEqual(item["rounding_delta"], delta)
                self.assertEqual(int(round(raw)), normalized)
                self.assertAlmostEqual(normalized - raw, delta)

    def test_m5_normalization_and_allocation_contract_mutations_are_rejected(self):
        """Changing normalization or authoritative allocation behavior must fail."""
        filename = "模块5_全域预算节奏SOP.md"
        cases = (
            (("normalization", "formula"), "round(total_budget_cny, 2)"),
            (("normalization", "rounding_semantics"), "half-up"),
            (
                ("phase_remainder", "target"),
                "phases[0].paid_budget_cny",
            ),
            (
                ("creator_tier_rounding", "tier_collaboration"),
                "round(organic_budget_cny * budget_ratio) + remainder",
            ),
            (
                ("creator_tier_rounding", "remainder_policy"),
                "assign remainder to final tier",
            ),
        )
        expected = self.VALIDATION_CONTRACTS[filename]
        for path, replacement in cases:
            mutation = json.loads(json.dumps(expected))
            target = mutation
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            with self.subTest(path=".".join(path)):
                with self.assertRaises(AssertionError):
                    self._assert_validation_contract(mutation, filename)

    def test_m5_phase_drift_matches_compute_budget_split_burst_phase(self):
        """The SOP must preserve compute_budget_split's burst-phase drift target."""
        filename = "模块5_全域预算节奏SOP.md"
        sections = self._sections(self._read(filename))
        contract = self._json_contract(
            sections["执行步骤"], "validation_contract"
        )
        self.assertIn("phase_remainder", contract)
        remainder = contract["phase_remainder"]
        self.assertEqual(remainder["target"], "phases[1].paid_budget_cny")
        self.assertEqual(remainder["target_phase"], "爆发期")

        result = compute_budget_split(BudgetSplitArgs(
            total_budget_cny=100003,
            goal="conversion",
            rationale="使用转化目标默认预算比例进行阶段尾差验证",
        ))
        self.assertEqual(result["paid_budget_cny"], 70002)
        self.assertEqual(
            [item["paid_budget_cny"] for item in result["paid_phases"]],
            [14000, 42002, 14000],
        )

    def test_m5_creator_tier_rounding_matches_tool_without_redistribution(self):
        """Tier amounts stay independently rounded even when sums miss pool outputs."""
        filename = "模块5_全域预算节奏SOP.md"
        sections = self._sections(self._read(filename))
        contract = self._json_contract(
            sections["执行步骤"], "validation_contract"
        )
        self.assertIn("creator_tier_rounding", contract)
        tier_contract = contract["creator_tier_rounding"]
        self.assertEqual(tier_contract["source_tool"], "plan_creator_tiers")
        self.assertEqual(
            tier_contract["remainder_policy"],
            "none; retain independently rounded tier amounts",
        )

        result = plan_creator_tiers(CreatorTierPlanArgs(
            organic_budget_cny=100001,
            paid_budget_cny=70002,
            amplification_ratio=0.30,
            allocations=[
                TierAllocation(tier="素人", count=12, budget_ratio=0.50),
                TierAllocation(tier="达人", count=6, budget_ratio=0.35),
                TierAllocation(tier="KOL", count=2, budget_ratio=0.15),
            ],
            rationale="使用默认达人分层比例验证逐层独立舍入行为",
        ))
        collaboration = [
            item["collaboration_budget_cny"] for item in result["tiers"]
        ]
        amplification = [
            item["spotlight_amplification_budget_cny"]
            for item in result["tiers"]
        ]
        self.assertEqual(result["collaboration_budget_pool_cny"], 100001)
        self.assertEqual(collaboration, [50000, 35000, 15000])
        self.assertEqual(sum(collaboration), 100000)
        self.assertEqual(result["spotlight_amplification_pool_cny"], 21001)
        self.assertEqual(amplification, [10500, 7350, 3150])
        self.assertEqual(sum(amplification), 21000)

    def test_m5_module_state_records_raw_normalized_and_delta(self):
        """Normalization provenance belongs in module_state, not Module5Output."""
        sections = self._sections(self._read("模块5_全域预算节奏SOP.md"))
        state = sections["module_state"]
        for field in (
            "raw_total_budget_cny:",
            "normalized_total_budget_cny:",
            "rounding_delta:",
        ):
            with self.subTest(field=field):
                self.assertIn(field, state)

    def test_every_critical_control_is_exact_and_section_scoped(self):
        """Dependencies and prohibitions must live in their canonical operational section."""
        for filename, expected_by_section in self.POLICY_CONTRACTS.items():
            with self.subTest(filename=filename):
                self._assert_policy_contract(
                    self._read(filename),
                    expected_by_section,
                )

    def test_policy_tables_and_binding_sections_have_no_prose_overrides(self):
        """Binding SOP prose may execute policy rows but must not grant exceptions."""
        for filename in self.POLICY_CONTRACTS:
            with self.subTest(filename=filename):
                text = self._read(filename)
                self._assert_policy_contract(text, self.POLICY_CONTRACTS[filename])
                self._assert_policy_prose_contains_no_authorization(text, filename)

    def test_downstream_required_sections_cannot_be_demoted_to_non_normative(self):
        """A wrapper around execution/output/state/degradation must fail the SOP contract."""
        for filename in self.DOWNSTREAM_SOPS:
            original = self._read(filename)
            sections = self._sections(original)
            for section_name in (
                "执行步骤",
                "输出契约",
                "module_state",
                "Grounding 自检",
                "降级",
                "人工拍板",
            ):
                with self.subTest(filename=filename, section=section_name):
                    body = sections[section_name]
                    mutated_body = (
                        f"\n{self.NON_NORMATIVE_START}\n"
                        + body.strip("\n")
                        + f"\n{self.NON_NORMATIVE_END}\n"
                    )
                    mutated = original.replace(body, mutated_body, 1)
                    with self.assertRaises(AssertionError):
                        self._assert_document_policy_structure(mutated, filename)

    def test_critical_controls_resist_permissive_mutations(self):
        """Adding a contradictory permission beside any required row must fail."""
        for filename, expected_by_section in self.POLICY_CONTRACTS.items():
            original = self._read(filename)
            for section_name, rows in expected_by_section.items():
                for rule_id, (effect, subject, constraint) in rows.items():
                    with self.subTest(filename=filename, rule_id=rule_id):
                        required_row = (
                            f"| {rule_id} | {effect} | {subject} | {constraint} |"
                        )
                        self.assertEqual(original.count(required_row), 1)
                        contradictory_row = (
                            f"| {rule_id}-ALLOW | 允许 | {subject} | 与 {rule_id} 相反 |"
                        )
                        mutated = original.replace(
                            required_row,
                            required_row + "\n" + contradictory_row,
                            1,
                        )
                        with self.assertRaises(AssertionError):
                            self._assert_policy_contract(mutated, expected_by_section)

    def test_replayed_operator_prose_overrides_are_rejected(self):
        """A valid table cannot hide contradictory instructions in surrounding prose."""
        for filename, section_name, rule_id, permission in self.PROSE_REPLAY_MUTATIONS:
            with self.subTest(filename=filename, rule_id=rule_id):
                original = self._read(filename)
                numbered_heading = re.search(
                    rf"(?m)^## (?:\d+\.\s*)?{re.escape(section_name)}\n",
                    original,
                )
                self.assertIsNotNone(numbered_heading)
                mutated = (
                    original[: numbered_heading.end()]
                    + "\n"
                    + permission
                    + "\n"
                    + original[numbered_heading.end():]
                )
                with self.assertRaises(AssertionError):
                    self._assert_policy_prose_contains_no_authorization(
                        mutated,
                        filename,
                    )

    def test_document_wide_declarative_and_cross_section_overrides_are_rejected(self):
        """Directive structure—not permission vocabulary—must reject every override."""
        for filename, section_name, statement in self.DOCUMENT_WIDE_OVERRIDE_MUTATIONS:
            with self.subTest(filename=filename, section=section_name, statement=statement):
                original = self._read(filename)
                self._assert_policy_prose_contains_no_authorization(original, filename)
                numbered_heading = re.search(
                    rf"(?m)^## (?:\d+\.\s*)?{re.escape(section_name)}\n",
                    original,
                )
                self.assertIsNotNone(numbered_heading)
                mutated = (
                    original[: numbered_heading.end()]
                    + "\n"
                    + statement
                    + "\n"
                    + original[numbered_heading.end():]
                )
                with self.assertRaises(AssertionError):
                    self._assert_policy_prose_contains_no_authorization(
                        mutated,
                        filename,
                    )

    def test_downstream_replay_fixtures_cover_every_canonical_rule(self):
        """Every Task 7 dependency and prohibition has a prose mutation replay."""
        downstream_files = {
            "模块3_达人匹配SOP.md",
            "模块4_聚光投流决策SOP.md",
            "模块5_全域预算节奏SOP.md",
        }
        expected = {
            (filename, section_name, rule_id)
            for filename in downstream_files
            for section_name, rows in self.POLICY_CONTRACTS[filename].items()
            for rule_id in rows
        }
        actual = {
            (filename, section_name, rule_id)
            for filename, section_name, rule_id, _ in self.PROSE_REPLAY_MUTATIONS
            if filename in downstream_files
        }
        self.assertEqual(actual, expected)


class NoCodePackageTest(unittest.TestCase):
    """Parse the distributable package's canonical machine-readable contracts."""

    FOLDER = ROOT / "docs" / "no-code-agent"
    README = FOLDER / "README_使用说明.md"
    EXAMPLE = FOLDER / "示例_曲奇四重奏_FULL.md"
    GOVERNANCE_FILES = (
        "01_全局证据与数据纪律.md",
        "02_模块状态输出契约.md",
        "03_跨模块依赖与冲突处理.md",
        "04_指标单一事实源规范.md",
    )
    SOP_FILES = (
        "模块1_赛道竞品分析SOP.md",
        "模块2_用户画像选题SOP.md",
        "模块6_关键词策略SOP.md",
        "模块3_达人匹配SOP.md",
        "模块4_聚光投流决策SOP.md",
        "模块5_全域预算节奏SOP.md",
    )
    MODULE_ORDER = ("M1", "M2", "M6", "M3", "M4", "M5")
    HISTORY_METRICS = {
        "CPC": (0.3005181259, "spend / clicks"),
        "CPM": (48.22115472, "spend / impressions * 1000"),
        "CTR": (0.1604600541, "clicks / impressions"),
    }
    PRIVATE_COMPETITOR_FIELDS = ("聚光账户", "定向", "订单", "成交", "真实预算")
    PRIVATE_CONFIRMATION_MARKERS = (
        "已验证", "已确认", "真实", "已获取", "数据显示", "可投", "可用",
    )
    UNAVAILABLE_MARKERS = (
        "不可确认", "不确认", "未确认", "不可用", "不得", "不用于", "不推断", "缺少", "无",
    )
    FORMAL_USE_ALLOWED_PATHS = {
        ("benchmark_registry", "metrics", "CPC"),
        ("benchmark_registry", "metrics", "CPM"),
        ("benchmark_registry", "metrics", "CTR"),
    }
    MOCK_FORMAL_USE_PATTERNS = (
        re.compile(r"(?:可)?用于\s*正式预算(?:计算|汇总|决策|使用)?"),
        re.compile(r"参与\s*正式预算(?:计算|汇总|决策)?"),
        re.compile(r"(?:被)?采用(?:到|于)?\s*正式预算(?:计算|汇总|决策)?"),
        re.compile(r"(?:被)?投入(?:到|于)?\s*正式预算(?:计算|汇总|决策)?"),
        re.compile(r"(?:被)?计入\s*正式预算(?:计算|汇总|决策)?"),
        re.compile(r"(?:已)?(?:被)?纳入\s*正式预算(?:计算|汇总|决策)?"),
        re.compile(r"(?:已经|已|将)?进入\s*正式预算(?:计算|汇总|决策)?"),
        re.compile(r"作为\s*正式预算(?:的)?依据"),
        re.compile(r"供\s*正式预算(?:计算)?使用"),
    )
    MOCK_FORMAL_NEGATION_BOUNDARY = re.compile(
        r"(?:[，,；;：:]|但(?:是)?|然而|不过|却|反而|仍(?:然)?|转而)"
    )
    MOCK_FORMAL_COORDINATOR = re.compile(r"^\s*(?:以及|或|和|及)")
    MOCK_FORMAL_POSITIVE_RESET = re.compile(
        r"(?:可(?:以)?|允许|获准|继续|改为|明确|确实|实际|已经|已|将|会|必须|应(?:当|该)?|需要)"
    )
    MOCK_FORMAL_NEGATION_GOVERNOR = re.compile(
        r"(?:不得|不可|不能|不应|不会|不允许|禁止|严禁|切勿|避免|拒绝|未获准|无权)"
        r"(?:将|把|让|使|被|该|此|本|这些?|相关|Mock|CVR|数据|指标|数值|其|\s)*$"
    )
    MOCK_FORMAL_USE_PROHIBITED_FIXTURES = (
        "Mock CVR 参与正式预算计算。",
        "Mock CVR 被采用到正式预算。",
        "Mock CVR 投入正式预算。",
        "Mock CVR 计入正式预算。",
        "Mock CVR 作为正式预算依据。",
        "Mock CVR 供正式预算使用。",
        "Mock CVR 不进入测试预算，但计入正式预算。",
        "Mock CVR 参与正式预算计算或计入正式预算。",
        "Mock CVR 不参与演示但计入正式预算",
        "Mock CVR 不得参与正式预算计算或可计入正式预算。",
        "Mock CVR 不得参与正式预算计算，计入正式预算。",
    )
    MOCK_FORMAL_USE_ALLOWED_FIXTURES = (
        "Mock CVR 不参与正式预算计算。",
        "Mock CVR 未被采用到正式预算。",
        "Mock CVR 不投入正式预算。",
        "Mock CVR 不计入正式预算。",
        "Mock CVR 不供正式预算使用。",
        "Mock CVR 不作为正式预算依据。",
        "Mock CVR 不作为依据，不进入正式预算。",
        "Mock CVR 不用于正式预算。",
        "Mock CVR 不进入正式预算。",
        "Mock CVR 仅用于演示不得参与正式预算计算。",
        "Mock CVR 不得参与正式预算计算或计入正式预算。",
        "Mock CVR 不得参与正式预算计算和计入正式预算。",
        "Mock CVR 不得参与正式预算计算及计入正式预算。",
        "Mock CVR 不得参与正式预算计算以及计入正式预算。",
    )

    def _section(self, text, heading):
        match = re.search(
            rf"^{re.escape(heading)}\n(.*?)(?=^## |\Z)",
            text,
            flags=re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match, f"Missing section: {heading}")
        return match.group(1)

    def _json_blocks(self, text):
        blocks = re.findall(r"```json\n(.*?)\n```", text, flags=re.DOTALL)
        self.assertGreaterEqual(len(blocks), 9, "Missing canonical JSON blocks")
        return [json.loads(block) for block in blocks]

    def _canonical_artifacts(self, text):
        blocks = self._json_blocks(text)
        registry = next(
            (block["benchmark_registry"] for block in blocks if "benchmark_registry" in block),
            None,
        )
        claims = next(
            (block["evidence_registry"] for block in blocks if "evidence_registry" in block),
            None,
        )
        ledger = next(
            (block["budget_ledger"] for block in blocks if "budget_ledger" in block),
            None,
        )
        states = [block["module_state"] for block in blocks if "module_state" in block]
        self.assertIsNotNone(registry, "Missing canonical benchmark_registry JSON")
        self.assertIsNotNone(claims, "Missing canonical evidence_registry JSON")
        self.assertFalse(any("claim_evidence_registry" in block for block in blocks))
        self.assertIsNotNone(ledger, "Missing canonical budget ledger JSON")
        return registry, claims, ledger, states

    def _heading_state_pairs(self, text):
        pairs = re.findall(
            r"^### (M[1-6]) module_state\n\n```json\n(\{.*?\})\n```",
            text,
            flags=re.MULTILINE | re.DOTALL,
        )
        self.assertEqual(len(pairs), len(self.MODULE_ORDER))
        return [(heading, json.loads(block)["module_state"]) for heading, block in pairs]

    def _formal_use_entries(self, value, path=()):
        if isinstance(value, dict):
            for key, child in value.items():
                current_path = path + (key,)
                if key == "formal_use":
                    yield current_path, child, value
                yield from self._formal_use_entries(child, current_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from self._formal_use_entries(child, path + (index,))

    def _operator_text(self, text):
        """Operator prose excludes canonical data blocks and is unsafe if it asserts private facts."""
        return re.sub(r"```(?:json|yaml)\n.*?\n```", "", text, flags=re.DOTALL)

    def _assert_formal_use_policy(self, registry, claims, states):
        artifacts = {
            "benchmark_registry": registry,
            "evidence_registry": claims,
            "module_states": states,
        }
        entries = list(self._formal_use_entries(artifacts))
        self.assertGreaterEqual(len(entries), 9, "Expected formal-use declarations in every scope")
        for path, value, container in entries:
            path_text = ".".join(map(str, path))
            is_scenario = "scenario_ratio" in path
            is_restricted = container.get("status") in {"mock", "unavailable"}
            if is_scenario or is_restricted:
                self.assertFalse(value, f"Restricted formal use at {path_text}")
            if value:
                parent_path = tuple(part for part in path[:-1] if isinstance(part, str))
                self.assertIn(parent_path, self.FORMAL_USE_ALLOWED_PATHS)
                self.assertEqual(container.get("formal_selection_status"), "verified")
                self.assertIsNotNone(container.get("selected_value"))
                self.assertIsNotNone(container.get("selected_source"))

    def _assert_operator_competitor_boundary(self, text, claims):
        known_subjects = {"竞品"}
        known_subjects.update(item["name"] for item in claims["competitor_subjects"])
        self.assertIn("奇华", known_subjects)
        sentences = re.split(r"[。！？\n]", self._operator_text(text))
        for sentence in sentences:
            if not any(subject in sentence for subject in known_subjects):
                continue
            if not any(field in sentence for field in self.PRIVATE_COMPETITOR_FIELDS):
                continue
            has_confirmation = (
                any(marker in sentence for marker in self.PRIVATE_CONFIRMATION_MARKERS)
                or re.search(r"订单(?:数量)?为\s*\d", sentence) is not None
            )
            if not has_confirmation:
                continue
            if any(marker in sentence for marker in self.UNAVAILABLE_MARKERS):
                continue
            self.fail(f"Operator prose asserts private competitor fact: {sentence}")

    def _assert_operator_mock_formal_boundary(self, text):
        for sentence in re.split(r"[。！？\n]", self._operator_text(text)):
            if "Mock" not in sentence:
                continue
            occurrences = sorted(
                (
                    match
                    for pattern in self.MOCK_FORMAL_USE_PATTERNS
                    for match in pattern.finditer(sentence)
                ),
                key=lambda match: (match.start(), match.end()),
            )
            previous_end = None
            previous_is_negated = False
            for match in occurrences:
                prefix = sentence[:match.start()]
                polarity_scope = self.MOCK_FORMAL_NEGATION_BOUNDARY.split(prefix)[-1]
                has_attached_negation = re.search(
                    r"(?:不|未|没|没有|无|勿|别)\s*$",
                    polarity_scope,
                )
                has_governing_negation = self.MOCK_FORMAL_NEGATION_GOVERNOR.search(
                    polarity_scope
                )
                inherits_negation = False
                if previous_end is not None and previous_is_negated:
                    bridge = sentence[previous_end:match.start()]
                    coordinator = self.MOCK_FORMAL_COORDINATOR.match(bridge)
                    if coordinator and not self.MOCK_FORMAL_NEGATION_BOUNDARY.search(bridge):
                        coordination_tail = bridge[coordinator.end():] + match.group()
                        inherits_negation = not self.MOCK_FORMAL_POSITIVE_RESET.search(
                            coordination_tail
                        )

                current_is_negated = bool(
                    has_attached_negation
                    or has_governing_negation
                    or inherits_negation
                )
                if not current_is_negated:
                    self.fail(f"Operator prose grants Mock formal use: {sentence}")
                previous_end = match.end()
                previous_is_negated = current_is_negated

    def _assert_example_safety_contract(self, text):
        registry, claims, ledger, states = self._canonical_artifacts(text)
        self.assertEqual(
            set(claims),
            {"version", "run_id", "evidence", "claims", "competitor_subjects"},
        )
        evidence_fields = {
            "id", "evidence_level", "source_type", "source_name", "source_url",
            "collected_at", "period", "status", "is_mock", "allowed_use",
            "prohibited_use",
        }
        claim_fields = {
            "id", "subject", "claim_type", "status", "value", "unit",
            "evidence_ids", "formal_use", "required_evidence",
        }
        evidence_ids = set()
        for item in claims["evidence"]:
            self.assertEqual(set(item), evidence_fields)
            evidence_ids.add(item["id"])
        for claim in claims["claims"]:
            self.assertEqual(set(claim), claim_fields)
            self.assertLessEqual(set(claim["evidence_ids"]), evidence_ids)
        for subject in claims["competitor_subjects"]:
            self.assertEqual(set(subject), {"name", "evidence_ids", "status"})
            self.assertLessEqual(set(subject["evidence_ids"]), evidence_ids)

        public_bundle = next(
            item
            for item in claims["evidence"]
            if item["source_name"] == "data/quartet_public_sources.json"
        )
        self.assertEqual(public_bundle["evidence_level"], "B_公开观察")
        self.assertNotEqual(public_bundle["evidence_level"], "A_官方或授权")
        a_entries = [
            item
            for item in claims["evidence"]
            if item["evidence_level"] == "A_官方或授权"
        ]
        self.assertTrue(a_entries)
        self.assertTrue(all(item["status"] == "unavailable" for item in a_entries))
        self.assertEqual(tuple(state["module"] for state in states), self.MODULE_ORDER)
        heading_pairs = self._heading_state_pairs(text)
        self.assertEqual(tuple(heading for heading, _ in heading_pairs), self.MODULE_ORDER)
        for heading, state in heading_pairs:
            self.assertEqual(heading, state["module"])
        for state in states:
            for field in (
                "run_id",
                "module",
                "status",
                "evidence_ids",
                "confirmed_facts",
                "assumptions",
                "decisions",
                "unresolved_gaps",
                "human_review_items",
                "confidence",
                "decision_source",
            ):
                self.assertIn(field, state)

        metrics = registry["metrics"]
        for metric_name, (value, formula) in self.HISTORY_METRICS.items():
            metric = metrics[metric_name]
            self.assertEqual(metric["selected_value"], value)
            self.assertEqual(metric["selected_source"], "C-01")
            self.assertEqual(metric["selection_reason"], "同口径的用户导入工作簿聚合")
            self.assertEqual(metric["period"], "2026-01/2026-05")
            self.assertEqual(metric["formula"], formula)
            self.assertEqual(metric["evidence_level"], "C_用户导入")
            self.assertEqual(metric["value_kind"], "historical_fact")
            self.assertEqual(metric["value_precision"], "exact")
            self.assertEqual(metric["candidates"], [{
                "value": value,
                "source": "C-01",
                "period": "2026-01/2026-05",
                "formula": formula,
                "evidence_level": "C_用户导入",
            }])

        for ratio_name in ("recommended_ratio", "scenario_ratio"):
            ratio = registry["ratios"][ratio_name]
            self.assertEqual(ratio["value_kind"], "future_recommendation")
            self.assertEqual(ratio["range_representation"], "complementary_pairs")
            self.assertEqual(ratio["conservation_rule"], "search + feed = 100%")
            self.assertGreaterEqual(len(ratio["pairs"]), 1)
            for pair in ratio["pairs"]:
                self.assertEqual(pair["search"] + pair["feed"], 100)
                self.assertEqual(pair["evidence_level"], "E_策略假设")
                self.assertIn(pair["evidence_id"], evidence_ids)
                self.assertTrue(pair["source"])
                self.assertTrue(pair["period"])
                self.assertEqual(pair["formula"], "search + feed = 100%")
                self.assertTrue(pair["selection_reason"])
                self.assertFalse(pair["formal_use"])

        self._assert_formal_use_policy(registry, claims, states)

        m4 = next(state for state in states if state["module"] == "M4")
        ratio_decision = next(
            decision
            for decision in m4["decisions"]
            if decision["decision"] == "search_feed_split"
        )
        self.assertEqual(
            ratio_decision["source_path"],
            "benchmark_registry.ratios.recommended_ratio.pairs[0]",
        )
        self.assertEqual(
            ratio_decision["selected_pair"],
            registry["ratios"]["recommended_ratio"]["pairs"][0],
        )
        self.assertEqual(
            ratio_decision["evidence_id"], ratio_decision["selected_pair"]["evidence_id"]
        )
        self.assertEqual(
            ratio_decision["selection_reason"],
            ratio_decision["selected_pair"]["selection_reason"],
        )
        self.assertFalse(ratio_decision["formal_use"])

        self.assertEqual(
            ledger["organic_budget_cny"] + ledger["paid_budget_cny"],
            ledger["normalized_total_budget_cny"],
        )
        self.assertEqual(
            sum(phase["paid_budget_cny"] for phase in ledger["paid_phases"]),
            ledger["paid_budget_cny"],
        )
        m5 = next(state for state in states if state["module"] == "M5")
        self.assertTrue(any(
            isinstance(item, dict)
            and item.get("raw_total_budget_cny") == 100000
            and item.get("rounding_delta") == 0
            for item in m5["assumptions"]
        ))
        self.assertTrue(any(
            isinstance(item, dict)
            and item.get("normalized_total_budget_cny") == 100000
            and item.get("rounding_delta") == 0
            for item in m5["decisions"]
        ))

        claims_by_id = {claim["id"]: claim for claim in claims["claims"]}
        for claim_id in (
            "CLAIM-COMPETITOR-SPOTLIGHT-ACCOUNT",
            "CLAIM-COMPETITOR-TARGETING",
            "CLAIM-COMPETITOR-ORDERS",
        ):
            self.assertEqual(claims_by_id[claim_id]["status"], "unavailable")
            self.assertFalse(claims_by_id[claim_id]["formal_use"])
        self.assertEqual(claims_by_id["CLAIM-MOCK-CVR"]["status"], "mock")
        self.assertFalse(claims_by_id["CLAIM-MOCK-CVR"]["formal_use"])

        self._assert_operator_competitor_boundary(text, claims)
        self._assert_operator_mock_formal_boundary(text)

    def test_readme_parses_upload_order_file_inventory_and_routes(self):
        """The guide must distinguish installation instructions from optional knowledge."""
        text = self.README.read_text(encoding="utf-8")
        upload = self._section(text, "## 上传顺序（必须遵守）")

        governance_positions = [upload.index(filename) for filename in self.GOVERNANCE_FILES]
        sop_positions = [upload.index(filename) for filename in self.SOP_FILES]
        optional_positions = [
            upload.index(filename)
            for filename in (
                "data/quartet_brand_dossier.json",
                "data/quartet_public_sources.json",
                "docs/QUARTET_DATA_PROVENANCE.md",
                "examples/cookie_quartet_full_case.json",
                "示例_曲奇四重奏_FULL.md",
            )
        ]
        self.assertEqual(governance_positions, sorted(governance_positions))
        self.assertEqual(sop_positions, sorted(sop_positions))
        self.assertLess(max(governance_positions), min(sop_positions))
        self.assertLess(max(sop_positions), min(optional_positions))
        self.assertIn("Instructions", upload)
        self.assertIn("不是普通知识文件", upload)

        inventory = self._section(text, "## 文件清单与维护规则")
        for filename in (*self.GOVERNANCE_FILES, *self.SOP_FILES):
            with self.subTest(filename=filename):
                self.assertIn(filename, inventory)
        for filename in (
            "data/quartet_public_sources.json",
            "docs/QUARTET_DATA_PROVENANCE.md",
        ):
            with self.subTest(filename=filename):
                self.assertIn(filename, inventory)
        self.assertRegex(inventory, r"quartet_public_sources\.json.*公开")
        self.assertRegex(inventory, r"QUARTET_DATA_PROVENANCE\.md.*来源")
        self.assertIn("一套共享业务规则", inventory)

        routes = self._section(text, "## 命令路由与快速开始")
        for route in ("/m1", "/m2", "/m3", "/m4", "/m5", "/m6", "/full"):
            with self.subTest(route=route):
                self.assertIn(f"`{route}`", routes)
        self.assertIn("M1 → M2 → M6 → M3 → M4 → M5", routes)
        self.assertIn("Claude Project", text)
        self.assertIn("自定义 GPT", text)
        self.assertIn("跨会话", text)
        self.assertIn("Web Search", text)
        self.assertIn("持久化", text)
        self.assertIn("算术", text)
        self.assertIn("人工审批", text)

    def test_example_parses_provenance_ssot_gaps_and_final_audit(self):
        """The worked /full run must expose its inputs, handoffs, and stop conditions."""
        text = self.EXAMPLE.read_text(encoding="utf-8")
        self._assert_example_safety_contract(text)
        self.assertIn("曲奇四重奏", text)
        self.assertIn("数据需求.xlsx", text)
        self.assertIn("公开观察", text)
        self.assertIn("不可确认", text)
        for label in (
            "A_官方或授权",
            "B_公开观察",
            "C_用户导入",
            "D_行业基准",
            "E_策略假设",
            "Mock",
        ):
            with self.subTest(label=label):
                self.assertIn(label, text)

        gaps = self._section(text, "## 未解决缺口与人工审批")
        for required in (
            "竞品聚光账户",
            "真实定向",
            "订单",
            "工作簿",
            "人工审批",
        ):
            with self.subTest(required=required):
                self.assertIn(required, gaps)

        audit = self._section(text, "## `/full` 最终审计")
        for required in (
            "来源覆盖",
            "SSOT 冲突",
            "预算守恒",
            "Mock 隔离",
            "跨模块冲突",
        ):
            with self.subTest(required=required):
                self.assertIn(required, audit)

    def test_mock_formal_budget_guard_rejects_exact_affirmative_fixtures(self):
        """Every supported affirmative predicate must grant prohibited formal use."""
        for sentence in self.MOCK_FORMAL_USE_PROHIBITED_FIXTURES:
            with self.subTest(sentence=sentence):
                with self.assertRaisesRegex(AssertionError, "grants Mock formal use"):
                    self._assert_operator_mock_formal_boundary(sentence)

    def test_mock_formal_budget_guard_allows_exact_negated_fixtures(self):
        """Negation attached to or governing a formal-use predicate must be allowed."""
        for sentence in self.MOCK_FORMAL_USE_ALLOWED_FIXTURES:
            with self.subTest(sentence=sentence):
                self._assert_operator_mock_formal_boundary(sentence)

    def test_example_contract_rejects_structural_and_operator_assertion_mutations(self):
        """Schema drift, unsafe claim status, and reviewer adversarial prose must fail."""
        original = self.EXAMPLE.read_text(encoding="utf-8")
        mutations = (
            original.replace('"evidence_registry": {', '"claim_evidence_registry": {', 1),
            original.replace(
                '"source_name": "data/quartet_public_sources.json", "source_url":',
                '"source_name": "data/quartet_public_sources.json", "source_url":',
                1,
            ).replace('"evidence_level": "B_公开观察"', '"evidence_level": "A_官方或授权"', 1),
            original.replace(
                '"claim_type": "private_competitor_account", "status": "unavailable"',
                '"claim_type": "private_competitor_account", "status": "available"',
                1,
            ),
            original.replace('"formal_use": false', '"formal_use": true', 1),
            original.replace(
                '"purpose": "仅用于 A/B 情景比较，不进入正式预算汇总", "formal_use": false',
                '"purpose": "仅用于 A/B 情景比较，不进入正式预算汇总", "formal_use": true',
                1,
            ),
            original.replace('"search": 60, "feed": 40', '"search": 61, "feed": 40', 1),
            original.replace('"evidence_id": "E-01"', '"evidence_id": "UNKNOWN-RATIO"', 1),
            original.replace(
                '"formula": "search + feed = 100%"',
                '"formula": "模型建议"',
                1,
            ),
            original.replace('"paid_budget_cny": 70000', '"paid_budget_cny": 69999', 1),
            original + "\n竞品奇华的聚光账户已验证，真实定向为旅游人群。\n",
            original + "\n奇华的聚光账户定向已验证。\n",
            original + "\n珍妮曲奇真实预算数据显示为 100 万。\n",
            original + "\n竞品账户订单为 1200 单。\n",
            original + "\n经确认，竞品真实定向可投。\n",
            original + "\nMock CVR 0.012 可用于正式预算。\n",
            original + "\nMock 数据已经进入正式预算。\n",
            *(
                original + f"\n{sentence}\n"
                for sentence in self.MOCK_FORMAL_USE_PROHIBITED_FIXTURES
            ),
            original.replace("### M6 module_state", "### M3 module_state", 1),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation[-80:]):
                with self.assertRaises(AssertionError):
                    self._assert_example_safety_contract(mutation)


if __name__ == "__main__":
    unittest.main()
