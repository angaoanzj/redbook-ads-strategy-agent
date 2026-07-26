"""模块 Agent 层：把确定性模块升级为「LLM 决策 + 工具算术 + 溯源校验」的 Agent。

base.py 提供通用底座 ModuleAgentSpec / run_module_agent；
每个具体模块（如 module5.py）只声明系统提示、输出契约与 user prompt 渲染。
本层禁止 import engine（engine 含 3.12 f-string 语法且会造成循环依赖）。
"""
from module_agents.base import (
    ModuleAgentError,
    ModuleAgentSpec,
    run_module_agent,
)

__all__ = ["ModuleAgentError", "ModuleAgentSpec", "run_module_agent"]
