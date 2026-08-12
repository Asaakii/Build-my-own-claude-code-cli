"""受限工作区内的只读文本文件工具。"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any


class ReadFileTool:
    """安全读取当前工作区内的 UTF-8 文本文件。"""

    name = "read_file"
    description = (
        "读取当前工作区内的 UTF-8 文本文件。"
        "path 必须是相对路径；可选 start_line 和 end_line 指定行号范围。"
        "拒绝工作区外路径、符号链接绕行、目录、二进制文件和超过 100 KiB 的文件。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "相对于当前工作区的文件路径。",
            },
            "start_line": {
                "type": "integer",
                "minimum": 1,
                "description": "起始行号，默认为 1。",
            },
            "end_line": {
                "type": "integer",
                "minimum": 1,
                "description": "结束行号，默认读取到文件末尾。",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    max_file_bytes = 100 * 1024
    max_output_lines = 200
    max_output_chars = 12_000
    max_line_chars = 500

    def __init__(self, workspace_root: Path | str) -> None:
        root = Path(workspace_root).resolve()

        if not root.is_dir():
            raise ValueError("工作区根目录必须是存在的目录。")

        self._root = root

    def run(self, arguments: Mapping[str, Any]) -> str:
        """读取并以带行号的文本形式返回文件内容。"""
        relative_path = arguments.get("path")

        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError("read_file 工具需要非空字符串类型的 path 参数。")

        if "\x00" in relative_path:
            raise ValueError("path 不能包含空字节。")

        requested_path = Path(relative_path)

        if requested_path.is_absolute():
            raise ValueError("read_file 只允许工作区内的相对路径。")

        resolved_path = (self._root / requested_path).resolve(strict=False)

        try:
            display_path = resolved_path.relative_to(self._root).as_posix()
        except ValueError as error:
            raise ValueError("拒绝读取工作区外的路径。") from error

        if not resolved_path.exists():
            raise ValueError(f"文件不存在：{display_path}。")

        if not resolved_path.is_file():
            raise ValueError(f"目标不是普通文件：{display_path}。")

        try:
            file_size = resolved_path.stat().st_size
        except OSError as error:
            raise ValueError("无法读取文件元数据，请检查访问权限。") from error

        if file_size > self.max_file_bytes:
            raise ValueError(
                f"文件过大：{display_path} 超过 "
                f"{self.max_file_bytes // 1024} KiB 上限。"
            )

        try:
            raw_content = resolved_path.read_bytes()
        except OSError as error:
            raise ValueError("无法读取文件，请检查访问权限。") from error

        if b"\x00" in raw_content:
            raise ValueError(f"拒绝读取二进制文件：{display_path}。")

        try:
            text = raw_content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(
                f"拒绝读取非 UTF-8 文本文件：{display_path}。"
            ) from error

        start_line = self._read_line_number(arguments, "start_line", default=1)
        end_line = self._read_line_number(arguments, "end_line", default=None)

        if end_line is not None and end_line < start_line:
            raise ValueError("end_line 不能小于 start_line。")

        lines = text.splitlines()

        if not lines:
            return f"文件：{display_path}\n文件为空。"

        if start_line > len(lines):
            raise ValueError(
                f"start_line 超出文件范围：文件共 {len(lines)} 行。"
            )

        last_requested_line = end_line or len(lines)
        selected_lines = lines[start_line - 1 : last_requested_line]

        return self._render(
            display_path=display_path,
            lines=selected_lines,
            start_line=start_line,
        )

    @staticmethod
    def _read_line_number(
        arguments: Mapping[str, Any],
        name: str,
        default: int | None,
    ) -> int | None:
        value = arguments.get(name, default)

        if value is None:
            return None

        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} 必须是大于 0 的整数。")

        return value

    def _render(
        self,
        display_path: str,
        lines: list[str],
        start_line: int,
    ) -> str:
        rendered_lines: list[str] = []
        output_chars = 0
        truncated = False

        for line_number, line in enumerate(lines, start=start_line):
            safe_line = self._truncate_line(line)
            rendered_line = f"{line_number:>4}: {safe_line}"

            if (
                len(rendered_lines) >= self.max_output_lines
                or output_chars + len(rendered_line) + 1 > self.max_output_chars
            ):
                truncated = True
                break

            rendered_lines.append(rendered_line)
            output_chars += len(rendered_line) + 1

        last_rendered_line = start_line + len(rendered_lines) - 1
        result = [
            f"文件：{display_path}",
            f"显示行：{start_line}-{last_rendered_line}",
            "---",
            *rendered_lines,
        ]

        if truncated:
            result.append(
                "[输出已截断：请使用 start_line 和 end_line 分段读取。]"
            )

        return "\n".join(result)

    def _truncate_line(self, line: str) -> str:
        if len(line) <= self.max_line_chars:
            return line

        return f"{line[:self.max_line_chars]}…"