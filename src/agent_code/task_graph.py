"""带依赖、原子领取和只读子代理分派的任务图。"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from agent_code.project_memory import _contains_secret_like_content
from agent_code.subagents import (
    ReadOnlySubagentRunner,
    ResearchTask,
    SubagentStatus,
)


class TaskStatus(StrEnum):
    """任务图可持久化的有限状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class TaskItem:
    """一个带依赖、领取状态和结果摘要的任务节点。"""

    id: str
    text: str
    dependencies: tuple[str, ...]
    read_only: bool
    status: TaskStatus
    claimed_by: str | None
    result_summary: str | None
    created_at: str
    updated_at: str


class TaskGraphStore:
    """使用锁和原子替换在 `.agent-code/task-graph.json` 保存任务图。"""

    max_items = 100
    max_text_chars = 1_000
    max_result_chars = 2_000
    max_file_bytes = 256 * 1024

    def __init__(self, workspace_root: Path) -> None:
        root = workspace_root.resolve()

        if not root.is_dir():
            raise ValueError("工作区根目录必须是存在的目录。")

        self._directory = root / ".agent-code"
        self._path = self._directory / "task-graph.json"
        self._lock_path = self._directory / "task-graph.lock"

    def list_items(self) -> tuple[TaskItem, ...]:
        """读取任务图；损坏状态从不被静默覆盖。"""
        with self._locked():
            return tuple(self._read_items())

    def add(
        self,
        text: str,
        *,
        dependencies: tuple[str, ...] = (),
        read_only: bool = True,
    ) -> TaskItem:
        """新建任务；依赖必须已经存在，写任务不自动分派。"""
        normalized_text = text.strip()

        if not normalized_text:
            raise ValueError("任务内容不能为空。")

        if len(normalized_text) > self.max_text_chars:
            raise ValueError(f"任务内容不能超过 {self.max_text_chars} 个字符。")

        if _contains_secret_like_content(normalized_text):
            raise ValueError("任务疑似包含密钥或凭据，已拒绝保存。")

        if len(set(dependencies)) != len(dependencies):
            raise ValueError("任务依赖不能重复。")

        with self._locked():
            items = self._read_items()

            if len(items) >= self.max_items:
                raise ValueError(f"任务图最多保存 {self.max_items} 项。")

            known_ids = {item.id for item in items}

            if not set(dependencies).issubset(known_ids):
                raise ValueError("任务依赖中包含未知任务 ID。")

            timestamp = _timestamp()
            item = TaskItem(
                id=uuid4().hex[:12],
                text=normalized_text,
                dependencies=dependencies,
                read_only=read_only,
                status=TaskStatus.PENDING,
                claimed_by=None,
                result_summary=None,
                created_at=timestamp,
                updated_at=timestamp,
            )
            items.append(item)
            self._write_items(items)
            return item

    def claim_next(self, worker_id: str) -> TaskItem | None:
        """原子领取一个依赖已完成的只读任务，避免重复领取。"""
        if not worker_id.strip():
            raise ValueError("领取者 ID 不能为空。")

        with self._locked():
            items = self._read_items()
            completed_ids = {
                item.id for item in items if item.status is TaskStatus.COMPLETED
            }

            for index, item in enumerate(items):
                if (
                    item.status is TaskStatus.PENDING
                    and item.read_only
                    and set(item.dependencies).issubset(completed_ids)
                ):
                    claimed = _replace_item(
                        item,
                        status=TaskStatus.IN_PROGRESS,
                        claimed_by=worker_id,
                    )
                    items[index] = claimed
                    self._write_items(items)
                    return claimed

        return None

    def finish(
        self,
        task_id: str,
        *,
        worker_id: str,
        status: TaskStatus,
        result_summary: str,
    ) -> TaskItem:
        """结束已领取任务，并保存受限结果摘要。"""
        if status not in {TaskStatus.COMPLETED, TaskStatus.BLOCKED}:
            raise ValueError("任务只能结束为 completed 或 blocked。")

        if len(result_summary) > self.max_result_chars:
            result_summary = result_summary[: self.max_result_chars] + "…"

        with self._locked():
            items = self._read_items()

            for index, item in enumerate(items):
                if item.id != task_id:
                    continue

                if item.status is not TaskStatus.IN_PROGRESS:
                    raise ValueError("任务当前未被领取，不能结束。")

                if item.claimed_by != worker_id:
                    raise ValueError("任务由其他领取者持有，不能结束。")

                finished = _replace_item(
                    item,
                    status=status,
                    claimed_by=None,
                    result_summary=result_summary.strip() or None,
                )
                items[index] = finished
                self._write_items(items)
                return finished

        raise ValueError("未找到该任务 ID。")

    def recover_in_progress(self) -> tuple[TaskItem, ...]:
        """重启后将遗留领取任务恢复为 pending，避免永久卡住。"""
        with self._locked():
            items = self._read_items()
            recovered: list[TaskItem] = []

            for index, item in enumerate(items):
                if item.status is not TaskStatus.IN_PROGRESS:
                    continue

                restored = _replace_item(
                    item,
                    status=TaskStatus.PENDING,
                    claimed_by=None,
                    result_summary="检测到上次运行未完成的领取，已恢复为 pending。",
                )
                items[index] = restored
                recovered.append(restored)

            if recovered:
                self._write_items(items)

            return tuple(recovered)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._directory.mkdir(parents=True, exist_ok=True)

        with self._lock_path.open("a", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read_items(self) -> list[TaskItem]:
        if not self._path.exists():
            return []

        try:
            raw_data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("任务图文件已损坏，未读取也未覆盖。") from error

        if not isinstance(raw_data, dict) or raw_data.get("version") != 1:
            raise ValueError("任务图文件格式不受支持，未读取也未覆盖。")

        raw_items = raw_data.get("items")

        if not isinstance(raw_items, list):
            raise ValueError("任务图文件格式不受支持，未读取也未覆盖。")

        try:
            return [_parse_item(raw_item) for raw_item in raw_items]
        except ValueError as error:
            raise ValueError("任务图文件格式不受支持，未读取也未覆盖。") from error

    def _write_items(self, items: list[TaskItem]) -> None:
        encoded = (
            json.dumps(
                {"version": 1, "items": [asdict(item) for item in items]},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

        if len(encoded) > self.max_file_bytes:
            raise ValueError("任务图文件将超过大小上限，拒绝保存。")

        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".agent-code-task-graph-",
            dir=self._directory,
        )

        try:
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(encoded)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            os.replace(temporary_path, self._path)
        except OSError as error:
            raise RuntimeError("任务图写入失败，原文件未被部分覆盖。") from error
        finally:
            Path(temporary_path).unlink(missing_ok=True)


class TaskCoordinator:
    """只将无依赖的只读任务交给有限数量的研究子代理。"""

    def __init__(
        self,
        store: TaskGraphStore,
        subagents: ReadOnlySubagentRunner,
    ) -> None:
        self._store = store
        self._subagents = subagents

    def dispatch_ready(
        self,
        worker_id: str,
        *,
        timeout_seconds: float = 10.0,
    ) -> tuple[TaskItem, ...]:
        """领取并并发研究最多两个就绪只读任务，再写回结构化结论。"""
        claimed: list[TaskItem] = []

        for _ in range(self._subagents.max_concurrency):
            item = self._store.claim_next(worker_id)

            if item is None:
                break

            claimed.append(item)

        results = self._subagents.run(
            tuple(ResearchTask(id=item.id, prompt=item.text) for item in claimed),
            timeout_seconds=timeout_seconds,
        )
        finished: list[TaskItem] = []

        for result in results:
            status = (
                TaskStatus.COMPLETED
                if result.status is SubagentStatus.COMPLETED
                else TaskStatus.BLOCKED
            )
            finished.append(
                self._store.finish(
                    result.task_id,
                    worker_id=worker_id,
                    status=status,
                    result_summary=result.conclusion,
                )
            )

        return tuple(finished)


def _parse_item(raw_item: object) -> TaskItem:
    if not isinstance(raw_item, dict):
        raise ValueError("任务项无效")

    dependencies = raw_item.get("dependencies")

    if not isinstance(dependencies, list) or not all(
        isinstance(dependency, str) for dependency in dependencies
    ):
        raise ValueError("任务依赖无效")

    read_only = raw_item.get("read_only")

    if not isinstance(read_only, bool):
        raise ValueError("只读标记无效")

    claimed_by = raw_item.get("claimed_by")
    result_summary = raw_item.get("result_summary")

    if claimed_by is not None and not isinstance(claimed_by, str):
        raise ValueError("领取者无效")

    if result_summary is not None and not isinstance(result_summary, str):
        raise ValueError("结果摘要无效")

    return TaskItem(
        id=_required_string(raw_item, "id"),
        text=_required_string(raw_item, "text"),
        dependencies=tuple(dependencies),
        read_only=read_only,
        status=TaskStatus(_required_string(raw_item, "status")),
        claimed_by=claimed_by,
        result_summary=result_summary,
        created_at=_required_string(raw_item, "created_at"),
        updated_at=_required_string(raw_item, "updated_at"),
    )


def _required_string(item: dict[str, object], name: str) -> str:
    value = item.get(name)

    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} 无效")

    return value


def _replace_item(item: TaskItem, **changes: object) -> TaskItem:
    values = asdict(item)
    values.update(changes)
    values["updated_at"] = _timestamp()
    return TaskItem(**values)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
