"""通用模块 Agent 底座。

流程（run_module_agent）：
  a. 用 AgentLoop 跑到 final answer（LLM 在循环内自主调用工具做决策）；
  b. 从 final 文本提取 JSON（```json 围栏或裸 JSON，取第一个能解析的对象）；
  c. 用 spec.output_model 校验；失败则把 ValidationError 摘要作为新 user 消息追加，
     复用同一 messages 上下文重新进入循环，最多 max_repair_rounds 轮；仍失败抛
     ModuleAgentError（含 trace）；
  d. 数字溯源检查：收集 trace 中成功工具结果里的全部数值，检查输出 JSON 指定溯源
     字段（spec.grounded_fields，支持点路径 + `*` 通配）里的每个数值是否有据可循；
     不匹配不硬失败，只在返回里记 grounding_check.mismatches；
  e. 模块状态判定（纯代码，不靠 LLM 自述）：溯源未通过或输出含「待接入/待补/待人工/
     待投手/待确认/演示补全」标记 → completed_with_gaps 并列出 unresolved_gaps，
     否则 completed（blocked 由编排层按硬前序判定，见 module_agents.orchestrator）；
     规则本体在 evidence_policy.derive_module_status，对齐
     模块状态契约（ready / blocked / completed_with_gaps）；
  f. 返回统一结构的 dict。

本文件只依赖 agent_core / tools / evidence_policy / pydantic，绝不 import engine。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from agent_core import AgentLoop
from evidence_policy import derive_module_status
from models import CampaignRequest
from tools import DEFAULT_REGISTRY
from tools.registry import ToolRegistry


class ModuleAgentError(RuntimeError):
    """模块 Agent 在 max_repair_rounds 内仍无法产出合法 JSON。"""

    def __init__(self, message: str, *, trace: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.trace = trace or []


@dataclass(frozen=True)
class ModuleAgentSpec:
    name: str
    title: str
    system_prompt: str
    output_model: type[BaseModel]
    build_user_prompt: Callable[[CampaignRequest], str]
    registry: ToolRegistry = DEFAULT_REGISTRY
    grounded_fields: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# JSON 提取：支持 ```json 围栏与裸 JSON，取第一个能解析成对象的顶层 {...}
# ---------------------------------------------------------------------------
def _find_top_level_objects(text: str) -> list[str]:
    """扫描文本，返回所有顶层平衡的 {...} 子串（能识别字符串内的花括号与转义）。"""
    objects: list[str] = []
    depth = 0
    start: int | None = None
    in_str = False
    escaped = False
    for index, char in enumerate(text):
        if in_str:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_str = False
            continue
        if char == '"':
            in_str = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(text[start : index + 1])
                    start = None
    return objects


def extract_json_object(text: str) -> dict[str, Any] | None:
    """取第一个能解析的 JSON 对象；同时兼容 ```json 围栏与裸 JSON。"""
    for candidate in _find_top_level_objects(text or ""):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _format_validation_error(exc: ValidationError) -> str:
    parts = []
    for item in exc.errors()[:12]:
        loc = ".".join(str(part) for part in item["loc"])
        parts.append(f"{loc}: {item['msg']}")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# 数字溯源
# ---------------------------------------------------------------------------
def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _flatten_numbers(value: Any) -> list[float]:
    numbers: list[float] = []
    if _is_number(value):
        numbers.append(float(value))
    elif isinstance(value, dict):
        for item in value.values():
            numbers.extend(_flatten_numbers(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            numbers.extend(_flatten_numbers(item))
    return numbers


def _collect_tool_numbers(trace: list[dict[str, Any]]) -> list[float]:
    numbers: list[float] = []
    for row in trace:
        if row.get("action") != "tool_call" or not row.get("ok"):
            continue
        result = row.get("result")
        if isinstance(result, dict):
            numbers.extend(_flatten_numbers(result))
    return numbers


def _number_grounded(value: float, tool_numbers: list[float]) -> bool:
    target = round(float(value), 2)
    return any(abs(target - round(num, 2)) <= 0.01 for num in tool_numbers)


def _resolve_path(obj: Any, segments: list[str], prefix: str):
    """按点路径解析，`*` 通配 dict 的任意键或 list 的任意下标。"""
    if not segments:
        yield prefix, obj
        return
    head, rest = segments[0], segments[1:]
    if head == "*":
        if isinstance(obj, dict):
            items = list(obj.items())
        elif isinstance(obj, (list, tuple)):
            items = list(enumerate(obj))
        else:
            return
        for key, sub in items:
            child = f"{prefix}.{key}" if prefix else str(key)
            yield from _resolve_path(sub, rest, child)
    else:
        if isinstance(obj, dict) and head in obj:
            child = f"{prefix}.{head}" if prefix else head
            yield from _resolve_path(obj[head], rest, child)


def grounding_check(
    output: dict[str, Any],
    trace: list[dict[str, Any]],
    grounded_fields: list[str],
) -> dict[str, Any]:
    tool_numbers = _collect_tool_numbers(trace)
    mismatches: list[dict[str, Any]] = []
    for field_path in grounded_fields:
        segments = field_path.split(".")
        for concrete_path, value in _resolve_path(output, segments, ""):
            for number in _flatten_numbers(value):
                if not _number_grounded(number, tool_numbers):
                    mismatches.append({"path": concrete_path, "value": number})
    return {"passed": not mismatches, "mismatches": mismatches}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
UPSTREAM_CONTEXT_HEADER = (
    "\n\n【上游模块结论摘要（可引用，与本模块矛盾时以本模块证据为准）】\n"
)


def run_module_agent(
    spec: ModuleAgentSpec,
    req: CampaignRequest,
    *,
    transport: Any = None,
    max_steps: int = 10,
    max_repair_rounds: int = 2,
    upstream_context: str = "",
) -> dict[str, Any]:
    agent = AgentLoop(spec.system_prompt, spec.registry, transport=transport)
    user_prompt = spec.build_user_prompt(req)
    # 依赖传递：编排层（module_agents.orchestrator）把上游模块结论压缩后注入证据区之后
    if upstream_context and upstream_context.strip():
        user_prompt = user_prompt + UPSTREAM_CONTEXT_HEADER + upstream_context.strip()

    outcome = agent.run(user_prompt, max_steps=max_steps)
    trace: list[dict[str, Any]] = list(outcome["trace"])
    messages: list[dict[str, Any]] = outcome["messages"]
    final_text: str = outcome["final"]
    total_steps: int = outcome["steps_used"]

    repair_rounds = 0
    validated: dict[str, Any] | None = None
    last_error = ""

    while True:
        candidate = extract_json_object(final_text)
        if candidate is None:
            last_error = "未能在回答中找到 JSON 对象"
        else:
            try:
                model_obj = spec.output_model.model_validate(candidate)
                validated = model_obj.model_dump()
                break
            except ValidationError as exc:
                last_error = _format_validation_error(exc)

        if repair_rounds >= max_repair_rounds:
            raise ModuleAgentError(
                f"模块 {spec.name} 在 {max_repair_rounds} 轮修复后仍无法产出合法 JSON："
                f"{last_error}",
                trace=trace,
            )

        repair_rounds += 1
        messages = list(messages) + [
            {"role": "assistant", "content": final_text},
            {
                "role": "user",
                "content": (
                    f"上一次输出的 JSON 校验失败：{last_error}。"
                    "请依据校验错误修正，并只输出一个 ```json 代码块，不要附带其它文字。"
                ),
            },
        ]
        outcome = agent.continue_run(messages, max_steps=max_steps)
        trace.extend(outcome["trace"])
        messages = outcome["messages"]
        final_text = outcome["final"]
        total_steps += outcome["steps_used"]

    grounding = grounding_check(validated, trace, spec.grounded_fields)
    state = derive_module_status(validated, grounding)
    return {
        "module": spec.name,
        "output": validated,
        "grounding_check": grounding,
        "module_status": state["module_status"],
        "unresolved_gaps": state["unresolved_gaps"],
        "steps_used": total_steps,
        "repair_rounds_used": repair_rounds,
        "trace": trace,
    }
