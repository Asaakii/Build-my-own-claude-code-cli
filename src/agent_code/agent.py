"""最小 Agent Loop。"""

from collections.abc import Iterable
from dataclasses import dataclass

from agent_code.models import Message, ToolCall
from agent_code.providers.base import Provider
from agent_code.tools.base import Tool


@dataclass(frozen=True)
class AgentResult:
    """一次 Agent 运行结束后返回的结果。"""

    text: str
    messages: tuple[Message, ...]


class Agent:
    """负责模型请求、工具执行和结果回填的最小循环。"""

    def __init__(
        self,
        provider: Provider,
        tools: Iterable[Tool],
        max_turns: int = 10,
    ) -> None:
        if max_turns <= 0:
            raise ValueError("max_turns 必须大于 0。")

        self._provider = provider
        self._tools = {tool.name: tool for tool in tools}
        self._max_turns = max_turns

    def run(self, prompt: str) -> AgentResult:
        """执行一次“模型 → 工具 → 模型”的循环。"""
        messages = [Message(role="user", content=prompt)]

        for _ in range(self._max_turns):
            response = self._provider.respond(
                messages,
                tools=tuple(self._tools.values()),
            )
            messages.append(
                Message(
                    role="assistant",
                    content=response.text,
                    tool_calls=response.tool_calls,
                )
            )

            if not response.tool_calls:
                return AgentResult(
                    text=response.text,
                    messages=tuple(messages),
                )

            for tool_call in response.tool_calls:
                messages.append(
                    Message(
                        role="tool",
                        content=self._execute_tool(tool_call),
                        tool_call_id=tool_call.id,
                    )
                )

        raise RuntimeError(
            f"Agent 在 {self._max_turns} 轮后仍未结束，已停止继续执行。"
        )

    def _execute_tool(self, tool_call: ToolCall) -> str:
        """执行单个工具调用，并将失败转为可供模型处理的结果。"""
        tool = self._tools.get(tool_call.name)

        if tool is None:
            return f"工具调用失败：未找到工具 {tool_call.name!r}。"

        try:
            return tool.run(tool_call.arguments)
        except Exception as error:
            return f"工具调用失败：{error}"