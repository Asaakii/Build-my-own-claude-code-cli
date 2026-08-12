"""Agent 运行时使用的基础数据模型。"""

from dataclasses import dataclass
from typing import Any, Literal

Role = Literal["user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    """模型请求调用工具时携带的信息。"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    """Agent 与模型之间保存的一条消息。"""

    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ModelResponse:
    """Provider 返回给 Agent 的模型响应。"""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()