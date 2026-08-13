"""受控 Git Worktree 测试。"""

import subprocess

import pytest

from agent_code.worktrees import WorktreeManager


def _run_git(root, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _create_repository(root) -> None:
    _run_git(root, "init")
    _run_git(root, "config", "user.email", "test@example.com")
    _run_git(root, "config", "user.name", "Test User")
    (root / "README.md").write_text("main\n", encoding="utf-8")
    _run_git(root, "add", "README.md")
    _run_git(root, "commit", "-m", "initial")


def test_worktree_creation_keeps_main_workspace_unchanged_until_merge(tmp_path) -> None:
    """写入隔离 Worktree 前，主工作区内容不发生变化。"""
    _create_repository(tmp_path)
    manager = WorktreeManager(tmp_path)

    path = manager.create("write-docs")
    (path / "README.md").write_text("task branch\n", encoding="utf-8")

    assert manager.is_available is True
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "main\n"
    report = manager.inspect("write-docs")
    assert "README.md" in report.changed_paths
    assert "确认后才可执行 /worktree merge write-docs --confirm" in report.merge_advice

    with pytest.raises(ValueError, match="--confirm"):
        manager.remove("write-docs", confirmed=False)

    with pytest.raises(ValueError, match="contains modified"):
        manager.remove("write-docs", confirmed=True)

    manager.remove("write-docs", confirmed=True, discard_changes=True)
    assert not path.exists()


def test_worktree_manager_degrades_without_git(tmp_path) -> None:
    """非 Git 目录必须明确降级，不能伪造隔离目录。"""
    manager = WorktreeManager(tmp_path)

    assert manager.is_available is False

    with pytest.raises(ValueError, match="不是 Git 仓库"):
        manager.create("task")
