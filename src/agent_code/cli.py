"""agent-code 的命令行入口。"""

import typer
from rich.console import Console

from agent_code import __version__
from agent_code.agent import Agent
from agent_code.providers.demo import DemoProvider
from agent_code.tools.echo import EchoTool

app = typer.Typer(
    help="一个从零学习构建的 Claude Code 风格命令行 Agent。",
    no_args_is_help=False,
    add_completion=False,
)

console = Console()


def create_demo_agent() -> Agent:
    """创建用于本地演示的 Agent。"""
    return Agent(
        provider=DemoProvider(),
        tools=[EchoTool()],
    )


@app.callback(invoke_without_command=True)
def app_callback(context: typer.Context) -> None:
    """处理未提供子命令时的默认行为。"""
    if context.invoked_subcommand is None:
        console.print(context.get_help())


@app.command()
def version() -> None:
    """显示 agent-code 的当前版本。"""
    console.print(f"agent-code {__version__}")


@app.command()
def run(
    prompt: str = typer.Argument(..., help="交给 Agent 处理的一次性提示词。"),
) -> None:
    """执行一次本地演示 Agent。"""
    result = create_demo_agent().run(prompt)
    console.print(result.text)


@app.command()
def repl() -> None:
    """进入本地演示 Agent 的交互式终端。"""
    console.print("已进入演示模式。输入 /exit 或 /quit 退出。")

    while True:
        try:
            prompt = input("你> ").strip()
        except EOFError:
            console.print("\n已退出 REPL。")
            break
        except KeyboardInterrupt:
            console.print("\n已退出 REPL。")
            break

        if prompt in {"/exit", "/quit"}:
            console.print("已退出 REPL。")
            break

        if not prompt:
            continue

        result = create_demo_agent().run(prompt)
        console.print(f"agent> {result.text}")


def main() -> None:
    """启动命令行应用。"""
    app()


if __name__ == "__main__":
    main()