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


def test_version_displays_current_version() -> None:
    """version 命令应输出当前版本号。"""
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert f"agent-code {__version__}" in result.output