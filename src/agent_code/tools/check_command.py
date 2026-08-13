"""供 Agent 查询 Shell 命令权限的只读工具。"""

from collections.abc import Mapping
from typing import Any

from agent_code.permissions import CommandPolicy


class CheckCommandTool:
    """评估 Shell 命令风险，但绝不执行命令。"""

    name = "check_command"
    description = (
        "评估一条 Shell 命令的权限级别，但绝不执行命令。"
        "只读命令会标记为可自动执行；写入或未知命令标记为需确认；"
        "高风险命令、网络访问、工作区外路径及 Shell 组合语法会被拒绝。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "待评估的一条 Shell 命令。",
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    def __init__(self, policy: CommandPolicy | None = None) -> None:
        self._policy = policy or CommandPolicy()

    def run(self, arguments: Mapping[str, Any]) -> str:
        """返回权限判定结果，不执行命令。"""
        if set(arguments) != {"command"}:
            raise ValueError("check_command 只接受 command 参数。")

        command = arguments["command"]

        if not isinstance(command, str):
            raise ValueError("command 必须是字符串。")

        decision = self._policy.evaluate(command)
        return "\n".join(
            [
                f"命令：{command}",
                f"风险级别：{decision.risk.value}",
                f"判定：{decision.reason}",
                "执行状态：未执行。此工具只进行权限判定。",
            ]
        )