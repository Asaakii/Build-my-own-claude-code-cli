"""EchoTool 的单元测试。"""

import pytest

from agent_code.tools.echo import EchoTool


def test_echo_tool_returns_text() -> None:
    """echo 工具应原样返回 text。"""
    assert EchoTool().run({"text": "你好"}) == "你好"


def test_echo_tool_rejects_missing_or_non_string_text() -> None:
    """缺少 text 或 text 不是字符串时，应给出明确错误。"""
    tool = EchoTool()

    with pytest.raises(ValueError, match="字符串类型"):
        tool.run({})

    with pytest.raises(ValueError, match="字符串类型"):
        tool.run({"text": 42})