"""最小 Agent Loop。"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from agent_code.context import ContextManager, ContextReport, TokenEstimator
from agent_code.hooks import (
    PostToolUseEvent,
    PostToolUseHook,
    PreToolUseDecision,
    PreToolUseEvent,
    PreToolUseHook,
)
from agent_code.models import Message, ModelResponse, ToolCall
from agent_code.providers.base import Provider, ProviderError, ProviderStreamEvent
from agent_code.tools.base import Tool


@dataclass(frozen=True)
class AgentResult:
    """一次 Agent 运行结束后返回的结果。"""

    text: str
    messages: tuple[Message, ...]
    context_report: ContextReport


@dataclass(frozen=True)
class AgentStreamEvent:
    """Agent 向界面发出的文本片段或一次运行的最终结果。"""

    text_delta: str = ""
    result: AgentResult | None = None


class Agent:
    """负责模型请求、工具执行和结果回填的最小循环。"""

    def __init__(
        self,
        provider: Provider,
        tools: Iterable[Tool],
        pre_tool_use_hooks: Iterable[PreToolUseHook] = (),
        post_tool_use_hooks: Iterable[PostToolUseHook] = (),
        token_estimator: TokenEstimator | None = None,
        max_turns: int = 10,
    ) -> None:
        if max_turns <= 0:
            raise ValueError("max_turns 必须大于 0。")

        self._provider = provider
        self._tools = {tool.name: tool for tool in tools}
        self._pre_tool_use_hooks = tuple(pre_tool_use_hooks)
        self._post_tool_use_hooks = tuple(post_tool_use_hooks)
        self._max_turns = max_turns
        self._token_estimator = token_estimator

    def run(
        self,
        prompt: str,
        history: Sequence[Message] = (),
        project_memory: str = "",
    ) -> AgentResult:
        """执行一次循环，并在不需要界面流式显示时收集最终结果。"""
        for event in self.run_stream(
            prompt,
            history=history,
            project_memory=project_memory,
        ):
            if event.result is not None:
                return event.result

        raise RuntimeError("Agent 未返回最终结果。")

    def run_stream(
        self,
        prompt: str,
        history: Sequence[Message] = (),
        project_memory: str = "",
    ) -> Iterable[AgentStreamEvent]:
        """执行循环并在模型生成时立即产出文本片段。"""
        if any(message.role not in {"user", "assistant"} for message in history):
            raise ValueError("恢复的会话历史只允许 user 或 assistant 消息。")

        context_manager = ContextManager(self._token_estimator)
        messages: list[Message] = []
        project_memory_message_count = 0

        if project_memory:
            messages.append(Message(role="user", content=project_memory))
            project_memory_message_count = 1

        messages.extend(context_manager.prepare_history(history))
        messages.append(Message(role="user", content=prompt))

        for _ in range(self._max_turns):
            context_manager.record_request(messages)
            response: ModelResponse | None = None

            for event in self._stream_provider_response(messages):
                if event.response is not None:
                    response = event.response
                elif event.text_delta:
                    yield AgentStreamEvent(text_delta=event.text_delta)

            if response is None:
                raise ProviderError("模型服务未返回完整响应。")

            messages.append(
                Message(
                    role="assistant",
                    content=response.text,
                    tool_calls=response.tool_calls,
                )
            )
            context_manager.record_model_output(response.text)

            if not response.tool_calls:
                yield AgentStreamEvent(
                    result=AgentResult(
                        text=response.text,
                        messages=tuple(messages[project_memory_message_count:]),
                        context_report=context_manager.report(),
                    )
                )
                return

            for tool_call in response.tool_calls:
                messages.append(
                    Message(
                        role="tool",
                        content=context_manager.limit_tool_result(
                            self._execute_tool(tool_call)
                        ),
                        tool_call_id=tool_call.id,
                    )
                )

        raise RuntimeError(
            f"Agent 在 {self._max_turns} 轮后仍未结束，已停止继续执行。"
        )

    def _stream_provider_response(
        self,
        messages: Sequence[Message],
    ) -> Iterable[ProviderStreamEvent]:
        """优先使用 Provider 的流式能力；其他 Provider 保持原有同步行为。"""
        stream_respond = getattr(self._provider, "stream_respond", None)

        if callable(stream_respond):
            yield from stream_respond(messages, tools=tuple(self._tools.values()))
            return

        yield ProviderStreamEvent(
            response=self._provider.respond(
                messages,
                tools=tuple(self._tools.values()),
            )
        )

    def _execute_tool(self, tool_call: ToolCall) -> str:
        """执行单个工具调用，并将失败转为可供模型处理的结果。"""
        for hook in self._pre_tool_use_hooks:
            try:
                decision = hook.before_tool_use(PreToolUseEvent(tool_call=tool_call))
            except Exception:
                continue

            if not isinstance(decision, PreToolUseDecision):
                continue

            if not decision.allow:
                reason = decision.reason or "未提供原因"
                result = f"工具调用已被 PreToolUse Hook 拒绝：{reason}"
                self._notify_post_tool_use(tool_call, succeeded=False, result=result)
                return result

        tool = self._tools.get(tool_call.name)

        if tool is None:
            result = f"工具调用失败：未找到工具 {tool_call.name!r}。"
            self._notify_post_tool_use(tool_call, succeeded=False, result=result)
            return result

        try:
            result = tool.run(tool_call.arguments)
        except Exception as error:
            result = f"工具调用失败：{error}"
            self._notify_post_tool_use(tool_call, succeeded=False, result=result)
            return result

        self._notify_post_tool_use(tool_call, succeeded=True, result=result)
        return result

    def _notify_post_tool_use(
        self,
        tool_call: ToolCall,
        *,
        succeeded: bool,
        result: str,
    ) -> None:
        """隔离后置 Hook 失败，并限制其收到的工具结果长度。"""
        event = PostToolUseEvent(
            tool_call=tool_call,
            succeeded=succeeded,
            result_summary=result[:512],
        )

        for hook in self._post_tool_use_hooks:
            try:
                hook.after_tool_use(event)
            except Exception:
                continue
