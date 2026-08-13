"""Shell 命令的最小权限判定。"""

import shlex
from dataclasses import dataclass
from enum import StrEnum


class CommandRisk(StrEnum):
    """命令的风险级别。"""

    READ_ONLY = "只读"
    ASK = "需确认"
    DENY = "拒绝"


@dataclass(frozen=True)
class CommandDecision:
    """一次命令权限判定的结果。"""

    risk: CommandRisk
    reason: str


class CommandPolicy:
    """以保守规则判定 Shell 命令；本类不执行任何命令。"""

    _dangerous_programs = frozenset(
        {
            "bash",
            "chmod",
            "chown",
            "dd",
            "doas",
            "ftp",
            "kill",
            "mkfs",
            "mount",
            "nc",
            "ncat",
            "pkill",
            "reboot",
            "rm",
            "scp",
            "sh",
            "shutdown",
            "ssh",
            "sudo",
            "telnet",
            "umount",
            "wget",
            "zsh",
        }
    )
    _network_programs = frozenset({"curl", "wget"})
    _shell_operators = ("&&", "||", ";", "|", ">", "<", "`", "$(")

    def evaluate(self, command: str) -> CommandDecision:
        """返回命令风险级别，不产生任何副作用。"""
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command 必须是非空字符串。")

        if "\x00" in command or "\n" in command or "\r" in command:
            return CommandDecision(
                CommandRisk.DENY,
                "拒绝包含空字节或换行符的命令。",
            )

        if any(operator in command for operator in self._shell_operators):
            return CommandDecision(
                CommandRisk.DENY,
                "拒绝包含管道、重定向、命令拼接或命令替换的 Shell 语法。",
            )

        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            return CommandDecision(
                CommandRisk.DENY,
                "拒绝无法安全解析的 Shell 命令。",
            )

        if not tokens:
            return CommandDecision(CommandRisk.DENY, "拒绝空命令。")

        if self._contains_outside_workspace_reference(tokens[1:]):
            return CommandDecision(
                CommandRisk.DENY,
                "拒绝包含绝对路径、家目录或工作区外相对路径的命令参数。",
            )

        program = tokens[0]

        if program in self._dangerous_programs:
            return CommandDecision(
                CommandRisk.DENY,
                f"拒绝高风险程序：{program}。",
            )

        if program in self._network_programs or any(
            "://" in token for token in tokens[1:]
        ):
            return CommandDecision(
                CommandRisk.DENY,
                "拒绝网络下载或网络访问命令。",
            )

        if self._is_allowed_read_only_command(tokens):
            return CommandDecision(
                CommandRisk.READ_ONLY,
                "该命令属于允许自动执行的最小只读命令集合。",
            )

        return CommandDecision(
            CommandRisk.ASK,
            "命令不在自动允许的只读集合中，后续执行必须经用户确认。",
        )

    def is_confirmable(self, command: str) -> bool:
        """判断命令是否属于当前可确认执行的最小普通写入集合。"""
        decision = self.evaluate(command)

        if decision.risk is not CommandRisk.ASK:
            return False

        tokens = shlex.split(command, posix=True)

        if tokens[0] not in {"mkdir", "touch"} or len(tokens) < 2:
            return False

        return all(
            path not in {"", "."}
            and not path.startswith("-")
            for path in tokens[1:]
        )

    @staticmethod
    def _contains_outside_workspace_reference(arguments: list[str]) -> bool:
        for argument in arguments:
            if (
                argument.startswith("/")
                or argument.startswith("~")
                or argument == ".."
                or argument.startswith("../")
                or "/../" in argument
            ):
                return True

        return False

    @staticmethod
    def _is_allowed_read_only_command(tokens: list[str]) -> bool:
        if tokens == ["pwd"]:
            return True

        if tokens[0] == "ls":
            return all(
                argument == "." or argument.startswith("-")
                for argument in tokens[1:]
            )

        if tokens[0] == "rg":
            return len(tokens) in {2, 3} and all(
                not argument.startswith("-") for argument in tokens[1:]
            )

        return tuple(tokens) in {
            ("git", "status"),
            ("git", "status", "--short"),
            ("git", "diff"),
            ("git", "diff", "--stat"),
            ("git", "diff", "--name-only"),
            ("git", "log"),
            ("git", "log", "--oneline"),
        }