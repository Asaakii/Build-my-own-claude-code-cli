"""待确认 Shell 命令及其最小审计服务。"""

import hashlib
import secrets
from dataclasses import dataclass

from agent_code.edits import EditAuditLog
from agent_code.tools.run_shell import RunShellTool


@dataclass(frozen=True)
class PendingCommand:
    """一条等待用户确认的 Shell 命令。"""

    command: str
    command_sha256: str


class PendingCommandStore:
    """仅在当前 REPL 进程中保存待确认 Shell 命令。"""

    def __init__(self) -> None:
        self._pending: dict[str, PendingCommand] = {}

    def create(self, command: str) -> str:
        """保存命令并返回一次性确认 ID。"""
        approval_id = secrets.token_urlsafe(12)
        self._pending[approval_id] = PendingCommand(
            command=command,
            command_sha256=hashlib.sha256(
                command.encode("utf-8")
            ).hexdigest(),
        )
        return approval_id

    def consume(self, approval_id: str) -> PendingCommand:
        """取出并立即作废一条待确认命令。"""
        if not isinstance(approval_id, str) or not approval_id:
            raise ValueError("确认 ID 不能为空。")

        try:
            return self._pending.pop(approval_id)
        except KeyError as error:
            raise ValueError("命令确认 ID 不存在、已过期，或已经执行过。") from error


def apply_pending_command(
    store: PendingCommandStore,
    runner: RunShellTool,
    approval_id: str,
    audit_log: EditAuditLog,
) -> str:
    """执行一条已由用户在 REPL 中明确确认的受限命令。"""
    pending_command = store.consume(approval_id)

    try:
        result = runner.execute_confirmed(pending_command.command)
    except (OSError, RuntimeError, ValueError):
        audit_log.record(
            operation="command",
            status="已拒绝",
            path="Shell 命令",
            after_sha256=pending_command.command_sha256,
        )
        raise

    audit_log.record(
        operation="command",
        status="已完成",
        path="Shell 命令",
        after_sha256=pending_command.command_sha256,
    )
    return result