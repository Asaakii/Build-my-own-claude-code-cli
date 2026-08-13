"""受限只读 Shell 执行工具的单元测试。"""

import subprocess

import pytest

from agent_code.tools import RunShellTool


def test_run_shell_executes_allowed_command_in_workspace(tmp_path) -> None:
    """允许的只读命令必须固定在工作区内执行。"""
    (tmp_path / "workspace-only.txt").write_text("内容", encoding="utf-8")
    tool = RunShellTool(tmp_path)

    pwd_result = tool.run({"command": "pwd"})
    ls_result = tool.run({"command": "ls ."})

    assert "执行状态：已执行" in pwd_result
    assert f"工作目录：{tmp_path.resolve()}" in pwd_result
    assert str(tmp_path.resolve()) in pwd_result
    assert "退出码：0" in ls_result
    assert "workspace-only.txt" in ls_result


def test_run_shell_returns_exit_code_and_truncates_output(tmp_path) -> None:
    """非零退出码与超长输出都必须被明确返回和限制。"""
    (tmp_path / "large.txt").write_text(
        "needle\n" * 100,
        encoding="utf-8",
    )
    tool = RunShellTool(tmp_path, max_output_bytes=100)

    no_match_result = tool.run({"command": "rg absent-text large.txt"})
    truncated_result = tool.run({"command": "rg needle large.txt"})

    assert "退出码：1" in no_match_result
    assert "退出码：0" in truncated_result
    assert "输出状态：已截断，仅返回前 100 字节" in truncated_result


def test_run_shell_does_not_execute_confirmation_or_denied_commands(
    tmp_path,
) -> None:
    """需确认和拒绝命令都不能产生文件系统副作用。"""
    tool = RunShellTool(tmp_path)

    confirmation_result = tool.run({"command": "touch created.txt"})

    assert "风险级别：需确认" in confirmation_result
    assert "执行状态：未执行" in confirmation_result
    assert not (tmp_path / "created.txt").exists()

    with pytest.raises(ValueError, match="策略拒绝"):
        tool.run({"command": "rm -rf ."})

    assert not (tmp_path / "created.txt").exists()


def test_run_shell_reports_timeout_without_raising(tmp_path, monkeypatch) -> None:
    """允许命令超时时必须停止并返回明确结果。"""

    def raise_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["pwd"], timeout=1)

    monkeypatch.setattr(
        "agent_code.tools.run_shell.subprocess.run",
        raise_timeout,
    )

    result = RunShellTool(tmp_path, timeout_seconds=1).run(
        {"command": "pwd"}
    )

    assert "执行状态：已超时，已在 1 秒后终止" in result


def test_run_shell_rejects_unexpected_arguments(tmp_path) -> None:
    """工具入口也必须拒绝不符合 schema 的参数。"""
    with pytest.raises(ValueError, match="只接受"):
        RunShellTool(tmp_path).run(
            {
                "command": "pwd",
                "confirmed": True,
            }
        )