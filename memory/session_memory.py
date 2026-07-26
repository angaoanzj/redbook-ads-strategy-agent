"""Short-lived structured memory for multi-turn strategy requests."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from agent_state import AgentStateStore


class SessionMemoryStore:
    SENSITIVE_KEY_PARTS = ("key", "token", "cookie", "authorization", "secret", "password", "credential")
    SENSITIVE_TEXT = re.compile(r"(?:1[3-9]\d{9}|手机号|身份证|银行卡|api[_ -]?key|cookie|authorization|审批|resume[_-]?token)", re.I)

    def __init__(self, state: AgentStateStore, *, ttl_seconds: int = 86400, max_items: int = 32):
        self.state = state
        self.ttl_seconds = max(1, ttl_seconds)
        self.max_items = max(1, max_items)

    def remember(self, session_id: str, values: dict[str, Any], *, ttl_seconds: int | None = None,
                 now: datetime | None = None) -> list[dict[str, Any]]:
        decisions: list[dict[str, Any]] = []
        safe: dict[str, Any] = {}
        for key, value in values.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if any(part in normalized for part in self.SENSITIVE_KEY_PARTS) or self.SENSITIVE_TEXT.search(str(value)):
                decisions.append({"key": str(key), "accepted": False, "reason": "敏感、凭据或高风险内容不得写入 Session Memory"})
                continue
            if value is None or value == "":
                continue
            safe[str(key)] = value
            decisions.append({"key": str(key), "value": value, "accepted": True, "ttl": "session"})
        if safe:
            self.state.set_session_memory(
                session_id, safe,
                ttl_seconds=ttl_seconds or self.ttl_seconds,
                max_items=self.max_items,
                now=now,
            )
        return decisions

    def load(self, session_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        return self.state.get_session_memory(session_id, now=now)

    def merge(self, session_id: str, explicit: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        merged = self.load(session_id, now=now)
        merged.update({key: value for key, value in explicit.items() if value not in (None, "")})
        return merged
