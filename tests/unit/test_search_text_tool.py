"""SearchTextTool 的单元测试。"""

import pytest

from agent_code.tools.search_text import SearchTextTool


def test_search_text_finds_lines_in_relative_directory(tmp_path) -> None:
    """工具应返回匹配行的相对路径、行号和文本。"""
    source_directory = tmp_path / "src"
    source_directory.mkdir()
    (source_directory / "main.py").write_text(
        "class Agent:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "agent-code",
        encoding="utf-8",
    )

    result = SearchTextTool(tmp_path).run(
        {
            "query": "agent",
            "path": "src",
        }
    )

    assert "src/main.py:1: class Agent:" in result
    assert "README.md" not in result


def test_search_text_supports_case_sensitive_option(tmp_path) -> None:
    """默认不区分大小写，开启后应严格匹配大小写。"""
    (tmp_path / "notes.txt").write_text(
        "Agent\nagent\n",
        encoding="utf-8",
    )
    tool = SearchTextTool(tmp_path)

    insensitive_result = tool.run({"query": "agent"})
    sensitive_result = tool.run(
        {
            "query": "agent",
            "case_sensitive": True,
        }
    )

    assert "匹配数量：2" in insensitive_result
    assert "匹配数量：1" in sensitive_result
    assert "notes.txt:2: agent" in sensitive_result
    assert "notes.txt:1: Agent" not in sensitive_result


def test_search_text_rejects_unsafe_or_invalid_arguments(tmp_path) -> None:
    """越界路径、空查询和错误类型都必须被拒绝。"""
    tool = SearchTextTool(tmp_path)

    cases = (
        ({"query": "", "path": "."}, "非空字符串"),
        ({"query": "agent", "path": "../outside"}, "不允许"),
        ({"query": "agent", "case_sensitive": "yes"}, "布尔值"),
    )

    for arguments, expected_message in cases:
        with pytest.raises(ValueError, match=expected_message):
            tool.run(arguments)


def test_search_text_skips_unsafe_files_and_limits_output(tmp_path) -> None:
    """符号链接、二进制和过大文件必须跳过，匹配输出必须受限。"""
    outside_file = tmp_path.parent / "outside.txt"
    outside_file.write_text("needle", encoding="utf-8")
    (tmp_path / "000-outside-link.txt").symlink_to(outside_file)

    (tmp_path / "binary.bin").write_bytes(b"\x00needle")
    (tmp_path / "large.txt").write_bytes(
        b"needle" * (SearchTextTool.max_file_bytes + 1)
    )

    for number in range(SearchTextTool.max_matches + 1):
        (tmp_path / f"match-{number:03}.txt").write_text(
            "needle",
            encoding="utf-8",
        )

    result = SearchTextTool(tmp_path).run({"query": "needle"})

    assert "匹配数量：200" in result
    assert "输出已截断" in result
    assert "已跳过 1 个符号链接" in result
    assert "已跳过 2 个非文本或过大文件" in result
    assert "000-outside-link.txt" not in result