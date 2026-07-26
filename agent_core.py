"""最小 Agent Loop：LLM + 工具 + 循环（观察→决策→行动）。

这是控制权反转的核心：LLM 不再只润色报告，而是在循环中主动调用工具做决策；
工具返回的校验错误也会回到 LLM，让它自我修正后重试。
每一步都写入 trace，供 checkpoint / 测试报告 / 评审追溯。
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from model_config import chat_request_extras, load_analyzer_config
from tools.registry import ToolRegistry

# 硅基流动等网关偶发掐连接 / 超时 / 5xx，属于瞬时故障，可退避重试
_RETRYABLE_EXCEPTIONS = (
    httpx.RemoteProtocolError,
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.WriteTimeout,
    httpx.ConnectError,
    httpx.PoolTimeout,
)
_RETRYABLE_STATUS = frozenset({429, 502, 503, 504})


class AgentLoopError(RuntimeError):
    pass


class AgentLoop:
    """OpenAI-compatible function calling 循环。

    默认使用 Analyzer 通道（AGENT_ANALYZER_* / AGENT_OPENAI_*）。
    transport 参数仅用于测试注入 httpx.MockTransport。
    """

    def __init__(
        self,
        system_prompt: str,
        registry: ToolRegistry,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 3,
        retry_backoff_sec: float = 1.0,
    ) -> None:
        config = load_analyzer_config()
        if not config["api_key"] and transport is None:
            raise AgentLoopError(
                "缺少 AGENT_ANALYZER_API_KEY 或 AGENT_OPENAI_API_KEY。"
                "请配置本项目 .env / course.env 或环境变量；"
                "只想验证工具层时运行 demo_agent_loop.py --offline"
            )
        self._config = config
        self._model = model or config["model"]
        self._temperature = temperature
        self._registry = registry
        self._system_prompt = system_prompt
        self._transport = transport
        self._max_retries = max(1, max_retries)
        self._retry_backoff_sec = max(0.0, retry_backoff_sec)

    def _chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        # Analyzer 通道：DeepSeek 关 thinking；硅基 Qwen 关 enable_thinking。
        # 对网关断连/超时/429/5xx 做有限次指数退避重试。
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "tools": self._registry.openai_schemas(),
            "tool_choice": "auto",
            **chat_request_extras({**self._config, "model": self._model}),
        }
        headers = {
            "Authorization": f"Bearer {self._config['api_key'] or 'test'}",
            "Content-Type": "application/json",
        }
        url = f"{self._config['base_url']}/chat/completions"
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                with httpx.Client(transport=self._transport, timeout=180.0) as client:
                    response = client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    return response.json()
            except _RETRYABLE_EXCEPTIONS as exc:
                last_error = exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in _RETRYABLE_STATUS:
                    body = (exc.response.text or "")[:500]
                    raise AgentLoopError(
                        f"模型接口拒绝请求 HTTP {exc.response.status_code}："
                        f"{body or exc}"
                    ) from exc
                last_error = exc

            if attempt >= self._max_retries:
                break
            time.sleep(self._retry_backoff_sec * (2 ** (attempt - 1)))

        raise AgentLoopError(
            f"模型接口在 {self._max_retries} 次尝试后仍失败："
            f"{last_error.__class__.__name__}: {last_error}"
        ) from last_error

    def run(self, user_prompt: str, *, max_steps: int = 8) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._loop(messages, max_steps=max_steps)

    def continue_run(
        self, messages: list[dict[str, Any]], *, max_steps: int = 8
    ) -> dict[str, Any]:
        """从已有 messages 上下文继续循环（用于模块 Agent 的 JSON 修复轮）。"""
        return self._loop(list(messages), max_steps=max_steps)

    def _loop(
        self, messages: list[dict[str, Any]], *, max_steps: int
    ) -> dict[str, Any]:
        trace: list[dict[str, Any]] = []
        for step in range(1, max_steps + 1):
            payload = self._chat(messages)
            message = payload["choices"][0]["message"]
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                trace.append({"step": step, "action": "final_answer"})
                return {
                    "final": message.get("content") or "",
                    "steps_used": step,
                    "trace": trace,
                    "messages": messages,
                }
            messages.append({
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": tool_calls,
            })
            for call in tool_calls:
                name = call["function"]["name"]
                arguments = call["function"].get("arguments") or "{}"
                result = self._registry.execute(name, arguments)
                trace.append({
                    "step": step,
                    "action": "tool_call",
                    "tool": name,
                    "arguments": arguments,
                    "ok": "error" not in result,
                    "result": result,
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id", name),
                    "content": json.dumps(result, ensure_ascii=False),
                })
        raise AgentLoopError(
            f"超过最大步数 {max_steps} 仍未收敛；trace={json.dumps(trace, ensure_ascii=False)[:2000]}"
        )
