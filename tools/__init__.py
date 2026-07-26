"""工具层：确定性计算函数，供 LLM 通过 function calling 调用。

分工契约：
- LLM 负责「决策」：选择哪档比例、什么倍率、如何分层，并给出理由。
- 工具负责「算术与校验」：参数用 Pydantic 强校验，数字保证加得起来。
- 校验失败不抛异常，而是把错误作为 tool result 返回，让 LLM 自我修正。
"""
from tools.registry import ToolRegistry, ToolSpec
from tools.budget import BUDGET_TOOLS
from tools.bidding import BIDDING_TOOLS
from tools.competitors import COMPETITOR_TOOLS
from tools.creators import CREATOR_TOOLS
from tools.creator_match import CREATOR_MATCH_TOOLS
from tools.forecast import FORECAST_TOOLS
from tools.keywords import KEYWORD_TOOLS
from tools.topics import TOPIC_TOOLS
from tools.trending import TRENDING_TOOLS
from tools.content_audit import CONTENT_AUDIT_TOOLS
from tools.ab_test import AB_TEST_TOOLS
from tools.competitor_monitor import COMPETITOR_MONITOR_TOOLS

DEFAULT_REGISTRY = ToolRegistry(
    [
        *BUDGET_TOOLS,
        *BIDDING_TOOLS,
        *COMPETITOR_TOOLS,
        *CREATOR_TOOLS,
        *CREATOR_MATCH_TOOLS,
        *FORECAST_TOOLS,
        *KEYWORD_TOOLS,
        *TOPIC_TOOLS,
        *TRENDING_TOOLS,
        *CONTENT_AUDIT_TOOLS,
        *AB_TEST_TOOLS,
        *COMPETITOR_MONITOR_TOOLS,
    ]
)

__all__ = ["ToolRegistry", "ToolSpec", "DEFAULT_REGISTRY"]
