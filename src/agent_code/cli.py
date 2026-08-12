"""agent-code 的命令行入口。

当前阶段只实现 CLI 基础能力：
- 显示帮助信息；
- 显示版本号；
- 为后续 REPL 和 Agent Loop 预留入口。
"""

import typer
from rich.console import Console

from agent_code import __version__

app = typer.Typer(
    help="一个从零学习构建的 Claude Code 风格命令行 Agent。",
    no_args_is_help=False,
    add_completion=False,
)

console = Console()


@app.callback(invoke_without_command=True)
def app_callback(context: typer.Context) -> None:
    """处理未提供子命令时的默认行为。"""
    if context.invoked_subcommand is None:
        console.print(context.get_help())


@app.command()
def version() -> None:
    """显示 agent-code 的当前版本。"""
    console.print(f"agent-code {__version__}")


def main() -> None:
    """启动命令行应用。"""
    app()


if __name__ == "__main__":
    main()