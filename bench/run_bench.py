#!/usr/bin/env python3
"""评测跑分入口（不进 unittest：--live 需要真实模型 Key 且耗时）。

两种模式
--------

1) 回放存档（离线，无需模型 Key）::

       python3 bench/run_bench.py --replay bench/fixtures/regression_outputs.json

   存档格式就是 `{module_name: result}`，其中 result 是
   `module_agents.base.run_module_agent` 的返回（含 output / grounding_check /
   steps_used / repair_rounds_used）。也接受
   `{"request": {...}, "modules": {module_name: result}}` 这种带请求的包装格式。

   **怎么从一次真实运行里存出这个文件**：

       from module_agents.orchestrator import run_pipeline
       from models import CampaignRequest
       import json

       req = CampaignRequest.model_validate(
           json.load(open("examples/cookie_quartet_full_case.json", encoding="utf-8"))
       )
       outcome = run_pipeline(req)          # {"modules": {...}, "pipeline_trace": [...]}
       json.dump(
           {"request": req.model_dump(mode="json"), "modules": outcome["modules"]},
           open("bench/fixtures/run_2026xxxx.json", "w", encoding="utf-8"),
           ensure_ascii=False, indent=2, default=str,
       )

   （demo_agent_loop.py / `/analyze?use_agent_modules=true` 的
   `modules.*.agent_decision` 也是同构结构，可同样存档回放。）

2) 真跑（需要模型 Key）::

       python3 bench/run_bench.py --live

   用 `examples/cookie_quartet_full_case.json` 调 `orchestrator.run_pipeline`，
   跑完立即评分。

报告
----

每次跑分写入 `bench/reports/<UTC时间戳>/report.json` 与 `report.md`；
若 `bench/reports/` 下已有更早的报告，markdown 里会带上与上一份的分差列。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # 允许 `python3 bench/run_bench.py` 直接执行
    sys.path.insert(0, str(ROOT))

from bench.score import render_markdown, score_run  # noqa: E402

DEFAULT_REQUEST = ROOT / "examples" / "cookie_quartet_full_case.json"
DEFAULT_REPORT_DIR = ROOT / "bench" / "reports"

# 评测矩阵：满证据 / 工作簿弱证据 / 极简请求（诚实分压力）
MATRIX_CASES: list[tuple[str, Path]] = [
    ("full_evidence", ROOT / "examples" / "cookie_quartet_full_case.json"),
    ("workbook_partial", ROOT / "examples" / "cookie_quartet_with_workbook_data.json"),
    ("minimal", ROOT / "examples" / "cookie_quartet.json"),
]


def _load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_archive(path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """返回 (modules, request_or_None)，兼容裸 {module: result} 与带 request 的包装。"""
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"存档格式非法：{path} 顶层必须是对象")
    if "modules" in payload and isinstance(payload["modules"], dict):
        return payload["modules"], payload.get("request")
    return payload, None


def run_live(request_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """真跑六模块流水线（需要模型 Key）。仅在 --live 时才 import 模块层。"""
    from models import CampaignRequest  # 延迟导入：回放模式无需 pydantic 契约
    from module_agents.orchestrator import run_pipeline

    payload = _load_json(request_path)
    req = CampaignRequest.model_validate(payload)
    outcome = run_pipeline(req)
    return outcome["modules"], req.model_dump(mode="json")


def find_previous_report(report_dir: Path, exclude: Path | None = None) -> dict[str, Any] | None:
    if not report_dir.exists():
        return None
    candidates = sorted(
        (path for path in report_dir.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    )
    for path in reversed(candidates):
        if exclude is not None and path.resolve() == exclude.resolve():
            continue
        report = path / "report.json"
        if report.exists():
            try:
                return _load_json(report)
            except (ValueError, OSError):
                continue
    return None


def write_report(
    summary: dict[str, Any],
    report_dir: Path,
    *,
    meta: dict[str, Any],
) -> tuple[Path, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = report_dir / stamp
    suffix = 1
    while target.exists():
        suffix += 1
        target = report_dir / f"{stamp}-{suffix}"
    target.mkdir(parents=True)

    previous = find_previous_report(report_dir, exclude=target)
    markdown = render_markdown(summary, previous)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "meta": meta,
        "overall": summary["overall"],
        "module_count": summary["module_count"],
        "dimension_avg": summary["dimension_avg"],
        "missing_modules": summary["missing_modules"],
        "unknown_modules": summary["unknown_modules"],
        "modules": summary["modules"],
        "previous_overall": previous.get("overall") if previous else None,
        "overall_delta": (
            round(summary["overall"] - previous["overall"], 2)
            if previous and isinstance(previous.get("overall"), (int, float))
            else None
        ),
    }
    json_path = target / "report.json"
    md_path = target / "report.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(markdown + "\n", encoding="utf-8")
    return json_path, md_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_bench",
        description="六模块回归评分：回放存档或真跑 pipeline 后打分并写报告",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--replay", metavar="JSON", help="回放 {module: result} 存档并评分")
    source.add_argument("--live", action="store_true", help="调 run_pipeline 真跑后评分（需模型 Key）")
    source.add_argument(
        "--matrix",
        action="store_true",
        help="真跑评测矩阵（满证据/弱证据/极简）；需模型 Key，耗时约为单次×案例数",
    )
    parser.add_argument(
        "--request",
        metavar="JSON",
        default=str(DEFAULT_REQUEST),
        help=f"评测用的请求（默认 {DEFAULT_REQUEST.name}）；不变量需要它来核对预算/证据口径",
    )
    parser.add_argument(
        "--out-dir", metavar="DIR", default=str(DEFAULT_REPORT_DIR), help="报告根目录"
    )
    parser.add_argument("--label", default="", help="写进报告 meta 的自定义标签（如 prompt 版本/模型名）")
    parser.add_argument("--no-write", action="store_true", help="只打印，不写报告文件")
    return parser


def run_matrix(out_dir: Path, *, label: str, no_write: bool) -> int:
    """逐案例真跑并各写一份报告，最后打印矩阵总表。"""
    rows: list[dict[str, Any]] = []
    for case_id, path in MATRIX_CASES:
        if not path.exists():
            print(f"[skip] {case_id}: 缺少 {path}", file=sys.stderr)
            continue
        print(f"[matrix] 跑案例 {case_id} ← {path.name} …", flush=True)
        modules, req = run_live(path)
        summary = score_run(modules, req)
        meta = {
            "source": f"matrix:{case_id}",
            "request": str(path),
            "label": label or case_id,
            "mode": "matrix",
            "case_id": case_id,
        }
        if not no_write:
            json_path, md_path = write_report(summary, out_dir, meta=meta)
            print(f"  → {json_path}")
        rows.append({
            "case_id": case_id,
            "overall": summary["overall"],
            "module_count": summary["module_count"],
            "dimension_avg": summary["dimension_avg"],
        })
    print("\n# 评测矩阵总表\n")
    print("| 案例 | 总分 | 溯源 | 诚实 | 不变量 | 结构 | 文本 |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in rows:
        avg = row["dimension_avg"]
        print(
            f"| {row['case_id']} | {row['overall']} | {avg.get('grounding')} | "
            f"{avg.get('honesty')} | {avg.get('invariants')} | {avg.get('structure')} | "
            f"{avg.get('text')} |"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    request_path = Path(args.request)

    if args.matrix:
        return run_matrix(Path(args.out_dir), label=args.label, no_write=args.no_write)

    if args.live:
        modules, req = run_live(request_path)
        source_desc = f"live:{request_path.name}"
    else:
        replay_path = Path(args.replay)
        modules, embedded_req = load_archive(replay_path)
        req = embedded_req if isinstance(embedded_req, dict) else _load_json(request_path)
        source_desc = f"replay:{replay_path.name}"

    summary = score_run(modules, req)
    meta = {
        "source": source_desc,
        "request": str(request_path),
        "label": args.label,
        "mode": "live" if args.live else "replay",
    }

    if args.no_write:
        print(summary["markdown"])
        return 0

    report_dir = Path(args.out_dir)
    json_path, md_path = write_report(summary, report_dir, meta=meta)
    print(Path(md_path).read_text(encoding="utf-8"))
    print(f"报告已写入：\n  - {json_path}\n  - {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
