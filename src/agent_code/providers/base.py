"""模型 Provider 的统一接口。"""

from collections.abc import Sequence
from typing import Protocol

from agent_code.models import Message, ModelResponse
from agent_code.tools.base import Tool


class ProviderError(RuntimeError):
    """模型 Provider 无法完成请求时抛出的用户可读错误。"""


class Provider(Protocol):
    """负责把消息与工具定义发送给模型，并返回响应。"""

    def respond(
        self,
        messages: Sequence[Message],
        tools: Sequence[Tool] = (),
    ) -> ModelResponse:
        """根据当前消息历史和可用工具生成下一次模型响应。"""