"""ListDirectoryTool 的单元测试。"""

import pytest

from agent_code.tools.list_dir import ListDirectoryTool


def test_list_dir_lists_direct_children_in_workspace(tmp_path) -> None:
    """目录工具应列出目录和文件。"""
    (tmp_path / "package").mkdir()
    (tmp_path / "README.md").write_text("说明", encoding="utf-8")

    result = ListDirectoryTool(tmp_path).run({"path": "."})

    assert "[目录] package/" in result
    assert "[文件] README.md" in result


def test_list_dir_rejects_unsafe_or_invalid_paths(tmp_path) -> None:
    """越界、文件目标与工作区外符号链接都必须被拒绝。"""
    outside = tmp_path.parent / "outside-directory"
    outside.mkdir(exist_ok=True)
    (tmp_path / "outside-link").symlink_to(outside, target_is_directory=True)
    (tmp_path / "file.txt").write_text("内容", encoding="utf-8")
    tool = ListDirectoryTool(tmp_path)

    cases = (
        ("../outside-directory", "不允许"),
        ("outside-link", "工作区外"),
        ("file.txt", "不是目录"),
    )

    for path, expected_message in cases:
        with pytest.raises(ValueError, match=expected_message):
            tool.run({"path": path})


def test_list_dir_limits_results_and_skips_symlinks(tmp_path) -> None:
    """目录工具应限制输出，并且不返回符号链接。"""
    outside_file = tmp_path.parent / "outside-file.txt"
    outside_file.write_text("外部内容", encoding="utf-8")
    (tmp_path / "000-outside-link.txt").symlink_to(outside_file)

    for number in range(ListDirectoryTool.max_entries + 1):
        (tmp_path / f"file-{number:03}.txt").write_text(
            "内容",
            encoding="utf-8",
        )

    result = ListDirectoryTool(tmp_path).run({})

    assert "显示条目：200" in result
    assert "输出已截断" in result
    assert "已跳过 1 个符号链接" in result
    assert "000-outside-link.txt" not in result