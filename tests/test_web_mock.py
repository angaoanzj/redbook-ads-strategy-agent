import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "web"


class MockWebTests(unittest.TestCase):
    def test_historical_baseline_and_knowledge_are_one_default_evidence_switch(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="useEvidence" type="checkbox" checked', html)
        self.assertIn("使用历史基准与本地知识库", html)
        self.assertIn('const useEvidence = $("#useEvidence").checked;', script)
        self.assertIn("const useKnowledge = useEvidence;", script)
        self.assertNotIn('id="useHistory"', html)
        self.assertNotIn('id="useKnowledge"', html)

    def test_form_sends_mock_control(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="allowMock"', html)
        self.assertIn("allow_mock=${allowMock}", script)

    def test_page_can_regenerate_reproducible_mock_group(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="mockSeed"', html)
        self.assertIn('id="regenerateMock"', html)
        self.assertIn("换一组 Mock", html)
        self.assertIn("mock_seed=${encodeURIComponent(currentMockSeed)}", script)
        self.assertIn('form.requestSubmit()', script)
        self.assertIn('mock_seed: "Mock种子"', script)

    def test_renderer_contains_visible_mock_badge(self):
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "style.css").read_text(encoding="utf-8")

        self.assertIn("模拟数据（Mock）", script)
        self.assertIn("data-badge", script)
        self.assertIn('evidence_boundary: "证据边界"', script)
        self.assertIn(".data-badge.mock", styles)

    def test_result_views_without_standalone_report_tab(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app.js").read_text(encoding="utf-8")

        self.assertNotIn('data-view="report"', html)
        self.assertIn('data-view="benchmark"', html)
        self.assertIn("对标拆解", html)
        self.assertIn("DeepSeek 人话解读写入对标看板", html)
        self.assertIn("agent-insight", script)
        self.assertNotIn("分析报告", html)
        self.assertNotIn('data-view="actions"', html)
        self.assertIn("聚光投流前置决策", html)
        self.assertIn("附加工具", html)
        self.assertIn('data-view="tools"', html)
        self.assertIn("证据附录", html)
        self.assertNotIn("function renderReportView", script)
        self.assertIn("function renderCompetitorBenchmarkBoard", script)
        self.assertIn("function renderAddonToolsSheet", script)
        self.assertIn("function peakSlotChart", script)
        self.assertIn("品牌自然内容表", script)
        self.assertIn("内容供给", script)
        self.assertNotIn("function renderActionPlan", script)
        self.assertIn("operator_playbook", script)
        self.assertIn("function renderEvidenceAppendix", script)
        self.assertIn('setResultView(hasBenchmark ? "benchmark" : "tools")', script)

    def test_native_charts_are_present_without_heavy_dependency(self):
        script = (ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn("function lineChart", script)
        self.assertIn("function donutChart", script)
        self.assertNotIn("chart.js", script.casefold())

    def test_competitor_board_shows_evidence_quality_columns(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn('label: "证据/样本"', app_js)
        self.assertIn('label: "结论类型"', app_js)
        self.assertIn('label: "置信度"', app_js)

    def test_frontend_persists_sends_and_displays_session_state(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="sessionState"', html)
        self.assertIn('id="newSession"', html)
        self.assertIn("新建会话", html)
        self.assertIn("xhs_agent_session_id", script)
        self.assertIn('"X-Session-ID"', script)
        self.assertIn('"Idempotency-Key"', script)
        self.assertIn("analysis_count", script)
        self.assertIn("function newSession", script)


if __name__ == "__main__":
    unittest.main()
