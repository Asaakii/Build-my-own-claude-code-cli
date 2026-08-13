"""受限只读子代理测试。"""

import time

from agent_code.models import ModelResponse
from agent_code.providers.mock import MockProvider
from agent_code.subagents import (
    ReadOnlySubagentRunner,
    ResearchResult,
    ResearchTask,
    SubagentStatus,
)


def test_subagents_run_independent_read_only_tasks_in_parallel() -> None:
    """两个任务分别创建无工具 Agent，并按输入顺序返回结构化结论。"""
    responses = iter([ModelResponse(text="结论 A"), ModelResponse(text="结论 B")])
    runner = ReadOnlySubagentRunner(lambda: MockProvider(responses=[next(responses)]))
    tasks = (ResearchTask("a", "研究 A"), ResearchTask("b", "研究 B"))

    assert runner.run(tasks) == (
        ResearchResult("a", SubagentStatus.COMPLETED, "结论 A"),
        ResearchResult("b", SubagentStatus.COMPLETED, "结论 B"),
    )


def test_subagents_finish_two_independent_research_tasks_in_parallel() -> None:
    """两项独立研究应受并发数上限约束而不是串行等待。"""
    class DelayedProvider:
        def respond(self, messages, tools=()):
            time.sleep(0.05)
            return ModelResponse(text="完成")

    runner = ReadOnlySubagentRunner(lambda: DelayedProvider())
    started_at = time.monotonic()
    results = runner.run(
        (ResearchTask("a", "A"), ResearchTask("b", "B")),
        timeout_seconds=1,
    )

    assert time.monotonic() - started_at < 0.09
    assert all(result.status is SubagentStatus.COMPLETED for result in results)


def test_subagent_cancellation_failure_timeout_and_depth_do_not_block_others() -> None:
    """取消、失败、超时和递归限制均返回结论状态而非抛出主会话错误。"""
    class SlowProvider:
        def respond(self, messages, tools=()):
            time.sleep(0.05)
            return ModelResponse(text="太慢")

    runner = ReadOnlySubagentRunner(lambda: SlowProvider())
    cancelled = ResearchTask("cancel", "取消")
    runner.cancel(cancelled.id)

    assert runner.run((cancelled,))[0].status is SubagentStatus.CANCELLED
    slow_result = runner.run(
        (ResearchTask("slow", "慢"),),
        timeout_seconds=0.001,
    )
    depth_result = runner.run((ResearchTask("deep", "深"),), depth=2)

    assert slow_result[0].status is SubagentStatus.TIMED_OUT
    assert depth_result[0].status is SubagentStatus.DEPTH_LIMITED


def test_subagent_failure_is_returned_as_structured_result() -> None:
    """单个 Provider 异常不应向主会话抛出未处理错误。"""
    class FailingProvider:
        def respond(self, messages, tools=()):
            raise RuntimeError("provider down")

    result = ReadOnlySubagentRunner(lambda: FailingProvider()).run(
        (ResearchTask("failed", "失败任务"),)
    )

    assert result[0].status is SubagentStatus.FAILED
    assert "provider down" in result[0].conclusion
