"""双通道模型配置。

分工（作业/生产可同时保留两套 Key）：
- Analyzer（分析 / 模块 Agent / 报告润色）：默认走 DeepSeek
- Embedding / 向量检索：默认走硅基流动

兼容旧变量 AGENT_OPENAI_*：未设置 ANALYZER_* / EMBEDDING_* 时回退到它。

本目录独立运行：只读取本项目下的 `.env` / `course.env`，不依赖上级课程仓。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# 本项目根目录（与 main.py / Dockerfile WORKDIR 对齐）
PROJECT_ROOT = Path(__file__).resolve().parent
# 优先 .env，其次 course.env（仅本目录，不读上级仓库）
LOCAL_ENV_CANDIDATES = (
    PROJECT_ROOT / ".env",
    PROJECT_ROOT / "course.env",
)

# DeepSeek 已弃用 deepseek-chat / deepseek-reasoner；官方现用 v4 系列
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"
DEEPSEEK_DEFAULT_BASE = "https://api.deepseek.com"
SILICONFLOW_DEFAULT_BASE = "https://api.siliconflow.cn/v1"
SILICONFLOW_DEFAULT_CHAT = "Qwen/Qwen3-8B"
SILICONFLOW_DEFAULT_EMBED = "Qwen/Qwen3-Embedding-4B"

_LEGACY_CHAT_ALIASES = {
    "deepseek-chat": DEEPSEEK_DEFAULT_MODEL,
    "deepseek-reasoner": "deepseek-v4-pro",
}


def _strip_inline_comment(value: str) -> str:
    """去掉 VALUE 里的行内注释（# 及之后），避免模型名带上说明文字。"""
    text = value.strip().strip("\"'")
    if "#" not in text:
        return text.strip()
    # 保留 URL 片段里的 #；配置值里常见的是「模型名 # 说明」
    if "://" in text and text.index("#") > text.index("://"):
        return text.strip()
    return text.split("#", 1)[0].strip()


def load_dotenv_files() -> None:
    """把本项目 .env / course.env 里尚未存在的键写入进程环境（不覆盖已 export 的值）。"""
    for env_path in LOCAL_ENV_CANDIDATES:
        if not env_path.exists():
            continue
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), _strip_inline_comment(value))
        break  # 只读第一个存在的文件，避免两份互相覆盖造成困惑


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = _strip_inline_comment(os.getenv(name, ""))
        if value:
            return value
    return default


def _normalize_chat_model(model: str, base_url: str) -> str:
    """把已废弃的 deepseek-chat 等映射到当前可用模型名。"""
    key = _strip_inline_comment(model or "")
    lowered = key.lower()
    if lowered in _LEGACY_CHAT_ALIASES:
        return _LEGACY_CHAT_ALIASES[lowered]
    if "deepseek.com" in base_url.lower() and lowered in {"", "deepseek-chat"}:
        return DEEPSEEK_DEFAULT_MODEL
    return key or SILICONFLOW_DEFAULT_CHAT


def load_analyzer_config() -> dict[str, str]:
    """模块 Agent / 报告生成用的聊天模型配置。

    优先级：AGENT_ANALYZER_* > AGENT_OPENAI_* > 硅基默认（保持旧行为）。
    换 DeepSeek 时请显式 export ANALYZER_* 或覆盖 OPENAI_BASE_URL/MODEL。
    """
    load_dotenv_files()
    base_url = _env(
        "AGENT_ANALYZER_BASE_URL",
        "AGENT_OPENAI_BASE_URL",
        default=SILICONFLOW_DEFAULT_BASE,
    ).rstrip("/")
    model = _normalize_chat_model(
        _env(
            "AGENT_ANALYZER_MODEL",
            "AGENT_OPENAI_MODEL",
            default=SILICONFLOW_DEFAULT_CHAT,
        ),
        base_url,
    )
    return {
        "api_key": _env("AGENT_ANALYZER_API_KEY", "AGENT_OPENAI_API_KEY"),
        "base_url": base_url,
        "model": model,
        "role": "analyzer",
    }


def load_embedding_config() -> dict[str, str]:
    """向量检索 / embedding 用的配置（默认硅基）。"""
    load_dotenv_files()
    return {
        "api_key": _env(
            "AGENT_EMBEDDING_API_KEY",
            "AGENT_OPENAI_API_KEY",
        ),
        "base_url": _env(
            "AGENT_EMBEDDING_BASE_URL",
            "AGENT_RAG_RERANK_BASE_URL",
            default=SILICONFLOW_DEFAULT_BASE,
        ).rstrip("/"),
        "model": _env(
            "AGENT_EMBEDDING_MODEL",
            default=SILICONFLOW_DEFAULT_EMBED,
        ),
        "role": "embedding",
    }


def chat_request_extras(config: dict[str, str]) -> dict[str, Any]:
    """按网关拼专属字段：硅基关 Qwen thinking；DeepSeek V4 关 thinking 以稳定工具调用。"""
    base = config.get("base_url", "").lower()
    model = config.get("model", "").lower()
    extras: dict[str, Any] = {}
    if "qwen" in model or "siliconflow" in base:
        extras["enable_thinking"] = False
    if "deepseek" in base or model.startswith("deepseek"):
        # V4 默认 thinking；工具多轮若不回传 reasoning_content 会 400。
        # 模块 Agent 循环里先关掉 thinking，保证 function calling 稳定。
        extras["thinking"] = {"type": "disabled"}
    return extras
