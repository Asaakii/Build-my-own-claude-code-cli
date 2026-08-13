"""仅在 Git 仓库中创建和检查受控 Worktree。"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_TASK_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


@dataclass(frozen=True)
class WorktreeReport:
    """一个 Worktree 的可审阅状态与验证摘要。"""

    task_id: str
    path: Path
    branch: str
    status: str
    diff_stat: str
    changed_paths: str
    test_summary: str
    merge_advice: str


class WorktreeManager:
    """在项目 `.agent-code/worktrees` 中管理可写任务隔离目录。"""

    test_timeout_seconds = 30

    def __init__(self, workspace_root: Path) -> None:
        root = workspace_root.resolve()

        if not root.is_dir():
            raise ValueError("工作区根目录必须是存在的目录。")

        self._workspace_root = root
        self._repository_root = self._resolve_repository_root()
        self._worktrees_root = root / ".agent-code" / "worktrees"

    @property
    def is_available(self) -> bool:
        """是否在 Git 仓库根目录中启用真正隔离。"""
        return self._repository_root == self._workspace_root

    def create(self, task_id: str) -> Path:
        """显式创建独立分支 Worktree，不修改主工作区文件。"""
        self._require_available()
        self._validate_task_id(task_id)
        path = self._path_for(task_id)

        if path.exists():
            raise ValueError("该任务 Worktree 已存在。")

        self._worktrees_root.mkdir(parents=True, exist_ok=True)
        branch = self._branch_for(task_id)
        self._run_git("worktree", "add", "-b", branch, str(path), "HEAD")
        return path

    def inspect(self, task_id: str) -> WorktreeReport:
        """读取差异、状态并运行固定测试命令，不自动合并或提交。"""
        self._require_available()
        self._validate_task_id(task_id)
        path = self._path_for(task_id)

        if not path.is_dir():
            raise ValueError("该任务 Worktree 不存在。")

        status = self._run_git("status", "--short", cwd=path)
        diff_stat = self._run_git("diff", "--stat", cwd=path)
        changed_paths = self._run_git("diff", "--name-only", cwd=path)
        test_summary = self._run_tests(path)
        return WorktreeReport(
            task_id=task_id,
            path=path,
            branch=self._branch_for(task_id),
            status=status or "工作区无未提交改动。",
            diff_stat=diff_stat or "暂无差异统计。",
            changed_paths=changed_paths or "暂无已跟踪文件差异。",
            test_summary=test_summary,
            merge_advice=(
                "请先审阅差异和测试结果；确认后才可执行 "
                f"/worktree merge {task_id} --confirm。"
            ),
        )

    def merge(self, task_id: str, *, confirmed: bool) -> None:
        """仅在用户显式确认后将任务分支合并到主分支。"""
        self._require_available()
        self._validate_task_id(task_id)

        if not confirmed:
            raise ValueError("合并必须附带 --confirm。")

        self._run_git("merge", "--no-ff", self._branch_for(task_id))

    def remove(
        self,
        task_id: str,
        *,
        confirmed: bool,
        discard_changes: bool = False,
    ) -> None:
        """显式删除 Worktree；未提交改动需要二次确认才会丢弃。"""
        self._require_available()
        self._validate_task_id(task_id)

        if not confirmed:
            raise ValueError("删除 Worktree 必须附带 --confirm。")

        path = self._path_for(task_id)
        arguments = ("worktree", "remove", "--force", str(path))

        if discard_changes:
            self._run_git(*arguments)
        else:
            self._run_git("worktree", "remove", str(path))

    def _resolve_repository_root(self) -> Path | None:
        try:
            output = self._run_git("rev-parse", "--show-toplevel")
        except ValueError:
            return None

        return Path(output).resolve()

    def _require_available(self) -> None:
        if self._repository_root is None:
            raise ValueError("当前目录不是 Git 仓库，无法提供 Worktree 隔离。")

        if not self.is_available:
            raise ValueError("请在 Git 仓库根目录运行 Worktree 命令，避免伪造隔离。")

    def _path_for(self, task_id: str) -> Path:
        return self._worktrees_root / task_id

    @staticmethod
    def _branch_for(task_id: str) -> str:
        return f"agent-code/{task_id}"

    @staticmethod
    def _validate_task_id(task_id: str) -> None:
        if not _TASK_ID_PATTERN.fullmatch(task_id):
            raise ValueError("任务 ID 只能包含小写字母、数字和连字符。")

    def _run_git(self, *arguments: str, cwd: Path | None = None) -> str:
        process = subprocess.run(
            ["git", *arguments],
            cwd=cwd or self._workspace_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if process.returncode != 0:
            detail = process.stderr.strip() or process.stdout.strip()
            raise ValueError(f"Git 操作失败：{detail or '未知错误'}")

        return process.stdout.strip()

    def _run_tests(self, path: Path) -> str:
        try:
            process = subprocess.run(
                [sys.executable, "-m", "pytest"],
                cwd=path,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.test_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return f"测试超时（{self.test_timeout_seconds} 秒）。"

        if process.returncode == 0:
            return "固定测试命令通过：python -m pytest。"

        return "固定测试命令失败；请查看 Worktree 内完整输出后再决定是否合并。"
