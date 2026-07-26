"""强模型 Critic 二审：只审「策略文本质量」，不审数字。

定位（对齐 docs/OPTIMIZATION_ROADMAP.md 第 2 节）：
- 现有护栏是数字导向的（工具参数校验 + 输出契约 + grounding_check 数值溯源），
  语义/措辞类问题不触发任何护栏；Critic 补的就是这块空档。
- 数字不归 Critic 管：数字已由 grounding_check 溯源审计负责，Critic 明确被禁止
  质疑数字大小，只看四个文本维度：
    evidence_citation  证据引用是否具体（有没有指到具体证据/来源，而非泛泛而谈）
    executability      动作是否可执行（有没有主体/条件/阈值/动作）
    compliance_wording 合规措辞（假设是否说成事实、是否绝对化宣称、是否越权承诺）
    consistency        与输入目标/证据/上游结论的一致性
- Critic 是增强不是闸门：任何失败（网络异常、坏 JSON、契约不过）都不阻塞模块产出，
  只返回 {"status": "degraded", "reason": ...} 由调用方记 trace。

配置（与 model_config 双通道兼容，只覆盖模型名）：
- AGENT_CRITIC_ENABLED：'1' / 'true' / 'yes' / 'on' 才开启，默认关闭（成本控制）；
- AGENT_CRITIC_MODEL：Critic 用的强模型名，缺省沿用 Analyzer 主模型；
- api_key / base_url 直接复用 load_analyzer_config()，不新增通道变量。

本文件只依赖 agent_core / model_config / base / pydantic，绝不 import engine。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

# 重试常量/异常直接复用 agent_core，避免两处退避策略漂移
from agent_core import (
    _RETRYABLE_EXCEPTIONS,
    _RETRYABLE_STATUS,
    AgentLoopError,
)
from model_config import (
    _normalize_chat_model,
    _strip_inline_comment,
    chat_request_extras,
    load_analyzer_config,
    load_dotenv_files,
)
from module_agents.base import extract_json_object

_TRUTHY = frozenset({"1", "true", "yes", "on"})

# 校验失败最多再给模型一次机会（把校验错误发回去）
MAX_CRITIC_REPAIR_ROUNDS = 1


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
def critic_enabled() -> bool:
    """AGENT_CRITIC_ENABLED 显式开启才跑 Critic（默认关闭）。"""
    load_dotenv_files()
    return _strip_inline_comment(os.getenv("AGENT_CRITIC_ENABLED", "")).lower() in _TRUTHY


def load_critic_config() -> dict[str, str]:
    """复用 Analyzer 通道的 api_key/base_url，只把模型名换成 AGENT_CRITIC_MODEL。"""
    config = load_analyzer_config()
    raw_model = _strip_inline_comment(os.getenv("AGENT_CRITIC_MODEL", ""))
    model = (
        _normalize_chat_model(raw_model, config["base_url"])
        if raw_model
        else config["model"]
    )
    return {
        "api_key": config["api_key"],
        "base_url": config["base_url"],
        "model": model,
        "role": "critic",
    }


# ---------------------------------------------------------------------------
# 输出契约
# ---------------------------------------------------------------------------
class DimensionScores(BaseModel):
    evidence_citation: int = Field(ge=1, le=10)
    executability: int = Field(ge=1, le=10)
    compliance_wording: int = Field(ge=1, le=10)
    consistency: int = Field(ge=1, le=10)


class CriticIssue(BaseModel):
    path: str = Field(min_length=1)
    severity: Literal["high", "medium", "low"]
    problem: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)


class CriticReport(BaseModel):
    verdict: Literal["pass", "revise"]
    dimension_scores: DimensionScores
    issues: list[CriticIssue] = Field(default_factory=list, max_length=10)
    summary: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
# 按模块定制的检查项（对齐 OPTIMIZATION_ROADMAP 第 2 节方案 1）
MODULE_CRITIC_CHECKLISTS: dict[str, list[str]] = {
    "module1": [
        "竞品定向是否写成「假设」而非事实断语",
        "热门形式/峰时是否有证据支撑，缺证据时是否诚实留空",
        "风险提醒是否可执行（主体/动作），而非空泛警示",
    ],
    "module2": [
        "内容方向是否可执行（选题角度 + 证据点），而非口号",
        "素材门槛阈值是否与证据口径一致，缺证据时是否标明待测",
        "人群包描述是否可落地到聚光定向，而非模糊画像",
    ],
    "module3": [
        "搜索/信息流广告词的 bid_note 是否可执行（试探区间或动作）",
        "达人缺口 open_slots 是否诚实，无证据时是否说明需补 CSV/蒲公英",
        "关键词赛道是否与上游共享词表冲突（若有共享词表）",
    ],
    "module4": [
        "campaigns 是否被误解为投放阶段（预热/爆发/长尾）而非账户计划",
        "daily_schedule 是否是投放时段而非值班表（总结当日/准备次日）",
        "调价是否用百分比（如提价5%）而非含糊「0.1 倍」",
        "objective/placement 语义是否像聚光付费计划，而非「自然内容/品牌曝光」",
        "风险预案是否引用本案例数字（止损线/测试带宽）",
    ],
    "module5": [
        "三阶段预算是否与总预算自洽，比例说明是否可执行",
        "联动规则是否有明确阈值与动作，而非空话",
        "自然/付费拆分理由是否与目标一致",
    ],
    "module6": [
        "热点监控 data_source_status 在无合规源时是否诚实写「待接入数据源」",
        "布局规则是否可执行（位置+动作），而非空泛建议",
        "蓝海词是否标明待验证，而非写成已验证事实",
    ],
}


SYSTEM_PROMPT = """你是小红书投放策略方案的「质检员」（Critic），负责对某个模块 Agent
已产出并通过结构契约校验的 JSON 做二审。

你只审「策略文本质量」，四个维度各打 1-10 分（10 最好）：
1. evidence_citation（证据引用）：结论有没有指向证据区里的具体对象/来源/口径，
   还是只写了「结合市场情况」这类空话；缺证据时有没有诚实标注缺口。
2. executability（可执行性）：动作有没有明确的执行主体、触发条件、判断阈值与
   具体动作；有没有把「投放动作」写成「值班表/日报表」这类非投放事项。
3. compliance_wording（合规措辞）：竞品定向等推断是否措辞为「假设」而非事实；
   有没有绝对化宣称、疗效/功效承诺、诱导性表述；调价等动作是否表述清晰
   （如「提价5%」而不是含糊的「0.1 倍」）；对不可得数据是否诚实标注待人工核验。
4. consistency（一致性）：与输入的品牌/商品/目标/人群/预算是否自洽；与证据摘要、
   上游模块结论是否冲突；模块内部字段之间是否互相矛盾。

铁律：
- 绝对不要质疑数字大小、加总、比例是否正确——数字已由独立的溯源审计（grounding_check）
  负责，重复审计只会制造噪音。只有当数字的「文字说明」与数字本身互相矛盾时，
  才作为 consistency 问题提出。
- 不要重写整份方案，只挑最值得改的问题，最多 10 条，按严重度排序。
- 没有实质问题时 verdict 填 "pass"、issues 可为空数组；存在 high 或多条 medium 问题时
  verdict 填 "revise"。
- path 用 JSON 里的点路径定位（如 account_structure.campaigns.0.placement）。

只输出一个 ```json 代码块（不要输出多余文字），结构如下：
{
  "verdict": "pass" 或 "revise",
  "dimension_scores": {"evidence_citation": 1-10 的整数, "executability": 1-10 的整数,
     "compliance_wording": 1-10 的整数, "consistency": 1-10 的整数},
  "issues": [ {"path": str, "severity": "high|medium|low", "problem": str,
     "suggestion": str}, 0-10 项 ],
  "summary": str（一句话总评）
}"""


def build_critic_prompt(
    module_name: str,
    module_title: str,
    output: dict[str, Any],
    evidence_digest: str,
) -> str:
    checklist = MODULE_CRITIC_CHECKLISTS.get(module_name) or []
    checklist_block = ""
    if checklist:
        checklist_block = (
            "【本模块重点检查项】\n"
            + "\n".join(f"- {item}" for item in checklist)
            + "\n\n"
        )
    return (
        f"待二审模块：{module_title}（{module_name}）\n\n"
        f"{checklist_block}"
        "【模块输出 JSON】\n"
        f"{json.dumps(output, ensure_ascii=False, indent=2)}\n\n"
        "【证据摘要（含输入关键字段与上游结论，供一致性判断）】\n"
        f"{evidence_digest or '（本次未提供证据摘要，仅按模块输出内部自洽性审阅）'}\n\n"
        "请按四个维度打分并给出问题清单，只输出一个 ```json 代码块。"
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def iter_critic_issues(review: dict[str, Any]) -> list[dict[str, Any]]:
    """从 run_critic 返回值里取出结构化 issues；degraded / 非 dict 一律空列表。"""
    if _as_dict(review).get("status") != "ok":
        return []
    issues = _as_list(_as_dict(review.get("report")).get("issues"))
    return [item for item in (_as_dict(row) for row in issues) if item.get("path")]


def has_high_severity_issues(review: dict[str, Any]) -> bool:
    return any(item.get("severity") == "high" for item in iter_critic_issues(review))


def format_critic_issue_note(issue: dict[str, Any]) -> str:
    severity = str(issue.get("severity") or "low")
    path = str(issue.get("path") or "")
    problem = str(issue.get("problem") or "").strip()
    suggestion = str(issue.get("suggestion") or "").strip()
    return f"[Critic/{severity}] {path}: {problem} → {suggestion}"


def merge_critic_issues_into_output(
    output: dict[str, Any],
    review: dict[str, Any],
    *,
    severities: set[str] | None = None,
) -> dict[str, Any]:
    """把 Critic issues 写入 human_review_items（默认全部严重度；可过滤）。

    不修改原 dict；缺 human_review_items 时新建列表。degraded 评审无操作。
    """
    allowed = severities
    notes: list[str] = []
    for issue in iter_critic_issues(review):
        severity = str(issue.get("severity") or "")
        if allowed is not None and severity not in allowed:
            continue
        notes.append(format_critic_issue_note(issue))
    if not notes:
        return dict(output)
    merged = dict(output)
    items = [str(item) for item in _as_list(merged.get("human_review_items"))]
    for note in notes:
        if note not in items:
            items.append(note)
    # 契约通常要求 1–6 条；超出时保留末尾（含 Critic 注记）并截断
    if len(items) > 6:
        items = items[-6:]
    if not items:
        items = ["Critic 二审提出问题，请人工复核相关字段。"]
    merged["human_review_items"] = items
    return merged


def format_critic_rewrite_context(review: dict[str, Any]) -> str:
    """给模块 Agent 定向重写用的上游上下文段落（high severity 才有实质内容）。"""
    highs = [
        item for item in iter_critic_issues(review) if item.get("severity") == "high"
    ]
    if not highs:
        return ""
    lines = [
        "【Critic 高严重度问题，请定向修正后重新输出完整 JSON】",
        "只修下列问题，不要改动已由工具溯源的数字字段；修完后仍须满足模块契约。",
    ]
    for issue in highs:
        lines.append(
            f"- {issue.get('path')}: {issue.get('problem')} → {issue.get('suggestion')}"
        )
    summary = str(_as_dict(review.get("report")).get("summary") or "").strip()
    if summary:
        lines.append(f"总评：{summary}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 单次 LLM 调用（无工具）
# ---------------------------------------------------------------------------
def _chat(
    config: dict[str, str],
    messages: list[dict[str, Any]],
    *,
    transport: httpx.BaseTransport | None,
    max_retries: int = 3,
    retry_backoff_sec: float = 1.0,
) -> dict[str, Any]:
    """与 AgentLoop._chat 同款退避策略，但不带 tools（Critic 是纯文本二审）。"""
    payload: dict[str, Any] = {
        "model": config["model"],
        "messages": messages,
        "temperature": 0.0,
        **chat_request_extras(config),
    }
    headers = {
        "Authorization": f"Bearer {config['api_key'] or 'test'}",
        "Content-Type": "application/json",
    }
    url = f"{config['base_url']}/chat/completions"
    last_error: Exception | None = None

    for attempt in range(1, max(1, max_retries) + 1):
        try:
            with httpx.Client(transport=transport, timeout=180.0) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                return response.json()
        except _RETRYABLE_EXCEPTIONS as exc:
            last_error = exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _RETRYABLE_STATUS:
                body = (exc.response.text or "")[:300]
                raise AgentLoopError(
                    f"Critic 模型接口拒绝请求 HTTP {exc.response.status_code}：{body or exc}"
                ) from exc
            last_error = exc

        if attempt >= max(1, max_retries):
            break
        time.sleep(max(0.0, retry_backoff_sec) * (2 ** (attempt - 1)))

    raise AgentLoopError(
        f"Critic 模型接口在 {max(1, max_retries)} 次尝试后仍失败："
        f"{last_error.__class__.__name__}: {last_error}"
    ) from last_error


def _format_validation_error(exc: ValidationError) -> str:
    parts = []
    for item in exc.errors()[:8]:
        loc = ".".join(str(part) for part in item["loc"])
        parts.append(f"{loc}: {item['msg']}")
    return "; ".join(parts)


def _degraded(reason: str) -> dict[str, Any]:
    return {"status": "degraded", "reason": reason[:300]}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def run_critic(
    module_name: str,
    module_title: str,
    output: dict[str, Any],
    evidence_digest: str,
    *,
    transport: httpx.BaseTransport | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """对单个模块输出做一次文本质量二审。

    返回：
      - 成功：{"status": "ok", "report": CriticReport.model_dump()}
      - 任何失败：{"status": "degraded", "reason": ...}（绝不抛异常，绝不阻塞模块产出）
    """
    try:
        config = load_critic_config()
        if model:
            config = {**config, "model": model}
        if not config["api_key"] and transport is None:
            return _degraded("缺少 Critic 模型 Key（AGENT_ANALYZER_API_KEY/AGENT_OPENAI_API_KEY）")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_critic_prompt(
                    module_name, module_title, output, evidence_digest
                ),
            },
        ]

        last_error = ""
        for round_index in range(MAX_CRITIC_REPAIR_ROUNDS + 1):
            payload = _chat(config, messages, transport=transport)
            try:
                final_text = payload["choices"][0]["message"].get("content") or ""
            except (KeyError, IndexError, TypeError, AttributeError) as exc:
                return _degraded(f"Critic 响应结构异常：{exc.__class__.__name__}: {exc}")

            candidate = extract_json_object(final_text)
            if candidate is None:
                last_error = "未能在回答中找到 JSON 对象"
            else:
                try:
                    report = CriticReport.model_validate(candidate)
                    return {"status": "ok", "report": report.model_dump()}
                except ValidationError as exc:
                    last_error = _format_validation_error(exc)

            if round_index >= MAX_CRITIC_REPAIR_ROUNDS:
                break
            messages = messages + [
                {"role": "assistant", "content": final_text},
                {
                    "role": "user",
                    "content": (
                        f"上一次输出的二审 JSON 校验失败：{last_error}。"
                        "请依据校验错误修正，并只输出一个 ```json 代码块，不要附带其它文字。"
                    ),
                },
            ]

        return _degraded(f"Critic 输出经 {MAX_CRITIC_REPAIR_ROUNDS} 次修复仍不合法：{last_error}")
    except Exception as exc:  # 网络/配置/解析等一切异常一律降级，不阻塞模块产出
        return _degraded(f"{exc.__class__.__name__}: {exc}")
