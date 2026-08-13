"""任务图和受限协调测试。"""

from concurrent.futures import ThreadPoolExecutor

from agent_code.models import ModelResponse
from agent_code.providers.mock import MockProvider
from agent_code.subagents import ReadOnlySubagentRunner
from agent_code.task_graph import (
    TaskCoordinator,
    TaskGraphStore,
    TaskStatus,
)


def test_task_dependencies_atomic_claim_and_recovery(tmp_path) -> None:
    """依赖不会提前领取；并发领取只能有一个胜者；崩溃状态可恢复。"""
    store = TaskGraphStore(tmp_path)
    prerequisite = store.add("先完成")
    dependent = store.add("后完成", dependencies=(prerequisite.id,))

    claimed_prerequisite = store.claim_next("worker")
    assert claimed_prerequisite is not None
    assert claimed_prerequisite.id == prerequisite.id
    assert store.claim_next("worker") is None
    store.finish(
        prerequisite.id,
        worker_id="worker",
        status=TaskStatus.COMPLETED,
        result_summary="完成",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda worker: store.claim_next(worker), ("a", "b")))

    assert sum(claim is not None for claim in claims) == 1
    recovered = TaskGraphStore(tmp_path).recover_in_progress()
    assert recovered[0].id == dependent.id
    assert recovered[0].status is TaskStatus.PENDING


def test_coordinator_dispatches_only_ready_read_only_tasks(tmp_path) -> None:
    """两个无依赖只读任务可并行分派，写任务保持 pending。"""
    store = TaskGraphStore(tmp_path)
    first = store.add("研究第一项")
    second = store.add("研究第二项")
    write_task = store.add("修改文件", read_only=False)
    responses = iter([ModelResponse(text="结论一"), ModelResponse(text="结论二")])
    runner = ReadOnlySubagentRunner(lambda: MockProvider(responses=[next(responses)]))
    coordinator = TaskCoordinator(store, runner)

    finished = coordinator.dispatch_ready("main")

    assert {item.id for item in finished} == {first.id, second.id}
    assert all(item.status is TaskStatus.COMPLETED for item in finished)
    persisted_write_task = next(
        item for item in store.list_items() if item.id == write_task.id
    )
    assert persisted_write_task.status is TaskStatus.PENDING
