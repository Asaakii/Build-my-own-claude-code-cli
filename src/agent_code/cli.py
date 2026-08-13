"""agent-code 的命令行入口。"""

from pathlib import Path

import typer
from rich.console import Console

from agent_code import __version__
from agent_code.agent import Agent, AgentResult
from agent_code.commands import PendingCommandStore, apply_pending_command
from agent_code.config import ConfigurationError, load_anthropic_config
from agent_code.edits import (
    EditAuditLog,
    PendingEditStore,
    apply_pending_edit,
)
from agent_code.hook_config import load_project_hooks
from agent_code.hooks import PreToolUseHook
from agent_code.models import Message
from agent_code.project_memory import ProjectMemoryStore
from agent_code.providers.anthropic import AnthropicProvider
from agent_code.providers.base import Provider, ProviderError
from agent_code.providers.demo import DemoProvider
from agent_code.sessions import SessionStore
from agent_code.tools.check_command import CheckCommandTool
from agent_code.tools.echo import EchoTool
from agent_code.tools.glob_files import GlobTool
from agent_code.tools.list_dir import ListDirectoryTool
from agent_code.tools.preview_create_file import PreviewCreateFileTool
from agent_code.tools.preview_replace import PreviewReplaceTool
from agent_code.tools.read_file import ReadFileTool
from agent_code.tools.run_shell import RunShellTool
from agent_code.tools.search_text import SearchTextTool

app = typer.Typer(
    help="一个从零学习构建的 Claude Code 风格命令行 Agent。",
    no_args_is_help=False,
    add_completion=False,
)

console = Console()


def create_agent(
    provider_name: str,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    pending_edits: PendingEditStore | None = None,
    pending_commands: PendingCommandStore | None = None,
    audit_log: EditAuditLog | None = None,
    pre_tool_use_hooks: tuple[PreToolUseHook, ...] = (),
) -> Agent:
    """根据 Provider 名称创建 Agent。"""
    provider = create_provider(
        provider_name=provider_name,
        api_key=api_key,
        model=model,
        base_url=base_url,
    )
    pending_edits = pending_edits or PendingEditStore()
    audit_log = audit_log or EditAuditLog()
    return Agent(
        provider=provider,
        tools=[
            CheckCommandTool(),
            EchoTool(),
            ReadFileTool(workspace_root=Path.cwd()),
            ListDirectoryTool(workspace_root=Path.cwd()),
            GlobTool(workspace_root=Path.cwd()),
            SearchTextTool(workspace_root=Path.cwd()),
            RunShellTool(
                workspace_root=Path.cwd(),
                pending_commands=pending_commands,
            ),
            PreviewReplaceTool(
                workspace_root=Path.cwd(),
                pending_edits=pending_edits,
            ),
            PreviewCreateFileTool(
                workspace_root=Path.cwd(),
                pending_edits=pending_edits,
            ),
        ],
        pre_tool_use_hooks=pre_tool_use_hooks,
    )


def create_provider(
    provider_name: str,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> Provider:
    """创建本地演示或真实 Anthropic-compatible Provider。"""
    if provider_name == "demo":
        return DemoProvider()

    if provider_name == "anthropic":
        config = load_anthropic_config(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
        return AnthropicProvider(
            api_key=config.api_key,
            model=config.model,
            base_url=config.base_url,
        )

    raise ConfigurationError("不支持的 Provider。可选值为 demo 或 anthropic。")


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
def status() -> None:
    """显示本地与真实 Provider 的配置状态。"""
    console.print("demo Provider：已就绪（本地运行，不联网）。")

    try:
        load_anthropic_config()
    except ConfigurationError as error:
        console.print(f"anthropic Provider：未配置（{error}）")
    else:
        console.print("anthropic Provider：已配置。")


@app.command()
def run(
    prompt: str = typer.Argument(..., help="交给 Agent 处理的一次性提示词。"),
    provider: str = typer.Option(
        "demo",
        "--provider",
        help="使用 demo 或 anthropic Provider。",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="覆盖 AGENT_CODE_MODEL 环境变量。",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        help="覆盖 ANTHROPIC_BASE_URL 环境变量。",
    ),
) -> None:
    """执行一次 Agent。"""
    loaded_hooks = load_project_hooks(Path.cwd())

    for warning in loaded_hooks.warnings:
        console.print(f"[yellow]{warning}[/yellow]")

    agent = _create_agent_or_exit(
        provider_name=provider,
        model=model,
        base_url=base_url,
        pre_tool_use_hooks=loaded_hooks.pre_tool_use_hooks,
    )
    result = _run_agent_or_exit(agent, prompt)
    console.print(result.text)


@app.command()
def repl(
    provider: str = typer.Option(
        "demo",
        "--provider",
        help="使用 demo 或 anthropic Provider。",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="覆盖 AGENT_CODE_MODEL 环境变量。",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        help="覆盖 ANTHROPIC_BASE_URL 环境变量。",
    ),
    session: str | None = typer.Option(
        None,
        "--session",
        help="恢复指定会话；不提供时创建新会话。",
    ),
) -> None:
    """进入交互式 Agent 终端。"""
    session_store = SessionStore(Path.cwd())
    memory_store = ProjectMemoryStore(Path.cwd())

    try:
        if session is None:
            session_id = session_store.create()
            history: tuple[Message, ...] = ()
            session_state = "新建"
        else:
            session_id = session
            history = session_store.load_messages(session_id)
            session_state = f"已恢复，已有 {len(history)} 条对话消息"
    except ValueError as error:
        console.print(f"[red]会话错误：{error}[/red]")
        raise typer.Exit(code=2) from error

    pending_edits = PendingEditStore()
    pending_commands = PendingCommandStore()
    audit_log = EditAuditLog()
    loaded_hooks = load_project_hooks(Path.cwd())

    for warning in loaded_hooks.warnings:
        console.print(f"[yellow]{warning}[/yellow]")

    agent = _create_agent_or_exit(
        provider_name=provider,
        model=model,
        base_url=base_url,
        pending_edits=pending_edits,
        pending_commands=pending_commands,
        audit_log=audit_log,
        pre_tool_use_hooks=loaded_hooks.pre_tool_use_hooks,
    )
    console.print(
        f"会话：{session_id}（{session_state}）。输入 /help、/session、/memory、"
        "/permissions、/exit、"
        "/quit、/audit、/approve <编辑确认 ID> 或 "
        "/approve-command <命令确认 ID>。"
    )

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

        if prompt == "/help":
            console.print(_render_repl_help())
            continue

        if prompt == "/clear":
            session_id = session_store.create()
            history = ()
            console.print(f"已清空当前对话并新建会话：{session_id}")
            continue

        if prompt == "/session":
            console.print(f"当前会话：{session_id} | 对话消息：{len(history)}")
            continue

        if prompt in {"/sessions", "/session list"}:
            console.print(_render_session_list(session_store))
            continue

        if prompt == "/permissions":
            console.print(_render_permission_summary())
            continue

        if prompt.startswith("/memory"):
            try:
                console.print(_handle_memory_command(memory_store, prompt))
            except ValueError as error:
                console.print(f"[red]项目记忆错误：{error}[/red]")
            continue

        if prompt == "/audit":
            console.print(audit_log.render())
            continue

        if prompt.startswith("/approve-command"):
            command_parts = prompt.split()

            if len(command_parts) != 2:
                console.print(
                    "[red]用法：/approve-command <命令确认 ID>[/red]"
                )
                continue

            try:
                result = apply_pending_command(
                    store=pending_commands,
                    runner=RunShellTool(workspace_root=Path.cwd()),
                    approval_id=command_parts[1],
                    audit_log=audit_log,
                )
            except (RuntimeError, ValueError) as error:
                console.print(f"[red]命令执行失败：{error}[/red]")
            else:
                console.print(result)

            continue

        if prompt.startswith("/approve"):
            command_parts = prompt.split()

            if len(command_parts) != 2:
                console.print("[red]用法：/approve <确认 ID>[/red]")
                continue

            try:
                result = apply_pending_edit(
                    pending_edits,
                    workspace_root=Path.cwd(),
                    approval_id=command_parts[1],
                    audit_log=audit_log,
                )
            except (RuntimeError, ValueError) as error:
                console.print(f"[red]写入失败：{error}[/red]")
            else:
                console.print(result)

            continue

        if not prompt:
            continue

        try:
            result = agent.run(
                prompt,
                history=history,
                project_memory=memory_store.render_context(),
            )
        except ProviderError as error:
            console.print(f"[red]模型服务错误：{error}[/red]")
            continue

        try:
            session_store.append_messages(
                session_id,
                (
                    Message(role="user", content=prompt),
                    Message(role="assistant", content=result.text),
                ),
            )
            history = session_store.load_messages(session_id)
        except ValueError as error:
            console.print(f"[yellow]会话未保存：{error}[/yellow]")

        console.print(f"agent> {result.text}")


def _handle_memory_command(store: ProjectMemoryStore, prompt: str) -> str:
    """处理项目记忆的显式添加、查看和删除命令。"""
    parts = prompt.split(maxsplit=2)

    if parts == ["/memory"]:
        items = store.list_items()

        if not items:
            return "当前项目没有已保存的长期约定。"

        return "\n".join(f"{item.id} | {item.text}" for item in items)

    if len(parts) == 3 and parts[1] == "add":
        item = store.add(parts[2])
        return f"已添加项目记忆：{item.id}"

    if len(parts) == 3 and parts[1] == "remove":
        store.remove(parts[2])
        return f"已删除项目记忆：{parts[2]}"

    raise ValueError(
        "用法：/memory；/memory add <长期约定>；/memory remove <记忆 ID>"
    )


def _render_repl_help() -> str:
    """返回当前 REPL 最小命令集的稳定帮助文本。"""
    return "\n".join(
        (
            "/help：显示帮助。",
            "/clear：新建空会话，不删除历史会话。",
            "/session：显示当前会话。",
            "/session list：列出可恢复会话（/sessions 为兼容别名）。",
            "/memory：查看；/memory add <文本>：保存；/memory remove <ID>：删除。",
            "/permissions：显示 Shell 权限边界。",
            "/audit：显示最小编辑与命令审计。",
            "/approve <ID>、/approve-command <ID>：确认已预览操作。",
            "/exit、/quit：退出 REPL。",
        )
    )


def _render_session_list(store: SessionStore) -> str:
    """将会话摘要呈现为不包含消息内容的文本。"""
    sessions = store.list_sessions()

    if not sessions:
        return "当前工作区没有可恢复会话。"

    lines: list[str] = []

    for session_info in sessions:
        corruption_note = (
            f"，损坏行：{session_info.corrupted_line_count}"
            if session_info.corrupted_line_count
            else ""
        )
        lines.append(
            f"{session_info.session_id} | "
            f"对话消息：{session_info.message_count}{corruption_note}"
        )

    return "\n".join(lines)


def _render_permission_summary() -> str:
    """说明程序级 Shell 权限边界，而不展示或执行任何命令。"""
    return "\n".join(
        (
            "Shell 权限边界：",
            "- 仅白名单只读命令可自动执行，工作目录固定为当前项目。",
            "- touch、mkdir 仅能通过一次性确认 ID 在工作区相对路径执行。",
            "- 删除、提权、网络、管道/重定向和工作区外路径一律拒绝。",
            "- 用户确认不会扩大程序预先定义的权限范围。",
        )
    )


def _create_agent_or_exit(
    provider_name: str,
    model: str | None,
    base_url: str | None,
    pending_edits: PendingEditStore | None = None,
    pending_commands: PendingCommandStore | None = None,
    audit_log: EditAuditLog | None = None,
    pre_tool_use_hooks: tuple[PreToolUseHook, ...] = (),
) -> Agent:
    """将配置错误转换为明确的 CLI 错误。"""
    try:
        return create_agent(
            provider_name=provider_name,
            model=model,
            base_url=base_url,
            pending_edits=pending_edits,
            pending_commands=pending_commands,
            audit_log=audit_log,
            pre_tool_use_hooks=pre_tool_use_hooks,
        )
    except ConfigurationError as error:
        console.print(f"[red]配置错误：{error}[/red]")
        raise typer.Exit(code=2) from error


def _run_agent_or_exit(agent: Agent, prompt: str) -> AgentResult:
    """将模型服务错误转换为明确的 CLI 错误。"""
    try:
        return agent.run(prompt)
    except ProviderError as error:
        console.print(f"[red]模型服务错误：{error}[/red]")
        raise typer.Exit(code=1) from error


def main() -> None:
    """启动命令行应用。"""
    app()


if __name__ == "__main__":
    main()
