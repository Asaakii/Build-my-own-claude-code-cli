"""模型 Provider 的统一接口。"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from agent_code.models import Message, ModelResponse
from agent_code.tools.base import Tool


class ProviderError(RuntimeError):
    """模型 Provider 无法完成请求时抛出的用户可读错误。"""


@dataclass(frozen=True)
class ProviderStreamEvent:
    """Provider 流式响应中的一段文本或最终完整响应。"""

    text_delta: str = ""
    response: ModelResponse | None = None


class Provider(Protocol):
    """负责把消息与工具定义发送给模型，并返回响应。"""

    def respond(
        self,
        messages: Sequence[Message],
        tools: Sequence[Tool] = (),
    ) -> ModelResponse:
        """根据当前消息历史和可用工具生成下一次模型响应。"""


class StreamingProvider(Protocol):
    """可在完整响应落定前输出文本片段的 Provider。"""

    def stream_respond(
        self,
        messages: Sequence[Message],
        tools: Sequence[Tool] = (),
    ) -> Iterator[ProviderStreamEvent]:
        """按顺序产出文本片段，并以最终响应结束。"""
