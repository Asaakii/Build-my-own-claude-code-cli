"""受限工作区内的新文件创建预览工具。"""

import difflib
import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_code.edits import MAX_FILE_BYTES, PendingEditStore


class PreviewCreateFileTool:
    """预览工作区内新文件的创建，不写入文件。"""

    name = "preview_create_file"
    description = (
        "预览在当前工作区内创建一个新的 UTF-8 文本文件，不会写入文件。"
        "path 必须是相对路径、父目录必须已存在，且目标文件必须不存在。"
        "content 最多 100 KiB；预览后需由用户在 REPL 输入 /approve <ID> 才会创建。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "相对于当前工作区的新文件路径。",
            },
            "content": {
                "type": "string",
                "description": "新文件的 UTF-8 文本内容。",
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    max_preview_chars = 12_000

    def __init__(
        self,
        workspace_root: Path | str,
        pending_edits: PendingEditStore | None = None,
    ) -> None:
        root = Path(workspace_root).resolve()

        if not root.is_dir():
            raise ValueError("工作区根目录必须是存在的目录。")

        self._root = root
        self._pending_edits = pending_edits or PendingEditStore()

    def run(self, arguments: Mapping[str, Any]) -> str:
        """生成新文件的统一 diff 预览，不写入文件。"""
        path = arguments.get("path")
        content = arguments.get("content")

        if not isinstance(path, str) or not path.strip():
            raise ValueError("preview_create_file 需要非空字符串类型的 path 参数。")

        if not isinstance(content, str):
            raise ValueError("preview_create_file 需要字符串类型的 content 参数。")

        if "\x00" in path or "\x00" in content:
            raise ValueError("path 和 content 不能包含空字节。")

        content_bytes = content.encode("utf-8")

        if len(content_bytes) > MAX_FILE_BYTES:
            raise ValueError(f"content 不能超过 {MAX_FILE_BYTES // 1024} KiB。")

        requested_path = Path(path)

        if requested_path.is_absolute() or ".." in requested_path.parts:
            raise ValueError("preview_create_file 只允许工作区内不含 '..' 的相对路径。")

        if requested_path == Path("."):
            raise ValueError("新文件路径无效。")

        self._validate_new_path(requested_path)
        display_path = requested_path.as_posix()
        updated_sha256 = hashlib.sha256(content_bytes).hexdigest()
        diff = "".join(
            difflib.unified_diff(
                [],
                content.splitlines(keepends=True),
                fromfile="/dev/null",
                tofile=f"b/{display_path}",
            )
        )

        if len(diff) > self.max_preview_chars:
            raise ValueError(
                f"变更预览超过 {self.max_preview_chars} 个字符上限，请缩小新文件内容。"
            )

        approval_id = self._pending_edits.create_file(
            path=display_path,
            content=content,
        )

        return "\n".join(
            [
                f"预览路径：{display_path}",
                f"新文件内容 SHA-256：{updated_sha256}",
                "新建文件：1",
                f"待确认 ID：{approval_id}",
                "写入状态：未写入。请在 REPL 中输入 /approve <ID> 创建文件。",
                "---",
                diff.rstrip("\n"),
            ]
        )

    def _validate_new_path(self, requested_path: Path) -> None:
        current_path = self._root

        for part in requested_path.parent.parts:
            current_path /= part

            if current_path.is_symlink():
                raise ValueError("拒绝创建包含符号链接的路径。")

        parent_directory = self._root / requested_path.parent

        if not parent_directory.exists() or not parent_directory.is_dir():
            raise ValueError("新文件的父目录不存在。")

        target_path = self._root / requested_path

        if target_path.exists() or target_path.is_symlink():
            raise ValueError("目标文件已存在，拒绝覆盖。")

        try:
            target_path.resolve(strict=False).relative_to(self._root)
        except ValueError as error:
            raise ValueError("拒绝创建工作区外的文件。") from error
