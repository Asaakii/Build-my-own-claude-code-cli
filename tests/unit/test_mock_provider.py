"""MockProvider 的单元测试。"""

import pytest

from agent_code.models import Message, ModelResponse
from agent_code.providers.mock import MockProvider


def test_mock_provider_returns_responses_in_order() -> None:
    """MockProvider 应按预设顺序返回响应并记录请求。"""
    first_response = ModelResponse(text="第一条响应")
    second_response = ModelResponse(text="第二条响应")
    provider = MockProvider(responses=[first_response, second_response])
    messages = [Message(role="user", content="你好")]

    assert provider.respond(messages) == first_response
    assert provider.respond(messages) == second_response
    assert provider.requests == [tuple(messages), tuple(messages)]


def test_mock_provider_raises_when_responses_are_exhausted() -> None:
    """没有预设响应时，应明确报错而不是悄悄返回空结果。"""
    provider = MockProvider(responses=[])

    with pytest.raises(RuntimeError, match="没有可返回的预设响应"):
        provider.respond([])