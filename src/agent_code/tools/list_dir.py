"""受限工作区内的目录列举工具。"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any


class ListDirectoryTool:
    """列举工作区内目录的直接子项。"""

    name = "list_dir"
    description = (
        "列举当前工作区内某个目录的直接子项。"
        "path 默认为工作区根目录，且必须是相对路径。"
        "拒绝工作区外路径、符号链接绕行和非目录目标；"
        "结果最多返回 200 项，符号链接不会返回。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "相对于当前工作区的目录路径，默认是工作区根目录。",
            },
        },
        "additionalProperties": False,
    }

    max_entries = 200

    def __init__(self, workspace_root: Path | str) -> None:
        root = Path(workspace_root).resolve()

        if not root.is_dir():
            raise ValueError("工作区根目录必须是存在的目录。")

        self._root = root

    def run(self, arguments: Mapping[str, Any]) -> str:
        """返回目标目录中受限数量的直接子项。"""
        relative_path = arguments.get("path", ".")

        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError("list_dir 的 path 必须是非空字符串。")

        if "\x00" in relative_path:
            raise ValueError("path 不能包含空字节。")

        requested_path = Path(relative_path)

        if requested_path.is_absolute():
            raise ValueError("list_dir 只允许工作区内的相对路径。")

        if ".." in requested_path.parts:
            raise ValueError("list_dir 不允许 path 中包含 '..'。")

        resolved_path = (self._root / requested_path).resolve(strict=False)

        try:
            display_path = resolved_path.relative_to(self._root).as_posix()
        except ValueError as error:
            raise ValueError("拒绝列举工作区外的路径。") from error

        if not resolved_path.exists():
            raise ValueError(f"目录不存在：{display_path}。")

        if not resolved_path.is_dir():
            raise ValueError(f"目标不是目录：{display_path}。")

        try:
            children = sorted(
                resolved_path.iterdir(),
                key=lambda child: (not child.is_dir(), child.name.lower()),
            )
        except OSError as error:
            raise ValueError("无法列举目录，请检查访问权限。") from error

        entries: list[str] = []
        skipped_symlinks = 0
        truncated = False

        for child in children:
            if child.is_symlink():
                skipped_symlinks += 1
                continue

            try:
                child.resolve(strict=False).relative_to(self._root)
            except ValueError:
                skipped_symlinks += 1
                continue

            if len(entries) >= self.max_entries:
                truncated = True
                break

            suffix = "/" if child.is_dir() else ""
            kind = "目录" if child.is_dir() else "文件"
            entries.append(f"[{kind}] {child.name}{suffix}")

        result = [
            f"目录：{display_path or '.'}",
            f"显示条目：{len(entries)}",
            "---",
            *entries,
        ]

        if not entries:
            result.append("目录为空。")

        if skipped_symlinks:
            result.append(f"[已跳过 {skipped_symlinks} 个符号链接。]")

        if truncated:
            result.append(
                f"[输出已截断：目录最多显示 {self.max_entries} 项。]"
            )

        return "\n".join(result)