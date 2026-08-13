"""可测量的上下文预算、工具截断和历史摘要。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil
from typing import Protocol

from agent_code.models import Message


class TokenEstimator(Protocol):
    """近似 token 估算器，可由真实模型的计费器替换。"""

    def estimate(self, text: str) -> int:
        """估算文本占用的 token 数。"""


class CharacterTokenEstimator:
    """按四字符约一 token 的保守、无外部依赖估算器。"""

    def estimate(self, text: str) -> int:
        return ceil(len(text) / 4)


@dataclass(frozen=True)
class ContextReport:
    """不含正文或凭据的本次运行上下文统计。"""

    input_chars: int
    input_tokens: int
    output_chars: int
    output_tokens: int
    tool_result_chars: int
    tool_result_tokens: int
    truncated_tool_results: int
    summarized_history_messages: int
    summary_reason: str | None


class ContextManager:
    """对本次 Agent 运行的输入、输出与历史应用有限预算。"""

    max_tool_result_chars = 2_000
    max_history_chars = 8_000
    recent_history_messages = 4
    max_summary_chars = 1_200

    def __init__(self, estimator: TokenEstimator | None = None) -> None:
        self._estimator = estimator or CharacterTokenEstimator()
        self._input_chars = 0
        self._input_tokens = 0
        self._output_chars = 0
        self._output_tokens = 0
        self._tool_result_chars = 0
        self._tool_result_tokens = 0
        self._truncated_tool_results = 0
        self._summarized_history_messages = 0
        self._summary_reason: str | None = None

    def prepare_history(self, history: Sequence[Message]) -> tuple[Message, ...]:
        """在超限时压缩较旧消息，保留最近原始消息以维持任务连续性。"""
        history_chars = sum(len(message.content) for message in history)

        if history_chars <= self.max_history_chars:
            return tuple(history)

        split_at = max(0, len(history) - self.recent_history_messages)
        older_messages = history[:split_at]
        recent_messages = history[split_at:]

        if not older_messages:
            older_messages = history[:-1]
            recent_messages = history[-1:]

        source = _summarize_messages(older_messages, self.max_summary_chars)
        self._summarized_history_messages = len(older_messages)
        self._summary_reason = (
            f"历史内容为 {history_chars} 字符，超过 {self.max_history_chars} 字符预算"
        )
        summary = Message(
            role="user",
            content=(
                "历史摘要（来源：会话较早消息；触发原因："
                f"{self._summary_reason}）：\n{source}"
            ),
        )
        return (summary, *recent_messages)

    def record_request(self, messages: Sequence[Message]) -> None:
        """累计发送给 Provider 的文本规模，不记录文本本身。"""
        self._input_chars += sum(len(message.content) for message in messages)
        self._input_tokens += sum(
            self._estimator.estimate(message.content) for message in messages
        )

    def record_model_output(self, text: str) -> None:
        """累计模型文本输出规模。"""
        self._output_chars += len(text)
        self._output_tokens += self._estimator.estimate(text)

    def limit_tool_result(self, result: str) -> str:
        """限制进入模型历史的工具输出，防止单次结果无限膨胀。"""
        self._tool_result_chars += len(result)
        self._tool_result_tokens += self._estimator.estimate(result)

        if len(result) <= self.max_tool_result_chars:
            return result

        self._truncated_tool_results += 1
        return (
            result[: self.max_tool_result_chars]
            + f"\n[工具输出已截断：原始长度 {len(result)} 字符]"
        )

    def report(self) -> ContextReport:
        """返回仅包含聚合数字与摘要原因的可观测性报告。"""
        return ContextReport(
            input_chars=self._input_chars,
            input_tokens=self._input_tokens,
            output_chars=self._output_chars,
            output_tokens=self._output_tokens,
            tool_result_chars=self._tool_result_chars,
            tool_result_tokens=self._tool_result_tokens,
            truncated_tool_results=self._truncated_tool_results,
            summarized_history_messages=self._summarized_history_messages,
            summary_reason=self._summary_reason,
        )


def _summarize_messages(messages: Sequence[Message], limit: int) -> str:
    lines: list[str] = []
    remaining = limit

    for index, message in enumerate(messages, start=1):
        excerpt = message.content.replace("\n", " ")
        line = f"{index}. {message.role}: {excerpt}"

        if len(line) > remaining:
            lines.append(line[:remaining] + "…")
            break

        lines.append(line)
        remaining -= len(line) + 1

        if remaining <= 0:
            break

    return "\n".join(lines) or "无可摘要的历史消息。"
