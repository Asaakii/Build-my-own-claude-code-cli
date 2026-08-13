"""磁盘持久化的项目 Todo。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from agent_code.project_memory import _contains_secret_like_content


class TodoStatus(StrEnum):
    """Todo 的受限状态集合。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class TodoItem:
    """一条可审阅的项目任务。"""

    id: str
    text: str
    status: TodoStatus
    created_at: str
    updated_at: str


class TodoStore:
    """在 `.agent-code/todos.json` 以原子替换保存任务。"""

    max_items = 100
    max_text_chars = 1_000
    max_file_bytes = 128 * 1024

    def __init__(self, workspace_root: Path) -> None:
        root = workspace_root.resolve()

        if not root.is_dir():
            raise ValueError("工作区根目录必须是存在的目录。")

        self._path = root / ".agent-code" / "todos.json"

    def list_items(self) -> tuple[TodoItem, ...]:
        """按创建顺序读取 Todo，损坏文件不覆盖。"""
        if not self._path.exists():
            return ()

        try:
            raw_data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("Todo 文件已损坏，未读取也未覆盖。") from error

        if not isinstance(raw_data, dict) or raw_data.get("version") != 1:
            raise ValueError("Todo 文件格式不受支持，未读取也未覆盖。")

        raw_items = raw_data.get("items")

        if not isinstance(raw_items, list):
            raise ValueError("Todo 文件格式不受支持，未读取也未覆盖。")

        items: list[TodoItem] = []

        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise ValueError("Todo 文件格式不受支持，未读取也未覆盖。")

            try:
                items.append(
                    TodoItem(
                        id=_read_string(raw_item, "id"),
                        text=_read_string(raw_item, "text"),
                        status=TodoStatus(_read_string(raw_item, "status")),
                        created_at=_read_string(raw_item, "created_at"),
                        updated_at=_read_string(raw_item, "updated_at"),
                    )
                )
            except ValueError as error:
                raise ValueError("Todo 文件格式不受支持，未读取也未覆盖。") from error

        return tuple(items)

    def add(self, text: str) -> TodoItem:
        """显式新建一条 pending 任务。"""
        normalized_text = text.strip()

        if not normalized_text:
            raise ValueError("Todo 内容不能为空。")

        if len(normalized_text) > self.max_text_chars:
            raise ValueError(f"Todo 内容不能超过 {self.max_text_chars} 个字符。")

        if _contains_secret_like_content(normalized_text):
            raise ValueError("Todo 疑似包含密钥或凭据，已拒绝保存。")

        items = list(self.list_items())

        if len(items) >= self.max_items:
            raise ValueError(f"Todo 最多保存 {self.max_items} 条，请先清理旧任务。")

        timestamp = _timestamp()
        item = TodoItem(
            id=uuid4().hex[:12],
            text=normalized_text,
            status=TodoStatus.PENDING,
            created_at=timestamp,
            updated_at=timestamp,
        )
        items.append(item)
        self._write_items(items)
        return item

    def set_status(self, item_id: str, status: TodoStatus) -> TodoItem:
        """更新一条任务状态；未知 ID 或非法状态均拒绝。"""
        items = list(self.list_items())

        for index, item in enumerate(items):
            if item.id == item_id:
                updated_item = TodoItem(
                    id=item.id,
                    text=item.text,
                    status=status,
                    created_at=item.created_at,
                    updated_at=_timestamp(),
                )
                items[index] = updated_item
                self._write_items(items)
                return updated_item

        raise ValueError("未找到该 Todo ID。")

    def _write_items(self, items: list[TodoItem]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (
            json.dumps(
                {"version": 1, "items": [asdict(item) for item in items]},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

        if len(encoded) > self.max_file_bytes:
            raise ValueError("Todo 文件将超过大小上限，拒绝保存。")

        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".agent-code-todos-",
            dir=self._path.parent,
        )

        try:
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(encoded)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            os.replace(temporary_path, self._path)
        except OSError as error:
            raise RuntimeError("Todo 写入失败，原文件未被部分覆盖。") from error
        finally:
            Path(temporary_path).unlink(missing_ok=True)


def _read_string(raw_item: dict[str, object], name: str) -> str:
    value = raw_item.get(name)

    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} 无效")

    return value


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
