"""Anthropic Messages API 与兼容端点的 Provider。"""

import json
from collections.abc import Iterator, Sequence
from typing import Any

from anthropic import (
    Anthropic,
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

from agent_code.models import Message, ModelResponse, ToolCall
from agent_code.providers.base import ProviderError, ProviderStreamEvent
from agent_code.tools.base import Tool


class AnthropicProvider:
    """将内部消息转换为 Anthropic Messages API 请求。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        max_tokens: int = 1024,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key 不能为空。")

        if not model:
            raise ValueError("model 不能为空。")

        if max_tokens <= 0:
            raise ValueError("max_tokens 必须大于 0。")

        self._model = model
        self._max_tokens = max_tokens

        if client is None:
            client_options: dict[str, Any] = {
                "api_key": api_key,
                "max_retries": 0,
            }

            if base_url:
                client_options["base_url"] = base_url

            client = Anthropic(**client_options)

        self._client = client

    def respond(
        self,
        messages: Sequence[Message],
        tools: Sequence[Tool] = (),
    ) -> ModelResponse:
        """调用 Messages API，并转换响应为内部模型。"""
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=self._to_api_messages(messages),
                tools=[
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.input_schema,
                    }
                    for tool in tools
                ],
            )
        except AuthenticationError as error:
            raise ProviderError(
                "模型服务认证失败。请检查本机密钥和 Base URL 配置。"
            ) from error
        except RateLimitError as error:
            raise ProviderError(
                "模型服务触发限流。请稍后再试，或检查账户额度。"
            ) from error
        except APITimeoutError as error:
            raise ProviderError(
                "模型服务请求超时。请检查网络后重试。"
            ) from error
        except APIConnectionError as error:
            raise ProviderError(
                "无法连接模型服务。请检查网络和 Base URL。"
            ) from error
        except APIStatusError as error:
            raise ProviderError(
                "模型服务返回异常状态。请稍后重试或检查服务配置。"
            ) from error
        except APIError as error:
            raise ProviderError(
                "模型服务请求失败。请检查配置后重试。"
            ) from error

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=dict(block.input),
                    )
                )

        return ModelResponse(
            text="".join(text_parts),
            tool_calls=tuple(tool_calls),
        )

    def stream_respond(
        self,
        messages: Sequence[Message],
        tools: Sequence[Tool] = (),
    ) -> Iterator[ProviderStreamEvent]:
        """流式输出文本；工具调用只在参数完整收齐后才作为最终响应返回。"""
        text_parts: list[str] = []
        tool_inputs: dict[int, dict[str, Any]] = {}

        try:
            events = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=self._to_api_messages(messages),
                tools=[
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.input_schema,
                    }
                    for tool in tools
                ],
                stream=True,
            )

            for event in events:
                event_type = getattr(event, "type", "")

                if event_type == "content_block_start":
                    block = getattr(event, "content_block", None)

                    if getattr(block, "type", "") == "tool_use":
                        tool_inputs[getattr(event, "index", 0)] = {
                            "id": getattr(block, "id", ""),
                            "name": getattr(block, "name", ""),
                            "input_json": "",
                        }
                    continue

                if event_type != "content_block_delta":
                    continue

                delta = getattr(event, "delta", None)
                delta_type = getattr(delta, "type", "")

                if delta_type == "text_delta":
                    text = getattr(delta, "text", "")
                    text_parts.append(text)
                    yield ProviderStreamEvent(text_delta=text)
                elif delta_type == "input_json_delta":
                    tool = tool_inputs.get(getattr(event, "index", 0))
                    if tool is not None:
                        tool["input_json"] += getattr(delta, "partial_json", "")
        except AuthenticationError as error:
            raise ProviderError(
                "模型服务认证失败。请检查本机密钥和 Base URL 配置。"
            ) from error
        except RateLimitError as error:
            raise ProviderError(
                "模型服务触发限流。请稍后再试，或检查账户额度。"
            ) from error
        except APITimeoutError as error:
            raise ProviderError(
                "模型服务请求超时。请检查网络后重试。"
            ) from error
        except APIConnectionError as error:
            raise ProviderError(
                "无法连接模型服务。请检查网络和 Base URL。"
            ) from error
        except APIStatusError as error:
            raise ProviderError(
                "模型服务返回异常状态。请稍后重试或检查服务配置。"
            ) from error
        except APIError as error:
            raise ProviderError(
                "模型服务请求失败。请检查配置后重试。"
            ) from error

        tool_calls: list[ToolCall] = []

        for tool in tool_inputs.values():
            try:
                arguments = json.loads(tool["input_json"] or "{}")
            except json.JSONDecodeError as error:
                raise ProviderError("模型服务返回了无效的工具参数。") from error

            if not isinstance(arguments, dict):
                raise ProviderError("模型服务返回了无效的工具参数。")

            tool_calls.append(
                ToolCall(
                    id=tool["id"],
                    name=tool["name"],
                    arguments=arguments,
                )
            )

        yield ProviderStreamEvent(
            response=ModelResponse(
                text="".join(text_parts),
                tool_calls=tuple(tool_calls),
            )
        )

    @staticmethod
    def _to_api_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
        """把内部消息转换为 Anthropic 的内容块格式。"""
        api_messages: list[dict[str, Any]] = []

        for message in messages:
            role, blocks = AnthropicProvider._to_api_blocks(message)

            if api_messages and api_messages[-1]["role"] == role:
                api_messages[-1]["content"].extend(blocks)
            else:
                api_messages.append({"role": role, "content": blocks})

        return api_messages

    @staticmethod
    def _to_api_blocks(message: Message) -> tuple[str, list[dict[str, Any]]]:
        """转换一条内部消息。"""
        if message.role == "user":
            return "user", [{"type": "text", "text": message.content}]

        if message.role == "assistant":
            blocks: list[dict[str, Any]] = []

            if message.content:
                blocks.append({"type": "text", "text": message.content})

            blocks.extend(
                {
                    "type": "tool_use",
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "input": tool_call.arguments,
                }
                for tool_call in message.tool_calls
            )
            return "assistant", blocks

        if message.role == "tool":
            if not message.tool_call_id:
                raise ValueError("工具结果消息必须包含 tool_call_id。")

            return "user", [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": message.content,
                }
            ]

        raise ValueError(f"不支持的消息角色：{message.role}")
