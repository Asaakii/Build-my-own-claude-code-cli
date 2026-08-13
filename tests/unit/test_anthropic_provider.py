"""AnthropicProvider 的单元测试。"""

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from anthropic import APIConnectionError, AuthenticationError, RateLimitError

from agent_code.models import Message, ToolCall
from agent_code.providers.anthropic import AnthropicProvider
from agent_code.providers.base import ProviderError
from agent_code.tools.echo import EchoTool


class FakeMessagesAPI:
    """记录请求并返回预设响应的假 Messages API。"""

    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        """保存请求参数并返回预设响应。"""
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    """用于隔离网络的假 Anthropic 客户端。"""

    def __init__(self, response: object) -> None:
        self.messages = FakeMessagesAPI(response)


def test_provider_sends_tool_schema_and_parses_tool_call() -> None:
    """Provider 应发送工具 schema，并解析 text 与 tool_use 内容块。"""
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="我将调用 echo。"),
            SimpleNamespace(
                type="tool_use",
                id="tool-1",
                name="echo",
                input={"text": "你好"},
            ),
        ]
    )
    client = FakeClient(response)
    provider = AnthropicProvider(
        api_key="test-key",
        model="test-model",
        client=client,
    )

    result = provider.respond(
        [Message(role="user", content="请调用 echo")],
        tools=[EchoTool()],
    )

    assert result.text == "我将调用 echo。"
    assert result.tool_calls == (
        ToolCall(
            id="tool-1",
            name="echo",
            arguments={"text": "你好"},
        ),
    )

    request = client.messages.calls[0]
    assert request["messages"] == [
        {
            "role": "user",
            "content": [{"type": "text", "text": "请调用 echo"}],
        }
    ]
    assert request["tools"][0]["name"] == "echo"


def test_provider_converts_tool_result_to_user_content_block() -> None:
    """工具结果应转换为 Anthropic 要求的 user/tool_result 内容块。"""
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="工具已完成。")]
    )
    client = FakeClient(response)
    provider = AnthropicProvider(
        api_key="test-key",
        model="test-model",
        client=client,
    )

    provider.respond(
        [
            Message(role="user", content="请调用 echo"),
            Message(
                role="assistant",
                tool_calls=(
                    ToolCall(
                        id="tool-1",
                        name="echo",
                        arguments={"text": "你好"},
                    ),
                ),
            ),
            Message(
                role="tool",
                content="你好",
                tool_call_id="tool-1",
            ),
        ]
    )

    assert client.messages.calls[0]["messages"] == [
        {
            "role": "user",
            "content": [{"type": "text", "text": "请调用 echo"}],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "echo",
                    "input": {"text": "你好"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-1",
                    "content": "你好",
                }
            ],
        },
    ]


def test_provider_streams_text_and_collects_complete_tool_arguments() -> None:
    """流式文本应立即向上游发出，工具参数只在收齐后作为最终响应返回。"""
    stream_events = [
        SimpleNamespace(
            type="content_block_start",
            index=0,
            content_block=SimpleNamespace(type="text"),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=0,
            delta=SimpleNamespace(type="text_delta", text="先输出"),
        ),
        SimpleNamespace(
            type="content_block_start",
            index=1,
            content_block=SimpleNamespace(
                type="tool_use",
                id="tool-1",
                name="echo",
            ),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=1,
            delta=SimpleNamespace(type="input_json_delta", partial_json='{"text":'),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=1,
            delta=SimpleNamespace(type="input_json_delta", partial_json='"你好"}'),
        ),
    ]
    client = FakeClient(stream_events)
    provider = AnthropicProvider(
        api_key="test-key",
        model="test-model",
        client=client,
    )

    events = list(
        provider.stream_respond(
            [Message(role="user", content="请调用 echo")],
            tools=[EchoTool()],
        )
    )

    assert [event.text_delta for event in events[:-1]] == ["先输出"]
    assert events[-1].response is not None
    assert events[-1].response.text == "先输出"
    assert events[-1].response.tool_calls == (
        ToolCall(id="tool-1", name="echo", arguments={"text": "你好"}),
    )
    assert client.messages.calls[0]["stream"] is True





@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            AuthenticationError(
                "invalid key",
                response=httpx.Response(
                    401,
                    request=httpx.Request(
                        "POST",
                        "https://api.example.com/v1/messages",
                    ),
                ),
                body=None,
            ),
            "认证失败",
        ),
        (
            RateLimitError(
                "rate limited",
                response=httpx.Response(
                    429,
                    request=httpx.Request(
                        "POST",
                        "https://api.example.com/v1/messages",
                    ),
                ),
                body=None,
            ),
            "触发限流",
        ),
        (
            APIConnectionError(
                message="connection failed",
                request=httpx.Request(
                    "POST",
                    "https://api.example.com/v1/messages",
                ),
            ),
            "无法连接",
        ),
    ],
)
def test_provider_converts_api_errors_to_safe_messages(
    error: Exception,
    message: str,
) -> None:
    """SDK 异常应转为不含敏感信息的用户可读错误。"""

    class FailingMessagesAPI:
        """始终抛出指定异常的假 API。"""

        def create(self, **kwargs: Any) -> object:
            """模拟 API 请求失败。"""
            raise error

    class FailingClient:
        """使用失败 API 的假客户端。"""

        messages = FailingMessagesAPI()

    provider = AnthropicProvider(
        api_key="secret-value-must-not-appear",
        model="test-model",
        client=FailingClient(),
    )

    with pytest.raises(ProviderError, match=message) as error_info:
        provider.respond([Message(role="user", content="你好")])

    assert "secret-value-must-not-appear" not in str(error_info.value)
