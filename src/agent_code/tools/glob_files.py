"""受限工作区内的路径 glob 工具。"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any


class GlobTool:
    """按 glob 模式查找工作区内的路径。"""

    name = "glob"
    description = (
        "按 glob 模式查找当前工作区内的文件和目录，例如 "
        "'src/**/*.py'。pattern 必须是相对模式，不能包含 '..'。"
        "最多返回 200 项，符号链接不会返回。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": (
                    "相对于工作区的 glob 模式，例如 'src/**/*.py'。"
                ),
            },
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }

    max_results = 200

    def __init__(self, workspace_root: Path | str) -> None:
        root = Path(workspace_root).resolve()

        if not root.is_dir():
            raise ValueError("工作区根目录必须是存在的目录。")

        self._root = root

    def run(self, arguments: Mapping[str, Any]) -> str:
        """查找并返回工作区内的受限数量路径。"""
        pattern = arguments.get("pattern")

        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError("glob 工具需要非空字符串类型的 pattern 参数。")

        if "\x00" in pattern:
            raise ValueError("pattern 不能包含空字节。")

        pattern_path = Path(pattern)

        if pattern_path.is_absolute():
            raise ValueError("glob 只允许工作区内的相对模式。")

        if ".." in pattern_path.parts:
            raise ValueError("glob 不允许 pattern 中包含 '..'。")

        try:
            candidates = self._root.glob(pattern)
        except ValueError as error:
            raise ValueError("glob 模式无效。") from error

        results: list[str] = []
        skipped_symlinks = 0
        truncated = False

        for candidate in candidates:
            if candidate.is_symlink():
                skipped_symlinks += 1
                continue

            resolved_candidate = candidate.resolve(strict=False)

            try:
                display_path = resolved_candidate.relative_to(self._root).as_posix()
            except ValueError:
                skipped_symlinks += 1
                continue

            if len(results) >= self.max_results:
                truncated = True
                break

            suffix = "/" if resolved_candidate.is_dir() else ""
            results.append(f"{display_path}{suffix}")

        results.sort()

        response = [
            f"模式：{pattern}",
            f"匹配数量：{len(results)}",
            "---",
            *results,
        ]

        if not results:
            response.append("未找到匹配路径。")

        if skipped_symlinks:
            response.append(f"[已跳过 {skipped_symlinks} 个符号链接。]")

        if truncated:
            response.append(
                f"[输出已截断：glob 最多显示 {self.max_results} 项。]"
            )

        return "\n".join(response)