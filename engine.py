from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from competitor_input import normalize_competitor_inputs
from competitor_insight_analysis import assess_content_gaps, format_content_gap_reason
from mock_agents import run_mock_subagents
from mock_scenarios import (
    MOCK_DATA_TYPE,
    MOCK_WARNING,
    build_mock_market_scenarios,
    build_mock_platform_market,
    evidence_meta,
    metric_or_mock,
    normalize_mock_seed,
)
from models import CampaignRequest, CategoryNoteEvidence, EvidenceGap, StrategyResponse
from module_agents._evidence_aggregation import (
    aggregate_peak_display_slots,
    extract_hour,
    parse_published_at,
    to_beijing,
)
from report_view import build_report_view, render_report_markdown
from bonus_modules import build_bonus_modules

# 演示用参考汇率：仅用于把商品价统一到 CNY 后再算 ROI；非实时牌价。
FX_TO_CNY = {
    "CNY": 1.0,
    "RMB": 1.0,
    "HKD": 0.92,
    "TWD": 0.23,
    "USD": 7.25,
    "EUR": 7.85,
}
MIN_NOTES_FOR_PEAK_HOUR = 3


GOAL_LABELS = {
    "awareness": "品牌曝光",
    "engagement": "点赞收藏",
    "search_growth": "搜索增长",
    "conversion": "商品成交",
    "leads": "客资收集",
    "live_traffic": "直播引流",
}


def _load_env() -> None:
    """加载本项目 .env / course.env（不依赖上级课程仓）。"""
    from model_config import load_dotenv_files

    load_dotenv_files()


def _round_money(value: float) -> int:
    return int(round(value))


def _budget_ratios(goal: str) -> tuple[float, float]:
    """自然:聚光 默认档，与 tools.budget.DEFAULT_ORGANIC_RATIO 对齐。"""
    from tools.budget import goal_split_guide

    guide = goal_split_guide(goal)
    return float(guide["organic_ratio"]), float(guide["paid_ratio"])


def _note_interactions(note: Any) -> int:
    return sum((
        note.likes or 0,
        note.favorites or 0,
        note.comments or 0,
        note.shares or 0,
    ))


def _cluster_evidence_themes(req: CampaignRequest) -> list[dict[str, Any]]:
    """证据召回 → 按标签/关键词聚类，供选题与词库共用。"""
    notes = req.category_note_evidence
    if not notes:
        return []
    theme_notes: dict[str, list[Any]] = defaultdict(list)
    theme_interactions: Counter[str] = Counter()
    for note in notes:
        themes = [tag for tag in note.tags if tag][:6]
        if note.search_keyword:
            themes.append(note.search_keyword)
        if not themes:
            themes = ["未标注主题"]
        for theme in themes:
            theme_notes[theme].append(note)
            theme_interactions[theme] += _note_interactions(note)
    clusters: list[dict[str, Any]] = []
    for theme, count in theme_interactions.most_common(12):
        sample = sorted(
            theme_notes[theme],
            key=_note_interactions,
            reverse=True,
        )[:3]
        clusters.append({
            "theme": theme,
            "note_count": len(theme_notes[theme]),
            "total_interactions": count,
            "avg_interactions": round(count / max(1, len(theme_notes[theme])), 1),
            "evidence_titles": [item.title for item in sample],
            "evidence_note_ids": [item.note_id for item in sample],
        })
    return clusters


_PAID_OBJECTIVE_BY_GOAL = {
    "awareness": "种草",
    "engagement": "种草",
    "search_growth": "种草",
    "conversion": "成交",
    "leads": "客资",
    "live_traffic": "直播引流",
}


def _paid_objective(goal: str) -> str:
    return _PAID_OBJECTIVE_BY_GOAL.get(goal, "种草")


def _persona_hooks(req: CampaignRequest) -> dict[str, list[str]]:
    pack = req.targeting_knowledge_pack if isinstance(req.targeting_knowledge_pack, dict) else {}
    persona = pack.get("persona") if isinstance(pack.get("persona"), dict) else {}
    demographic = [str(x) for x in (persona.get("demographic") or []) if str(x).strip()]
    behavioral = [str(x) for x in (persona.get("behavioral") or []) if str(x).strip()]
    psychological = [str(x) for x in (persona.get("psychological") or []) if str(x).strip()]
    if req.initial_audience and req.initial_audience not in demographic:
        demographic = [req.initial_audience, *demographic]
    if not demographic:
        demographic = [req.initial_audience or "目标用户"]
    if not behavioral:
        behavioral = [
            f"会搜索「{req.category}」并收藏对比",
            "偏好开箱/测评/清单类内容",
            "决策前常问价格、履约与口碑",
        ]
    if not psychological:
        psychological = [
            "怕踩雷、要确定性",
            "重视可感知证据（口感/质感/反馈）",
            *req.selling_points[:2],
        ]
    return {
        "demographic": demographic[:6],
        "behavioral": behavioral[:6],
        "psychological": psychological[:6],
    }


def _topic_title(
    *,
    angle: str,
    product: str,
    category: str,
    point: str,
    audience: str,
    psycho: str,
    theme: str | None,
    variant: int,
) -> str:
    short_aud = audience[:18]
    short_psycho = psycho[:16]
    if angle == "场景痛点型":
        templates = [
            f"{short_aud}怎么选{category}？先看「{point}」",
            f"给{short_aud}的{product}场景清单｜关键看「{point}」",
            f"别再盲目跟风｜{short_aud}真实会用到的{category}",
            f"{theme or category}场景拆解｜{product}为什么更贴「{point}」",
            f"从痛点出发：{short_psycho}时，我会选{product}",
        ]
    elif angle == "对比决策型":
        templates = [
            f"{category}避坑对比｜{product}在「{point}」上差在哪",
            f"同样预算怎么选？{product} vs 常见选项（看{point}）",
            f"{short_aud}最容易忽略的3个点｜第2个和「{point}」有关",
            f"别只看包装｜{category}决策清单（含{point}）",
            f"{theme or '热门主题'}对照表｜{product}适不适合你",
        ]
    else:
        templates = [
            f"实测{product}：关于「{point}」我留下的结论",
            f"{short_aud}体验后还愿意复购吗？关键在「{point}」",
            f"开箱到收尾｜{product}有没有兑现「{point}」",
            f"连续体验记录：{point}是否经得起追问",
            f"{theme or product}真实反馈｜围绕「{point}」的证据链",
        ]
    return templates[variant % len(templates)]


def _topic_cover(
    *,
    angle: str,
    product: str,
    point: str,
    audience: str,
    theme: str | None,
    variant: int,
) -> str:
    if angle == "场景痛点型":
        options = [
            f"场景定妆照（{audience[:12]}）+ 6字利益点「{point}」",
            f"痛点前后对比拼图 + 产品入镜，标题区写「{point}」",
            f"清单封面：3个场景图标 + {product}主图",
            f"旅行/送礼氛围图 + 角标「{point}」",
            f"主题「{theme or product}」主视觉，底部一行人群标签",
        ]
    elif angle == "对比决策型":
        options = [
            f"左右对比板：常见选项 vs {product}，中心标注「{point}」",
            f"表格封面（3行决策维度）+ 产品特写",
            f"红叉/绿勾信息图，突出「{point}」差异",
            f"手持对比开箱第一帧 + 字幕「别只看…」",
            f"决策清单封面：编号1-3，第2项指向「{point}」",
        ]
    else:
        options = [
            f"开箱第一视角 + 特写证明「{point}」",
            f"前后测/细节微距（纹理/层次/包装）+ 结论字幕",
            f"真人出镜反馈卡：一句关于「{point}」的结论",
            f"时间轴封面：Day1→复购决策，落到「{point}」",
            f"证据拼贴：成分/工艺/口感三格，主卖点「{point}」",
        ]
    return options[variant % len(options)]


def _topic_outline(
    *,
    angle: str,
    product: str,
    category: str,
    point: str,
    secondary_point: str,
    audience: str,
    behavioral: str,
    psycho: str,
    theme: str | None,
    evidence_title: str | None,
    price_band: str,
    variant: int,
    goal_label: str = "成交",
) -> list[str]:
    theme_bit = theme or category
    evidence_bit = (evidence_title or theme_bit)[:28]
    if angle == "场景痛点型":
        pools = [
            [
                f"开场点名人群「{audience}」与场景痛点：{psycho}",
                f"还原他们常见行为：{behavioral}",
                f"用「{point}」解释{product}为何匹配该场景，辅以「{secondary_point}」",
                f"给出可执行清单（何时买/买给谁/怎么带），并做合规披露",
            ],
            [
                f"以「{theme_bit}」热搜场景切入，先共情{audience}",
                f"拆3个高频失误（跟风/只看包装/忽略履约）",
                f"把卖点「{point}」映射到具体使用瞬间",
                f"收尾给场景决策口令 + 价格带参考 {price_band}",
            ],
            [
                f"先抛问题：{audience}最怕什么？（对应{psycho}）",
                f"用短案例展示错误选择成本",
                f"展示{product}在「{point}」上的可感知证据",
                f"行动建议：按场景选规格/组合，避免绝对化表述",
            ],
            [
                f"封面承诺解决一个明确痛点，正文从{behavioral}写起",
                f"中段只讲一个核心卖点「{point}」，避免卖点堆砌",
                f"补充次卖点「{secondary_point}」作为加分项而非口号",
                f"评论引导：让同人群补充自己的场景，沉淀社群证据",
            ],
            [
                f"场景蒙太奇开场（2-3个切片）对准{audience}",
                f"每个切片对应一个决策疑问，最后汇总到「{point}」",
                f"产品出场只回答疑问，不讲无关参数",
                f"结束页：适用/不适用人群边界 + 合规提示",
            ],
        ]
    elif angle == "对比决策型":
        pools = [
            [
                f"列出{category}购买时最容易忽略的3件事（人群：{audience}）",
                f"第1件事对齐心理诉求「{psycho}」，第2件事落到「{point}」",
                f"用对照表呈现{product}与常见选项差异，引用样本主题「{theme_bit}」",
                f"给决策阈值：什么情况下选它/不选它，并标注价格带 {price_band}",
            ],
            [
                f"开场声明：不是踩一捧一，只帮{audience}做可比维度",
                f"维度A口碑可信度，维度B「{point}」，维度C履约便利",
                f"每维给可核验观察点（参考：{evidence_bit}）",
                f"结论写成选择树，避免「全网第一」类绝对化",
            ],
            [
                f"以搜索词/热门主题「{theme_bit}」引入对比需求",
                f"先写用户真实行为「{behavioral}」，再进入参数对比",
                f"把「{point}」写成可感知差异，而不是形容词",
                f"附购买检查清单 + 「{secondary_point}」作为加分项",
            ],
            [
                f"对比对象匿名化（选项A/B/C），降低引战",
                f"只比与{audience}相关的决策点，不比无关噱头",
                f"用「{point}」解释为何影响复购/送礼反馈",
                f"收尾：按预算 {price_band} 给出3档选择建议",
            ],
            [
                f"先问：你更在意{psycho}还是便利？",
                f"按答案分支展示不同对比重点",
                f"分支汇合到卖点「{point}」与产品证据",
                f"行动：收藏对比表，下次到店/下单直接套用",
            ],
        ]
    else:
        pools = [
            [
                f"体验动机：作为{audience}，我要验证「{point}」是否成立",
                f"过程记录：外观/开箱/关键感受，对应行为「{behavioral}」",
                f"结论只保留可复述证据；辅证卖点「{secondary_point}」",
                f"适用边界 + 价格带 {price_band} + 合规披露",
            ],
            [
                f"设定验证问题：{product}能不能满足「{psycho}」",
                f"用前后对比或细节特写证明「{point}」",
                f"引用/对齐热门主题「{theme_bit}」（参考：{evidence_bit}）",
                f"给出复购/送礼建议，不写无法证明的功效承诺",
            ],
            [
                f"开箱第一分钟只拍证据，不先下结论",
                f"中段集中回答「{point}」，删除空泛形容词",
                f"用真实使用瞬间连接{audience}的决策顾虑",
                f"结尾三句话：适合谁、不适合谁、下一步怎么买",
            ],
            [
                f"连续体验时间线（到货→首次→分享反馈）",
                f"每一段只验证一个点，主线是「{point}」",
                f"把「{secondary_point}」放在次要证据位",
                f"引导同人群在评论区补充反例，增强可信度",
            ],
            [
                f"先展示失败预期（怕踩雷），再进入实测",
                f"实测指标对齐「{point}」与价格带 {price_band}",
                f"对照样本主题「{theme_bit}」说明同异",
                f"行动建议：若目标是{goal_label}，优先把此证据型笔记纳入投流素材池",
            ],
        ]
    return pools[variant % len(pools)]


def _content_topics(req: CampaignRequest) -> dict[str, Any]:
    clusters = _cluster_evidence_themes(req)
    hooks = _persona_hooks(req)
    points = [p for p in req.selling_points if str(p).strip()] or [req.product_name]
    price_band = f"{req.currency} {req.price_min:g}–{req.price_max:g}"
    angle_cycle = [
        ("场景痛点型", "organic", "种草"),
        ("对比决策型", "balanced", "种草"),
        ("体验证据型", "paid", _paid_objective(req.goal)),
    ]
    topics: list[dict[str, Any]] = []

    # 15条覆盖：卖点轮转 × 方向轮转 × 画像钩子轮转，保证大纲/标题不雷同
    for i in range(15):
        angle, bias, default_obj = angle_cycle[i % len(angle_cycle)]
        point = points[i % len(points)]
        secondary = points[(i + 1) % len(points)]
        audience = hooks["demographic"][i % len(hooks["demographic"])]
        behavioral = hooks["behavioral"][i % len(hooks["behavioral"])]
        psycho = hooks["psychological"][i % len(hooks["psychological"])]
        variant = i // len(angle_cycle)  # 0,1,2,3,4 across five rounds

        if clusters:
            cluster = clusters[i % len(clusters)]
            theme = cluster["theme"]
            evidence_title = cluster["evidence_titles"][0] if cluster["evidence_titles"] else theme
            organic = min(10, 6 + min(3, cluster["note_count"] // 2) + (1 if bias == "organic" else 0))
            paid = min(10, 5 + min(3, int(cluster["avg_interactions"] // 500)) + (1 if bias == "paid" else 0))
            # 卖点被明确点名的选题，投流潜力略加权
            if point in (req.selling_points or []) and bias == "paid":
                paid = min(10, paid + 1)
            suitable = paid >= 7
            title = _topic_title(
                angle=angle,
                product=req.product_name,
                category=req.category,
                point=point,
                audience=audience,
                psycho=psycho,
                theme=theme,
                variant=variant + i,
            )
            cover = _topic_cover(
                angle=angle,
                product=req.product_name,
                point=point,
                audience=audience,
                theme=theme,
                variant=variant + i,
            )
            outline = _topic_outline(
                angle=angle,
                product=req.product_name,
                category=req.category,
                point=point,
                secondary_point=secondary,
                audience=audience,
                behavioral=behavioral,
                psycho=psycho,
                theme=theme,
                evidence_title=evidence_title,
                price_band=price_band,
                variant=variant + i,
                goal_label=GOAL_LABELS[req.goal],
            )
            topics.append({
                "id": i + 1,
                "pipeline": "卖点×画像×证据主题交叉生成",
                "direction": angle,
                "theme_cluster": theme,
                "persona_hook": {
                    "demographic": audience,
                    "behavioral": behavioral,
                    "psychological": psycho,
                },
                "selling_point_focus": point,
                "evidence_note_count": cluster["note_count"],
                "evidence_titles": cluster["evidence_titles"][:2],
                "title_template": title,
                "cover": cover,
                "cover_suggestion": cover,
                "outline": outline,
                "organic_potential": organic,
                "paid_conversion_potential": paid,
                "suitable_for_spotlight": suitable,
                "suitable_for_paid": suitable,
                "promotion_goal": GOAL_LABELS[req.goal],
                "paid_objective": default_obj if suitable else "种草",
            })
        else:
            title = _topic_title(
                angle=angle,
                product=req.product_name,
                category=req.category,
                point=point,
                audience=audience,
                psycho=psycho,
                theme=None,
                variant=variant + i,
            )
            cover = _topic_cover(
                angle=angle,
                product=req.product_name,
                point=point,
                audience=audience,
                theme=None,
                variant=variant + i,
            )
            outline = _topic_outline(
                angle=angle,
                product=req.product_name,
                category=req.category,
                point=point,
                secondary_point=secondary,
                audience=audience,
                behavioral=behavioral,
                psycho=psycho,
                theme=None,
                evidence_title=None,
                price_band=price_band,
                variant=variant + i,
                goal_label=GOAL_LABELS[req.goal],
            )
            topics.append({
                "id": i + 1,
                "pipeline": "卖点×画像交叉生成（缺笔记证据，评分待补）",
                "direction": angle,
                "theme_cluster": None,
                "persona_hook": {
                    "demographic": audience,
                    "behavioral": behavioral,
                    "psychological": psycho,
                },
                "selling_point_focus": point,
                "evidence_note_count": 0,
                "evidence_titles": [],
                "title_template": title,
                "cover": cover,
                "cover_suggestion": cover,
                "outline": outline,
                "organic_potential": None,
                "paid_conversion_potential": None,
                "suitable_for_spotlight": False,
                "suitable_for_paid": False,
                "promotion_goal": GOAL_LABELS[req.goal],
                "paid_objective": default_obj,
                "data_status": "待导入品类笔记后再评分；大纲已按卖点与画像展开，可先作创作提纲",
            })

    if clusters:
        return {
            "status": "基于卖点×用户画像×笔记主题交叉生成",
            "cluster_count": len(clusters),
            "clusters_used": clusters[:8],
            "topics": topics,
        }
    return {
        "status": "证据不足：已按卖点与画像生成差异化提纲，评分待笔记证据补齐",
        "cluster_count": 0,
        "clusters_used": [],
        "topics": topics,
    }


def _build_module2_audience(req: CampaignRequest, topic_pack: dict[str, Any]) -> dict[str, Any]:
    pack = req.targeting_knowledge_pack if isinstance(req.targeting_knowledge_pack, dict) else {}
    kb_persona = pack.get("persona") if isinstance(pack.get("persona"), dict) else {}
    kb_tags = pack.get("targeting_tags") if isinstance(pack.get("targeting_tags"), dict) else {}

    demographic = [str(x) for x in (kb_persona.get("demographic") or []) if str(x).strip()]
    behavioral = [str(x) for x in (kb_persona.get("behavioral") or []) if str(x).strip()]
    psychological = [str(x) for x in (kb_persona.get("psychological") or []) if str(x).strip()]

    if req.initial_audience and req.initial_audience not in demographic:
        demographic = [req.initial_audience, *demographic][:6]
    if not demographic:
        demographic = [req.initial_audience or "待补充目标人群"]
    if not behavioral:
        behavioral = [
            f"主动搜索{req.category}",
            "收藏对比型内容",
            "受真实体验与口碑影响",
        ]
    if not psychological:
        psychological = [
            "重视可信证据",
            "关注性价比与适用场景",
            *req.selling_points[:2],
        ]

    interest_tags = [str(x) for x in (kb_tags.get("interest_tags") or []) if str(x).strip()]
    behavior_tags = [str(x) for x in (kb_tags.get("behavior_tags") or []) if str(x).strip()]
    crowd_packages = [str(x) for x in (kb_tags.get("crowd_packages") or []) if str(x).strip()]
    if not interest_tags:
        interest_tags = [
            f"关键词兴趣：{req.category}",
            f"关键词兴趣：{req.product_name}",
            *[f"关键词兴趣：{point}" for point in req.selling_points[:3]],
        ]
    if not behavior_tags:
        behavior_tags = [
            f"近7/15/30天关键词行为：{req.category}",
            "近30天阅读过测评/开箱类内容",
        ]
    if not crowd_packages:
        crowd_packages = [
            "平台精选-行业人群（按品类后台检索）",
            "自定义-店铺/落地页访客包",
            "自定义-历史转化 Lookalike",
        ]

    flat_tags = list(dict.fromkeys([*interest_tags, *behavior_tags, *crowd_packages]))
    price_band = f"{req.currency} {req.price_min:g}–{req.price_max:g}"
    has_evidence = bool(topic_pack.get("cluster_count"))
    demo0 = demographic[0] if demographic else req.initial_audience
    behav0 = behavioral[0] if behavioral else f"搜索{req.category}"
    psycho0 = psychological[0] if psychological else "怕踩雷"
    points_text = "、".join(req.selling_points[:4])
    content_directions = [
        {
            "name": "场景痛点",
            "direction": "场景痛点",
            "organic_score": 9 if has_evidence else 8,
            "paid_score": 7 if has_evidence else 6,
            "rationale": (
                f"服务「{demo0}」：从其行为「{behav0}」与诉求「{psycho0}」切入场景，"
                f"自然内容先验证痛点共鸣，再小预算种草。"
            ),
        },
        {
            "name": "产品证据",
            "direction": "产品证据",
            "organic_score": 7 if has_evidence else 6,
            "paid_score": 9 if has_evidence else 7,
            "rationale": (
                f"把卖点「{points_text}」做成可感知证据链，定价带 {price_band}；"
                f"更适合转化/复购向投流素材。"
            ),
        },
        {
            "name": "对比决策",
            "direction": "对比决策",
            "organic_score": 8 if has_evidence else 7,
            "paid_score": 8 if has_evidence else 7,
            "rationale": (
                f"针对「{psycho0}」做{req.category}可比维度拆解，降低踩雷成本；"
                f"适合搜索承接与信息流种草双轨。"
            ),
        },
    ]

    return {
        "persona": {
            "demographic": demographic,
            "behavioral": behavioral,
            "psychological": psychological,
            "psychographic": psychological,  # 兼容旧字段名
            "price_band": price_band,
            "targeting_tags": {
                "interest_tags": interest_tags,
                "behavior_tags": behavior_tags,
                "crowd_packages": crowd_packages,
            },
            "targeting_tags_to_validate": flat_tags,
            "tag_status": "标签需在聚光后台核对可用性；知识库输出为候选，不是账户已确认可投标签",
        },
        "content_directions": content_directions,
        "topic_pipeline": topic_pack["status"],
        "theme_clusters": topic_pack["clusters_used"],
        "topics": topic_pack["topics"],
        "material_screening": {
            "principle": "先用自然笔记表现筛选，再小预算投流验证；阈值需用品牌历史中位数校准",
            "observation_hours": 24,
            "ctr_threshold": 0.10,
            "engagement_threshold": 0.07,
            "ctr_percent": 10,
            "engagement_rate_percent": 7,
            "rule_text": "发布24小时内 CTR>10% 且互动率>7% 的自然笔记，优先进入聚光素材池",
            "warning": "阈值来自作业示例，不是平台通用事实",
        },
        "paid_material_gate": {
            "principle": "先用自然数据筛选，再小预算测试；阈值需用品牌历史中位数校准",
            "prototype_thresholds": {
                "observation_hours": 24,
                "ctr_percent": 10,
                "engagement_rate_percent": 7,
            },
            "warning": "阈值来自作业示例，不是平台通用事实",
        },
        "knowledge_targeting": {
            "status": pack.get("status") or "not_loaded",
            "playbook_id": pack.get("playbook_id"),
            "playbook_title": pack.get("playbook_title"),
            "matched_playbooks": pack.get("matched_playbooks") or [],
            "evidence_grade": pack.get("evidence_grade"),
            "warning": pack.get("warning")
            or "候选标签须在聚光后台核对可用性。",
            "backend_checklist": pack.get("backend_checklist") or [],
            "platform_taxonomy": pack.get("platform_taxonomy") or {},
            "targeting_tags": {
                "interest_tags": interest_tags,
                "behavior_tags": behavior_tags,
                "crowd_packages": crowd_packages,
            },
            "brief": req.targeting_knowledge_brief,
        },
    }


def _normalize_tier_keyword(raw: Any) -> str | None:
    text = str(raw or "").strip().lstrip("#＃").strip()
    if not (2 <= len(text) <= 24):
        return None
    return text


def _mine_kb_keyword_pool(req: CampaignRequest) -> list[dict[str, Any]]:
    """Pull keyword candidates from knowledge-base notes already on the request."""
    from knowledge_base import KnowledgeBase

    return KnowledgeBase.aggregate_keyword_stats(
        req.category_note_evidence or [],
        limit=40,
    )


def _keyword_related_to_brand(keyword: str, req: CampaignRequest) -> bool:
    blob = keyword.casefold()
    seeds = [
        req.category,
        req.product_name,
        req.brand_name,
        *list(req.selling_points or [])[:4],
    ]
    for seed in seeds:
        token = (seed or "").strip().casefold()
        if len(token) >= 2 and (token in blob or blob in token):
            return True
    return False


def _build_keyword_tier_items(req: CampaignRequest) -> tuple[list[Any], list[str], str]:
    """Mine KB terms → exclusive core/long_tail/blue_ocean → KeywordItem list.

    Dedup contract matches tools.keywords.KeywordTiersArgs (casefold global unique).
    """
    from tools.keywords import (
        MIN_BLUE_OCEAN,
        MIN_CORE,
        MIN_LONG_TAIL,
        KeywordItem,
    )

    pool = _mine_kb_keyword_pool(req)
    evidence_themes = [row["keyword"] for row in pool[:12]]
    evidence_keys = {row["keyword"].casefold() for row in pool}
    seen: set[str] = set()
    items: list[Any] = []

    def _take(
        keyword: str,
        *,
        level: str,
        intent: str,
        lane: str,
        from_evidence: bool,
    ) -> bool:
        normalized = _normalize_tier_keyword(keyword)
        if not normalized:
            return False
        key = normalized.casefold()
        if key in seen:
            return False
        seen.add(key)
        items.append(
            KeywordItem(
                keyword=normalized,
                level=level,  # type: ignore[arg-type]
                intent=intent,  # type: ignore[arg-type]
                lane=lane,  # type: ignore[arg-type]
                from_evidence=from_evidence,
            )
        )
        return True

    def _count(level: str) -> int:
        return sum(1 for item in items if item.level == level)

    # 1) 核心词：品牌主词优先，再取知识库高频且与品牌相关的词
    for seed in (req.category, req.product_name, *(req.selling_points or [])[:2]):
        text = _normalize_tier_keyword(seed)
        if not text:
            continue
        _take(
            text,
            level="core",
            intent="high",
            lane="search",
            from_evidence=text.casefold() in evidence_keys,
        )
    for row in sorted(
        pool,
        key=lambda r: (-r["note_count"], -r["total_interactions"], r["keyword"]),
    ):
        if _count("core") >= 4:
            break
        kw = row["keyword"]
        if row["note_count"] >= 2 and _keyword_related_to_brand(kw, req):
            _take(kw, level="core", intent="high", lane="search", from_evidence=True)

    decision_markers = ("推荐", "怎么选", "测评", "对比", "避雷", "清单", "攻略", "真实", "值得")
    # 2) 长尾词：知识库中更具体/决策向的词，且未进核心
    for row in sorted(
        pool,
        key=lambda r: (-r["total_interactions"], -r["note_count"], r["keyword"]),
    ):
        if _count("long_tail") >= 8:
            break
        kw = row["keyword"]
        key = kw.casefold()
        if key in seen:
            continue
        specific = (
            any(marker in kw for marker in decision_markers)
            or len(kw) >= 4
            or row["note_count"] >= 2
        )
        if not specific:
            continue
        intent = "high" if any(m in kw for m in ("推荐", "怎么选", "真实")) else "mid"
        _take(kw, level="long_tail", intent=intent, lane="search", from_evidence=True)

    # 3) 蓝海待验证：知识库中供给偏少（笔记覆盖低）且未被前两层占用
    sparse = sorted(
        (row for row in pool if row["keyword"].casefold() not in seen),
        key=lambda r: (r["note_count"], -r["total_interactions"], r["keyword"]),
    )
    for row in sparse:
        if _count("blue_ocean") >= 5:
            break
        # 跳过已被品类/产品/卖点字面覆盖的主词，留给核心/长尾
        if row["keyword"] in {req.category, req.product_name, *(req.selling_points or [])}:
            continue
        _take(
            row["keyword"],
            level="blue_ocean",
            intent="low",
            lane="search",
            from_evidence=True,
        )

    # 4) 数量下限补齐：仅用品牌种子衍生，且继续遵守全局去重
    audience_bit = ""
    if req.initial_audience:
        audience_bit = re.split(r"[、，,/｜|]", req.initial_audience)[0].strip()[:12]
    selling0 = (req.selling_points or ["精选"])[0]
    pads = [
        (req.category, "core", "high"),
        (req.product_name, "core", "high"),
        (f"{req.category}推荐", "long_tail", "high"),
        (f"{req.category}怎么选", "long_tail", "mid"),
        (f"{req.product_name}真实体验", "long_tail", "high"),
        (f"{audience_bit}适合的{req.category}" if audience_bit else f"{req.category}送礼", "long_tail", "mid"),
        (f"{audience_bit}{req.category}" if audience_bit else f"小众{req.category}", "blue_ocean", "low"),
        (f"{req.category}{selling0}", "blue_ocean", "low"),
    ]
    for keyword, level, intent in pads:
        if level == "core" and _count("core") >= MIN_CORE:
            continue
        if level == "long_tail" and _count("long_tail") >= MIN_LONG_TAIL:
            continue
        if level == "blue_ocean" and _count("blue_ocean") >= MIN_BLUE_OCEAN:
            continue
        text = _normalize_tier_keyword(keyword)
        if not text:
            continue
        # 截断超长衍生词
        if len(text) > 24:
            text = text[:24]
        _take(
            text,
            level=level,
            intent=intent,
            lane="search",
            from_evidence=text.casefold() in evidence_keys,
        )

    # build_keyword_tiers 要求总数 ≥8：若仍不足，用未占用的 pool 词补长尾
    for row in pool:
        if len(items) >= 8:
            break
        _take(
            row["keyword"],
            level="long_tail",
            intent="mid",
            lane="search",
            from_evidence=True,
        )

    status = (
        "基于知识库笔记标签/搜索词分层，已按 build_keyword_tiers 全局去重；"
        "蓝海仍需搜索量/竞争度验证后放量"
        if pool
        else "知识库笔记不足：仅输出待验证种子词，禁止当作热搜或蓝海结论"
    )
    return items, evidence_themes, status


def _keyword_library(req: CampaignRequest) -> dict[str, Any]:
    """知识库抽词 + tools.keywords.build_keyword_tiers 去重/下限校验。"""
    from pydantic import ValidationError

    from tools.keywords import KeywordTiersArgs, LevelBudgetSplit, build_keyword_tiers

    items, evidence_themes, status = _build_keyword_tier_items(req)
    try:
        tool_result = build_keyword_tiers(
            KeywordTiersArgs(
                keywords=items,
                level_budget_split=LevelBudgetSplit(
                    core=0.30,
                    long_tail=0.50,
                    blue_ocean=0.20,
                ),
                baseline_cpc_cny=None,
                baseline_source=None,
                rationale=(
                    "核心承接品牌/品类主词，长尾承接知识库高频决策词，"
                    "蓝海仅保留供给偏少的待验证候选；跨层全局去重。"
                ),
            )
        )
    except (ValidationError, ValueError) as exc:
        # 极端不足时降级：保持互斥列表，不编造出价
        core = [i.keyword for i in items if i.level == "core"]
        long_tail = [i.keyword for i in items if i.level == "long_tail"]
        blue = [i.keyword for i in items if i.level == "blue_ocean"]
        return {
            "pipeline": "知识库抽词→build_keyword_tiers（校验未通过，已保留互斥分层）",
            "status": f"{status}；分层校验提示：{exc}",
            "core": core,
            "long_tail": long_tail,
            "blue_ocean_candidates": blue,
            "evidence_themes": evidence_themes,
            "level_budget_split": {"core": 0.30, "long_tail": 0.50, "blue_ocean": 0.20},
        }

    tiers = tool_result.get("keyword_tiers") or {}
    return {
        "pipeline": "知识库抽词→build_keyword_tiers去重分层",
        "status": status,
        "core": [row["keyword"] for row in tiers.get("core") or []],
        "long_tail": [row["keyword"] for row in tiers.get("long_tail") or []],
        "blue_ocean_candidates": [row["keyword"] for row in tiers.get("blue_ocean") or []],
        "evidence_themes": evidence_themes,
        "level_budget_split": tool_result.get("level_budget_split")
        or {"core": 0.30, "long_tail": 0.50, "blue_ocean": 0.20},
        "evidence_coverage": tool_result.get("evidence_coverage"),
        "tier_counts": tool_result.get("counts"),
    }


def _evidence_gaps(
    req: CampaignRequest,
    *,
    mock_injected: dict[str, Any] | None = None,
) -> list[EvidenceGap]:
    gaps: list[EvidenceGap] = []
    mock_fields = {
        item["field"] for item in (mock_injected or {}).get("fields", [])
    }
    notes_are_mock = (
        "category_note_evidence" in mock_fields
        or (req.category_note_evidence and all(n.is_mock for n in req.category_note_evidence))
    )
    if not req.competitor_evidence and not req.category_note_evidence:
        gaps.append(EvidenceGap(
            field="竞品笔记表现与广告标识",
            impact="无法可靠判断竞品爆款共性、投流笔记和投放时长",
            recommended_source="小红书官方公开页面人工核验，或合规第三方导出",
        ))
    elif notes_are_mock and not req.competitor_evidence:
        gaps.append(EvidenceGap(
            field="竞品笔记表现与广告标识",
            impact="当前品类笔记为 Mock 演示样本；共性/空白仅供演示，需替换为真实公开笔记",
            recommended_source="小红书官方公开页面人工核验，或合规第三方导出",
        ))

    has_real_benchmark = any(not item.is_mock for item in req.benchmark_evidence)
    if not req.benchmark_evidence:
        gaps.append(EvidenceGap(
            field="CPC/CPM/CTR/CVR行业基准",
            impact="不能给出可信的出价和ROI区间，只能给测试带宽与止损公式",
            recommended_source="品牌聚光账户历史报表或官方行业报告",
        ))
    elif not has_real_benchmark or "benchmark_evidence" in mock_fields:
        gaps.append(EvidenceGap(
            field="CPC/CPM/CTR/CVR行业基准",
            impact="部分或全部指标为 Mock 演示情景，出价/ROI 仅供敏感性分析，需投手用账户数据替换",
            recommended_source="品牌聚光账户历史报表或官方行业报告",
        ))

    real_creators = [item for item in req.creator_evidence if not item.is_mock]
    if not req.creator_evidence:
        gaps.append(EvidenceGap(
            field="达人候选、报价与历史效果",
            impact="不输出推荐达人名单；仅保留分层预算槽位待导入 CSV/蒲公英",
            recommended_source="蒲公英/品牌授权达人库/合规第三方工具导出的 CSV",
        ))
    elif not real_creators:
        gaps.append(EvidenceGap(
            field="达人候选、报价与历史效果",
            impact="当前仅为 Mock 演示候选，不是真实推荐名单；禁止据此下单",
            recommended_source="蒲公英/品牌授权达人库/合规第三方工具导出的 CSV",
        ))

    real_trending = [item for item in req.trending_keyword_evidence if not item.is_mock]
    if not req.trending_keyword_evidence:
        gaps.append(EvidenceGap(
            field="热搜/趋势词",
            impact="不伪造实时热搜；需人工粘贴热搜词或接入合规趋势源后再评分",
            recommended_source="官方活动页/合规趋势工具导出，或投手手工粘贴当日热搜词",
        ))
    elif not real_trending:
        gaps.append(EvidenceGap(
            field="热搜/趋势词",
            impact="当前为 Mock 演示热搜情景，不是平台实时热搜榜",
            recommended_source="官方活动页/合规趋势工具导出，或投手手工粘贴当日热搜词",
        ))

    real_violations = [item for item in req.account_violation_evidence if not item.is_mock]
    if not req.account_violation_evidence:
        gaps.append(EvidenceGap(
            field="赛道高频违规/拒审台账",
            impact="官方规则不能替代高频排名；无台账时不宣称赛道高频违规类型",
            recommended_source="聚光拒审记录或账号违规中心导出",
        ))
    elif not real_violations:
        gaps.append(EvidenceGap(
            field="赛道高频违规/拒审台账",
            impact="当前为 Mock 演示拒审台账，高频排序不可用于正式合规结论",
            recommended_source="聚光拒审记录或账号违规中心导出",
        ))
    return gaps


def _benchmark_map(req: CampaignRequest) -> dict[str, dict[str, Any]]:
    return {
        item.metric_name.lower(): {
            "value": item.value,
            "unit": item.unit,
            "source": item.source_name,
            "source_name": item.source_name,
            "source_url": item.source_url,
            "collected_at": item.collected_at,
            "evidence_grade": item.evidence_grade,
            "is_mock": item.is_mock,
            "mock_seed": item.mock_seed,
            "data_type": MOCK_DATA_TYPE if item.is_mock else "真实样本",
            "warning": MOCK_WARNING if item.is_mock else None,
            "mock_basis": item.notes if item.is_mock else None,
            "notes": item.notes,
        }
        for item in req.benchmark_evidence
    }


def _notes_in_analysis_window(
    notes: list[CategoryNoteEvidence],
    analysis_days: int,
) -> tuple[list[CategoryNoteEvidence], list[CategoryNoteEvidence], int]:
    """按 analysis_days 过滤；无发布时间的笔记不计入趋势/高峰，但计入样本说明。"""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, analysis_days))
    in_window: list[CategoryNoteEvidence] = []
    undated: list[CategoryNoteEvidence] = []
    out_of_window = 0
    for item in notes:
        if not item.published_at:
            undated.append(item)
            continue
        try:
            published = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if published >= cutoff:
                in_window.append(item)
            else:
                out_of_window += 1
        except ValueError:
            undated.append(item)
    return in_window, undated, out_of_window


def _price_to_cny(amount: float, currency: str) -> tuple[float | None, dict[str, Any]]:
    code = (currency or "CNY").strip().upper()
    rate = FX_TO_CNY.get(code)
    if rate is None:
        return None, {
            "status": "unsupported_currency",
            "currency": code,
            "warning": f"暂不支持将 {code} 自动换汇为 CNY，拒绝输出 ROI 点估计",
        }
    return round(amount * rate, 2), {
        "status": "converted" if code != "CNY" else "native_cny",
        "currency": code,
        "fx_to_cny": rate,
        "warning": None if code in {"CNY", "RMB"} else "汇率为演示参考值，非实时牌价；上线前用财务汇率复核",
    }


def _category_market_summary(req: CampaignRequest) -> dict[str, Any]:
    raw_notes = req.category_note_evidence
    if not raw_notes:
        return {
            "status": "待导入品类公开笔记样本",
            "sample_size": 0,
            "trend": "证据不足，禁止由模型猜测",
            "recommended_dimensions": ["发布量", "互动量", "发布时间", "内容形式", "标签"],
        }
    in_window, undated, out_of_window = _notes_in_analysis_window(raw_notes, req.analysis_days)
    # 趋势与高峰：全部带发布时间的命中笔记；近 N 天窗口仅用于「窗口样本」等近窗指标
    notes = in_window
    dated_for_trend: list[CategoryNoteEvidence] = []
    for item in raw_notes:
        if not item.published_at:
            continue
        try:
            datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
            dated_for_trend.append(item)
        except ValueError:
            continue
    window_warning = (
        f"近{req.analysis_days}天窗内{len(in_window)}条（窗口样本/篇均近窗指标）；"
        f"趋势与高峰使用全部有发布时间笔记{len(dated_for_trend)}条；"
        f"窗外{out_of_window}条；无发布时间{len(undated)}条未计入趋势/高峰。"
    )
    if not notes and not dated_for_trend:
        return {
            "status": "无可用带发布时间的笔记样本",
            "sample_size": 0,
            "raw_sample_size": len(raw_notes),
            "out_of_window_count": out_of_window,
            "undated_count": len(undated),
            "window_warning": window_warning,
            "trend": "证据不足：缺少可解析发布时间的笔记",
            "recommended_dimensions": ["发布量", "互动量", "发布时间", "内容形式", "标签"],
            "traffic_peak_hours": {
                "status": "样本量不足，禁止输出高峰建议",
                "hours": [],
                "decision_conclusion": "有发布时间的样本不足；首轮多时段等量测试，暂不指定高峰。",
            },
        }
    stats_notes = dated_for_trend or notes
    total_likes = sum(item.likes or 0 for item in stats_notes)
    total_favorites = sum(item.favorites or 0 for item in stats_notes)
    total_comments = sum(item.comments or 0 for item in stats_notes)
    total_shares = sum(item.shares or 0 for item in stats_notes)
    total_interactions = total_likes + total_favorites + total_comments + total_shares
    tag_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    type_interactions: defaultdict[str, int] = defaultdict(int)
    keyword_counts: dict[str, int] = {}
    daily: defaultdict[str, dict[str, int]] = defaultdict(
        lambda: {"note_count": 0, "interactions": 0}
    )
    monthly: defaultdict[str, dict[str, int]] = defaultdict(
        lambda: {"note_count": 0, "interactions": 0}
    )
    hourly: defaultdict[int, dict[str, int]] = defaultdict(
        lambda: {"note_count": 0, "interactions": 0}
    )
    for item in stats_notes:
        item_interactions = sum((
            item.likes or 0,
            item.favorites or 0,
            item.comments or 0,
            item.shares or 0,
        ))
        keyword_counts[item.search_keyword] = keyword_counts.get(item.search_keyword, 0) + 1
        note_type = item.note_type or "未知"
        type_counts[note_type] += 1
        type_interactions[note_type] += item_interactions
        tag_counts.update(tag for tag in item.tags if tag)
    for item in dated_for_trend:
        item_interactions = sum((
            item.likes or 0,
            item.favorites or 0,
            item.comments or 0,
            item.shares or 0,
        ))
        published = parse_published_at(item.published_at)
        if published is None:
            continue
        beijing = to_beijing(published)
        day = beijing.date().isoformat()
        month = beijing.strftime("%Y-%m")
        daily[day]["note_count"] += 1
        daily[day]["interactions"] += item_interactions
        monthly[month]["note_count"] += 1
        monthly[month]["interactions"] += item_interactions
    # 高峰与趋势同口径：全部有发布时间的命中笔记（北京时间小时）
    for item in dated_for_trend:
        hour = extract_hour(item.published_at)
        if hour is None:
            continue
        item_interactions = sum((
            item.likes or 0,
            item.favorites or 0,
            item.comments or 0,
            item.shares or 0,
        ))
        hourly[hour]["note_count"] += 1
        hourly[hour]["interactions"] += item_interactions
    top_tags = sorted(tag_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:15]
    top_formats = sorted(type_counts.items(), key=lambda pair: (-pair[1], pair[0]))
    daily_series = [
        {"date": day, **values}
        for day, values in sorted(daily.items())
    ]
    monthly_series = [
        {"date": month, **values}
        for month, values in sorted(monthly.items())
    ]
    # 日点过稀或跨度大时改用月度，避免「库里 200 条却只画出 3 个点」
    if len(daily_series) >= 8 and len(daily_series) <= 90:
        time_series = daily_series
        trend_granularity = "按日"
    elif monthly_series:
        time_series = monthly_series
        trend_granularity = "按月"
    else:
        time_series = daily_series
        trend_granularity = "按日"
    eligible_hours = [
        {
            "hour": f"{hour:02d}:00–{hour:02d}:59",
            "hour_label_beijing": f"{hour:02d}:00–{hour:02d}:59 北京时间",
            **values,
            "average_interactions": round(
                values["interactions"] / values["note_count"], 1
            ),
        }
        for hour, values in hourly.items()
        if values["note_count"] >= MIN_NOTES_FOR_PEAK_HOUR
    ]
    peak_hours = sorted(
        eligible_hours,
        key=lambda row: (-row["average_interactions"], -row["note_count"]),
    )[:5]
    peak_slots = aggregate_peak_display_slots(dated_for_trend)
    top_slot = max(peak_slots, key=lambda row: row["count"])["slot"] if peak_slots else None
    trend_conclusion = (
        f"知识库/导入命中{len(dated_for_trend)}条有发布时间笔记，"
        f"{trend_granularity}聚合为{len(time_series)}个趋势点（日期按北京时间）；"
        f"近{req.analysis_days}天窗内{len(in_window)}条仅作窗口样本参考；"
        "仅反映当前检索样本，不能外推全平台发布量。"
        if time_series
        else "缺少有效发布时间，暂时不能判断发布量和互动量趋势。"
    )
    if peak_slots and top_slot:
        slot_text = "、".join(
            f"{row['slot']}（{row['count']}条）" for row in peak_slots if row["count"] > 0
        )
        peak_conclusion = (
            f"高峰集中在{top_slot}等种草窗（北京时间分桶：{slot_text}）。"
            "口径=笔记 published_at 转北京时间后的发布量分布，不是平台曝光高峰，也不是评论时间。"
        )
    elif peak_hours:
        peak_conclusion = (
            f"全样本中互动表现最高的发布时间段为{peak_hours[0]['hour']}（北京时间）"
            f"（该时段至少{MIN_NOTES_FOR_PEAK_HOUR}条样本，基于笔记发布时间而非评论/曝光时间）；"
            "建议作为首轮发布时间测试窗口。"
        )
    else:
        peak_conclusion = (
            f"高峰证据不足（单时段需≥{MIN_NOTES_FOR_PEAK_HOUR}条笔记）；"
            "首轮采用多个时段等量测试，暂不指定唯一高峰。"
        )
    tag_conclusion = (
        f"样本高频标签以“{'、'.join(tag for tag, _ in top_tags[:5])}”为主；用于内容测试，不宣称为平台扶持标签。"
        if top_tags
        else "样本没有可用标签；先补充标签数据，再决定标签布局。"
    )
    format_conclusion = (
        f"当前样本中“{max(top_formats, key=lambda pair: type_interactions[pair[0]] / pair[1])[0]}”的平均互动最高；优先进入内容A/B测试。"
        if top_formats
        else "缺少内容形式数据，图文与视频需同时小样本测试。"
    )
    all_mock_notes = all(item.is_mock for item in stats_notes)
    mock_note_count = sum(1 for item in stats_notes if item.is_mock)
    return {
        "status": (
            "基于 Mock 演示笔记样本（非平台大盘）"
            if all_mock_notes
            else (
                f"基于用户导入的公开搜索样本（含 {mock_note_count} 条 Mock）"
                if mock_note_count
                else "基于用户导入的公开搜索样本"
            )
        ),
        **evidence_meta(
            MOCK_DATA_TYPE if all_mock_notes else "真实样本",
            source_name="、".join(sorted({item.source_name for item in stats_notes})),
            as_of=max(item.collected_at for item in stats_notes),
            evidence_grade="M" if all_mock_notes else "B",
            is_mock=all_mock_notes,
            mock_basis="系统生成演示笔记，用于选题/聚类管线演示" if all_mock_notes else None,
            warning=(
                MOCK_WARNING
                if all_mock_notes
                else "结论仅适用于当前关键词搜索样本，不代表平台全量大盘。"
            ),
            mock_seed=stats_notes[0].mock_seed if all_mock_notes else None,
        ),
        "sample_size": len(notes),
        "raw_sample_size": len(raw_notes),
        "trend_sample_size": len(dated_for_trend),
        "window_average_interactions_per_note": (
            round(
                sum(
                    (item.likes or 0) + (item.favorites or 0)
                    + (item.comments or 0) + (item.shares or 0)
                    for item in notes
                ) / len(notes),
                1,
            )
            if notes
            else None
        ),
        "out_of_window_count": out_of_window,
        "undated_count": len(undated),
        "window_warning": window_warning,
        "mock_note_count": mock_note_count,
        "keywords_covered": keyword_counts,
        "publication_interaction_trend": {
            "status": "可计算" if time_series else "缺少笔记发布时间",
            "granularity": trend_granularity,
            "analysis_days": req.analysis_days,
            "series": time_series,
            "daily_series": daily_series,
            "monthly_series": monthly_series,
            "decision_conclusion": trend_conclusion,
        },
        "traffic_peak_hours": {
            "status": (
                "样本发布时间代理指标（已过最小样本量，北京时间）"
                if peak_hours or peak_slots
                else f"高峰证据不足（单时段需≥{MIN_NOTES_FOR_PEAK_HOUR}条）"
            ),
            "timezone": "Asia/Shanghai",
            "hours": peak_hours,
            "slots": peak_slots,
            "min_notes_per_hour": MIN_NOTES_FOR_PEAK_HOUR,
            "warning": (
                "公开笔记没有曝光时间分布；这里按 published_at→北京时间分桶统计发布量，"
                "不等同平台真实流量/曝光高峰，也不是评论时间。"
            ),
            "decision_conclusion": peak_conclusion,
        },
        "total_interactions": total_interactions,
        "average_interactions_per_note": round(total_interactions / len(stats_notes), 1),
        "interaction_breakdown": {
            "likes": total_likes,
            "favorites": total_favorites,
            "comments": total_comments,
            "shares": total_shares,
        },
        "observed_hot_tags": {
            "status": "样本高频标签，不等同平台扶持标签",
            "tags": [{"tag": tag, "sample_count": count} for tag, count in top_tags],
            "decision_conclusion": tag_conclusion,
            "next_action": "将前5个高频标签分组测试；平台扶持标签必须用官方活动页或平台公告二次确认。",
        },
        "popular_content_formats": [
            {
                "format": key,
                "sample_count": value,
                "average_interactions": round(type_interactions[key] / value, 1),
            }
            for key, value in top_formats
        ],
        "popular_content_format_conclusion": format_conclusion,
        # Compatibility aliases for existing API consumers.
        "top_tags": [{"tag": tag, "sample_count": count} for tag, count in top_tags],
        "content_formats": [{"format": key, "sample_count": value} for key, value in top_formats],
        "sampling_warning": (
            f"{window_warning} 这是登录后关键词搜索样本，不代表小红书全平台大盘；"
            "会受关键词、排序、时间和个性化推荐影响。"
        ),
        "source_names": sorted({item.source_name for item in notes}),
        "latest_collected_at": max(item.collected_at for item in notes),
    }


def _spotlight_market_summary(
    req: CampaignRequest,
    benchmarks: dict[str, dict[str, Any]],
    *,
    allow_mock: bool,
    mock_seed: str | None,
) -> dict[str, Any]:
    scenarios = build_mock_market_scenarios(
        req.total_budget_cny, req.goal, mock_seed=mock_seed
    )

    def metric(label: str, scenario_key: str, unit: str, *names: str) -> dict[str, Any]:
        for name in names:
            if name in benchmarks:
                return metric_or_mock(
                    benchmarks,
                    name,
                    label=label,
                    mock_value=scenarios[scenario_key]["base"],
                    low=scenarios[scenario_key]["low"],
                    high=scenarios[scenario_key]["high"],
                    unit=unit,
                    basis="真实数据优先",
                    allow_mock=allow_mock,
                    mock_seed=mock_seed,
                )
        return metric_or_mock(
            benchmarks,
            names[0],
            label=label,
            mock_value=scenarios[scenario_key]["base"],
            low=scenarios[scenario_key]["low"],
            high=scenarios[scenario_key]["high"],
            unit=unit,
            basis=f"{label}采用低／中／高三档首轮测试情景；不是行业平均值。",
            allow_mock=allow_mock,
            mock_seed=mock_seed,
        )

    mock_meta = scenarios["meta"] if allow_mock else evidence_meta(
        "数据缺口",
        source_name="尚无可用来源",
        evidence_grade="D",
        is_mock=False,
        warning="缺少品牌聚光账户或具有明确统计口径的公开资料。",
    )
    budget_share = scenarios["budget_share"] if allow_mock else {
        "search_ratio": None,
        "feed_ratio": None,
    }

    average_ctr = metric("CTR", "ctr", "ratio", "ctr", "click_through_rate")
    # 互动成本 ≠ CPA：仅在投流表有该字段时输出，禁止用转化成本情景冒充
    if any(name in benchmarks for name in ("cost_per_interaction", "cpi_interaction")):
        interaction_cost = metric(
            "单次互动成本",
            "conversion_cost",
            "元/次互动",
            "cost_per_interaction",
            "cpi_interaction",
        )
    else:
        interaction_cost = {
            "label": "单次互动成本",
            "value": None,
            "unit": "元/次互动",
            "status": "缺口",
            "decision_conclusion": "投流表未提供单次互动成本；不得用 CPA/转化成本字段替代。",
            **(
                mock_meta
                if allow_mock
                else evidence_meta(
                    "数据缺口",
                    source_name="尚无可用来源",
                    evidence_grade="D",
                    is_mock=False,
                    warning="缺少 cost_per_interaction 字段。",
                )
            ),
        }
    conversion_cost = metric(
        "转化成本",
        "conversion_cost",
        "元/次转化",
        "cpa",
        "cost_per_conversion",
        "cost_per_order",
        "cost_per_lead",
    )
    # 作业目标枚举：种草 / 成交 / 客资（按本次任务目标排序，非品类消耗热度榜）
    goal_rank_map = {
        "conversion": ["成交", "种草", "客资"],
        "leads": ["客资", "种草", "成交"],
        "awareness": ["种草", "成交", "客资"],
        "engagement": ["种草", "成交", "客资"],
        "search_growth": ["种草", "成交", "客资"],
        "live_traffic": ["种草", "客资", "成交"],
    }
    goal_ranking = goal_rank_map.get(req.goal, ["种草", "成交", "客资"])
    # 无分版位消耗时，按目标给首轮可比较默认配比（与模块4 / Mock 共用 SSOT）
    from tools.budget import search_feed_share_for_goal

    goal_share = search_feed_share_for_goal(req.goal)
    if allow_mock:
        # Mock 只可补 CPC/CPA 等情景数字；搜推比例必须与模块4一致，禁止随机第二套。
        search_ratio = goal_share["search_ratio"]
        feed_ratio = goal_share["feed_ratio"]
        share_status = f"{goal_share['basis']}（Mock 场景仍用目标默认档，待账户数据替换）"
        share_conclusion = (
            f"首轮按搜索{search_ratio:.0%}／信息流{feed_ratio:.0%}做可比较测试；"
            "每3天依据真实分版位消耗替换。"
        )
    elif isinstance(budget_share.get("search_ratio"), (int, float)):
        search_ratio = budget_share["search_ratio"]
        feed_ratio = budget_share["feed_ratio"]
        share_status = "已导入分版位消耗"
        share_conclusion = "按导入的分版位消耗占比作为首轮参考，每3天用账户成本复核。"
    else:
        search_ratio = goal_share["search_ratio"]
        feed_ratio = goal_share["feed_ratio"]
        share_status = goal_share["basis"]
        share_conclusion = (
            f"无分版位消耗台账时，首轮按搜索{search_ratio:.0%}／信息流{feed_ratio:.0%}做可比较测试；"
            "上线后用账户真实消耗替换。"
        )

    has_paid_benchmarks = any(
        benchmarks.get(name) and benchmarks[name].get("value") is not None
        for name in ("cpc", "cpm", "ctr")
    )
    traffic_points = [
        "搜索承接：品类词 + 竞品截流词做高意向转化",
        "信息流种草：场景/证据素材先测 CTR 与互动成本",
        "达人/笔记加热：仅在自然表现过门槛后复用",
    ]
    if has_paid_benchmarks:
        traffic_status = "基于品牌投流表的首轮倾斜建议（非平台2026官方公告）"
        traffic_conclusion = (
            "在缺少官方流量倾斜公告时，按账户历史 CPC/CTR 做搜索承接 + 信息流种草双轨；"
            "官方公告或对照实验结果出来前不写死单一流量池。"
        )
    else:
        traffic_status = "待接入2026年官方公告/帮助中心证据"
        traffic_conclusion = (
            "当前不把任何平台流量倾斜传闻写入预算决策；仅在官方公告或账户实验验证后放大。"
        )

    return {
        "average_cpc": metric("CPC", "cpc", "元/点击", "cpc"),
        "average_cpm": metric("CPM", "cpm", "元/千次曝光", "cpm"),
        "average_ctr": average_ctr,
        "interaction_cost": interaction_cost,
        "conversion_cost": conversion_cost,
        "popular_promotion_goals": {
            "status": (
                "模拟优先级，待分目标消耗数据验证"
                if allow_mock
                else "按本次任务目标排序的测试优先级（非品类消耗热度榜）"
            ),
            "requested_goal": GOAL_LABELS[req.goal],
            "market_ranking": goal_ranking if allow_mock else goal_ranking,
            "goal_notes": [
                f"主目标：{goal_ranking[0]}（对应本次任务「{GOAL_LABELS[req.goal]}」）",
                f"辅目标：{goal_ranking[1]}（用种草/搜索承接验证素材与意向）",
                f"观察目标：{goal_ranking[2]}（小预算探测，不抢主预算）",
            ],
            "required_fields": ["推广目标", "消耗", "转化数", "统计周期"],
            **mock_meta,
            "decision_conclusion": (
                f"本次将“{GOAL_LABELS[req.goal]}”设为测试主目标；排序是方案假设，不是市场热度事实。"
                if allow_mock
                else (
                    f"本次先以“{GOAL_LABELS[req.goal]}”为主目标，测试优先级："
                    f"{' > '.join(goal_ranking)}；品类真实热度需导入分目标消耗后再调整。"
                )
            ),
        },
        "search_feed_budget_share": {
            "status": share_status,
            "search_ratio": search_ratio,
            "feed_ratio": feed_ratio,
            **(
                mock_meta
                if allow_mock
                else evidence_meta(
                    "任务目标推导配比" if share_status.startswith("按任务目标") else "真实样本",
                    source_name=(
                        "任务目标默认配比"
                        if share_status.startswith("按任务目标")
                        else "分版位消耗导入"
                    ),
                    evidence_grade="E" if share_status.startswith("按任务目标") else "C",
                    is_mock=False,
                    warning=(
                        "非账户分版位消耗事实，仅作首轮可比较测试起点。"
                        if share_status.startswith("按任务目标")
                        else None
                    ),
                )
            ),
            "decision_conclusion": share_conclusion,
        },
        "latest_traffic_direction_2026": {
            "status": traffic_status if not allow_mock else "模拟探索方向，待官方公告或账户实验验证",
            "conclusion": "搜索承接与信息流种草双轨测试",
            "direction_points": traffic_points,
            **mock_meta,
            "decision_conclusion": (
                "该方向仅作为探索情景，保留20%测试预算；验证后才可写成账户决策。"
                if allow_mock
                else traffic_conclusion
            ),
        },
        "benchmarks": benchmarks,
    }


def _competitor_market_summary(
    req: CampaignRequest, *, allow_mock: bool, mock_seed: str | None
) -> dict[str, Any]:
    scenarios = build_mock_market_scenarios(
        req.total_budget_cny, req.goal, mock_seed=mock_seed
    )
    mock_meta = scenarios["meta"]
    rows = []
    format_counts: Counter[str] = Counter()
    user_theme_counts: Counter[str] = Counter()
    rich_user_samples = 0
    for item in req.competitor_evidence:
        note_format = item.note_format or "待核验"
        format_counts[note_format] += 1
        themes = list(item.content_themes or [])
        if themes or item.interactions is not None or item.is_ad_labeled is not None:
            rich_user_samples += 1
        for theme in themes:
            cleaned = theme.strip()
            if cleaned:
                user_theme_counts[cleaned] += 1
        rows.append({
            "account": item.account_name,
            "title": item.title,
            "url": item.profile_or_note_url,
            "format": note_format,
            "interactions": item.interactions,
            "ad_labeled": item.is_ad_labeled,
            "content_themes": themes,
            "ad_note_status": (
                "Mock 模拟广告标识"
                if item.is_mock and item.is_ad_labeled is True
                else "Mock 模拟无广告标识"
                if item.is_mock and item.is_ad_labeled is False
                else "公开页检出广告标识"
                if item.is_ad_labeled is True
                else "公开页未见广告标识"
                if item.is_ad_labeled is False
                else "公开页未判定广告标识"
            ),
            "campaign_duration": {
                "status": (
                    "模拟验证周期，非竞品真实投放时长"
                    if allow_mock
                    else (
                        "已提供投放天数"
                        if item.campaign_duration_days is not None
                        else "公开页无法认定投放时长；禁止由互动量反推"
                    )
                ),
                "days": (
                    item.campaign_duration_days
                    if item.campaign_duration_days is not None
                    else scenarios["competitor_hypothesis"]["duration_days"]
                    if allow_mock else None
                ),
                **(mock_meta if allow_mock else {}),
            },
            "estimated_budget_cny": {
                "low": item.estimated_budget_low_cny,
                "high": item.estimated_budget_high_cny,
            },
            "audience_signals": item.observed_audience,
            "evidence_status": item.notes or "已纳入对标条目",
            "source_name": item.source_name,
            "mock_basis": item.notes if item.is_mock else None,
            "data_type": MOCK_DATA_TYPE if item.is_mock else "给定链接抓取样本",
            "is_mock": bool(item.is_mock),
            "evidence_grade": "M" if item.is_mock else (item.evidence_grade or "C"),
            "mock_seed": item.mock_seed if item.is_mock else None,
            "warning": MOCK_WARNING if item.is_mock else None,
        })

    # 优先用给定链接拆解的 content_themes；品类笔记仅作补充，不替代对标证据
    note_clusters = _cluster_evidence_themes(req)
    note_format_counts: Counter[str] = Counter()
    for note in req.category_note_evidence:
        note_format_counts[note.note_type or "未知"] += 1

    user_theme_rows = [
        {
            "theme": theme,
            "note_count": count,
            "total_interactions": sum(
                (item.interactions or 0)
                for item in req.competitor_evidence
                if theme in (item.content_themes or [])
            ),
            "evidence_titles": [
                item.title or item.account_name
                for item in req.competitor_evidence
                if theme in (item.content_themes or [])
            ][:5],
            "source": "user_competitor_evidence",
        }
        for theme, count in user_theme_counts.most_common(8)
    ]
    top_themes = user_theme_rows[:5] or note_clusters[:5]
    occupied_themes = [str(item.get("theme") or "").strip() for item in top_themes if item.get("theme")]
    gap_assessment = assess_content_gaps(
        req.selling_points,
        req.competitor_evidence,
        occupied_themes=occupied_themes,
    )
    gap_opportunities = [
        {
            "opportunity": f"测试卖点「{row['point']}」的对比/体验内容",
            "reason": row.get("gap_blank")
            or format_content_gap_reason(row, occupied_themes=occupied_themes),
            "evidence_basis": row["evidence_basis"],
            "stage": row["stage"],
            "conclusion_type": row["conclusion_type"],
            "validation_required": row["validation_required"],
        }
        for row in gap_assessment["candidates"][:5]
    ]

    merged_formats = format_counts or note_format_counts
    observed_formats = [
        {"format": name, "sample_count": count}
        for name, count in merged_formats.most_common()
    ]
    if user_theme_rows:
        commonality_status = "基于给定链接抓取的主题字段"
        top_format = merged_formats.most_common(1)[0][0] if merged_formats else "未知"
        commonality_conclusion = (
            f"对标样本高频主题为“{'、'.join(item['theme'] for item in top_themes)}”；"
            f"内容形式以“{top_format}”为主。"
            "优先拆解高互动对标笔记的标题、封面与决策信息密度。"
        )
    elif note_clusters:
        commonality_status = "基于品类笔记样本统计（对标主题尚未拆解）"
        top_format = merged_formats.most_common(1)[0][0] if merged_formats else "未知"
        commonality_conclusion = (
            f"样本高频主题为“{'、'.join(item['theme'] for item in top_themes)}”；"
            f"内容形式以“{top_format}”为主。"
            "优先拆解高互动主题的标题、封面与卖点证据。"
        )
    else:
        commonality_status = "证据不足" if not rows else "仅有链接/条目，缺主题标注"
        commonality_conclusion = (
            f"现有对标条目主要内容形式为“{format_counts.most_common(1)[0][0]}”；"
            "请对给定链接完成抓取（或检查登录墙），补全 content_themes / 互动量 / 广告标识后重跑。"
            if format_counts
            else "对标证据不足：请粘贴3–5个笔记/账号链接，系统将抓取这些给定链接。"
        )

    audience_signals = sorted({
        signal
        for item in req.competitor_evidence
        for signal in item.observed_audience
    })
    if allow_mock and not audience_signals:
        audience_signals = scenarios["competitor_hypothesis"]["targeting_tests"]
    targeting_status = (
        "模拟定向测试假设，非竞品真实定向"
        if allow_mock
        else (
            "基于给定链接正文/评论画像信号的定向测试假设"
            if audience_signals
            else "待从给定链接补抓评论画像信号"
        )
    )

    return {
        "status": (
            "已抓取给定对标链接的结构化证据"
            if rich_user_samples
            else (
                "仅有链接占位，待完成给定链接抓取"
                if rows
                else (
                    "有品类笔记样本可替代统计"
                    if note_clusters
                    else "待粘贴3-5个对标账号/笔记链接"
                )
            )
        ),
        "input_policy": "fetch_user_given_links_only_no_bulk_crawl",
        "accounts": rows,
        "organic_hits_commonalities": {
            "observed_formats": observed_formats,
            "top_themes": top_themes,
            "sample_note_count": len(req.category_note_evidence),
            "user_competitor_count": len(req.competitor_evidence),
            "status": commonality_status,
            "decision_conclusion": commonality_conclusion,
        },
        "content_gaps": {
            "status": gap_assessment["status"],
            "covered_points": gap_assessment["covered_points"],
            "covered_selling_points": gap_assessment["covered_points"],
            "gap_selling_points": gap_assessment["gap_selling_points"],
            "candidates": gap_assessment["candidates"],
            "opportunities": gap_opportunities,
            "decision_conclusion": gap_assessment["decision_conclusion"],
            "missing_evidence": gap_assessment["missing_evidence"],
        },
        "paid_notes": {
            "confirmed_count": sum(item.is_ad_labeled is True for item in req.competitor_evidence),
            "notes": [row for row in rows if row["ad_labeled"] is True],
            "warning": (
                "广告标识来自给定链接公开页可观测信号；"
                "未确认样本不得当作正在投流。"
            ),
            "decision_conclusion": (
                f"公开页确认{sum(item.is_ad_labeled is True for item in req.competitor_evidence)}条带广告标识笔记；"
                "只有确认样本进入投流内容拆解，未确认样本不作为投流证据。"
            ),
        },
        "targeting_inference": {
            "status": targeting_status,
            "audience_signals": audience_signals,
            **(mock_meta if allow_mock else {}),
            "evidence_boundary": "评论区只能形成受众假设，不能还原竞品真实聚光定向。",
            **({"warning": MOCK_WARNING} if allow_mock else {
                "warning": "评论区只能形成受众假设，不能还原竞品真实聚光定向。"
            }),
            "decision_conclusion": (
                "评论画像仅用于提出定向测试假设；首轮必须在自有聚光账户中分组验证，不能照搬为竞品真实定向。"
            ),
        },
        "budget_range": {
            "status": "本品牌同预算验证情景，非竞品真实预算" if allow_mock else "不可由公开互动量可靠反推",
            "low_cny": scenarios["competitor_hypothesis"]["budget_cny"]["low"] if allow_mock else None,
            "high_cny": scenarios["competitor_hypothesis"]["budget_cny"]["high"] if allow_mock else None,
            **(mock_meta if allow_mock else {}),
            "required_evidence": "竞品账户授权数据、媒体监测数据，或明确披露的合作报价与投放周期",
            "decision_conclusion": (
                "不依据点赞量反推竞品预算；本品牌预算按自身转化成本和止损线分配。"
            ),
        },
    }


def _bid_range(
    benchmarks: dict[str, dict[str, Any]],
    *,
    low_multiplier: float,
    high_multiplier: float,
    bid_note: str | None = None,
) -> dict[str, Any]:
    cpc = benchmarks.get("cpc")
    if not cpc:
        return {
            "low_cny_per_click": None,
            "high_cny_per_click": None,
            "basis": "缺少历史CPC：使用聚光账户建议价做首轮小预算测试",
            "evidence_status": "待补数据",
            "multiplier_band": [low_multiplier, high_multiplier],
            "bid_note": bid_note,
        }
    baseline = float(cpc["value"])
    return {
        "low_cny_per_click": round(baseline * low_multiplier, 2),
        "high_cny_per_click": round(baseline * high_multiplier, 2),
        "basis": f"品牌历史加权CPC ¥{baseline:.2f} × {low_multiplier:.1f}–{high_multiplier:.1f}",
        "source": cpc["source"],
        "collected_at": cpc["collected_at"],
        "evidence_status": "有来源证据，仍需以账户实时建议价校准",
        "multiplier_band": [low_multiplier, high_multiplier],
        "bid_note": bid_note,
    }


def _classify_search_intent(req: CampaignRequest, keyword: str) -> tuple[str, str]:
    """返回 (intent_code, intent_label)。与 tools.keywords 的 high/mid/low 对齐。"""
    text = (keyword or "").strip()
    brand = (req.brand_name or "").strip()
    product = (req.product_name or "").strip()
    if (brand and brand in text) or (product and product in text):
        return "high", "品牌/产品高意向"
    decision_markers = (
        "推荐", "怎么选", "对比", "测评", "哪家", "保质期", "值得买", "避雷", "攻略", "清单",
    )
    if any(marker in text for marker in decision_markers):
        return "mid", "品类决策意向"
    return "low", "品类泛需求"


def _keyword_suggested_bid(
    benchmarks: dict[str, dict[str, Any]],
    *,
    level: str,
    intent: str,
    lane: str,
) -> dict[str, Any]:
    """按词级别×意向×版位固定倍率带出价；与 build_keyword_tiers 同一套护栏。"""
    from tools.keywords import _multiplier_band

    (low_m, high_m), note = _multiplier_band(level, intent, lane)
    return _bid_range(
        benchmarks,
        low_multiplier=low_m,
        high_multiplier=high_m,
        bid_note=note,
    )


def _build_dual_track_keyword_library(
    req: CampaignRequest,
    keywords: dict[str, Any],
    benchmarks: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """作业模块3：自然流量词库（标题/正文/标签）+ 聚光搜索/信息流双轨出价。"""
    audience_parts = [
        part.strip()
        for part in re.split(r"[、，,/｜|]", req.initial_audience or "")
        if part and part.strip()
    ]
    from knowledge_base import KnowledgeBase

    core = list(keywords.get("core") or [])
    long_tail = list(keywords.get("long_tail") or [])
    blue_ocean = list(keywords.get("blue_ocean_candidates") or [])
    # 场景/人群从知识库识别（与 core/long_tail/blue_ocean 正交，允许同词复用到布局）
    role_pack = KnowledgeBase.extract_scene_audience_keywords(
        req.category_note_evidence or [],
        scene_limit=8,
        audience_limit=6,
    )
    scene_keywords = [
        row["keyword"]
        for row in role_pack.get("scene_keywords") or []
        if _normalize_tier_keyword(row.get("keyword"))
    ]
    audience_keywords = [
        row["keyword"]
        for row in role_pack.get("audience_keywords") or []
        if _normalize_tier_keyword(row.get("keyword"))
    ]
    # 知识库未识别到人群词时：仅回退请求画像短词
    if not audience_keywords:
        for part in audience_parts[:6] or [((req.initial_audience or "")[:16])]:
            text = _normalize_tier_keyword(part)
            if not text:
                continue
            if text.casefold() in {k.casefold() for k in audience_keywords}:
                continue
            audience_keywords.append(text)
            if len(audience_keywords) >= 6:
                break
    # 知识库未识别到场景词时：主题词 → 品牌输入中带场景标记的词（弱回退）
    if not scene_keywords:
        fallback_scene = [
            *(keywords.get("evidence_themes") or []),
            *list(req.selling_points or [])[:4],
            req.category,
        ]
        for theme in fallback_scene:
            text = _normalize_tier_keyword(theme)
            if not text:
                continue
            if text.casefold() in {k.casefold() for k in scene_keywords}:
                continue
            if KnowledgeBase._keyword_role(text) == "scene":
                scene_keywords.append(text)
            if len(scene_keywords) >= 6:
                break
    title_keywords = list(dict.fromkeys([
        *(core[:1] or []),
        *(long_tail[:1] or []),
    ]))[:2]
    body_keywords = list(dict.fromkeys([
        *scene_keywords[:3],
        *req.selling_points[:2],
        *long_tail[1:3],
    ]))[:5]
    tag_keywords = list(dict.fromkeys([
        *core[:2],
        *scene_keywords[:2],
        *audience_keywords[:2],
        *blue_ocean[:1],
    ]))[:6]
    layout_rule = {
        "title": "放1个核心词或高意向长尾词，避免堆砌",
        "body": "首段出现用户场景词，中段围绕卖点自然覆盖2–4个相关词",
        "tags": "核心词 + 场景词 + 人群词组合，发布后按搜索表现迭代",
    }

    search_keywords: list[dict[str, Any]] = []
    for keyword in long_tail:
        intent_code, intent_label = _classify_search_intent(req, keyword)
        search_keywords.append(
            {
                "keyword": keyword,
                "track": "search_promotion",
                "intent": intent_label,
                "intent_code": intent_code,
                "suggested_bid_range": _keyword_suggested_bid(
                    benchmarks,
                    level="long_tail",
                    intent=intent_code,
                    lane="search",
                ),
            }
        )
    for keyword in core[:2]:
        if any(row["keyword"] == keyword for row in search_keywords):
            continue
        intent_code, intent_label = _classify_search_intent(req, keyword)
        if intent_code != "high":
            intent_code, intent_label = "high", "品牌/产品高意向"
        search_keywords.insert(
            0,
            {
                "keyword": keyword,
                "track": "search_promotion",
                "intent": intent_label,
                "intent_code": intent_code,
                "suggested_bid_range": _keyword_suggested_bid(
                    benchmarks,
                    level="core",
                    intent=intent_code,
                    lane="search",
                ),
            },
        )

    interest_words = list(dict.fromkeys([
        req.category,
        *req.selling_points[:3],
        *audience_keywords[:3],
        *keywords.get("evidence_themes", [])[:4],
        *blue_ocean[:2],
    ]))
    feed_keywords = [
        {
            "keyword": word,
            "interest_word": word,
            "track": "feed_interest",
            "audience_role": "品类/卖点/人群泛需求兴趣信号",
            "intent": "信息流兴趣触达（泛需求）",
            "intent_code": "mid",
            "suggested_bid_range": _keyword_suggested_bid(
                benchmarks,
                level="long_tail",
                intent="mid",
                lane="feed",
            ),
        }
        for word in interest_words
        if word
    ]

    return {
        "pipeline": keywords.get("pipeline"),
        "status": keywords.get("status"),
        "organic_traffic": {
            "usage": "用于笔记标题、正文、标签布局（自然搜索可见性）",
            "core_keywords": core,
            "long_tail_keywords": long_tail,
            "scene_keywords": scene_keywords,
            "audience_keywords": audience_keywords,
            "blue_ocean_candidates_to_validate": blue_ocean,
            "layout_rule": layout_rule,
            "layout_plan": {
                "title_keywords": title_keywords,
                "body_keywords": body_keywords,
                "tag_keywords": tag_keywords,
                "example": (
                    f"标题放「{title_keywords[0]}」；"
                    f"正文覆盖「{' / '.join(body_keywords[:3])}」；"
                    f"标签组合「{' #'.join(tag_keywords[:4])}」"
                    if title_keywords
                    else "待生成布局示例"
                ),
            },
        },
        "spotlight_paid": {
            "search_promotion": {
                "purpose": "承接主动搜索用户，优先高意向长尾词",
                "keyword_type": "搜索推广词（高意向长尾）",
                "keywords": search_keywords,
            },
            "feed_interest": {
                "purpose": "触达泛需求与潜在人群，用于信息流兴趣定向测试",
                "keyword_type": "信息流兴趣词（泛需求）",
                "keywords": feed_keywords,
            },
            "bid_note": (
                "各词出价按意向×版位固定倍率带（搜索高意向 1.0–1.3 / 中意向 0.9–1.1 / "
                "低意向 0.8–1.0；信息流 0.7–1.0），以品牌历史加权CPC为基准；"
                "不是平台保证价，上线时以账户实时建议价校准。"
            ),
            "counts": {
                "search_promotion": len(search_keywords),
                "feed_interest": len(feed_keywords),
                "organic_core": len(core),
                "organic_long_tail": len(long_tail),
            },
        },
    }


def _creator_tier(followers: int | None) -> str:
    if followers is None:
        return "待判定"
    if followers < 10_000:
        return "素人"
    if followers < 500_000:
        return "达人"
    return "KOL"


def _creator_match_score(req: CampaignRequest, audience_tags: list[str]) -> int:
    corpus = f"{req.initial_audience} {' '.join(req.selling_points)} {req.category} {req.product_name}"
    hits = sum(1 for tag in audience_tags if tag and tag in corpus)
    return min(95, 55 + hits * 10)


def _creator_plan(
    req: CampaignRequest,
    *,
    organic_budget: float,
    paid_budget: float,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    tiers = [
        {"tier": "素人", "count": 12, "budget_ratio": 0.50},
        {"tier": "达人", "count": 6, "budget_ratio": 0.35},
        {"tier": "KOL", "count": 2, "budget_ratio": 0.15},
    ]
    amplification_pool = paid_budget * 0.30
    for tier in tiers:
        tier["collaboration_budget_cny"] = _round_money(organic_budget * tier["budget_ratio"])
        tier["suggested_quote_per_creator_cny"] = _round_money(
            organic_budget * tier["budget_ratio"] / tier["count"]
        )
        tier["spotlight_amplification_budget_cny"] = _round_money(
            amplification_pool * tier["budget_ratio"]
        )
        tier["suggested_spotlight_per_note_cny"] = _round_money(
            amplification_pool * tier["budget_ratio"] / tier["count"]
        )

    tier_lookup = {item["tier"]: item for item in tiers}
    recommendations: list[dict[str, Any]] = []
    for creator in req.creator_evidence:
        tier_name = _creator_tier(creator.followers)
        plan = tier_lookup.get(tier_name) or tier_lookup["达人"]
        is_mock = bool(creator.is_mock)
        recommendations.append(
            {
                "rank": 0,
                "creator_name": creator.name,
                "tier": tier_name,
                "profile_url": creator.profile_url,
                "followers": creator.followers,
                "average_interactions": creator.average_interactions,
                "quote_cny": creator.quote_cny,
                "audience_match_score": _creator_match_score(req, creator.audience_tags),
                "audience_tags": creator.audience_tags,
                "past_paid_performance": creator.past_campaign_result or "数据未提供",
                "suggested_spotlight_per_note_cny": plan["suggested_spotlight_per_note_cny"],
                "source": creator.source_name,
                "source_name": creator.source_name,
                "collected_at": creator.collected_at,
                "data_status": (
                    "模拟候选（Mock），禁止当作真实推荐"
                    if is_mock
                    else "已提供候选证据"
                ),
                "is_recommendation": not is_mock,
                "is_mock": is_mock,
                "data_type": MOCK_DATA_TYPE if is_mock else "真实样本",
                "evidence_grade": "M" if is_mock else (creator.evidence_grade or "C"),
                "mock_seed": creator.mock_seed if is_mock else None,
                "mock_basis": creator.past_campaign_result if is_mock else None,
                "warning": MOCK_WARNING if is_mock else None,
            }
        )
    recommendations.sort(
        key=lambda item: (
            0 if item["is_mock"] else 1,
            item["audience_match_score"],
            item["average_interactions"] or 0,
        ),
        reverse=True,
    )
    for index, item in enumerate(recommendations[:20], start=1):
        item["rank"] = index
    candidates = recommendations[:20]
    verified_candidates = [item for item in candidates if not item["is_mock"]]
    mock_candidates = [item for item in candidates if item["is_mock"]]

    filled_by_tier: Counter[str] = Counter(item["tier"] for item in candidates)
    open_slots = []
    for tier in tiers:
        remaining = max(0, tier["count"] - filled_by_tier.get(tier["tier"], 0))
        if remaining:
            open_slots.append({
                "tier": tier["tier"],
                "slots_needed": remaining,
                "suggested_quote_per_creator_cny": tier["suggested_quote_per_creator_cny"],
                "suggested_spotlight_per_note_cny": tier["suggested_spotlight_per_note_cny"],
                "data_status": "检索槽位，非推荐名单；导入 CSV/蒲公英后再进入候选",
            })

    roster_meta = {
        "target_roster_size": 20,
        "real_candidate_count": len(verified_candidates),
        "mock_candidate_count": len(mock_candidates),
        "open_slot_count": sum(item["slots_needed"] for item in open_slots),
        "open_slots": open_slots,
        "policy": (
            "无真实证据不输出推荐名单；Mock 候选仅用于演示分层，禁止当作真实达人推荐"
        ),
    }
    return candidates, {
        "collaboration_budget_pool_cny": _round_money(organic_budget),
        "spotlight_amplification_pool_cny": _round_money(amplification_pool),
        "spotlight_pool_rule": "暂按聚光预算的30%用于达人笔记二次放大，可在模块4账户规划中调整",
        "tiers": tiers,
    }, roster_meta


def _slot_role_for_hour(hour_label: str) -> str:
    """把样本高峰小时映射成可读投放角色，便于演示多时段差异。"""
    try:
        hour = int(str(hour_label).split(":")[0])
    except (TypeError, ValueError, IndexError):
        return "样本高互动发布时间窗"
    if 7 <= hour <= 9:
        return "早通勤浏览窗"
    if 11 <= hour <= 13:
        return "午间碎片消费窗"
    if 17 <= hour <= 19:
        return "晚高峰种草窗"
    if 20 <= hour <= 22:
        return "夜间决策下单窗"
    if 14 <= hour <= 16:
        return "下午浏览对照窗"
    return "样本高互动发布时间窗"


def _daily_schedules(req: CampaignRequest, organic_market: dict[str, Any]) -> dict[str, Any]:
    peak_hours = organic_market.get("traffic_peak_hours", {}).get("hours") or []
    if peak_hours:
        slots = []
        share = round(1 / min(5, len(peak_hours)), 2)
        for item in peak_hours[:5]:
            hour_label = item["hour"]
            note_count = item.get("note_count")
            avg_interactions = item.get("average_interactions")
            slots.append({
                "slot": hour_label,
                "role": _slot_role_for_hour(hour_label),
                "budget_share_hint": share,
                "action": "该时段优先投放已验证素材；其余预算均分测试",
                "source": "品类笔记发布时间×互动代理指标",
                "sample_note_count": note_count,
                "sample_avg_interactions": avg_interactions,
            })
        # normalize last share
        if slots:
            used = round(sum(s["budget_share_hint"] for s in slots[:-1]), 2)
            slots[-1]["budget_share_hint"] = round(max(0.05, 1 - used), 2)
        roles = sorted({s["role"] for s in slots})
        return {
            "status": (
                f"基于样本发布时间高峰生成每日时段（覆盖{len(slots)}个高峰窗："
                f"{'、'.join(roles)}）"
            ),
            "warning": "公开笔记无曝光时刻分布；此处为发布时刻代理，上线前用账户分时报表校准",
            "slots": slots,
        }
    default_slots = [
        {"slot": "07:00–09:00", "role": "早通勤浏览", "budget_share_hint": 0.15},
        {"slot": "11:30–13:30", "role": "午间碎片消费", "budget_share_hint": 0.20},
        {"slot": "18:00–20:00", "role": "晚高峰种草", "budget_share_hint": 0.30},
        {"slot": "21:00–23:00", "role": "决策下单窗口", "budget_share_hint": 0.25},
        {"slot": "其他时段", "role": "探索对照", "budget_share_hint": 0.10},
    ]
    for slot in default_slots:
        slot["action"] = "首轮等量或按份额测试，禁止在无账户分时数据时锁死单一高峰"
        slot["source"] = "默认测试窗（待账户分时报表替换）"
    return {
        "status": "缺少发布时间证据：使用默认每日测试窗",
        "warning": "默认窗口不是平台流量事实；导入账户分时消耗后再固化",
        "slots": default_slots,
    }


def _forecast_block(
    req: CampaignRequest,
    *,
    paid_budget: float,
    benchmarks: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cpc = benchmarks.get("cpc")
    ctr = benchmarks.get("ctr")
    cvr = benchmarks.get("cvr") or benchmarks.get("conversion_rate")
    aov_native = (req.price_min + req.price_max) / 2
    aov_cny, fx_meta = _price_to_cny(aov_native, req.currency)
    min_conversions = 20
    historical_cpc = float(cpc["value"]) if cpc else None
    # 测试带宽：min(聚光×15%, 目标CPA×最小转化×1.5)；无CPA时用 CPC×预估点击路径近似
    target_cpa = None
    if historical_cpc and cvr and float(cvr["value"]) > 0:
        target_cpa = historical_cpc / float(cvr["value"])
    elif historical_cpc:
        target_cpa = historical_cpc * 25  # 无CVR时的保守占位：假设约4%点击转化，仅用于带宽计算
    bandwidth_by_ratio = paid_budget * 0.15
    bandwidth_by_sample = (target_cpa * min_conversions * 1.5) if target_cpa else paid_budget * 0.10
    test_budget = _round_money(min(bandwidth_by_ratio, bandwidth_by_sample))
    stop_cpc = round(historical_cpc * 1.5, 2) if historical_cpc else None
    stop_cpa = round(target_cpa * 1.2, 2) if target_cpa else None
    min_impressions = 3000
    min_clicks = 100

    roi_range = None
    forecast_status = "证据不足：仅输出测试带宽与止损公式"
    if cpc and ctr and cvr and aov_cny is not None:
        # ROI ≈ (1/CPC)×CVR×客单价(CNY) - 1；CPC 默认按 CNY
        clicks_per_yuan = 1 / float(cpc["value"]) if float(cpc["value"]) else 0
        orders_per_yuan = clicks_per_yuan * float(cvr["value"])
        revenue_per_yuan = orders_per_yuan * aov_cny
        roi_point = round(revenue_per_yuan - 1, 2)
        warnings = [
            "未计入退货、归因窗口与版位差异；上线前由投手用账户真实CVR复核",
        ]
        if fx_meta.get("warning"):
            warnings.append(fx_meta["warning"])
        roi_range = {
            "point_estimate": roi_point,
            "band": [round(roi_point * 0.7, 2), round(roi_point * 1.2, 2)],
            "formula": "ROI ≈ (1/CPC_CNY)×CVR×客单价_CNY - 1；客单价取价带中值并换汇",
            "aov_native": aov_native,
            "aov_cny": aov_cny,
            "currency": fx_meta.get("currency"),
            "fx_to_cny": fx_meta.get("fx_to_cny"),
            "warning": "；".join(warnings),
        }
        forecast_status = "有CPC/CTR/CVR且客单价可换汇为CNY时可给ROI粗算 + 测试带宽"
    elif cpc and ctr and cvr and aov_cny is None:
        forecast_status = f"币种 {req.currency} 无法换汇为 CNY：拒绝输出 ROI，仅保留测试带宽"
    elif cpc:
        forecast_status = "仅有CPC：可给出价与止损，ROI区间仍待CVR"

    return {
        "status": forecast_status,
        "benchmarks_present": sorted(benchmarks.keys()),
        "test_bandwidth": {
            "formula": "首轮测试预算 = min(聚光预算×15%, 目标CPA×最小转化样本×1.5)",
            "cold_start_budget_cny": test_budget,
            "min_conversions_for_decision": min_conversions,
            "min_impressions": min_impressions,
            "min_clicks": min_clicks,
            "target_cpa_used_cny": round(target_cpa, 2) if target_cpa else None,
            "decision_conclusion": (
                f"首轮只用约 ¥{test_budget:,} 做可比较测试；未达最小转化/点击样本前不放大预算。"
            ),
        },
        "stop_loss": {
            "formula": (
                "若 (CPC>历史×1.5 或 CPA>目标×1.2) 且 (曝光≥最小样本 或 点击≥最小点击) → 暂停该素材/定向"
            ),
            "cpc_stop_cny": stop_cpc,
            "cpa_stop_cny": stop_cpa,
            "min_impressions": min_impressions,
            "min_clicks": min_clicks,
            "owner": "投手确认后执行",
        },
        "roi_range": roi_range,
        "fx": fx_meta,
        "note": "无完整CTR/CVR/可换汇客单价时不输出承诺式效果区间，只给测试带宽与止损公式",
    }


def _risk_playbook_sop(req: CampaignRequest | None = None) -> list[dict[str, Any]]:
    playbook = [
        {
            "issue": "冷启动无量",
            "diagnosis": [
                "出价低于账户建议价过多",
                "定向过窄或人群包过小",
                "素材审核中/拒审导致无法进入竞价",
            ],
            "actions_0_2h": [
                "核对单元状态与拒审原因",
                "将出价调至建议价的90%–100%，保持其他变量不变",
                "若定向预估覆盖过低，复制单元并放宽一层兴趣/相似",
            ],
            "actions_2_24h": [
                "仍无量则更换首屏封面/标题再开测",
                "单次只改出价或只改定向，禁止同时大改",
            ],
            "stop_or_escalate": "连续两个观察窗无有效曝光且非审核问题 → 暂停该单元，升级投手复核账户限额",
            "owner": "优化师执行 / 投手确认放量",
        },
        {
            "issue": "点击成本过高",
            "diagnosis": [
                "CPC持续高于历史×1.3",
                "搜索词过宽导致无效点击",
                "素材吸引力不足但竞价偏高",
            ],
            "actions_0_2h": [
                "暂停高消耗低CTR素材",
                "搜索单元加否定词，收缩到高意向长尾",
            ],
            "actions_2_24h": [
                "按测试带宽重开对照组：原价 vs -10%出价",
                "CTR仍低则优先换素材，而非持续提价抢量",
            ],
            "stop_or_escalate": "CPC>止损线且点击达最小样本 → 暂停该定向包",
            "owner": "优化师",
        },
        {
            "issue": "点击高但转化低",
            "diagnosis": [
                "人群意图与商品页不匹配",
                "价格力/库存/落地页加载问题",
                "归因延迟或转化目标设置错误",
            ],
            "actions_0_2h": [
                "检查商品页价格、券、库存与加载",
                "核对转化目标与像素/店铺归因是否一致",
            ],
            "actions_2_24h": [
                "把预算从宽兴趣切到高意向搜索词",
                "素材话术对齐落地页主利益点，减少预期落差",
            ],
            "stop_or_escalate": "CPA>止损线且转化样本足够 → 暂停该人群，保留搜索承接",
            "owner": "优化师 + 电商运营",
        },
        {
            "issue": "素材衰退",
            "diagnosis": [
                "同素材连续多日CTR下滑",
                "频次过高导致审美疲劳",
                "竞品同期加投同类钩子",
            ],
            "actions_0_2h": [
                "标记衰退素材，降低其预算份额",
                "启用已过自然门槛的备份素材",
            ],
            "actions_2_24h": [
                "按“方向×标题×封面”矩阵轮换，每周至少2组新组合",
                "保留1个对照旧素材用于衰退斜率对比",
            ],
            "stop_or_escalate": "CTR较自身峰值下降>30%且消耗仍高 → 停投并归档",
            "owner": "内容 + 优化师",
        },
        {
            "issue": "审核拒绝",
            "diagnosis": [
                "绝对化/功效承诺/虚假稀缺",
                "资质不全或跨境表述不合规",
                "未披露商业合作",
            ],
            "actions_0_2h": [
                "对照拒审原因改文案与主图",
                "补齐食品/跨境所需资质后再提审",
            ],
            "actions_2_24h": [
                "把拒审原因写入账户违规台账",
                "同类表述加入发布前黑名单检查",
            ],
            "stop_or_escalate": "同原因连续拒审≥2次 → 升级合规复核，禁止反复撞审",
            "owner": "合规预审 + 投手",
        },
    ]
    scenario_by_issue: dict[str, Any] = {}
    if req:
        for item in req.paid_risk_demo_scenarios:
            scenario_by_issue[item.issue] = item
    for entry in playbook:
        scenario = scenario_by_issue.get(entry["issue"])
        if not scenario:
            continue
        entry["demo_scenario"] = {
            "data_type": MOCK_DATA_TYPE,
            "is_mock": True,
            "evidence_grade": "M" if scenario.is_mock else (scenario.evidence_grade or "C"),
            "warning": MOCK_WARNING if scenario.is_mock else None,
            "source_name": scenario.source_name,
            "collected_at": scenario.collected_at,
            "example_diagnosis": scenario.example_diagnosis,
            "demo_signals": scenario.demo_signals,
            "notes": scenario.notes,
            "mock_seed": scenario.mock_seed if scenario.is_mock else None,
            "mock_basis": scenario.notes if scenario.is_mock else None,
        }
    return playbook


def _score_trending_keywords(req: CampaignRequest) -> dict[str, Any]:
    items = req.trending_keyword_evidence
    if not items:
        return {
            "status": "已降级：无合规趋势源；请人工粘贴热搜词后再评分",
            "input_mode": "manual_paste_required",
            "scored_keywords": [],
            "rising_keywords": [],
            "decision_rule": "相关性、增长速度、内容供给缺口、品牌风险四项评分后再跟进",
            "how_to_supply": (
                "在请求中提交 trending_keyword_evidence，或在页面粘贴热搜词"
                "（来源填：人工粘贴热搜词 / 合规趋势工具名）"
            ),
            "data_source_note": (
                "未接入官方实时热搜 API；当前无导入词，不输出跟进建议。"
            ),
        }
    scored = []
    category_blob = f"{req.category} {req.product_name} {' '.join(req.selling_points)}".casefold()
    risk_markers = ("最好", "第一", "治愈", "根除", "100%", "必买不踩雷")
    for item in items:
        kw = item.keyword.strip()
        if not kw:
            continue
        relevance = 3 if any(
            token and token in kw.casefold()
            for token in re.split(r"[/／|｜,，、;；\s\-－—]+", category_blob)
            if len(token) >= 2
        ) else (2 if req.category[:2] in kw else 1)
        growth = 3 if (item.heat_score or 0) >= 80 else (2 if (item.heat_score or 0) >= 50 else 1)
        # 供给缺口：知识库主题未覆盖则更高
        themes = {c["theme"] for c in _cluster_evidence_themes(req)}
        supply_gap = 3 if kw not in themes and not any(kw in t or t in kw for t in themes) else 1
        risk = 1 if any(marker in kw for marker in risk_markers) else 3
        total = relevance + growth + supply_gap + risk
        is_mock = bool(item.is_mock)
        follow = total >= 9 and risk >= 3
        recommendation = "跟进" if follow else ("不跟进" if risk < 3 else "观察")
        scored.append({
            "keyword": kw,
            "heat_score": item.heat_score,
            "source_name": item.source_name,
            "collected_at": item.collected_at,
            "scores": {
                "relevance": relevance,
                "growth": growth,
                "supply_gap": supply_gap,
                "brand_risk_safety": risk,
                "total": total,
            },
            "recommendation": recommendation,
            "action": "可跟进测试" if follow else "谨慎或放弃",
            "reason": (
                "相关性/增速/供给缺口/品牌风险四项达标，建议小预算内容跟进"
                if follow
                else (
                    "品牌风险项未满分，禁止跟进"
                    if risk < 3
                    else "总分未达跟进线，仅观察或小样本试探"
                )
            ),
            "notes": item.notes,
            "is_mock": is_mock,
            "data_type": MOCK_DATA_TYPE if is_mock else "真实样本",
            "evidence_grade": "M" if is_mock else (item.evidence_grade or "C"),
            "mock_seed": item.mock_seed if is_mock else None,
            "mock_basis": item.notes if is_mock else None,
            "warning": MOCK_WARNING if is_mock else None,
        })
    scored.sort(key=lambda row: (-row["scores"]["total"], row["keyword"]))
    all_mock = bool(scored) and all(row["is_mock"] for row in scored)
    rising = [row for row in scored if row.get("recommendation") == "跟进"]
    return {
        "status": (
            "已对 Mock 演示热搜情景评分（非实时热搜）"
            if all_mock
            else "已对人工/合规源热搜词评分"
        ),
        "input_mode": "mock_demo" if all_mock else "evidence_supplied",
        "scored_keywords": scored,
        "rising_keywords": rising,
        "decision_rule": "总分≥9且品牌风险项满分才「跟进」；否则「观察」或「不跟进」",
        "how_to_supply": None,
        "warning": MOCK_WARNING if all_mock else None,
        "data_source_note": (
            "未接入官方实时热搜 API 时，仅消费请求内 trending_keyword_evidence / 合规导入词；"
            "禁止伪装为平台实时抓取。"
        ),
    }


def _module_outputs(
    req: CampaignRequest, *, allow_mock: bool, mock_seed: str | None
) -> dict[str, Any]:
    organic_ratio, paid_ratio = _budget_ratios(req.goal)
    paid_budget = req.spotlight_budget_cny or req.total_budget_cny * paid_ratio
    organic_budget = req.total_budget_cny - paid_budget
    keywords = _keyword_library(req)
    benchmarks = _benchmark_map(req)
    creator_recommendations, creator_tier_plan, creator_roster = _creator_plan(
        req,
        organic_budget=organic_budget,
        paid_budget=paid_budget,
    )
    preferred_rule_order = {
        "食品行业规则&投放规则": 0,
        "内容审核规则总则": 1,
        "跨境广告内容规范": 2,
        "专业号合规经营指南：自查与规范手册": 3,
        "治理公告&违规公示": 4,
        "商业化风险积分管理规则": 5,
    }
    ordered_official_rules = sorted(
        req.official_rule_evidence,
        key=lambda rule: preferred_rule_order.get(rule.title, 99),
    )
    official_rule_sources = [
        {
            "title": rule.title,
            "source_url": rule.source_url,
            "source_updated_at": rule.source_updated_at,
            "collected_at": rule.collected_at,
        }
        for rule in ordered_official_rules
    ]
    official_risk_items: list[dict[str, str]] = []
    seen_risk_items: set[str] = set()
    for rule in ordered_official_rules:
        for item in rule.risk_items:
            if item in seen_risk_items:
                continue
            seen_risk_items.add(item)
            official_risk_items.append({
                "rule_title": rule.title,
                "risk_item": item,
                "source_url": rule.source_url,
            })
    review_risk_items = [
        item
        for item in official_risk_items
        if any(
            marker in item["risk_item"]
            for marker in ("审核", "驳回", "资质", "不得", "禁止")
        )
    ]
    violation_rows = sorted(
        (
            {
                "reason": item.reason,
                "occurrence_count": item.occurrence_count,
                "period": item.period,
                "source_name": item.source_name,
                "collected_at": item.collected_at,
                "notes": item.notes,
                "is_mock": bool(item.is_mock),
                "data_type": MOCK_DATA_TYPE if item.is_mock else "真实样本",
                "evidence_grade": "M" if item.is_mock else (item.evidence_grade or "C"),
                "mock_seed": item.mock_seed if item.is_mock else None,
                "mock_basis": item.notes if item.is_mock else None,
                "warning": MOCK_WARNING if item.is_mock else None,
            }
            for item in req.account_violation_evidence
        ),
        key=lambda row: (-row["occurrence_count"], row["reason"]),
    )
    organic_market = _category_market_summary(req)
    topic_pack = _content_topics(req)
    module1 = {
        "analysis_window_days": req.analysis_days,
        "owned_content_history": {
            "status": "已接入品牌自有月度数据" if req.owned_content_history else "暂无品牌自有月度数据",
            "period_count": len(req.owned_content_history),
            "periods": req.owned_content_history,
            "warning": "该数据来自品牌导入文件，不代表平台全量内容大盘。",
        },
        "organic_market": organic_market,
        "simulated_platform_market": (
            build_mock_platform_market(req, mock_seed=mock_seed)
            if allow_mock else None
        ),
        "spotlight_market": _spotlight_market_summary(
            req, benchmarks, allow_mock=allow_mock, mock_seed=mock_seed
        ),
        "competitor_full_funnel": _competitor_market_summary(
            req, allow_mock=allow_mock, mock_seed=mock_seed
        ),
        "risk_warning": {
            "official_rules": {
                "label": "官方规则（合规底线，不等于赛道高频）",
                "status": (
                    "已接入小红书官方公开规则"
                    if official_rule_sources
                    else "待接入官方规则"
                ),
                "confirmed_types": official_risk_items[:12],
                "official_sources": official_rule_sources,
                "decision_conclusion": (
                    "按官方规则做发布前必检项；条文存在≠该赛道近期高发。"
                    if official_rule_sources
                    else "缺少官方规则证据时，仍对绝对化、功效承诺、未披露合作做人工预审。"
                ),
            },
            "category_high_frequency_violations": {
                "label": "赛道高频违规/拒审（需台账频次）",
                "status": (
                    "已接入账户/赛道违规台账，可按频次排序"
                    if violation_rows
                    else "待导入拒审/违规台账；当前禁止把官方规则列表称作赛道高频"
                ),
                "ranked_reasons": violation_rows[:12],
                "decision_conclusion": (
                    f"台账显示高频原因以“{violation_rows[0]['reason']}”为首，发布前优先规避。"
                    if violation_rows
                    else "无频次证据时不输出“赛道高频违规榜”；仅保留官方规则检查 + 建立台账动作。"
                ),
            },
            # 兼容旧字段：官方规则检查项
            "recent_restricted_content_types": {
                "status": (
                    "官方规则风险项（非赛道频次）"
                    if official_rule_sources
                    else "待接入近期官方规则、处罚案例或账号违规记录"
                ),
                "confirmed_types": official_risk_items[:12],
                "official_sources": official_rule_sources,
                "decision_conclusion": (
                    "已按官方规则形成发布前风险检查项；高频与否见 category_high_frequency_violations。"
                    if official_rule_sources
                    else
                    "尚不能认定该赛道近期存在特定限流类型；发布前对功效承诺、绝对化表述、"
                    "虚假稀缺和未披露商业合作执行人工预审。"
                ),
            },
            "frequent_ad_rejection_reasons": {
                "status": (
                    "官方审核规则条目（频次见台账）"
                    if official_rule_sources
                    else "待导入聚光审核记录后按拒审原因统计"
                ),
                "confirmed_reasons": review_risk_items[:12] if not violation_rows else [],
                "account_ledger_reasons": violation_rows[:12],
                "official_sources": official_rule_sources,
                "decision_conclusion": (
                    "高频排名仅来自 account_violation_evidence；官方规则只作预审清单。"
                    if violation_rows
                    else (
                        "先按官方审核风险项预审素材；当前没有拒审次数，不能称为高频排名。"
                        if official_rule_sources
                        else "当前没有该账户拒审频次证据；先建立拒审台账。"
                    )
                ),
            },
            "baseline_checks": [
                "避免绝对化、最高级、无法证明的功效或收益承诺",
                "广告笔记、赞助合作和数据采集必须遵守平台规则与适用法律",
                "官方规则与赛道高频台账必须分开表述，不可混用",
            ],
        },
    }
    module2 = _build_module2_audience(req, topic_pack)
    dual_track = _build_dual_track_keyword_library(req, keywords, benchmarks)
    trending = _score_trending_keywords(req)
    organic_dual = dual_track.get("organic_traffic") or {}
    paid_mix = {"core": 0.30, "long_tail": 0.50, "blue_ocean": 0.20}
    level_split = keywords.get("level_budget_split") or paid_mix
    module6 = {
        "module_goal": "产出三级词库、布局策略与热搜跟进建议，供达人匹配与聚光词库承接",
        "inputs": {
            "brand_name": req.brand_name,
            "product_name": req.product_name,
            "category": req.category,
            "selling_points": list(req.selling_points or [])[:6],
            "from_module1_themes": list(keywords.get("evidence_themes") or [])[:8],
        },
        "keyword_pipeline": keywords.get("pipeline"),
        "status": keywords.get("status"),
        "keyword_levels": {
            "core": list(keywords.get("core") or []),
            "long_tail": list(keywords.get("long_tail") or []),
            "blue_ocean": list(keywords.get("blue_ocean_candidates") or []),
            "blue_ocean_candidates": list(keywords.get("blue_ocean_candidates") or []),
        },
        "layout": {
            "title": (organic_dual.get("layout_rule") or {}).get("title")
            or "自然放入1个核心词或高意向长尾词，避免堆砌",
            "body": (organic_dual.get("layout_rule") or {}).get("body")
            or "首段说明场景，中段围绕卖点自然覆盖相关词",
            "tags": (organic_dual.get("layout_rule") or {}).get("tags")
            or "核心词、场景词、目标人群词组合，并以实测搜索表现迭代",
            "paid_mix": {
                "core": float(level_split.get("core", 0.30)),
                "long_tail": float(level_split.get("long_tail", 0.50)),
                "blue_ocean_test": float(
                    level_split.get("blue_ocean")
                    or level_split.get("blue_ocean_test")
                    or 0.20
                ),
            },
            "layout_plan": organic_dual.get("layout_plan") or {},
            "layout_rule": organic_dual.get("layout_rule") or {},
            "frequency_guide": {
                "title": "1 个主词（核心或高意向长尾），不堆砌",
                "body": "场景词出现在首段；卖点/长尾自然覆盖 2–4 次",
                "tags": "3–6 个标签：核心 + 场景 + 人群，可带 1 个蓝海待验证词",
            },
        },
        "level_budget_split": {
            "core": float(level_split.get("core", 0.30)),
            "long_tail": float(level_split.get("long_tail", 0.50)),
            "blue_ocean": float(
                level_split.get("blue_ocean") or level_split.get("blue_ocean_test") or 0.20
            ),
        },
        "trending_monitor": trending,
        "handoff_to_module3": {
            "core": list(keywords.get("core") or []),
            "long_tail": list(keywords.get("long_tail") or []),
            "blue_ocean": list(keywords.get("blue_ocean_candidates") or []),
            "layout_plan": organic_dual.get("layout_plan") or {},
            "rising_follow": [
                row.get("keyword")
                for row in (trending.get("rising_keywords") or trending.get("scored_keywords") or [])
                if row.get("recommendation") == "跟进" or row.get("action") == "可跟进测试"
            ][:5],
        },
    }
    module3 = {
        "module_goal": "承接关键词策略词库，完成聚光双轨出价词与达人分层匹配",
        "input_summary": {
            "brand_product": f"{req.brand_name}｜{req.product_name}",
            "total_campaign_budget_cny": _round_money(req.total_budget_cny),
            "upstream_signals_used": [
                req.category,
                req.initial_audience,
                *req.selling_points[:3],
            ],
            "keyword_strategy_pipeline": module6.get("keyword_pipeline"),
        },
        "keyword_strategy_ref": {
            "status": module6.get("status"),
            "pipeline": module6.get("keyword_pipeline"),
            "levels": module6.get("keyword_levels"),
            "level_budget_split": module6.get("level_budget_split"),
            "layout_plan": (module6.get("layout") or {}).get("layout_plan") or {},
            "rising_follow": (module6.get("handoff_to_module3") or {}).get("rising_follow") or [],
            "note": "达人匹配与聚光词库必须承接关键词策略三级词库，不得另起一套互斥词表",
        },
        "dual_track_keyword_library": dual_track,
        "creator_tier_plan": creator_tier_plan,
        "creator_candidates": creator_recommendations,
        "creator_recommendations_20": creator_recommendations,
        "creator_roster": creator_roster,
        "creator_data_status": (
            (
                f"真实候选 {creator_roster['real_candidate_count']} 位；"
                f"Mock 演示候选 {creator_roster['mock_candidate_count']} 位"
                f"（非推荐名单）；开放槽位 {creator_roster['open_slot_count']}"
            )
            if creator_recommendations
            else "未提供达人证据：不输出推荐名单，仅保留分层预算与开放槽位，请导入 CSV"
        ),
    }
    spotlight_objective = {
        "awareness": "产品种草",
        "engagement": "产品种草",
        "search_growth": "产品种草",
        "conversion": "商品成交",
        "leads": "客资收集",
        "live_traffic": "直播引流",
    }.get(req.goal, "产品种草")
    forecast_block = _forecast_block(req, paid_budget=paid_budget, benchmarks=benchmarks)
    from tools.budget import search_feed_share_for_goal as _search_feed_share

    m4_search_feed = _search_feed_share(req.goal)
    cpc_row = benchmarks.get("cpc") or {}
    cpc_val = cpc_row.get("value") if isinstance(cpc_row, dict) else None
    cold_bid = {
        "method": "稳定成本出价（优先账户可用的稳定成本/成本上限类策略）",
        "bid_low_cny": round(float(cpc_val) * 0.9, 2) if isinstance(cpc_val, (int, float)) else None,
        "bid_high_cny": round(float(cpc_val) * 1.1, 2) if isinstance(cpc_val, (int, float)) else None,
        "basis": (
            f"以历史/报表 CPC={cpc_val} 为锚，冷启动落在建议价 90%–110%；无 CPC 时以上线账户建议价为准"
            if isinstance(cpc_val, (int, float))
            else "缺基准 CPC：初始出价以上线时账户建议价为准，不编造金额"
        ),
    }
    module4 = {
        "account_structure": {
            "hierarchy_logic": (
                f"按推广目标「{spotlight_objective}」× 版位（搜索/信息流）× 定向类型拆计划；"
                "搜索与信息流分计划，不在同一单元混测定向与素材。"
            ),
            "plans": [
                {
                    "name": f"{spotlight_objective}_搜索_高意向",
                    "objective": spotlight_objective,
                    "placement": "搜索推广",
                    "budget_ratio": 0.40,
                    "budget_share": 0.40,
                },
                {
                    "name": f"{spotlight_objective}_信息流_精准",
                    "objective": spotlight_objective,
                    "placement": "信息流推广",
                    "budget_ratio": 0.35,
                    "budget_share": 0.35,
                },
                {
                    "name": f"{spotlight_objective}_信息流_扩量",
                    "objective": spotlight_objective,
                    "placement": "信息流推广",
                    "budget_ratio": 0.25,
                    "budget_share": 0.25,
                },
            ],
            "unit_naming": "目标_渠道_定向包_素材方向_日期",
            "unit_naming_rule": "目标_渠道_定向包_素材方向_日期",
            "creative_test": "3个内容方向 × 2个标题 × 2个封面，小预算正交测试",
            "creative_grouping": (
                "创意分组：按「内容方向」建组；组内做标题×封面正交，正文随方向固定；"
                "同组只改一个变量，便于归因。"
            ),
        },
        "daily_schedules": _daily_schedules(req, organic_market),
        "targeting_packages": [
            {
                "name": "精准定向",
                "package": "精准定向",
                "ratio": 0.45,
                "budget_share": 0.45,
                "expansion": False,
                "smart_expansion": False,
                "stage": "冷启动",
                "applicable_stage": "冷启动/预热",
                "audience_desc": f"高意向：品类搜索词 + {req.initial_audience or '目标人群'} + 核心卖点兴趣",
            },
            {
                "name": "宽定向",
                "package": "宽定向",
                "ratio": 0.30,
                "budget_share": 0.30,
                "expansion": True,
                "smart_expansion": True,
                "stage": "探索/放量",
                "applicable_stage": "探索/放量",
                "audience_desc": f"品类泛兴趣 + 智能扩量，用于发现增量人群（{req.category}）",
            },
            {
                "name": "达人相似定向",
                "package": "达人相似定向",
                "ratio": 0.25,
                "budget_share": 0.25,
                "expansion": True,
                "smart_expansion": True,
                "stage": "有种子人群后",
                "applicable_stage": "有达人/转化种子后",
                "audience_desc": "达人粉丝相似 / 转化用户 Lookalike，种子不足时降权",
            },
        ],
        "bidding": {
            "cold_start": cold_bid,
            "scale_rule": "连续两个观察窗口成本低于目标10%且转化量稳定，单次提价不超过5%",
            "scaling_rules": [
                "成本低于目标 10% 且转化稳定 → 提价 5%",
                "成本高于目标 10% 但未触止损 → 降价 5%–10% 或缩预算",
                "达最小样本后仍无转化 → 先换素材/定向，不同时大改出价与人群",
            ],
            "stop_loss": "成本高于目标20%且达到最小样本量时暂停素材或定向包",
        },
        "search_feed_split": {
            "search": m4_search_feed["search_ratio"],
            "feed": m4_search_feed["feed_ratio"],
            "synergy_note": (
                "搜索计划承接主动搜索高意向词；信息流对搜索点击/互动/收藏用户做相似扩量二次触达；"
                "创意池可复用，但预算与出价分计划控制，避免搜推抢量互抬成本。"
            ),
        },
        "forecast": forecast_block,
        "risk_playbook": _risk_playbook_sop(req),
        "inputs": {
            "spotlight_budget_cny": _round_money(paid_budget),
            "campaign_days": req.campaign_days,
            "promotion_goal": spotlight_objective,
            "campaign_goal": req.goal,
        },
    }
    from tools.budget import (
        all_goal_split_matrix,
        build_campaign_phases,
        build_emergency_adjustments,
        build_organic_paid_synergy,
        goal_split_guide,
    )

    split_guide = goal_split_guide(req.goal)
    campaign_phases = build_campaign_phases(
        campaign_days=req.campaign_days,
        paid_budget_cny=paid_budget,
    )
    screening = module2.get("material_screening") or module2.get("paid_material_gate") or {}
    directions = [
        str(row.get("name") or row.get("direction") or "").strip()
        for row in (module2.get("content_directions") or [])
        if str(row.get("name") or row.get("direction") or "").strip()
    ]
    handoff = module3.get("keyword_strategy_ref") or {}
    search_kw = [
        str(row.get("keyword") or "").strip()
        for row in (
            ((module3.get("dual_track_keyword_library") or {})
             .get("spotlight_paid") or {})
            .get("search_promotion") or {}
        ).get("keywords")
        or []
        if str(row.get("keyword") or "").strip()
    ]
    rising_follow = [
        str(x).strip() for x in (handoff.get("rising_follow") or []) if str(x).strip()
    ]
    if not rising_follow:
        trending_rows = (module6.get("trending_monitor") or {}).get("rising_keywords") or (
            module6.get("trending_monitor") or {}
        ).get("scored_keywords") or []
        rising_follow = [
            str(row.get("keyword") or "").strip()
            for row in trending_rows
            if (
                str(row.get("recommendation") or "") == "跟进"
                or str(row.get("action") or "") == "可跟进测试"
            )
            and str(row.get("keyword") or "").strip()
        ]
    probe_budget = (module4.get("forecast") or {}).get("test_bandwidth", {}).get(
        "cold_start_budget_cny"
    )
    synergy = build_organic_paid_synergy(
        material_screening=screening,
        probe_budget_cny=probe_budget,
        search_keywords=search_kw,
        rising_follow=rising_follow,
        content_directions=directions,
        goal=req.goal,
    )
    emergency_playbook = build_emergency_adjustments(
        phases=campaign_phases,
        goal=req.goal,
        organic_budget_cny=organic_budget,
        paid_budget_cny=paid_budget,
    )
    module5 = {
        "budget": {
            "organic_content_cny": _round_money(organic_budget),
            "spotlight_cny": _round_money(paid_budget),
            "organic_ratio": round(organic_ratio, 2),
            "spotlight_ratio": round(paid_ratio, 2),
            "ratio_label": split_guide["ratio_label"],
            "goal": req.goal,
            "goal_label": split_guide["goal_label"],
            "split_rationale": split_guide["rationale"],
            "total_budget_cny": _round_money(req.total_budget_cny),
            "campaign_days": req.campaign_days,
            "goal_split_matrix": all_goal_split_matrix(),
        },
        "phases": campaign_phases,
        "pacing_rule": "聚光预算按预热20% → 爆发60% → 长尾20% 分配；天数随投放周期切分，尾差归爆发期。",
        "coordination": synergy["principle"],
        "organic_paid_synergy": synergy,
        "emergency_rules": [
            f"{row['scenario']}：{row['budget_adjustment']}" for row in emergency_playbook[:3]
        ],
        "emergency_playbook": emergency_playbook,
        "upstream_handoff": {
            "from_modules": [
                "module_1_market_competitor",
                "module_2_audience_content",
                "module_6_keyword_strategy",
                "module_3_keyword_creator",
                "module_4_spotlight_decision",
            ],
            "note": (
                "本页汇总总预算/周期/目标，并承接画像素材门槛、关键词策略词包、"
                "达人分层预算与聚光探测/止损，形成自然流+付费流协同节奏。"
            ),
            "material_gate": synergy["start_paid_when"]["rule_text"],
            "probe_budget_cny": probe_budget,
            "search_keywords": search_kw[:6],
            "content_directions": directions,
        },
    }
    return {
        "module_1_market_competitor": module1,
        "module_2_audience_content": module2,
        "module_3_keyword_creator": module3,
        "module_4_spotlight_decision": module4,
        "module_5_budget_pacing": module5,
        "module_6_keyword_strategy": module6,
    }


def _markdown(req: CampaignRequest, modules: dict[str, Any], gaps: list[EvidenceGap]) -> str:
    budget = modules["module_5_budget_pacing"]["budget"]
    topics = modules["module_2_audience_content"]["topics"][:5]
    gap_lines = "\n".join(f"- **{g.field}**：{g.impact}；建议：{g.recommended_source}" for g in gaps) or "- 当前关键数据证据齐全。"
    topic_lines = "\n".join(
        f"{t['id']}. {t['title_template']}"
        f"（自然 {t.get('organic_potential') or '待评'}/10，投流 {t.get('paid_conversion_potential') or '待评'}/10）"
        for t in topics
    )
    module3 = modules["module_3_keyword_creator"]
    dual = module3["dual_track_keyword_library"]
    organic_keywords = dual["organic_traffic"]
    search_keywords = dual["spotlight_paid"]["search_promotion"]["keywords"]
    feed_keywords = dual["spotlight_paid"]["feed_interest"]["keywords"]
    layout_plan = organic_keywords.get("layout_plan") or {}
    creator_tiers = module3["creator_tier_plan"]["tiers"]
    forecast = modules["module_4_spotlight_decision"]["forecast"]
    schedules = modules["module_4_spotlight_decision"]["daily_schedules"]["slots"][:5]
    schedule_lines = "\n".join(
        f"- {s['slot']}：{s['role']}（预算份额提示 {int(s['budget_share_hint'] * 100)}%）"
        for s in schedules
    )
    risk_playbook = modules["module_4_spotlight_decision"]["risk_playbook"]
    risk_lines = "\n".join(
        (
            f"- **{item['issue']}**：{item['demo_scenario']['example_diagnosis']}"
            if item.get("demo_scenario", {}).get("example_diagnosis")
            else f"- **{item['issue']}**：完整 SOP（0–2h / 2–24h / 止损升级）已就绪"
        )
        for item in risk_playbook
    )
    keyword_lines = "\n".join(
        f"- {item['keyword']}：¥{item['suggested_bid_range']['low_cny_per_click'] or '待定'}"
        f"–¥{item['suggested_bid_range']['high_cny_per_click'] or '待定'}/点击"
        f"（{item.get('intent') or '搜索词'}）"
        for item in search_keywords[:8]
    )
    feed_lines = "\n".join(
        f"- {item.get('interest_word') or item.get('keyword')}："
        f"¥{(item.get('suggested_bid_range') or {}).get('low_cny_per_click') or '待定'}"
        f"–¥{(item.get('suggested_bid_range') or {}).get('high_cny_per_click') or '待定'}/点击"
        for item in feed_keywords[:6]
    ) or "- 待生成信息流兴趣词"
    creator_lines = "\n".join(
        f"- {item['tier']}：{item['count']}人，合作预算 ¥{item['collaboration_budget_cny']:,}，"
        f"每篇建议聚光投流 ¥{item['suggested_spotlight_per_note_cny']:,}"
        for item in creator_tiers
    )
    creator_rows = module3.get("creator_candidates") or []
    verified_creator_lines = "\n".join(
        f"- {c['creator_name']}（{c['tier']}，匹配分 {c['audience_match_score']}）"
        for c in creator_rows if not c.get("is_mock")
    ) or "- 暂无真实达人候选，请导入 CSV"
    mock_creator_lines = "\n".join(
        f"- {c['creator_name']}（{c['tier']}，匹配分 {c['audience_match_score']}；Mock 演示，非推荐）"
        for c in creator_rows if c.get("is_mock")
    ) or "- 本次未注入 Mock 达人演示候选"
    trending = modules["module_6_keyword_strategy"]["trending_monitor"]
    module1 = modules["module_1_market_competitor"]
    platform_market = module1.get("simulated_platform_market") or {}
    mock_seed = platform_market.get("mock_seed")
    spotlight = module1["spotlight_market"]
    competitor = module1["competitor_full_funnel"]
    mock_candidates = [
        ("CPC", spotlight["average_cpc"]),
        ("CPM", spotlight["average_cpm"]),
        ("CTR", spotlight.get("average_ctr") or {}),
        ("单次互动成本", spotlight.get("interaction_cost") or {}),
        ("转化成本", spotlight["conversion_cost"]),
        ("搜索／信息流预算占比", spotlight["search_feed_budget_share"]),
        ("推广目标排序", spotlight["popular_promotion_goals"]),
        ("平台流量探索方向", spotlight["latest_traffic_direction_2026"]),
        ("竞品定向测试假设", competitor["targeting_inference"]),
        ("竞品预算验证情景", competitor["budget_range"]),
    ]
    mock_lines = "\n".join(
        f"- **{label}**：模拟数据（Mock）；依据：{row.get('mock_basis') or '系统情景模拟'}；"
        f"提示：{row.get('warning') or MOCK_WARNING}"
        for label, row in mock_candidates
        if row.get("is_mock") is True
    ) or "- 本次未启用模拟数据（Mock），缺失字段保持为空。"
    return f"""# {req.brand_name}｜{req.product_name} 小红书全域投放策略

## 决策摘要

- 核心目标：{GOAL_LABELS[req.goal]}
- 周期：{req.campaign_days} 天
- 总预算：¥{_round_money(req.total_budget_cny):,}
- 自然内容预算：¥{budget['organic_content_cny']:,}
- 聚光预算：¥{budget['spotlight_cny']:,}
- 核心人群：{req.initial_audience}
- 选题管线：{modules['module_2_audience_content'].get('topic_pipeline', '—')}
- 首轮测试带宽：¥{forecast['test_bandwidth']['cold_start_budget_cny']:,}
{f"- Mock种子：`{mock_seed}`（同一种子可复现；换种子可生成新一组）" if mock_seed else ""}

## 数据可信度与缺口

{gap_lines}

## 模拟数据（Mock）清单

{mock_lines}

## 内容策略

主方向为场景痛点、产品证据和对比决策。首批建议选题：

{topic_lines}

## 关键词与达人匹配

### 双轨关键词库

- 词库管线：{dual.get('pipeline', '—')}
- 自然流量词库（标题/正文/标签）：
  - 核心词：{"、".join(organic_keywords.get("core_keywords") or []) or "—"}
  - 长尾词：{"、".join(organic_keywords.get("long_tail_keywords") or []) or "—"}
  - 场景词：{"、".join(organic_keywords.get("scene_keywords") or []) or "—"}
  - 人群词：{"、".join(organic_keywords.get("audience_keywords") or []) or "—"}
  - 布局示例：{layout_plan.get("example") or "—"}
- 聚光搜索推广词（高意向长尾）及出价：

{keyword_lines}

- 信息流兴趣词（泛需求）及出价：

{feed_lines}

达人分层方案：

{creator_lines}

真实达人候选：

{verified_creator_lines}

Mock 演示达人（禁止当作真实推荐）：

{mock_creator_lines}

达人名单状态：{module3["creator_data_status"]}。

## 聚光账户与测试策略

- 搜索/信息流预算建议：{module4.get("search_feed_split", {}).get("search", 0.4):.0%} / {module4.get("search_feed_split", {}).get("feed", 0.6):.0%}。
- 每日时段：
{schedule_lines}
- 精准、宽定向、达人相似三类定向包分别独立建单元。
- 使用“3个方向 × 2个标题 × 2个封面”测试，避免一次同时修改所有变量。
- 效果预估状态：{forecast['status']}；止损公式见模块4（CPC/CPA 阈值 × 最小样本）。
- 五个投流问题完整 SOP：
{risk_lines}

## 热搜与趋势

- 状态：{trending['status']}
- 规则：{trending['decision_rule']}

## 全域节奏

- 预热期：20% 聚光预算，自然内容铺量并筛选素材。
- 爆发期：60% 聚光预算，放大胜出素材。
- 长尾期：20% 聚光预算，持续投放并占位搜索词。

## 合规边界

达人名单、热搜、竞品投流和真实效果必须来自官方、品牌自有或获授权的数据。标记为“模拟数据（Mock）”的字段只用于方案演示和敏感性分析，不代表真实平台、竞品或账户事实，执行前必须由投手用后台数据替换。官方规则与赛道高频违规台账分开表述。
"""


def _model_polish(req: CampaignRequest, report: str) -> tuple[str, dict[str, Any]]:
    from model_config import chat_request_extras, load_analyzer_config

    config = load_analyzer_config()
    api_key = config["api_key"]
    if not api_key or api_key in {"你的模型平台 Key", "your-api-key", "YOUR_API_KEY"}:
        return report, {"stage": "model_polish", "status": "skipped", "reason": "model_key_missing"}
    base_url = config["base_url"]
    model = config["model"]
    system = (
        "你是小红书投放策略顾问。只能依据用户提供的报告润色表达，不得新增实时数据、"
        "达人、报价、平台政策、CPC/CPM或效果承诺。必须保留管理层摘要、七章分析、"
        "全部数字、数据标识、Mock种子、证据边界、执行方案、证据缺口与 Agent 溯源告警，"
        "输出Markdown。"
    )
    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": report},
                ],
                "temperature": 0.2,
                **chat_request_extras(config),
            },
            timeout=45,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        return content or report, {
            "stage": "model_polish",
            "status": "success",
            "model": model,
            "provider": "analyzer",
        }
    except Exception as exc:
        return report, {
            "stage": "model_polish",
            "status": "fallback",
            "reason": exc.__class__.__name__,
            "model": model,
        }


# 已 Agent 化的模块注册表：模块名 -> (导入路径, 便捷函数名, modules 字典中的 engine_key)
_AGENT_MODULE_REGISTRY: dict[str, tuple[str, str, str]] = {
    "module1": ("module_agents.module1", "run_module1", "module_1_market_competitor"),
    "module2": ("module_agents.module2", "run_module2", "module_2_audience_content"),
    "module3": ("module_agents.module3", "run_module3", "module_3_keyword_creator"),
    "module4": ("module_agents.module4", "run_module4", "module_4_spotlight_decision"),
    "module5": ("module_agents.module5", "run_module5", "module_5_budget_pacing"),
    "module6": ("module_agents.module6", "run_module6", "module_6_keyword_strategy"),
}


def _attach_agent_modules(
    effective_req: CampaignRequest,
    modules: dict[str, Any],
    trace: list[dict[str, Any]],
    agent_module_names: list[str],
    *,
    brand_calibration: dict[str, Any] | None = None,
) -> None:
    """按业务依赖顺序（orchestrator.PIPELINE_ORDER）执行已注册的模块 Agent，成功则把
    agent_decision + decision_source 挂到对应确定性模块块上；上游模块结论压缩成摘要注入
    下游 prompt；模块6 成功后注入共享词表供模块3 复用；开启 Critic 时二审，high 触发
    一轮定向重写，medium/low 写入 human_review_items（失败只降级不阻塞）。

    硬前序检查复用 orchestrator.should_block（同一份 PREREQUISITES，逻辑不复制）：
    前序 failed / blocked → 本模块不执行并记 blocked；前序 completed_with_gaps →
    照常执行但在 upstream_context 附缺口提示（docs/no-code-agent/03 文档第 1 节）。"""
    import importlib

    from evidence_policy import derive_module_status
    from module_agents.orchestrator import (
        BLOCKED_REASON,
        PIPELINE_ORDER,
        build_gap_notice,
        build_shared_keyword_handoff,
        build_upstream_digest,
        format_calibration_digest,
        module_status_of,
        should_block,
        unresolved_gaps_of,
    )

    try:
        from module_agents.critic import (
            critic_enabled,
            format_critic_rewrite_context,
            has_high_severity_issues,
            merge_critic_issues_into_output,
            run_critic,
        )

        critic_on = critic_enabled()
    except Exception:  # Critic 是增强不是闸门，加载失败直接当作未开启
        critic_on = False

    requested = list(agent_module_names)
    ordered = [item for item in PIPELINE_ORDER if item in requested]
    ordered.extend(item for item in requested if item not in PIPELINE_ORDER)
    upstream_digests: list[str] = []
    if brand_calibration and brand_calibration.get("status") == "ready":
        cal_digest = format_calibration_digest(brand_calibration)
        if cal_digest:
            upstream_digests.append(cal_digest)
    module_status_map: dict[str, str] = {}
    module_gaps_map: dict[str, list[str]] = {}

    for name in ordered:
        entry = _AGENT_MODULE_REGISTRY.get(name)
        stage = f"agent_{name}"
        if entry is None:
            trace.append({"stage": stage, "status": "skipped", "reason": "unregistered_module"})
            continue
        module_path, fn_name, engine_key = entry
        block = modules.get(engine_key)
        if not isinstance(block, dict):
            trace.append({"stage": stage, "status": "skipped", "reason": "module_key_missing"})
            continue
        blocked_by = should_block(name, module_status_map)
        if blocked_by:
            module_status_map[name] = "blocked"
            block["module_status"] = "blocked"
            trace.append({
                "stage": stage,
                "status": "blocked",
                "blocked_by": blocked_by,
                "reason": BLOCKED_REASON,
            })
            continue
        # 只注入最近 3 段上游摘要；共享词表 handoff 优先保留
        if upstream_digests:
            window = upstream_digests[-3:]
            handoffs = [
                item for item in upstream_digests
                if item.startswith("【模块6共享词表】")
            ]
            if handoffs and handoffs[-1] not in window:
                window = (
                    window[1:] + [handoffs[-1]]
                    if len(window) >= 3
                    else window + [handoffs[-1]]
                )
            upstream_context = "\n\n".join(window)
        else:
            upstream_context = ""
        # 前序带缺口完成：照常执行，但把缺口提示压进上下文
        gap_notice = build_gap_notice(name, module_status_map, module_gaps_map)
        if gap_notice:
            upstream_context = (
                upstream_context + "\n\n" + gap_notice if upstream_context else gap_notice
            )
        try:
            run_fn = getattr(importlib.import_module(module_path), fn_name)
            agent_result = run_fn(effective_req, upstream_context=upstream_context)
            grounding = agent_result.get("grounding_check") or {}
            module_status = module_status_of(agent_result)
            unresolved_gaps = unresolved_gaps_of(agent_result)
            module_status_map[name] = module_status
            module_gaps_map[name] = unresolved_gaps
            block["agent_decision"] = {
                "output": agent_result["output"],
                "grounding_check": grounding,
                "steps_used": agent_result["steps_used"],
                "module_status": module_status,
                "unresolved_gaps": unresolved_gaps,
            }
            block["module_status"] = module_status
            block["decision_source"] = (
                "llm_agent"
                if grounding.get("passed") is True
                else "llm_agent_ungrounded"
            )
            trace.append({
                "stage": stage,
                "status": "success",
                "module_status": module_status,
                "unresolved_gap_count": len(unresolved_gaps),
                "steps_used": agent_result["steps_used"],
                "repair_rounds_used": agent_result["repair_rounds_used"],
                "grounding_passed": grounding.get("passed") is True,
                "decision_source": block["decision_source"],
                "upstream_digest_chars": len(upstream_context),
            })
        except Exception as exc:  # 任何异常都回退到确定性输出，不影响其它模块
            module_status_map[name] = "failed"
            trace.append({
                "stage": stage,
                "status": "fallback",
                "module_status": "failed",
                "reason": exc.__class__.__name__,
                "detail": str(exc)[:300],
            })
            continue

        if critic_on:
            evidence_digest = "\n".join(part for part in [
                f"品牌：{effective_req.brand_name}（{effective_req.category}）",
                f"商品：{effective_req.product_name}｜卖点："
                + "、".join(effective_req.selling_points),
                f"目标：{effective_req.goal}｜总预算：{effective_req.total_budget_cny:g} 元"
                f"｜周期：{effective_req.campaign_days} 天｜初始人群：{effective_req.initial_audience}",
                ("约束：" + "；".join(effective_req.constraints))
                if effective_req.constraints else "",
                ("上游模块结论摘要：\n" + upstream_context) if upstream_context else "",
            ] if part)
            review = run_critic(
                name, engine_key, agent_result["output"], evidence_digest
            )
            # medium/low（及未重写时的 high）写入人工复核项
            rewritten = False
            if has_high_severity_issues(review):
                rewrite_ctx = format_critic_rewrite_context(review)
                try:
                    rewritten_result = run_fn(
                        effective_req,
                        upstream_context="\n\n".join(
                            part for part in [upstream_context, rewrite_ctx] if part
                        ),
                    )
                    new_output = merge_critic_issues_into_output(
                        dict(rewritten_result["output"]),
                        review,
                        severities={"medium", "low"},
                    )
                    agent_result = {
                        **rewritten_result,
                        "output": new_output,
                    }
                    grounding = agent_result.get("grounding_check") or {}
                    block["agent_decision"] = {
                        "output": new_output,
                        "grounding_check": grounding,
                        "steps_used": agent_result["steps_used"],
                        "critic_review": review,
                        "critic_rewritten": True,
                    }
                    block["decision_source"] = (
                        "llm_agent"
                        if grounding.get("passed") is True
                        else "llm_agent_ungrounded"
                    )
                    rewritten = True
                    trace.append({
                        "stage": f"critic_rewrite_{name}",
                        "status": "success",
                        "steps_used": agent_result["steps_used"],
                        "grounding_passed": grounding.get("passed") is True,
                    })
                except Exception as exc:
                    merged = merge_critic_issues_into_output(
                        dict(agent_result["output"]), review
                    )
                    agent_result = {**agent_result, "output": merged}
                    block["agent_decision"]["output"] = merged
                    block["agent_decision"]["critic_review"] = review
                    block["agent_decision"]["critic_rewritten"] = False
                    trace.append({
                        "stage": f"critic_rewrite_{name}",
                        "status": "fallback",
                        "reason": exc.__class__.__name__,
                        "detail": str(exc)[:300],
                    })
            else:
                merged = merge_critic_issues_into_output(
                    dict(agent_result["output"]), review
                )
                agent_result = {**agent_result, "output": merged}
                block["agent_decision"]["output"] = merged
                block["agent_decision"]["critic_review"] = review
                block["agent_decision"]["critic_rewritten"] = False

            if rewritten:
                pass  # already attached critic_review above
            elif "critic_review" not in block["agent_decision"]:
                block["agent_decision"]["critic_review"] = review

            trace.append({
                "stage": f"critic_{name}",
                "status": review.get("status", "degraded"),
                "rewritten": rewritten,
            })
            # Critic 会改写输出（合入 issues / 人工复核项）：按最终输出重判模块状态，
            # 避免「已完成」掩盖新写入的缺口（02 文档禁止行为）。
            decision_block = block.get("agent_decision")
            if isinstance(decision_block, dict):
                state = derive_module_status(
                    decision_block.get("output"), decision_block.get("grounding_check")
                )
                decision_block["module_status"] = state["module_status"]
                decision_block["unresolved_gaps"] = state["unresolved_gaps"]
                block["module_status"] = state["module_status"]
                module_status_map[name] = state["module_status"]
                module_gaps_map[name] = state["unresolved_gaps"]

        digest = build_upstream_digest(name, agent_result["output"])
        if digest:
            upstream_digests.append(digest)
        # 模块6 → 模块3：共享完整词表 JSON，避免两套词库
        if name == "module6":
            handoff = build_shared_keyword_handoff(agent_result["output"])
            if handoff:
                upstream_digests.append(handoff)
                trace.append({
                    "stage": "shared_keyword_handoff",
                    "status": "ready",
                    "chars": len(handoff),
                })


def run_strategy(
    req: CampaignRequest,
    use_model: bool = True,
    allow_mock: bool = False,
    mock_seed: str | None = None,
    use_agent_modules: bool = False,
    previous_competitor_snapshot: dict[str, Any] | None = None,
    brand_calibration: dict[str, Any] | None = None,
) -> StrategyResponse:
    mock_injected: dict[str, Any] = {"fields": [], "subagents": []}
    # API 路径会先抓取给定链接；此处再归一化，避免重复/空链接
    normalized_competitors = normalize_competitor_inputs(
        req.competitor_links,
        req.competitor_evidence,
    )
    effective_req = req.model_copy(update={"competitor_evidence": normalized_competitors})
    effective_mock_seed = normalize_mock_seed(mock_seed) if allow_mock else None
    if allow_mock:
        effective_req, mock_injected = run_mock_subagents(
            effective_req, mock_seed=effective_mock_seed
        )
    gaps = _evidence_gaps(effective_req, mock_injected=mock_injected)
    modules = _module_outputs(
        effective_req, allow_mock=allow_mock, mock_seed=effective_mock_seed
    )
    modules.update(
        build_bonus_modules(
            effective_req,
            modules,
            previous_competitor_snapshot=previous_competitor_snapshot,
        )
    )
    # Mock 补足不能抬高可信度：仅真实证据齐全才算 high
    if not gaps and not mock_injected.get("fields"):
        confidence = "high"
    elif len(gaps) == 1 and not mock_injected.get("fields"):
        confidence = "medium"
    else:
        confidence = "low"
    trace: list[dict[str, Any]] = [
        {"stage": "validate_input", "status": "success"},
        {"stage": "evidence_audit", "status": "success", "gap_count": len(gaps)},
        {"stage": "six_module_planning", "status": "success", "module_count": 6},
        {
            "stage": "bonus_modules",
            "status": "success",
            "modules": [
                "bonus_content_audit",
                "bonus_ab_test",
                "bonus_competitor_monitor",
            ],
        },
        {
            "stage": "mock_fallback",
            "status": "enabled" if allow_mock else "disabled",
            "allow_mock": allow_mock,
            "mock_seed": effective_mock_seed,
            "injected_fields": mock_injected.get("fields", []),
            "subagents": mock_injected.get("subagents", []),
            "agent_count_activated": mock_injected.get("agent_count_activated", 0),
            "warning": MOCK_WARNING if mock_injected.get("fields") else None,
        },
    ]
    # Agent 必须在报告生成前挂载，否则 report_view / Markdown 看不到 agent_decision
    if use_agent_modules:
        _load_env()
        from model_config import load_analyzer_config

        agent_api_key = load_analyzer_config()["api_key"]
        if agent_api_key and agent_api_key not in {"你的模型平台 Key", "your-api-key", "YOUR_API_KEY"}:
            _attach_agent_modules(
                effective_req,
                modules,
                trace,
                list(_AGENT_MODULE_REGISTRY),
                brand_calibration=brand_calibration,
            )
        else:
            trace.append({
                "stage": "agent_modules",
                "status": "skipped",
                "reason": "model_key_missing",
            })
    report_view = build_report_view(
        effective_req,
        modules,
        gaps,
        confidence,
        mock_subagents=mock_injected.get("subagents") or [],
    )
    deterministic_report = render_report_markdown(effective_req, report_view)
    report = deterministic_report
    if use_model:
        report, model_trace = _model_polish(effective_req, deterministic_report)
        trace.append(model_trace)
    else:
        trace.append({"stage": "model_polish", "status": "disabled"})
    return StrategyResponse(
        run_id=str(uuid4()),
        generated_at=datetime.now(timezone.utc).isoformat(),
        data_confidence=confidence,
        evidence_gaps=gaps,
        modules=modules,
        report_view=report_view,
        report_markdown=report,
        trace=trace,
    )
