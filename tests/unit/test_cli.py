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
    """run 命令应完成一次本地 Agent Loop。"""
    result = runner.invoke(app, ["run", "你好"])

    assert result.exit_code == 0
    assert "演示完成：你好" in result.output


def test_repl_accepts_prompt_and_exit_command() -> None:
    """REPL 应处理输入，并在 /exit 后正常退出。"""
    result = runner.invoke(app, ["repl"], input="你好\n/exit\n")

    assert result.exit_code == 0
    assert "演示完成：你好" in result.output
    assert "已退出 REPL。" in result.output