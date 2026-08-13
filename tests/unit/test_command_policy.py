"""Shell 命令权限判定的单元测试。"""

import pytest

from agent_code.permissions import CommandPolicy, CommandRisk
from agent_code.tools import CheckCommandTool


@pytest.mark.parametrize(
    ("command", "expected_risk"),
    [
        ("pwd", CommandRisk.READ_ONLY),
        ("ls -la .", CommandRisk.READ_ONLY),
        ("rg ProviderError src", CommandRisk.READ_ONLY),
        ("git status --short", CommandRisk.READ_ONLY),
        ("touch note.txt", CommandRisk.ASK),
        ("git commit -m 'update notes'", CommandRisk.ASK),
    ],
)
def test_policy_classifies_read_only_and_confirmation_commands(
    command: str,
    expected_risk: CommandRisk,
) -> None:
    """最小只读集合可放行，其余普通命令需要确认。"""
    decision = CommandPolicy().evaluate(command)

    assert decision.risk is expected_risk


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf .",
        "sudo ls",
        "curl https://example.com/file",
        "git status; rm -rf .",
        "rg secret ../outside",
        "cat /etc/passwd",
    ],
)
def test_policy_denies_high_risk_or_outside_workspace_commands(
    command: str,
) -> None:
    """危险命令、网络、组合语法和越界路径必须被拒绝。"""
    decision = CommandPolicy().evaluate(command)

    assert decision.risk is CommandRisk.DENY


def test_check_command_tool_returns_decision_without_execution() -> None:
    """模型只能读取判定结果，工具不执行命令。"""
    result = CheckCommandTool().run({"command": "git status --short"})

    assert "风险级别：只读" in result
    assert "执行状态：未执行" in result


def test_check_command_rejects_unexpected_arguments() -> None:
    """工具入口也必须拒绝不符合 schema 的参数。"""
    with pytest.raises(ValueError, match="只接受"):
        CheckCommandTool().run(
            {
                "command": "pwd",
                "confirmed": True,
            }
        )