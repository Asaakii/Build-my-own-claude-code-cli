"""受限工作区内的精确替换预览工具。"""

import difflib
import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_code.edits import PendingEditStore


class PreviewReplaceTool:
    """预览工作区文本文件中的一次精确替换，不写入文件。"""

    name = "preview_replace"
    description = (
        "预览当前工作区内文本文件的一次精确字符串替换，不会写入文件。"
        "调用前必须先用 read_file 读取文件，并提供其内容 SHA-256。"
        "old_text 必须在文件中恰好出现一次；拒绝符号链接、工作区外路径、"
        "二进制/非 UTF-8/超过 100 KiB 文件，以及超过预览上限的变更。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "相对于当前工作区的文件路径。",
            },
            "old_text": {
                "type": "string",
                "description": "文件中必须恰好出现一次的原文本。",
            },
            "new_text": {
                "type": "string",
                "description": "替换后的新文本。",
            },
            "expected_sha256": {
                "type": "string",
                "description": "read_file 返回的当前内容 SHA-256。",
            },
        },
        "required": [
            "path",
            "old_text",
            "new_text",
            "expected_sha256",
        ],
        "additionalProperties": False,
    }

    max_file_bytes = 100 * 1024
    max_replacement_text_chars = 8_000
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
        """生成精确替换的统一 diff，不写入任何文件。"""
        path = self._read_path(arguments)
        old_text = self._read_replacement_text(arguments, "old_text")
        new_text = self._read_replacement_text(arguments, "new_text")
        expected_sha256 = self._read_sha256(arguments)

        if old_text == new_text:
            raise ValueError("old_text 与 new_text 不能相同。")

        resolved_path, display_path = self._resolve_file(path)
        raw_content = self._read_file_bytes(resolved_path, display_path)
        current_sha256 = hashlib.sha256(raw_content).hexdigest()

        if current_sha256 != expected_sha256:
            raise ValueError("文件内容已变化，或尚未使用当前文件内容调用 read_file。")

        try:
            original_text = raw_content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"拒绝预览非 UTF-8 文本文件：{display_path}。") from error

        occurrence_count = self._count_overlapping_matches(
            original_text,
            old_text,
        )

        if occurrence_count == 0:
            raise ValueError("old_text 未在文件中找到，拒绝生成预览。")

        if occurrence_count > 1:
            raise ValueError(
                "old_text 在文件中出现多次，替换目标不唯一，拒绝生成预览。"
            )

        updated_text = original_text.replace(old_text, new_text, 1)
        diff = "".join(
            difflib.unified_diff(
                original_text.splitlines(keepends=True),
                updated_text.splitlines(keepends=True),
                fromfile=f"a/{display_path}",
                tofile=f"b/{display_path}",
            )
        )

        if len(diff) > self.max_preview_chars:
            raise ValueError(
                f"变更预览超过 {self.max_preview_chars} 个字符上限，请缩小替换范围。"
            )

        updated_sha256 = hashlib.sha256(updated_text.encode("utf-8")).hexdigest()
        approval_id = self._pending_edits.create_replace(
            path=display_path,
            expected_sha256=current_sha256,
            old_text=old_text,
            new_text=new_text,
        )

        return "\n".join(
            [
                f"预览路径：{display_path}",
                f"当前内容 SHA-256：{current_sha256}",
                f"替换后内容 SHA-256：{updated_sha256}",
                "替换次数：1",
                f"待确认 ID：{approval_id}",
                "写入状态：未写入。请在 REPL 中输入 /approve <ID> 执行写入。",
                "---",
                diff.rstrip("\n"),
            ]
        )

    def _read_path(self, arguments: Mapping[str, Any]) -> str:
        path = arguments.get("path")

        if not isinstance(path, str) or not path.strip():
            raise ValueError("preview_replace 工具需要非空字符串类型的 path 参数。")

        if "\x00" in path:
            raise ValueError("path 不能包含空字节。")

        requested_path = Path(path)

        if requested_path.is_absolute():
            raise ValueError("preview_replace 只允许工作区内的相对路径。")

        if ".." in requested_path.parts:
            raise ValueError("preview_replace 不允许 path 中包含 '..'。")

        return path

    def _read_replacement_text(
        self,
        arguments: Mapping[str, Any],
        name: str,
    ) -> str:
        value = arguments.get(name)

        if not isinstance(value, str):
            raise ValueError(f"{name} 必须是字符串。")

        if not value:
            raise ValueError(f"{name} 不能是空字符串。")

        if "\x00" in value:
            raise ValueError(f"{name} 不能包含空字节。")

        if len(value) > self.max_replacement_text_chars:
            raise ValueError(
                f"{name} 不能超过 {self.max_replacement_text_chars} 个字符。"
            )

        return value

    @staticmethod
    def _read_sha256(arguments: Mapping[str, Any]) -> str:
        value = arguments.get("expected_sha256")

        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError(
                "expected_sha256 必须是 read_file 返回的 64 位小写 SHA-256。"
            )

        return value

    def _resolve_file(self, path: str) -> tuple[Path, str]:
        requested_path = Path(path)
        candidate_path = self._root / requested_path
        current_path = self._root

        for part in requested_path.parts:
            current_path /= part

            if current_path.is_symlink():
                raise ValueError("拒绝预览包含符号链接的路径。")

        resolved_path = candidate_path.resolve(strict=False)

        try:
            display_path = resolved_path.relative_to(self._root).as_posix()
        except ValueError as error:
            raise ValueError("拒绝预览工作区外的路径。") from error

        if not resolved_path.exists():
            raise ValueError(f"文件不存在：{display_path}。")

        if not resolved_path.is_file():
            raise ValueError(f"目标不是普通文件：{display_path}。")

        return resolved_path, display_path

    def _read_file_bytes(
        self,
        file_path: Path,
        display_path: str,
    ) -> bytes:
        try:
            file_size = file_path.stat().st_size
        except OSError as error:
            raise ValueError("无法读取文件元数据，请检查访问权限。") from error

        if file_size > self.max_file_bytes:
            raise ValueError(
                f"文件过大：{display_path} 超过 "
                f"{self.max_file_bytes // 1024} KiB 上限。"
            )

        try:
            raw_content = file_path.read_bytes()
        except OSError as error:
            raise ValueError("无法读取文件，请检查访问权限。") from error

        if b"\x00" in raw_content:
            raise ValueError(f"拒绝预览二进制文件：{display_path}。")

        return raw_content

    @staticmethod
    def _count_overlapping_matches(text: str, target: str) -> int:
        count = 0
        start = 0

        while True:
            found_at = text.find(target, start)

            if found_at == -1:
                return count

            count += 1
            start = found_at + 1
