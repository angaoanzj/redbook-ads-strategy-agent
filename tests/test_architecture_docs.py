"""技术架构文档契约：保证作业交付 ARCHITECTURE 文档含关键边界与图。"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

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

    def _assert_architecture_semantics(self, architecture: str) -> None:
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

    def test_architecture_documents_current_system_boundaries(self) -> None:
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

    def test_architecture_semantic_guard_rejects_missing_approval_or_deployment_path(
        self,
    ) -> None:
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


if __name__ == "__main__":
    unittest.main()
