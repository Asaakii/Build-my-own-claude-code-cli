"""模型 Provider 的统一接口。"""

from collections.abc import Sequence
from typing import Protocol

from agent_code.models import Message, ModelResponse


class Provider(Protocol):
    """负责把消息发送给模型并返回响应。"""

    def respond(self, messages: Sequence[Message]) -> ModelResponse:
        """根据当前消息历史生成下一次模型响应。"""