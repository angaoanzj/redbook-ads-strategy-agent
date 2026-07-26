import sys
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated.*")
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import app
from tests.test_engine import sample_request


class MockApiTests(unittest.TestCase):
    def test_mock_seed_is_reproducible_through_api(self):
        client = TestClient(app)
        url = "/analyze?use_model=false&use_knowledge=false&allow_mock=true&mock_seed=api-a"
        first = client.post(url, json=sample_request().model_dump(mode="json")).json()
        repeated = client.post(url, json=sample_request().model_dump(mode="json")).json()
        changed = client.post(
            url.replace("api-a", "api-b"),
            json=sample_request().model_dump(mode="json"),
        ).json()

        self.assertEqual(first["modules"], repeated["modules"])
        self.assertNotEqual(first["modules"], changed["modules"])
        mock_trace = next(row for row in first["trace"] if row.get("stage") == "mock_fallback")
        self.assertEqual(mock_trace["mock_seed"], "api-a")

    def test_analyze_query_enables_mock_fallback(self):
        response = TestClient(app).post(
            "/analyze?use_model=false&use_knowledge=false&allow_mock=true",
            json=sample_request().model_dump(mode="json"),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        cpc = payload["modules"]["module_1_market_competitor"]["spotlight_market"]["average_cpc"]
        self.assertTrue(cpc["is_mock"])
        self.assertEqual(cpc["data_type"], "模拟数据（Mock）")
        self.assertTrue(any(row.get("allow_mock") is True for row in payload["trace"]))

    def test_api_returns_human_readable_report_view(self):
        response = TestClient(app).post(
            "/analyze?use_model=false&use_knowledge=false&allow_mock=true&mock_seed=api-report",
            json=sample_request().model_dump(mode="json"),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["report_view"]["report_sections"]), 4)
        self.assertEqual(payload["report_view"]["report_sections"][0]["key"], "market_competitor")
        mock_trace = next(row for row in payload["trace"] if row.get("stage") == "mock_fallback")
        self.assertGreaterEqual(mock_trace.get("agent_count_activated", 0), 1)
        self.assertTrue(mock_trace.get("subagents"))
        self.assertEqual(
            payload["report_view"]["executive_summary"]["mock_seed"], "api-report"
        )

    def test_board_refresh_and_export(self):
        client = TestClient(app)
        analyzed = client.post(
            "/analyze?use_model=false&use_knowledge=false&allow_mock=true&mock_seed=board-api",
            json=sample_request().model_dump(mode="json"),
        )
        self.assertEqual(analyzed.status_code, 200)
        payload = analyzed.json()
        report_id = payload["report_id"]
        self.assertTrue(report_id)
        board = client.get(f"/board/{report_id}?refresh=true")
        self.assertEqual(board.status_code, 200)
        dash = board.json()
        self.assertEqual(dash["report_id"], report_id)
        self.assertGreaterEqual(len(dash.get("module_panels") or []), 5)
        self.assertTrue(dash.get("delivery", {}).get("phases"))
        md = client.get(f"/board/{report_id}/export?format=markdown")
        self.assertEqual(md.status_code, 200)
        self.assertIn("全域投放数据看板", md.text)
        csv_resp = client.get(f"/board/{report_id}/export?format=csv")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("section,key,label", csv_resp.text)


if __name__ == "__main__":
    unittest.main()
