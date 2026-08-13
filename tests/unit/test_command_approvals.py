"""需确认 Shell 命令的单元测试。"""

import re

import pytest

from agent_code.commands import PendingCommandStore, apply_pending_command
from agent_code.edits import EditAuditLog
from agent_code.tools import RunShellTool


def _approval_id(result: str) -> str:
    matched = re.search(r"待确认命令 ID：([A-Za-z0-9_-]+)", result)

    if matched is None:
        raise AssertionError("命令预览中没有待确认命令 ID。")

    return matched.group(1)


def test_approved_touch_runs_once_and_audits_without_command_content(
    tmp_path,
) -> None:
    """只有用户确认后，允许的 touch 命令才执行一次。"""
    store = PendingCommandStore()
    audit_log = EditAuditLog()
    tool = RunShellTool(tmp_path, pending_commands=store)

    preview = tool.run({"command": "touch note.txt"})
    approval_id = _approval_id(preview)
    result = apply_pending_command(
        store=store,
        runner=RunShellTool(tmp_path),
        approval_id=approval_id,
        audit_log=audit_log,
    )

    assert "风险级别：需确认（已确认）" in result
    assert "退出码：0" in result
    assert (tmp_path / "note.txt").exists()
    assert "已完成 | command | Shell 命令" in audit_log.render()
    assert "touch note.txt" not in audit_log.render()

    with pytest.raises(ValueError, match="不存在"):
        apply_pending_command(
            store=store,
            runner=RunShellTool(tmp_path),
            approval_id=approval_id,
            audit_log=audit_log,
        )


def test_confirmation_rejects_unknown_command_even_after_approval(tmp_path) -> None:
    """确认不是执行任意未知程序的通行证。"""
    store = PendingCommandStore()
    audit_log = EditAuditLog()
    tool = RunShellTool(tmp_path, pending_commands=store)

    preview = tool.run({"command": "python -c 'print(1)'"})

    with pytest.raises(ValueError, match="仅允许确认后执行"):
        apply_pending_command(
            store=store,
            runner=RunShellTool(tmp_path),
            approval_id=_approval_id(preview),
            audit_log=audit_log,
        )

    assert "已拒绝 | command | Shell 命令" in audit_log.render()
    assert "python -c" not in audit_log.render()


def test_confirmation_rejects_symlink_write_path(tmp_path) -> None:
    """确认命令不能通过工作区内符号链接写到外部。"""
    outside_directory = tmp_path.parent / "outside-command-directory"
    outside_directory.mkdir(exist_ok=True)
    (tmp_path / "outside-link").symlink_to(
        outside_directory,
        target_is_directory=True,
    )
    store = PendingCommandStore()
    audit_log = EditAuditLog()
    tool = RunShellTool(tmp_path, pending_commands=store)

    preview = tool.run({"command": "touch outside-link/escaped.txt"})

    with pytest.raises(ValueError, match="符号链接"):
        apply_pending_command(
            store=store,
            runner=RunShellTool(tmp_path),
            approval_id=_approval_id(preview),
            audit_log=audit_log,
        )

    assert not (outside_directory / "escaped.txt").exists()