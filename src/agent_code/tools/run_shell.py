"""受限只读 Shell 命令执行工具。"""

import os
import shlex
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_code.permissions import CommandPolicy, CommandRisk


class RunShellTool:
    """仅执行权限策略明确放行的只读命令。"""

    name = "run_shell"
    description = (
        "在当前工作区执行已被权限策略放行的只读 Shell 命令。"
        "只读命令自动执行；写入或未知命令不会执行，需用户确认；"
        "危险命令、网络、工作区外路径和 Shell 组合语法会被拒绝。"
        "命令固定在工作区运行，超时 5 秒，返回输出最多 12 KiB。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "待执行的一条 Shell 命令。",
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
        self._timeout_seconds = timeout_seconds
        self._max_output_bytes = max_output_bytes

    def run(self, arguments: Mapping[str, Any]) -> str:
        """按权限策略执行只读命令，并限制返回输出。"""
        if set(arguments) != {"command"}:
            raise ValueError("run_shell 只接受 command 参数。")

        command = arguments["command"]

        if not isinstance(command, str):
            raise ValueError("command 必须是字符串。")

        decision = self._policy.evaluate(command)

        if decision.risk is CommandRisk.DENY:
            raise ValueError(f"命令已被策略拒绝：{decision.reason}")

        if decision.risk is CommandRisk.ASK:
            return "\n".join(
                [
                    f"命令：{command}",
                    "风险级别：需确认",
                    f"判定：{decision.reason}",
                    "执行状态：未执行。当前版本尚不执行需确认命令。",
                ]
            )

        tokens = shlex.split(command, posix=True)

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
                    "风险级别：只读",
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
            "风险级别：只读",
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

    @staticmethod
    def _safe_environment() -> dict[str, str]:
        """只向子进程传递命令查找和字符编码所需的最小环境。"""
        return {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }