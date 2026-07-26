#!/usr/bin/env python3
"""竞品监控定时扫描守护脚本：周期性调用 /competitors/scan，刷新快照并落预警。

纯客户端：不 import 项目模块。需先启动服务（python3 main.py 或 docker compose）。

用法::

    python3 scripts/competitor_scan_daemon.py --brand CookieQuartet
    python3 scripts/competitor_scan_daemon.py --brand CookieQuartet --interval 60 --count 3
    curl 'http://127.0.0.1:8010/alerts?brand_name=CookieQuartet'
"""
from __future__ import annotations

import argparse
import sys
import time

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8010"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="competitor_scan_daemon",
        description="周期性调用 /competitors/scan，演示竞品监控定时器",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--brand", required=True, help="品牌名（与分析请求 brand_name 一致）")
    parser.add_argument("--interval", type=float, default=3600.0, help="扫描间隔秒数（默认 1 小时）")
    parser.add_argument("--count", type=int, default=1, help="扫描次数（默认 1）")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def scan_once(client: httpx.Client, brand: str) -> dict:
    response = client.post("/competitors/scan", params={"brand_name": brand})
    response.raise_for_status()
    return response.json()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(
        f"竞品扫描守护：brand={args.brand} interval={args.interval}s count={args.count} "
        f"→ {args.base_url}"
    )
    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        for index in range(1, max(1, args.count) + 1):
            try:
                payload = scan_once(client, args.brand)
            except Exception as exc:
                print(f"[{index}/{args.count}] 失败：{exc.__class__.__name__}: {exc}", file=sys.stderr)
                if index < args.count:
                    time.sleep(max(0.0, args.interval))
                continue
            monitor = payload.get("monitor") or {}
            alerts = monitor.get("alerts") or []
            print(
                f"[{index}/{args.count}] status={payload.get('status')} "
                f"alerts_saved={payload.get('alerts_saved')} "
                f"had_previous={payload.get('had_previous_snapshot')} "
                f"ttl={payload.get('cache_ttl_seconds')}s"
            )
            for alert in alerts[:5]:
                print(
                    f"        · [{alert.get('severity')}] {alert.get('type')}: "
                    f"{alert.get('message')}"
                )
            if index < args.count:
                time.sleep(max(0.0, args.interval))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
