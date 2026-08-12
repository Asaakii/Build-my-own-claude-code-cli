"""受限工作区内的固定字符串搜索工具。"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class SearchTextTool:
    """在工作区内搜索 UTF-8 文本中的固定字符串。"""

    name = "search_text"
    description = (
        "在当前工作区内搜索固定文本，不支持正则表达式。"
        "query 必须是非空字符串；path 默认为工作区根目录且必须是相对路径。"
        "默认忽略大小写，最多检查 1000 个文件、返回 200 条匹配；"
        "跳过符号链接、二进制文件、非 UTF-8 文件、超过 100 KiB 的文件和"
        ".git、.venv、缓存目录。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "需要搜索的固定文本，不是正则表达式。",
            },
            "path": {
                "type": "string",
                "description": "相对于工作区的搜索目录，默认是工作区根目录。",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "是否区分大小写，默认 false。",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    max_query_chars = 200
    max_file_bytes = 100 * 1024
    max_files_scanned = 1000
    max_matches = 200
    max_output_chars = 12_000
    max_line_chars = 500
    excluded_directory_names = {
        ".agent-code",
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
    }

    def __init__(self, workspace_root: Path | str) -> None:
        root = Path(workspace_root).resolve()

        if not root.is_dir():
            raise ValueError("工作区根目录必须是存在的目录。")

        self._root = root

    def run(self, arguments: Mapping[str, Any]) -> str:
        """搜索工作区内受限数量的文本文件。"""
        query = arguments.get("query")

        if not isinstance(query, str) or not query:
            raise ValueError("search_text 工具需要非空字符串类型的 query 参数。")

        if len(query) > self.max_query_chars:
            raise ValueError(
                f"query 不能超过 {self.max_query_chars} 个字符。"
            )

        relative_path = arguments.get("path", ".")

        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError("search_text 的 path 必须是非空字符串。")

        if "\x00" in query or "\x00" in relative_path:
            raise ValueError("query 和 path 不能包含空字节。")

        case_sensitive = arguments.get("case_sensitive", False)

        if not isinstance(case_sensitive, bool):
            raise ValueError("case_sensitive 必须是布尔值。")

        search_root = self._resolve_search_root(relative_path)
        display_root = search_root.relative_to(self._root).as_posix() or "."

        needle = query if case_sensitive else query.casefold()
        matches: list[str] = []
        output_chars = 0
        scanned_files = 0
        skipped_symlinks = 0
        skipped_non_text_files = 0
        stopped_by_match_limit = False
        stopped_by_scan_limit = False

        for directory, directory_names, file_names in os.walk(
            search_root,
            followlinks=False,
        ):
            current_directory = Path(directory)
            directory_names.sort()
            file_names.sort()

            kept_directory_names: list[str] = []

            for directory_name in directory_names:
                child_directory = current_directory / directory_name

                if directory_name in self.excluded_directory_names:
                    continue

                if child_directory.is_symlink():
                    skipped_symlinks += 1
                    continue

                try:
                    child_directory.resolve(strict=False).relative_to(self._root)
                except ValueError:
                    skipped_symlinks += 1
                    continue

                kept_directory_names.append(directory_name)

            directory_names[:] = kept_directory_names

            for file_name in file_names:
                file_path = current_directory / file_name

                if file_path.is_symlink():
                    skipped_symlinks += 1
                    continue

                try:
                    resolved_file = file_path.resolve(strict=False)
                    display_path = resolved_file.relative_to(self._root).as_posix()
                except ValueError:
                    skipped_symlinks += 1
                    continue

                if scanned_files >= self.max_files_scanned:
                    stopped_by_scan_limit = True
                    break

                scanned_files += 1
                lines = self._read_searchable_lines(resolved_file)

                if lines is None:
                    skipped_non_text_files += 1
                    continue

                for line_number, line in enumerate(lines, start=1):
                    haystack = line if case_sensitive else line.casefold()

                    if needle not in haystack:
                        continue

                    rendered_line = self._render_match(
                        display_path,
                        line_number,
                        line,
                    )

                    if (
                        len(matches) >= self.max_matches
                        or output_chars + len(rendered_line) + 1
                        > self.max_output_chars
                    ):
                        stopped_by_match_limit = True
                        break

                    matches.append(rendered_line)
                    output_chars += len(rendered_line) + 1

                if stopped_by_match_limit:
                    break

            if stopped_by_scan_limit or stopped_by_match_limit:
                break

        result = [
            f"查询：{query}",
            f"搜索目录：{display_root}",
            f"已检查文件：{scanned_files}",
            f"匹配数量：{len(matches)}",
            "---",
            *matches,
        ]

        if not matches:
            result.append("未找到匹配文本。")

        if skipped_symlinks:
            result.append(f"[已跳过 {skipped_symlinks} 个符号链接。]")

        if skipped_non_text_files:
            result.append(
                f"[已跳过 {skipped_non_text_files} 个非文本或过大文件。]"
            )

        if stopped_by_scan_limit:
            result.append(
                f"[搜索已停止：最多检查 {self.max_files_scanned} 个文件。]"
            )

        if stopped_by_match_limit:
            result.append(
                "[输出已截断：请缩小 path 或使用更具体的 query。]"
            )

        return "\n".join(result)

    def _resolve_search_root(self, relative_path: str) -> Path:
        requested_path = Path(relative_path)

        if requested_path.is_absolute():
            raise ValueError("search_text 只允许工作区内的相对路径。")

        if ".." in requested_path.parts:
            raise ValueError("search_text 不允许 path 中包含 '..'。")

        resolved_path = (self._root / requested_path).resolve(strict=False)

        try:
            resolved_path.relative_to(self._root)
        except ValueError as error:
            raise ValueError("拒绝搜索工作区外的路径。") from error

        if not resolved_path.exists():
            raise ValueError(f"搜索目录不存在：{relative_path}。")

        if not resolved_path.is_dir():
            raise ValueError(f"搜索目标不是目录：{relative_path}。")

        return resolved_path

    def _read_searchable_lines(self, file_path: Path) -> list[str] | None:
        try:
            if file_path.stat().st_size > self.max_file_bytes:
                return None

            raw_content = file_path.read_bytes()
        except OSError:
            return None

        if b"\x00" in raw_content:
            return None

        try:
            return raw_content.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            return None

    def _render_match(
        self,
        display_path: str,
        line_number: int,
        line: str,
    ) -> str:
        if len(line) > self.max_line_chars:
            line = f"{line[:self.max_line_chars]}…"

        return f"{display_path}:{line_number}: {line}"