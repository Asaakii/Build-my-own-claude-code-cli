"""Agent Loop 的单元测试。"""

import pytest

from agent_code.agent import Agent
from agent_code.models import Message, ModelResponse, ToolCall
from agent_code.providers.mock import MockProvider
from agent_code.tools.echo import EchoTool


def test_agent_returns_text_when_model_does_not_call_tools() -> None:
    """模型直接回答时，Agent 应立即结束。"""
    provider = MockProvider(responses=[ModelResponse(text="你好，世界！")])
    agent = Agent(provider=provider, tools=[])

    result = agent.run("打个招呼")

    assert result.text == "你好，世界！"
    assert result.messages == (
        Message(role="user", content="打个招呼"),
        Message(role="assistant", content="你好，世界！"),
    )


def test_agent_executes_tool_and_returns_follow_up_response() -> None:
    """模型请求工具后，Agent 应回填工具结果并继续请求模型。"""
    tool_call = ToolCall(
        id="call-1",
        name="echo",
        arguments={"text": "来自 echo 的文本"},
    )
    provider = MockProvider(
        responses=[
            ModelResponse(tool_calls=(tool_call,)),
            ModelResponse(text="工具调用完成。"),
        ]
    )
    agent = Agent(provider=provider, tools=[EchoTool()])

    result = agent.run("调用 echo 工具")

    assert result.text == "工具调用完成。"
    assert provider.requests[1][-1] == Message(
        role="tool",
        content="来自 echo 的文本",
        tool_call_id="call-1",
    )


def test_agent_returns_unknown_tool_error_to_model() -> None:
    """未知工具不应让循环崩溃，而应作为工具结果回传。"""
    provider = MockProvider(
        responses=[
            ModelResponse(
                tool_calls=(
                    ToolCall(id="call-1", name="missing", arguments={}),
                )
            ),
            ModelResponse(text="已收到工具失败信息。"),
        ]
    )
    agent = Agent(provider=provider, tools=[])

    result = agent.run("调用不存在的工具")

    assert result.text == "已收到工具失败信息。"
    assert "未找到工具 'missing'" in provider.requests[1][-1].content


def test_agent_stops_after_reaching_max_turns() -> None:
    """模型持续调用工具时，Agent 必须受 max_turns 限制。"""
    tool_call = ToolCall(id="call-1", name="echo", arguments={"text": "继续"})
    provider = MockProvider(responses=[ModelResponse(tool_calls=(tool_call,))])
    agent = Agent(provider=provider, tools=[EchoTool()], max_turns=1)

    with pytest.raises(RuntimeError, match="1 轮后仍未结束"):
        agent.run("不要结束")


def test_agent_sends_restored_history_before_new_prompt() -> None:
    """恢复的 user / assistant 消息应先于当前输入发送给模型。"""
    provider = MockProvider(responses=[ModelResponse(text="继续回答。")])
    agent = Agent(provider=provider, tools=[])
    history = (
        Message(role="user", content="旧问题"),
        Message(role="assistant", content="旧回答"),
    )

    agent.run("新问题", history=history)

    assert provider.requests[0] == (
        Message(role="user", content="旧问题"),
        Message(role="assistant", content="旧回答"),
        Message(role="user", content="新问题"),
    )