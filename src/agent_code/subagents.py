"""只读研究子代理的受限并发运行器。"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from uuid import uuid4

from agent_code.agent import Agent
from agent_code.providers.base import Provider


class SubagentStatus(StrEnum):
    """子代理任务的终态。"""

    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    DEPTH_LIMITED = "depth_limited"


@dataclass(frozen=True)
class ResearchTask:
    """一项仅供子代理研究的任务说明。"""

    id: str
    prompt: str


@dataclass(frozen=True)
class ResearchResult:
    """主代理收到的最小结构化子代理结论。"""

    task_id: str
    status: SubagentStatus
    conclusion: str


class ReadOnlySubagentRunner:
    """每项研究创建无工具 Agent，禁止子代理拥有写入能力。"""

    max_concurrency = 2
    max_recursion_depth = 1
    max_turns = 4
    max_result_chars = 2_000

    def __init__(self, provider_factory: Callable[[], Provider]) -> None:
        self._provider_factory = provider_factory
        self._cancelled_task_ids: set[str] = set()
        self._lock = Lock()

    def cancel(self, task_id: str) -> None:
        """取消尚未开始的任务；已运行任务在返回时转换为取消状态。"""
        with self._lock:
            self._cancelled_task_ids.add(task_id)

    def run(
        self,
        tasks: tuple[ResearchTask, ...],
        *,
        timeout_seconds: float = 10.0,
        depth: int = 0,
    ) -> tuple[ResearchResult, ...]:
        """有限并发运行独立只读研究会话，失败不会阻塞其他结论。"""
        if depth > self.max_recursion_depth:
            return tuple(
                ResearchResult(
                    task_id=task.id,
                    status=SubagentStatus.DEPTH_LIMITED,
                    conclusion="子代理递归深度超过上限，未执行。",
                )
                for task in tasks
            )

        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0。")

        if len(tasks) > self.max_concurrency:
            raise ValueError(f"一次最多运行 {self.max_concurrency} 个子代理任务。")

        if len({task.id for task in tasks}) != len(tasks):
            raise ValueError("子代理任务 ID 不能重复。")

        if not tasks:
            return ()

        executor = ThreadPoolExecutor(max_workers=self.max_concurrency)

        try:
            futures = {executor.submit(self._run_one, task): task for task in tasks}
            done, pending = wait(futures, timeout=timeout_seconds)
            results = [future.result() for future in done]

            for future in pending:
                future.cancel()
                task = futures[future]
                results.append(
                    ResearchResult(
                        task_id=task.id,
                        status=SubagentStatus.TIMED_OUT,
                        conclusion="研究任务超过时间上限，已停止等待结果。",
                    )
                )
        finally:
            # 不等待已经超时的运行中任务，避免其阻塞主 Agent 会话。
            executor.shutdown(wait=False, cancel_futures=True)

        result_by_id = {result.task_id: result for result in results}
        return tuple(result_by_id[task.id] for task in tasks)

    def _run_one(self, task: ResearchTask) -> ResearchResult:
        if self._is_cancelled(task.id):
            return ResearchResult(
                task_id=task.id,
                status=SubagentStatus.CANCELLED,
                conclusion="研究任务已取消，未执行。",
            )

        try:
            agent = Agent(
                provider=self._provider_factory(),
                tools=(),
                max_turns=self.max_turns,
            )
            result = agent.run(task.prompt)
        except Exception as error:
            return ResearchResult(
                task_id=task.id,
                status=SubagentStatus.FAILED,
                conclusion=f"研究任务失败：{str(error)[:self.max_result_chars]}",
            )

        if self._is_cancelled(task.id):
            return ResearchResult(
                task_id=task.id,
                status=SubagentStatus.CANCELLED,
                conclusion="研究任务已取消，结果未交给主代理。",
            )

        return ResearchResult(
            task_id=task.id,
            status=SubagentStatus.COMPLETED,
            conclusion=result.text[:self.max_result_chars],
        )

    def _is_cancelled(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._cancelled_task_ids


def create_research_task(prompt: str) -> ResearchTask:
    """为一项研究任务生成独立 ID。"""
    if not prompt.strip():
        raise ValueError("研究任务说明不能为空。")

    return ResearchTask(id=uuid4().hex[:12], prompt=prompt.strip())
