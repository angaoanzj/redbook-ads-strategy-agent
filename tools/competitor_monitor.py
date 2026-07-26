"""竞品投放监控工具（加分项）：对比前后快照，输出预警与应对建议。

无历史快照时做 on-demand 基线扫描；有历史快照时输出增量预警。
不伪造实时爬虫结果。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from tools.registry import ToolSpec


class CompetitorMonitorArgs(BaseModel):
    brand_name: str = Field(min_length=1)
    current_accounts: list[dict[str, Any]] = Field(default_factory=list)
    current_ad_labeled_count: int = Field(default=0, ge=0)
    current_sample_note_count: int = Field(default=0, ge=0)
    previous_snapshot: dict[str, Any] | None = None


def _snapshot_from_current(args: CompetitorMonitorArgs) -> dict[str, Any]:
    accounts = []
    for row in args.current_accounts:
        if not isinstance(row, dict):
            continue
        accounts.append(
            {
                "account": row.get("account") or row.get("name") or row.get("url"),
                "interactions": row.get("interactions"),
                "ad_labeled": row.get("ad_labeled"),
                "format": row.get("format"),
            }
        )
    return {
        "brand_name": args.brand_name,
        "account_count": len(accounts),
        "ad_labeled_count": int(args.current_ad_labeled_count),
        "sample_note_count": int(args.current_sample_note_count),
        "accounts": accounts[:20],
    }


def _parse_interactions(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").upper()
        try:
            if text.endswith("W"):
                return float(text[:-1]) * 10000
            if text.endswith("K"):
                return float(text[:-1]) * 1000
            return float(text)
        except ValueError:
            return None
    return None


def _viral_accounts(accounts: list[dict[str, Any]], threshold: float = 5000) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for row in accounts:
        if not isinstance(row, dict):
            continue
        interactions = _parse_interactions(row.get("interactions"))
        if interactions is None or interactions < threshold:
            continue
        hits.append(
            {
                "account": row.get("account"),
                "interactions": interactions,
                "ad_labeled": row.get("ad_labeled"),
                "format": row.get("format"),
            }
        )
    hits.sort(key=lambda item: item["interactions"], reverse=True)
    return hits[:5]


def monitor_competitors(args: CompetitorMonitorArgs) -> dict[str, Any]:
    current = _snapshot_from_current(args)
    previous = args.previous_snapshot if isinstance(args.previous_snapshot, dict) else None
    alerts: list[dict[str, Any]] = []
    viral = _viral_accounts(list(current.get("accounts") or []))

    if previous is None:
        if current["ad_labeled_count"] >= 3:
            alerts.append(
                {
                    "severity": "high",
                    "type": "baseline_large_scale_ads",
                    "message": (
                        f"基线扫描发现 {current['ad_labeled_count']} 条带广告标识笔记，"
                        "疑似已开启较密集投放。"
                    ),
                    "response": (
                        "立即复核对方主搜词与素材卖点；本周提高防守词预算，"
                        "并用差异化真实体验内容做小预算对冲，禁止直接复刻封面。"
                    ),
                }
            )
        elif current["ad_labeled_count"] > 0:
            alerts.append(
                {
                    "severity": "medium",
                    "type": "baseline_ads_detected",
                    "message": (
                        f"基线扫描发现 {current['ad_labeled_count']} 条带广告标识笔记；"
                        "请人工打开原笔记核验投放时长与素材。"
                    ),
                    "response": "建立对标账号观察清单；差异化内容先做小预算测试，不直接复制封面。",
                }
            )
        if viral:
            top = viral[0]
            alerts.append(
                {
                    "severity": "high",
                    "type": "viral_note_detected",
                    "message": (
                        f"监测到疑似爆款样本：{top.get('account') or '对标账号'} "
                        f"互动约 {int(top['interactions']):,}；共 {len(viral)} 条高互动条目。"
                    ),
                    "response": (
                        "拆解其封面钩子、标题句式与评论痛点，转成自有 A/B 探测格；"
                        "24–48 小时内用同方向但差异化证据内容试投，避免硬跟热点。"
                    ),
                }
            )
        if current["account_count"] == 0:
            alerts.append(
                {
                    "severity": "low",
                    "type": "no_competitor_sample",
                    "message": "当前无可用竞品账号样本，监控仅建立空基线。",
                    "response": "补充 3–5 个对标账号或笔记链接后重新运行。",
                }
            )
        elif not alerts:
            alerts.append(
                {
                    "severity": "low",
                    "type": "baseline_ready",
                    "message": (
                        f"已建立竞品监控基线：{current['account_count']} 个对标条目，"
                        f"广告标识笔记 {current['ad_labeled_count']} 条。"
                    ),
                    "response": "下次分析将自动对比增量；发现爆款或投放加码时会发出 medium/high 预警。",
                }
            )
        status = "baseline"
    else:
        prev_ads = int(previous.get("ad_labeled_count") or 0)
        delta_ads = current["ad_labeled_count"] - prev_ads
        if delta_ads >= 3:
            alerts.append(
                {
                    "severity": "high",
                    "type": "ad_volume_spike",
                    "message": f"竞品带广告标识笔记较上次 +{delta_ads}，疑似开启大规模投放。",
                    "response": (
                        "启动应对包：①防守核心搜索词；②加速对比/真实体验素材上线；"
                        "③暂停低效信息流试投，把预算集中到已验证素材。"
                    ),
                }
            )
        elif delta_ads >= 2:
            alerts.append(
                {
                    "severity": "high",
                    "type": "ad_volume_spike",
                    "message": f"竞品带广告标识笔记较上次 +{delta_ads}，疑似加大投放。",
                    "response": "复核对方素材卖点；加速自有对比/真实体验素材上线，并提高搜索词防守预算。",
                }
            )
        elif delta_ads >= 1:
            alerts.append(
                {
                    "severity": "medium",
                    "type": "new_ad_note",
                    "message": "竞品新增至少 1 条带广告标识笔记。",
                    "response": "拆解其内容类型与评论画像，转化为自有定向测试包。",
                }
            )
        prev_viral = {
            row.get("account")
            for row in _viral_accounts(list(previous.get("accounts") or []))
            if row.get("account")
        }
        new_viral = [row for row in viral if row.get("account") not in prev_viral]
        if new_viral:
            names = "、".join(str(row.get("account")) for row in new_viral[:3])
            alerts.append(
                {
                    "severity": "high",
                    "type": "new_viral_note",
                    "message": f"竞品出现新的高互动/疑似爆款样本：{names}",
                    "response": (
                        "当日完成钩子拆解并生成 1–2 个差异化探测格；"
                        "若对方带广告标识，同步加码相关搜索词防守。"
                    ),
                }
            )
        prev_accounts = {
            (row.get("account") if isinstance(row, dict) else None)
            for row in (previous.get("accounts") or [])
        }
        new_accounts = [
            row.get("account")
            for row in current["accounts"]
            if row.get("account") and row.get("account") not in prev_accounts
        ]
        if new_accounts:
            alerts.append(
                {
                    "severity": "medium",
                    "type": "new_competitor_account",
                    "message": f"新出现对标账号：{'、'.join(str(a) for a in new_accounts[:3])}",
                    "response": "纳入观察清单，采样近 30 天爆款后再决定是否跟进。",
                }
            )
        if not alerts:
            alerts.append(
                {
                    "severity": "low",
                    "type": "stable",
                    "message": "相对上次快照，竞品投放信号无明显突变。",
                    "response": "维持既定节奏，按周复扫即可。",
                }
            )
        status = "diff"

    return {
        "status": status,
        "snapshot": current,
        "viral_candidates": viral,
        "alerts": alerts,
        "alert_count": len(alerts),
        "playbook": [
            "爆款预警：拆钩子→差异化复刻→小流量 A/B，不直接抄封面",
            "大规模投放预警：先守搜索词，再推已验证素材，砍掉无效试投",
            "所有广告标识与投放时长以人工打开原笔记核验为准",
        ],
        "evidence_boundary": (
            "监控基于本次导入/知识库快照对比，非实时爬虫；"
            "广告标识与投放时长须人工打开原笔记核验。"
        ),
    }


COMPETITOR_MONITOR_TOOLS = [
    ToolSpec(
        name="monitor_competitor_ads",
        description="对比竞品投放快照并生成预警与应对策略",
        args_model=CompetitorMonitorArgs,
        fn=monitor_competitors,
    )
]
