#!/usr/bin/env python3
"""实时数据源演示守护脚本：周期性调用本地 API 的 /feeds/pull，打印每批摘要。

这是一个**纯客户端脚本**：不 import 项目模块，只用 httpx 打本地 HTTP 接口，
因此它演示的正是「外部数据源持续把数据推进来」这件事本身。

用法（先在另一个终端起服务：`python3 main.py` 或 docker compose up）::

    python3 scripts/feed_daemon.py                       # 每 10 秒一批，共 6 批
    python3 scripts/feed_daemon.py --interval 3 --count 20 --seed demo-2026
    python3 scripts/feed_daemon.py --base-url http://127.0.0.1:8010 --category 香港蝴蝶酥伴手礼

拉完之后可以验证合并效果::

    curl 'http://127.0.0.1:8010/feeds/status'
    curl -X POST 'http://127.0.0.1:8010/analyze?use_realtime_feed=true&use_model=false' \
         -H 'Content-Type: application/json' \
         -d @examples/cookie_quartet_full_case.json | jq '.trace[] | select(.step=="realtime_feed_merge")'
"""
from __future__ import annotations

import argparse
import sys
import time

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8010"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feed_daemon",
        description="周期性调用 /feeds/pull，演示模拟实时数据源持续传入",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"服务地址（默认 {DEFAULT_BASE_URL}）")
    parser.add_argument("--interval", type=float, default=10.0, help="两批之间的间隔秒数（默认 10）")
    parser.add_argument("--count", type=int, default=6, help="拉取批次数（默认 6）")
    parser.add_argument("--seed", default="", help="Mock 种子；同种子生成同一批次序列")
    parser.add_argument("--category", default="", help="品类（用于生成上升词）")
    parser.add_argument("--brand", default="", help="品牌（用于生成上升词）")
    parser.add_argument("--product-name", default="", help="商品名（用于生成上升词）")
    parser.add_argument("--timeout", type=float, default=15.0, help="单次请求超时秒数")
    return parser


def pull_once(client: httpx.Client, params: dict[str, str]) -> dict:
    response = client.post("/feeds/pull", params=params)
    response.raise_for_status()
    return response.json()


def format_summary(index: int, total: int, summary: dict) -> str:
    counts = summary.get("counts") or {}
    keywords = summary.get("trending_keywords") or []
    accounts = summary.get("competitor_accounts") or []
    return (
        f"[{index}/{total}] {summary.get('batch_id')} @ {summary.get('generated_at')}\n"
        f"        来源：{summary.get('source_name')}（is_mock={summary.get('is_mock')}）\n"
        f"        条目：热搜 {counts.get('trending', 0)}、竞品事件 "
        f"{counts.get('competitor_event', 0)}、基准漂移 {counts.get('benchmark_drift', 0)}\n"
        f"        上升词：{'、'.join(keywords) or '(无)'}\n"
        f"        竞品：{'、'.join(accounts) or '(无)'}"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    params = {
        key: value
        for key, value in (
            ("seed", args.seed),
            ("category", args.category),
            ("brand", args.brand),
            ("product_name", args.product_name),
        )
        if value
    }

    print(
        f"开始拉取模拟实时数据源：{args.base_url}/feeds/pull，"
        f"共 {args.count} 批，间隔 {args.interval:g}s"
    )
    failures = 0
    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        for index in range(1, args.count + 1):
            try:
                summary = pull_once(client, params)
            except (httpx.HTTPError, ValueError) as exc:
                failures += 1
                print(f"[{index}/{args.count}] 拉取失败：{exc.__class__.__name__}: {exc}")
            else:
                print(format_summary(index, args.count, summary))
            if index < args.count:
                time.sleep(max(0.0, args.interval))

    try:
        with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
            status = client.get("/feeds/status").json()
        print(
            "\n累计状态：批次 {batch}、条目 {items}（{counts}），最新 {latest}".format(
                batch=status.get("batch_count"),
                items=status.get("item_total"),
                counts=status.get("item_counts"),
                latest=status.get("latest_generated_at"),
            )
        )
    except (httpx.HTTPError, ValueError) as exc:
        print(f"读取 /feeds/status 失败：{exc.__class__.__name__}: {exc}")

    if failures:
        print(f"\n注意：{failures} 批拉取失败（服务是否已启动？）", file=sys.stderr)
        return 1
    print("\n下一步：调 /analyze?use_realtime_feed=true 让本批数据进入证据区（trace 会记 realtime_feed_merge）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
