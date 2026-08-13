"""与 Agent Loop 解耦的工具调用 Hook 协议。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_code.models import ToolCall


@dataclass(frozen=True)
class PreToolUseEvent:
    """工具执行前提供给 Hook 的最小事件。"""

    tool_call: ToolCall


@dataclass(frozen=True)
class PreToolUseDecision:
    """前置 Hook 对工具调用作出的允许或拒绝决定。"""

    allow: bool
    reason: str = ""


@dataclass(frozen=True)
class PostToolUseEvent:
    """工具执行完成后提供给 Hook 的受限结果。"""

    tool_call: ToolCall
    succeeded: bool
    result_summary: str


class PreToolUseHook(Protocol):
    """可在工具执行前拒绝操作的 Hook。"""

    def before_tool_use(self, event: PreToolUseEvent) -> PreToolUseDecision:
        """返回本次工具调用的决定。"""


class PostToolUseHook(Protocol):
    """工具执行后的观察 Hook，不可改变既有执行结果。"""

    def after_tool_use(self, event: PostToolUseEvent) -> None:
        """接收工具调用的最小结果事件。"""
