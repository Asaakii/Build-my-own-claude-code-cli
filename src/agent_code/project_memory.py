"""可审阅、可删除的项目长期记忆。"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"""(?ix)
    ["']?
    (?:[a-z][a-z0-9_-]*(?:api[_-]?key|auth[_-]?token|secret|password)|api[_-]?key|token|secret|password)
    ["']?
    \s*[:=]\s*
    ["']?
    [^"'\s,;\]\}]+"""
)
_BEARER_TOKEN_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SK_TOKEN_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")


@dataclass(frozen=True)
class MemoryItem:
    """一条由用户显式保存的项目长期约定。"""

    id: str
    text: str
    created_at: str


class ProjectMemoryStore:
    """在 `.agent-code/project-memory.json` 保存项目长期记忆。"""

    max_items = 50
    max_item_chars = 1_000
    max_file_bytes = 128 * 1024
    max_context_chars = 6_000

    def __init__(self, workspace_root: Path) -> None:
        root = workspace_root.resolve()

        if not root.is_dir():
            raise ValueError("工作区根目录必须是存在的目录。")

        self._path = root / ".agent-code" / "project-memory.json"

    def list_items(self) -> tuple[MemoryItem, ...]:
        """按保存顺序返回全部可审阅项目记忆。"""
        if not self._path.exists():
            return ()

        try:
            raw_data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("项目记忆文件已损坏，未读取也未覆盖。") from error

        if not isinstance(raw_data, dict) or raw_data.get("version") != 1:
            raise ValueError("项目记忆文件格式不受支持，未读取也未覆盖。")

        raw_items = raw_data.get("items")

        if not isinstance(raw_items, list):
            raise ValueError("项目记忆文件格式不受支持，未读取也未覆盖。")

        items: list[MemoryItem] = []

        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise ValueError("项目记忆文件格式不受支持，未读取也未覆盖。")

            item_id = raw_item.get("id")
            text = raw_item.get("text")
            created_at = raw_item.get("created_at")

            if not all(isinstance(value, str) for value in (item_id, text, created_at)):
                raise ValueError("项目记忆文件格式不受支持，未读取也未覆盖。")

            items.append(MemoryItem(id=item_id, text=text, created_at=created_at))

        return tuple(items)

    def add(self, text: str) -> MemoryItem:
        """保存用户明确要求记住的一条长期约定。"""
        normalized_text = text.strip()

        if not normalized_text:
            raise ValueError("项目记忆不能为空。")

        if len(normalized_text) > self.max_item_chars:
            raise ValueError(f"项目记忆不能超过 {self.max_item_chars} 个字符。")

        if _contains_secret_like_content(normalized_text):
            raise ValueError("项目记忆疑似包含密钥或凭据，已拒绝保存。")

        items = list(self.list_items())

        if len(items) >= self.max_items:
            raise ValueError(f"项目记忆最多保存 {self.max_items} 条，请先删除旧条目。")

        item = MemoryItem(
            id=uuid4().hex[:12],
            text=normalized_text,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        items.append(item)
        self._write_items(items)
        return item

    def remove(self, item_id: str) -> None:
        """删除指定长期记忆；未知 ID 不会静默成功。"""
        items = list(self.list_items())
        remaining_items = [item for item in items if item.id != item_id]

        if len(remaining_items) == len(items):
            raise ValueError("未找到该项目记忆 ID。")

        self._write_items(remaining_items)

    def render_context(self) -> str:
        """生成仅用于本轮模型请求的记忆上下文，不改变会话历史。"""
        lines = ["以下是用户显式保存的项目长期约定，请在本次任务中遵守："]
        remaining_chars = self.max_context_chars - len(lines[0]) - 1

        for item in self.list_items():
            line = f"- [{item.id}] {item.text}"

            if len(line) > remaining_chars:
                break

            lines.append(line)
            remaining_chars -= len(line) + 1

        return "\n".join(lines) if len(lines) > 1 else ""

    def _write_items(self, items: list[MemoryItem]) -> None:
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
            raise ValueError("项目记忆文件将超过大小上限，拒绝保存。")

        file_descriptor, temporary_path = tempfile.mkstemp(
            prefix=".agent-code-memory-",
            dir=self._path.parent,
        )

        try:
            with os.fdopen(file_descriptor, "wb") as temporary_file:
                temporary_file.write(encoded)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            os.replace(temporary_path, self._path)
        except OSError as error:
            raise RuntimeError("项目记忆写入失败，原文件未被部分覆盖。") from error
        finally:
            Path(temporary_path).unlink(missing_ok=True)


def _contains_secret_like_content(text: str) -> bool:
    return any(
        pattern.search(text) is not None
        for pattern in (
            _SECRET_ASSIGNMENT_PATTERN,
            _BEARER_TOKEN_PATTERN,
            _SK_TOKEN_PATTERN,
        )
    )
