#!/usr/bin/env python3
"""实时拉取关键词搜索热度，输出 Agent 可用的 trending_keyword_evidence。

数据源（按优先级）：

1. ``5118`` — 正式搜索热度
   - ``lookup``：关键词搜索量信息 APIv2（`/keywordparam/v2`，异步 1–10 分钟）
     返回流量指数 / 移动指数 / PC·移动日检索量等。
   - ``expand``：海量长尾词挖掘 APIv2（`/keyword/word/v2`，同步）
     按种子词挖相关长尾并带指数（对应 cw.5118.com 监控页意图）。
2. ``proxy`` — 无 API Key 时的公开下拉代理（**不是**真实搜索热度，仅相对排序）

用法::

    # 精确查热度（需 AGENT_5118_API_KEY）
    python3 scripts/fetch_keyword_heat.py lookup \\
      --keywords 香港伴手礼,珍妮曲奇,蝴蝶酥 \\
      --out examples/hongkong_souvenir_heat_live.json

    # 从种子扩词 + 指数（同步，适合「香港伴手礼」长尾监控）
    python3 scripts/fetch_keyword_heat.py expand \\
      --seed 香港伴手礼 --limit 30 \\
      --out examples/hongkong_souvenir_heat_expand.json

    # 无 Key：百度下拉代理（会标注 is_proxy）
    python3 scripts/fetch_keyword_heat.py proxy --seed 香港伴手礼 --limit 24

环境变量：

- ``AGENT_5118_API_KEY``：5118 API Key（https://account.5118.com/signin/myapi）
- 也可 ``--api-key`` 或从本仓 ``.env`` 自动读取

边界：5118 指数是搜索引擎 SEO 流量词热度，**不等于**小红书官方热搜。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = ROOT / ".env"

API_HOST = "http://apis.5118.com"
LOOKUP_PATH = "/keywordparam/v2"
EXPAND_PATH = "/keyword/word/v2"

# 异步查热度：5118 文档建议约 60s 轮询，最长约 10 分钟
DEFAULT_POLL_INTERVAL = 60.0
DEFAULT_POLL_TIMEOUT = 600.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def _today() -> str:
    return datetime.now().date().isoformat()


def load_dotenv(path: Path = DEFAULT_ENV) -> None:
    """极简 .env 加载：不覆盖已有环境变量。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_api_key(cli_key: str | None) -> str:
    key = (cli_key or os.environ.get("AGENT_5118_API_KEY") or "").strip()
    if not key:
        raise SystemExit(
            "缺少 5118 API Key。请设置 AGENT_5118_API_KEY，或传入 --api-key。\n"
            "申请：https://account.5118.com/signin/myapi\n"
            "无 Key 时可改用：python3 scripts/fetch_keyword_heat.py proxy --seed 香港伴手礼"
        )
    return key


def parse_keywords(raw: str | None, path: str | None) -> list[str]:
    items: list[str] = []
    if raw:
        for part in re.split(r"[,|，\n]+", raw):
            kw = part.strip()
            if kw:
                items.append(kw)
    if path:
        text = Path(path).read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # 兼容 UI 粘贴格式 keyword|heat
            kw = line.split("|", 1)[0].strip()
            if kw:
                items.append(kw)
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for kw in items:
        if kw not in seen:
            seen.add(kw)
            out.append(kw)
    if not out:
        raise SystemExit("请通过 --keywords 或 --keywords-file 提供至少一个关键词")
    if len(out) > 50:
        raise SystemExit(f"一次最多 50 个词（5118 限制），当前 {len(out)} 个")
    return out


def http_post_form(
    path: str,
    fields: dict[str, Any],
    *,
    api_key: str,
    timeout: float = 60.0,
) -> dict[str, Any]:
    body = urllib.parse.urlencode({k: v for k, v in fields.items() if v is not None}).encode(
        "utf-8"
    )
    req = urllib.request.Request(
        API_HOST + path,
        data=body,
        method="POST",
        headers={
            "Authorization": api_key,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "xiaohongshu-agent/fetch_keyword_heat",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"5118 HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"5118 网络错误: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"5118 返回非 JSON: {raw[:300]}") from exc
    return payload


def assert_5118_ok(payload: dict[str, Any], *, allow_pending: bool = False) -> dict[str, Any]:
    err = str(payload.get("errcode", "0"))
    if err in {"0", "0.0"}:
        data = payload.get("data")
        return data if isinstance(data, dict) else {}
    if allow_pending and err == "200104":
        return {"_pending": True, "errmsg": payload.get("errmsg") or "数据获取中"}
    raise SystemExit(
        f"5118 业务错误 errcode={err} errmsg={payload.get('errmsg') or payload}"
    )


def heat_score_from_metrics(
    *,
    index: float | None,
    mobile_index: float | None,
    pc_pv: float | None,
    mobile_pv: float | None,
) -> float:
    """把 5118 原始指标压到 Agent 常用的 0–100 heat_score。

    优先用流量指数；指数缺失时用日检索量的对数映射。
    """
    idx = max(float(index or 0), float(mobile_index or 0))
    if idx > 0:
        # index 常见数百～数千；对数压缩后约落在 40–99
        return round(min(99.0, max(1.0, 18.0 * math.log10(idx + 1) + 20.0)), 1)
    pv = float(pc_pv or 0) + float(mobile_pv or 0)
    if pv > 0:
        return round(min(99.0, max(1.0, 12.0 * math.log10(pv + 1) + 25.0)), 1)
    return 0.0


def row_to_evidence(row: dict[str, Any], *, source_name: str, mode: str) -> dict[str, Any]:
    keyword = str(row.get("keyword") or "").strip()
    index = _as_float(row.get("index"))
    mobile_index = _as_float(row.get("mobile_index"))
    pc_pv = _as_float(row.get("bidword_pcpv"))
    mobile_pv = _as_float(row.get("bidword_wisepv"))
    douyin = _as_float(row.get("douyin_index"))
    haosou = _as_float(row.get("haosou_index"))
    heat = heat_score_from_metrics(
        index=index, mobile_index=mobile_index, pc_pv=pc_pv, mobile_pv=mobile_pv
    )
    notes_parts = [
        f"mode={mode}",
        f"流量指数={_fmt(index)}",
        f"移动指数={_fmt(mobile_index)}",
        f"PC日检索={_fmt(pc_pv)}",
        f"移动日检索={_fmt(mobile_pv)}",
    ]
    if douyin is not None:
        notes_parts.append(f"抖音指数={_fmt(douyin)}")
    if haosou is not None:
        notes_parts.append(f"360指数={_fmt(haosou)}")
    reason = row.get("bidword_showreasons") or row.get("sem_reason")
    if reason:
        notes_parts.append(f"特点={reason}")
    return {
        "keyword": keyword,
        "source_name": source_name,
        "collected_at": _today(),
        "collected_at_precise": _now_iso(),
        "heat_score": heat,
        "raw_metrics": {
            "index": index,
            "mobile_index": mobile_index,
            "bidword_pcpv": pc_pv,
            "bidword_wisepv": mobile_pv,
            "douyin_index": douyin,
            "haosou_index": haosou,
            "long_keyword_count": row.get("long_keyword_count"),
            "bidword_company_count": row.get("bidword_company_count"),
            "bidword_kwc": row.get("bidword_kwc"),
            "sem_price": row.get("sem_price") or row.get("bidword_price"),
        },
        "notes": "；".join(notes_parts),
        "is_mock": False,
        "is_proxy": False,
        "evidence_grade": "B_5118_live",
    }


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: float | None) -> str:
    if value is None:
        return "—"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}"


def fetch_lookup(
    keywords: list[str],
    *,
    api_key: str,
    poll_interval: float,
    poll_timeout: float,
) -> list[dict[str, Any]]:
    print(f"[lookup] 提交 {len(keywords)} 个词到 5118 搜索量 API …", flush=True)
    submit = http_post_form(
        LOOKUP_PATH,
        {"keywords": "|".join(keywords)},
        api_key=api_key,
    )
    data = assert_5118_ok(submit)
    task_id = data.get("taskid")
    if task_id is None:
        raise SystemExit(f"5118 未返回 taskid: {submit}")
    print(f"[lookup] taskid={task_id}，开始轮询（间隔 {poll_interval:.0f}s，最长 {poll_timeout:.0f}s）", flush=True)

    deadline = time.time() + poll_timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        result = http_post_form(LOOKUP_PATH, {"taskid": task_id}, api_key=api_key)
        err = str(result.get("errcode", "0"))
        if err == "200104":
            remain = max(0, int(deadline - time.time()))
            print(f"[lookup] 第 {attempt} 次：数据获取中，剩余约 {remain}s …", flush=True)
            time.sleep(poll_interval)
            continue
        data = assert_5118_ok(result)
        rows = data.get("keyword_param") or []
        if not isinstance(rows, list):
            raise SystemExit(f"5118 结果格式异常: {result}")
        print(f"[lookup] 完成，拿到 {len(rows)} 条", flush=True)
        return [
            row_to_evidence(
                row,
                source_name="5118关键词搜索量APIv2",
                mode="lookup",
            )
            for row in rows
            if isinstance(row, dict) and row.get("keyword")
        ]
    raise SystemExit(
        f"轮询超时（{poll_timeout:.0f}s）。可用同一 taskid 稍后重试：\n"
        f"  python3 scripts/fetch_keyword_heat.py poll --task-id {task_id}"
    )


def fetch_poll(task_id: str, *, api_key: str) -> list[dict[str, Any]]:
    result = http_post_form(LOOKUP_PATH, {"taskid": task_id}, api_key=api_key)
    err = str(result.get("errcode", "0"))
    if err == "200104":
        raise SystemExit(f"taskid={task_id} 仍在获取中（errcode=200104），稍后再 poll")
    data = assert_5118_ok(result)
    rows = data.get("keyword_param") or []
    return [
        row_to_evidence(row, source_name="5118关键词搜索量APIv2", mode="lookup")
        for row in rows
        if isinstance(row, dict) and row.get("keyword")
    ]


def fetch_expand(
    seed: str,
    *,
    api_key: str,
    page_index: int,
    page_size: int,
    sort_fields: int,
) -> list[dict[str, Any]]:
    print(f"[expand] 种子「{seed}」拉取长尾词（page={page_index}, size={page_size}）…", flush=True)
    payload = http_post_form(
        EXPAND_PATH,
        {
            "keyword": seed,
            "page_index": page_index,
            "page_size": page_size,
            "sort_fields": sort_fields,
            "sort_type": "desc",
            "filter": 1,
        },
        api_key=api_key,
    )
    data = assert_5118_ok(payload)
    rows = data.get("word") or data.get("words") or []
    if not isinstance(rows, list):
        raise SystemExit(f"5118 expand 结果格式异常: {payload}")
    print(f"[expand] total={data.get('total')} 本页={len(rows)}", flush=True)
    return [
        row_to_evidence(
            row,
            source_name=f"5118长尾词挖掘APIv2（种子={seed}）",
            mode="expand",
        )
        for row in rows
        if isinstance(row, dict) and row.get("keyword")
    ]


def baidu_suggest(seed: str) -> list[str]:
    url = (
        "https://suggestion.baidu.com/su?wd="
        + urllib.parse.quote(seed)
        + "&cb=window.bdsug.sug"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("gbk", errors="ignore")
    match = re.search(r"s:\s*(\[[^\]]*\])", raw)
    if not match:
        return []
    return [str(x) for x in json.loads(match.group(1)) if str(x).strip()]


def fetch_proxy(seed: str, *, limit: int) -> list[dict[str, Any]]:
    """无 5118 Key 时的公开下拉代理：热度仅为排序分，不是真实搜索量。"""
    seeds = [seed, f"{seed}必买", f"{seed}推荐", "香港手信", "珍妮曲奇", "蝴蝶酥"]
    seen: set[str] = set()
    ranked: list[str] = []
    for s in seeds:
        try:
            sug = baidu_suggest(s)
        except Exception as exc:  # noqa: BLE001 — 单种子失败不中断
            print(f"[proxy] 下拉失败 seed={s}: {exc}", flush=True)
            sug = []
        for kw in [s, *sug]:
            if kw and kw not in seen:
                seen.add(kw)
                ranked.append(kw)
        time.sleep(0.2)
    ranked = ranked[:limit]
    items: list[dict[str, Any]] = []
    n = max(1, len(ranked))
    for i, kw in enumerate(ranked):
        heat = round(95.0 - (i * 50.0 / n), 1)
        items.append(
            {
                "keyword": kw,
                "source_name": f"百度下拉代理（种子={seed}）",
                "collected_at": _today(),
                "collected_at_precise": _now_iso(),
                "heat_score": heat,
                "raw_metrics": {"suggest_rank": i + 1},
                "notes": (
                    "PROXY：非真实搜索热度，仅为下拉排序相对分；"
                    "请配置 AGENT_5118_API_KEY 后用 lookup/expand 拉取正式指数"
                ),
                "is_mock": False,
                "is_proxy": True,
                "evidence_grade": "C_proxy_suggest",
            }
        )
    return items


def build_output(
    items: list[dict[str, Any]],
    *,
    mode: str,
    seed: str | None,
    keywords: list[str] | None,
) -> dict[str, Any]:
    ranked = sorted(
        items,
        key=lambda row: (-float(row.get("heat_score") or 0), str(row.get("keyword") or "")),
    )
    paste = "\n".join(
        f"{row['keyword']}|{int(float(row['heat_score']))}"
        for row in ranked
        if row.get("keyword") is not None
    )
    evidence = []
    for row in ranked:
        evidence.append(
            {
                "keyword": row["keyword"],
                "source_name": row["source_name"],
                "collected_at": row["collected_at"],
                "heat_score": row["heat_score"],
                "notes": row.get("notes"),
                "is_mock": bool(row.get("is_mock")),
                "evidence_grade": row.get("evidence_grade") or "C_user_provided",
            }
        )
    return {
        "mode": mode,
        "seed": seed,
        "requested_keywords": keywords,
        "fetched_at": _now_iso(),
        "count": len(evidence),
        "disclaimer": (
            "热度为搜索引擎侧指数/检索量（或下拉代理分），不等于小红书官方热搜；"
            "导入 Agent 模块6 时勿表述为平台实时热搜榜。"
        ),
        "trending_keyword_evidence": evidence,
        "rows_with_raw_metrics": ranked,
        "paste_for_ui": paste,
    }


def write_output(payload: dict[str, Any], out: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        paste_path = out.with_suffix(".paste.txt")
        paste_path.write_text((payload.get("paste_for_ui") or "") + "\n", encoding="utf-8")
        print(f"[out] JSON  → {out}")
        print(f"[out] paste → {paste_path}")
    else:
        print(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fetch_keyword_heat",
        description="实时拉取关键词搜索热度（5118 / 下拉代理）",
    )
    parser.add_argument(
        "command",
        choices=("lookup", "expand", "proxy", "poll"),
        help="lookup=精确查热度；expand=种子扩长尾；proxy=无Key代理；poll=按taskid取结果",
    )
    parser.add_argument("--seed", default="香港伴手礼", help="expand/proxy 种子词")
    parser.add_argument("--keywords", default="", help="lookup 用，逗号/竖线分隔")
    parser.add_argument("--keywords-file", default="", help="lookup 用，每行一个词或 keyword|heat")
    parser.add_argument("--task-id", default="", help="poll 用的 5118 taskid")
    parser.add_argument("--api-key", default="", help="5118 API Key（默认读环境变量）")
    parser.add_argument("--limit", type=int, default=30, help="expand/proxy 最多保留条数")
    parser.add_argument("--page-index", type=int, default=1, help="expand 页码")
    parser.add_argument("--page-size", type=int, default=50, help="expand 每页条数≤100")
    parser.add_argument(
        "--sort-fields",
        type=int,
        default=4,
        help="expand 排序：4流量指数 5移动指数 7PC检索 8移动检索",
    )
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL)
    parser.add_argument("--poll-timeout", type=float, default=DEFAULT_POLL_TIMEOUT)
    parser.add_argument(
        "--out",
        default="",
        help="输出 JSON 路径（同时写 .paste.txt）",
    )
    parser.add_argument("--env-file", default=str(DEFAULT_ENV), help=".env 路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(Path(args.env_file))
    out = Path(args.out) if args.out else None

    if args.command == "proxy":
        items = fetch_proxy(args.seed, limit=max(1, args.limit))
        payload = build_output(items, mode="proxy", seed=args.seed, keywords=None)
        write_output(payload, out)
        return 0

    api_key = resolve_api_key(args.api_key or None)

    if args.command == "poll":
        if not args.task_id:
            raise SystemExit("poll 需要 --task-id")
        items = fetch_poll(args.task_id, api_key=api_key)
        payload = build_output(items, mode="lookup", seed=None, keywords=None)
        write_output(payload, out)
        return 0

    if args.command == "lookup":
        keywords = parse_keywords(args.keywords or None, args.keywords_file or None)
        items = fetch_lookup(
            keywords,
            api_key=api_key,
            poll_interval=args.poll_interval,
            poll_timeout=args.poll_timeout,
        )
        payload = build_output(items, mode="lookup", seed=None, keywords=keywords)
        write_output(payload, out)
        return 0

    if args.command == "expand":
        items = fetch_expand(
            args.seed,
            api_key=api_key,
            page_index=max(1, args.page_index),
            page_size=min(100, max(1, args.page_size)),
            sort_fields=args.sort_fields,
        )[: max(1, args.limit)]
        payload = build_output(items, mode="expand", seed=args.seed, keywords=None)
        write_output(payload, out)
        return 0

    raise SystemExit(f"未知命令: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
