"""不调用真实网络模型的测试 Provider。"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from agent_code.models import Message, ModelResponse
from agent_code.tools.base import Tool


@dataclass
class MockProvider:
    """按预设顺序返回响应，并保存每次收到的消息。"""

    responses: list[ModelResponse]
    requests: list[tuple[Message, ...]] = field(default_factory=list, init=False)

    def respond(
        self,
        messages: Sequence[Message],
        tools: Sequence[Tool] = (),
    ) -> ModelResponse:
        """记录请求，并取出下一条预设响应。"""
        self.requests.append(tuple(messages))

        if not self.responses:
            raise RuntimeError("MockProvider 没有可返回的预设响应。")

        return self.responses.pop(0)