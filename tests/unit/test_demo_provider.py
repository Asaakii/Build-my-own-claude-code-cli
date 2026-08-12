"""DemoProvider 的单元测试。"""

from agent_code.models import Message
from agent_code.providers.demo import DemoProvider


def test_demo_provider_requests_echo_for_user_message() -> None:
    """收到用户输入时，应请求 echo 工具。"""
    response = DemoProvider().respond([Message(role="user", content="你好")])

    assert response.tool_calls[0].name == "echo"
    assert response.tool_calls[0].arguments == {"text": "你好"}


def test_demo_provider_returns_final_text_after_tool_result() -> None:
    """收到工具结果时，应返回最终文本。"""
    response = DemoProvider().respond(
        [
            Message(
                role="tool",
                content="你好",
                tool_call_id="demo-echo-1",
            )
        ]
    )

    assert response.text == "演示完成：你好"