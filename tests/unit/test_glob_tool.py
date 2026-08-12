"""GlobTool 的单元测试。"""

import pytest

from agent_code.tools.glob_files import GlobTool


def test_glob_finds_relative_paths_in_workspace(tmp_path) -> None:
    """glob 应返回匹配的工作区相对路径。"""
    source_directory = tmp_path / "src" / "package"
    source_directory.mkdir(parents=True)
    (source_directory / "main.py").write_text("print('hi')", encoding="utf-8")
    (source_directory / "notes.txt").write_text("说明", encoding="utf-8")

    result = GlobTool(tmp_path).run({"pattern": "src/**/*.py"})

    assert "src/package/main.py" in result
    assert "notes.txt" not in result


def test_glob_rejects_unsafe_patterns(tmp_path) -> None:
    """绝对模式与 .. 模式必须被拒绝。"""
    tool = GlobTool(tmp_path)

    with pytest.raises(ValueError, match="相对模式"):
        tool.run({"pattern": str(tmp_path / "*.py")})

    with pytest.raises(ValueError, match="不允许"):
        tool.run({"pattern": "../*.py"})


def test_glob_limits_results_and_skips_symlinks(tmp_path) -> None:
    """glob 应限制结果数量，并跳过符号链接。"""
    for number in range(GlobTool.max_results + 1):
        (tmp_path / f"file-{number:03}.py").write_text(
            "pass",
            encoding="utf-8",
        )

    outside_file = tmp_path.parent / "outside.py"
    outside_file.write_text("pass", encoding="utf-8")
    (tmp_path / "outside-link.py").symlink_to(outside_file)

    result = GlobTool(tmp_path).run({"pattern": "*.py"})

    assert "匹配数量：200" in result
    assert "输出已截断" in result
    assert "已跳过 1 个符号链接" in result
    assert "outside-link.py" not in result