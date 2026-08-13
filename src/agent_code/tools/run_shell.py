"""受限 Shell 命令执行工具。"""

import os
import shlex
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from agent_code.permissions import CommandPolicy, CommandRisk


class CommandApprovalStore(Protocol):
    """待确认命令仓库的最小接口。"""

    def create(self, command: str) -> str:
        """保存命令并返回一次性确认 ID。"""


class RunShellTool:
    """自动执行只读命令，并受限执行已确认的普通写入命令。"""

    name = "run_shell"
    description = (
        "在当前工作区执行受限 Shell 命令。白名单只读命令自动执行；"
        "普通写入或未知命令只生成一次性确认 ID，不会立即执行。"
        "当前确认后仅允许 touch 和 mkdir 的工作区相对路径写入。"
        "危险命令、网络、工作区外路径和 Shell 组合语法会被拒绝。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "待执行或待确认的一条 Shell 命令。",
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    default_timeout_seconds = 5
    default_max_output_bytes = 12 * 1024

    def __init__(
        self,
        workspace_root: Path | str,
        policy: CommandPolicy | None = None,
        pending_commands: CommandApprovalStore | None = None,
        timeout_seconds: int = default_timeout_seconds,
        max_output_bytes: int = default_max_output_bytes,
    ) -> None:
        root = Path(workspace_root).resolve()

        if not root.is_dir():
            raise ValueError("工作区根目录必须是存在的目录。")

        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0。")

        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes 必须大于 0。")

        self._root = root
        self._policy = policy or CommandPolicy()
        self._pending_commands = pending_commands
        self._timeout_seconds = timeout_seconds
        self._max_output_bytes = max_output_bytes

    def run(self, arguments: Mapping[str, Any]) -> str:
        """按权限策略执行只读命令，或生成待确认命令。"""
        if set(arguments) != {"command"}:
            raise ValueError("run_shell 只接受 command 参数。")

        command = arguments["command"]

        if not isinstance(command, str):
            raise ValueError("command 必须是字符串。")

        decision = self._policy.evaluate(command)

        if decision.risk is CommandRisk.DENY:
            raise ValueError(f"命令已被策略拒绝：{decision.reason}")

        if decision.risk is CommandRisk.ASK:
            return self._render_pending_command(command, decision.reason)

        return self._execute(
            command=command,
            tokens=shlex.split(command, posix=True),
            risk_label="只读",
        )

    def execute_confirmed(self, command: str) -> str:
        """执行已由 REPL 用户确认的受限普通写入命令。"""
        decision = self._policy.evaluate(command)

        if decision.risk is not CommandRisk.ASK:
            raise ValueError("该命令不需要或不允许通过确认路径执行。")

        if not self._policy.is_confirmable(command):
            raise ValueError(
                "当前仅允许确认后执行 touch 或 mkdir 的工作区相对路径命令。"
            )

        tokens = shlex.split(command, posix=True)
        self._validate_confirmed_paths(tokens)
        return self._execute(
            command=command,
            tokens=tokens,
            risk_label="需确认（已确认）",
        )

    def _render_pending_command(self, command: str, reason: str) -> str:
        lines = [
            f"命令：{command}",
            "风险级别：需确认",
            f"判定：{reason}",
        ]

        if self._pending_commands is None:
            lines.append("执行状态：未执行。当前会话没有命令确认仓库。")
            return "\n".join(lines)

        approval_id = self._pending_commands.create(command)
        lines.extend(
            [
                f"待确认命令 ID：{approval_id}",
                "执行状态：未执行。请在 REPL 输入 "
                "/approve-command <ID> 执行。",
            ]
        )
        return "\n".join(lines)

    def _execute(
        self,
        command: str,
        tokens: list[str],
        risk_label: str,
    ) -> str:
        try:
            completed = subprocess.run(
                tokens,
                cwd=self._root,
                env=self._safe_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self._timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "\n".join(
                [
                    f"命令：{command}",
                    f"风险级别：{risk_label}",
                    f"工作目录：{self._root}",
                    f"执行状态：已超时，已在 {self._timeout_seconds} 秒后终止。",
                ]
            )
        except OSError as error:
            raise RuntimeError(f"无法启动受限命令：{error}") from error

        output = completed.stdout or b""
        truncated = len(output) > self._max_output_bytes
        limited_output = output[: self._max_output_bytes].decode(
            "utf-8",
            errors="replace",
        )

        lines = [
            f"命令：{command}",
            f"风险级别：{risk_label}",
            f"工作目录：{self._root}",
            "执行状态：已执行。",
            f"退出码：{completed.returncode}",
        ]

        if truncated:
            lines.append(
                f"输出状态：已截断，仅返回前 {self._max_output_bytes} 字节。"
            )

        lines.extend(
            [
                "--- 输出 ---",
                limited_output.rstrip("\n") or "（无输出）",
            ]
        )
        return "\n".join(lines)

    def _validate_confirmed_paths(self, tokens: list[str]) -> None:
        """拒绝确认命令通过符号链接或越界路径写出工作区。"""
        for raw_path in tokens[1:]:
            requested_path = Path(raw_path)
            candidate_path = self._root / requested_path
            current_path = self._root

            for part in requested_path.parts:
                current_path /= part

                if current_path.is_symlink():
                    raise ValueError("拒绝确认命令使用包含符号链接的路径。")

            try:
                candidate_path.resolve(strict=False).relative_to(self._root)
            except ValueError as error:
                raise ValueError("拒绝确认命令写入工作区外路径。") from error

    @staticmethod
    def _safe_environment() -> dict[str, str]:
        """只向子进程传递命令查找和字符编码所需的最小环境。"""
        return {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }