"""Agent Loop 的单元测试。"""

import pytest

from agent_code.agent import Agent
from agent_code.hooks import PostToolUseEvent, PreToolUseDecision, PreToolUseEvent
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


def test_agent_sends_project_memory_without_storing_it_in_history() -> None:
    """项目记忆应注入请求，但不伪装为可恢复的历史消息。"""
    provider = MockProvider(responses=[ModelResponse(text="收到。")])
    agent = Agent(provider=provider, tools=[])

    result = agent.run(
        "新问题",
        history=(Message(role="user", content="旧问题"),),
        project_memory="以下是用户显式保存的项目长期约定：\n- 使用 Python 3.12。",
    )

    assert provider.requests[0] == (
        Message(
            role="user",
            content="以下是用户显式保存的项目长期约定：\n- 使用 Python 3.12。",
        ),
        Message(role="user", content="旧问题"),
        Message(role="user", content="新问题"),
    )
    assert result.messages == (
        Message(role="user", content="旧问题"),
        Message(role="user", content="新问题"),
        Message(role="assistant", content="收到。"),
    )


def test_pre_tool_hook_can_deny_tool_and_post_hook_observes_denial() -> None:
    """PreToolUse 拒绝应阻止执行，PostToolUse 仍可观察最小结果。"""
    tool_call = ToolCall(id="call-1", name="echo", arguments={"text": "不应执行"})
    provider = MockProvider(
        responses=[
            ModelResponse(tool_calls=(tool_call,)),
            ModelResponse(text="已处理。"),
        ]
    )
    post_events: list[PostToolUseEvent] = []

    class DenyHook:
        def before_tool_use(self, event: PreToolUseEvent) -> PreToolUseDecision:
            assert event.tool_call == tool_call
            return PreToolUseDecision(allow=False, reason="需要人工复核")

    class ObserveHook:
        def after_tool_use(self, event: PostToolUseEvent) -> None:
            post_events.append(event)

    agent = Agent(
        provider=provider,
        tools=[EchoTool()],
        pre_tool_use_hooks=[DenyHook()],
        post_tool_use_hooks=[ObserveHook()],
    )

    agent.run("调用工具")

    assert "需要人工复核" in provider.requests[1][-1].content
    assert post_events == [
        PostToolUseEvent(
            tool_call=tool_call,
            succeeded=False,
            result_summary="工具调用已被 PreToolUse Hook 拒绝：需要人工复核",
        )
    ]


def test_hook_exceptions_do_not_break_tool_loop() -> None:
    """非关键 Hook 异常不能阻止工具执行或后续模型回答。"""
    tool_call = ToolCall(id="call-1", name="echo", arguments={"text": "正常结果"})
    provider = MockProvider(
        responses=[ModelResponse(tool_calls=(tool_call,)), ModelResponse(text="完成。")]
    )

    class BrokenPreHook:
        def before_tool_use(self, event: PreToolUseEvent) -> PreToolUseDecision:
            raise RuntimeError("pre hook failed")

    class BrokenPostHook:
        def after_tool_use(self, event: PostToolUseEvent) -> None:
            raise RuntimeError("post hook failed")

    agent = Agent(
        provider=provider,
        tools=[EchoTool()],
        pre_tool_use_hooks=[BrokenPreHook()],
        post_tool_use_hooks=[BrokenPostHook()],
    )

    assert agent.run("调用工具").text == "完成。"
    assert provider.requests[1][-1].content == "正常结果"
