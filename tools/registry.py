"""工具注册表：Pydantic 参数模型 → OpenAI function calling schema → 受控执行。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ValidationError


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[[BaseModel], dict[str, Any]]

    def openai_schema(self) -> dict[str, Any]:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec]) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            if spec.name in self._specs:
                raise ValueError(f"重复注册工具: {spec.name}")
            self._specs[spec.name] = spec

    @property
    def names(self) -> list[str]:
        return list(self._specs)

    def openai_schemas(self) -> list[dict[str, Any]]:
        return [spec.openai_schema() for spec in self._specs.values()]

    def execute(self, name: str, arguments: str | dict[str, Any]) -> dict[str, Any]:
        """执行工具。任何失败都返回 error dict（不抛异常），交给 LLM 自我修正。"""
        spec = self._specs.get(name)
        if not spec:
            return {
                "error": f"未知工具: {name}",
                "hint": f"可用工具: {', '.join(self._specs)}",
            }
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError as exc:
                return {"error": f"参数不是合法 JSON: {exc}", "hint": "请重新生成参数"}
        try:
            args = spec.args_model.model_validate(arguments)
        except ValidationError as exc:
            return {
                "error": "参数校验失败",
                "details": [
                    {
                        "field": ".".join(str(part) for part in item["loc"]),
                        "problem": item["msg"],
                    }
                    for item in exc.errors()
                ],
                "hint": "请按 details 修正参数后重新调用本工具",
            }
        try:
            return spec.fn(args)
        except Exception as exc:  # 工具内部错误也返回给 LLM，保持循环不中断
            return {"error": f"工具执行失败: {exc.__class__.__name__}: {exc}"}
