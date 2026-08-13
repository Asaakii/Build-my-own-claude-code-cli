"""命令行基础功能测试。"""

from typer.testing import CliRunner

from agent_code import __version__
from agent_code.cli import app

runner = CliRunner()


def test_help_displays_usage() -> None:
    """不带参数运行时，应显示帮助信息。"""
    result = runner.invoke(app)

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "version" in result.output
    assert "run" in result.output
    assert "repl" in result.output


def test_version_displays_current_version() -> None:
    """version 命令应输出当前版本号。"""
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert f"agent-code {__version__}" in result.output


def test_run_executes_demo_agent() -> None:
    """run 默认使用本地 DemoProvider。"""
    result = runner.invoke(app, ["run", "你好"])

    assert result.exit_code == 0
    assert "演示完成：你好" in result.output


def test_repl_accepts_prompt_and_exit_command() -> None:
    """REPL 应处理输入，并在 /exit 后正常退出。"""
    result = runner.invoke(app, ["repl"], input="你好\n/exit\n")

    assert result.exit_code == 0
    assert "演示完成：你好" in result.output
    assert "已退出 REPL。" in result.output


def test_anthropic_provider_requires_configuration(
    monkeypatch,
) -> None:
    """未配置真实 Provider 时，不应联网且应说明缺失项。"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("AGENT_CODE_MODEL", raising=False)

    result = runner.invoke(
        app,
        ["run", "你好", "--provider", "anthropic"],
    )

    assert result.exit_code == 2
    assert "配置错误" in result.output
    assert "ANTHROPIC_API_KEY" in result.output
    assert "AGENT_CODE_MODEL" in result.output


def test_unknown_provider_is_rejected() -> None:
    """不支持的 Provider 名称应被明确拒绝。"""
    result = runner.invoke(
        app,
        ["run", "你好", "--provider", "unknown"],
    )

    assert result.exit_code == 2
    assert "demo 或 anthropic" in result.output


def test_status_reports_missing_anthropic_configuration(
    monkeypatch,
) -> None:
    """未配置真实 Provider 时，status 应说明缺失项。"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("AGENT_CODE_MODEL", raising=False)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "demo Provider：已就绪" in result.output
    assert "anthropic Provider：未配置" in result.output
    assert "ANTHROPIC_API_KEY" in result.output


def test_status_does_not_display_secret_values(
    monkeypatch,
) -> None:
    """status 只显示配置状态，不得回显敏感配置值。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-value-must-not-appear")
    monkeypatch.setenv("AGENT_CODE_MODEL", "private-model-name")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://private.example.com")

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "anthropic Provider：已配置。" in result.output
    assert "secret-value-must-not-appear" not in result.output
    assert "private-model-name" not in result.output
    assert "https://private.example.com" not in result.output


def test_repl_rejects_approve_command_without_identifier() -> None:
    """REPL 应拒绝没有确认 ID 的写入命令。"""
    result = runner.invoke(app, ["repl"], input="/approve\n/exit\n")

    assert result.exit_code == 0
    assert "用法：/approve <确认 ID>" in result.output


def test_repl_displays_empty_edit_audit() -> None:
    """REPL 的 /audit 应显示当前会话的最小审计状态。"""
    result = runner.invoke(app, ["repl"], input="/audit\n/exit\n")

    assert result.exit_code == 0
    assert "当前会话没有编辑审计记录" in result.output


def test_repl_rejects_command_approval_without_identifier() -> None:
    """REPL 应拒绝没有命令确认 ID 的确认命令。"""
    result = runner.invoke(app, ["repl"], input="/approve-command\n/exit\n")

    assert result.exit_code == 0
    assert "用法：/approve-command <命令确认 ID>" in result.output