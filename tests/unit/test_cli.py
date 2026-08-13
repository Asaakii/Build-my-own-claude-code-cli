"""命令行基础功能测试。"""

from typer.testing import CliRunner

from agent_code import __version__
from agent_code.cli import app
from agent_code.models import Message, ModelResponse, ToolCall
from agent_code.sessions import SessionStore

runner = CliRunner()


def test_help_displays_usage() -> None:
    """--help 应显示帮助而不进入交互会话。"""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "version" in result.output
    assert "run" in result.output
    assert "repl" in result.output


def test_no_arguments_starts_real_provider_repl(monkeypatch) -> None:
    """像 Claude Code 一样，直接运行命令应进入前台交互。"""
    called: dict[str, str] = {}

    def fake_repl(provider: str, **options) -> None:
        assert options == {"model": None, "base_url": None, "session": None}
        called["provider"] = provider

    monkeypatch.setattr("agent_code.cli.repl", fake_repl)

    result = runner.invoke(app)

    assert result.exit_code == 0
    assert called == {"provider": "anthropic"}


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


def test_run_renders_markdown_instead_of_printing_syntax(monkeypatch) -> None:
    """Markdown 回答在终端中不应把强调标记原样暴露给用户。"""

    class MarkdownProvider:
        def respond(self, messages, tools=()):
            del messages, tools
            return ModelResponse(text="**这是粗体文本**")

    monkeypatch.setattr(
        "agent_code.cli.create_provider",
        lambda **_: MarkdownProvider(),
    )

    result = runner.invoke(app, ["run", "测试"])

    assert result.exit_code == 0
    assert "这是粗体文本" in result.output
    assert "**这是粗体文本**" not in result.output


def test_repl_accepts_prompt_and_exit_command() -> None:
    """REPL 应处理输入，并在 /exit 后正常退出。"""
    result = runner.invoke(app, ["repl"], input="你好\n/exit\n")

    assert result.exit_code == 0
    assert "演示完成：你好" in result.output
    assert "已退出 REPL。" in result.output


def test_anthropic_provider_requires_configuration(
    tmp_path,
    monkeypatch,
) -> None:
    """未配置真实 Provider 时，不应联网且应说明缺失项。"""
    monkeypatch.chdir(tmp_path)
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
    tmp_path,
    monkeypatch,
) -> None:
    """未配置真实 Provider 时，status 应说明缺失项。"""
    monkeypatch.chdir(tmp_path)
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


class _SmokeProvider:
    """为真实冒烟命令提供不联网的协议级替身。"""

    def respond(self, messages, tools=()):
        if messages[-1].role == "user":
            return ModelResponse(
                tool_calls=(
                    ToolCall(
                        id="smoke-echo",
                        name="echo",
                        arguments={"text": "smoke-ok"},
                    ),
                )
            )

        return ModelResponse(text="SMOKE_OK")


def test_smoke_requires_the_real_provider_and_verifies_tool_round_trip(
    monkeypatch,
) -> None:
    """真实冒烟只接受真实 Provider，并要求精确的工具调用结果。"""
    monkeypatch.setattr("agent_code.cli.create_provider", lambda **_: _SmokeProvider())

    result = runner.invoke(app, ["smoke"])
    demo_result = runner.invoke(app, ["smoke", "--provider", "demo"])

    assert result.exit_code == 0
    assert "真实模型冒烟通过" in result.output
    assert demo_result.exit_code == 2
    assert "仅支持 --provider anthropic" in demo_result.output


def test_telegram_run_retries_transient_poll_failures(
    monkeypatch,
) -> None:
    """Telegram 短暂轮询失败时不应退出常驻进程。"""
    from agent_code.telegram import TelegramError

    class FakeChannel:
        def __init__(self, *args, **kwargs):
            del args, kwargs
            self.calls = 0

        def poll_once(self):
            self.calls += 1
            if self.calls == 1:
                raise TelegramError("暂时失败")
            raise KeyboardInterrupt

    monkeypatch.setattr("agent_code.cli.load_telegram_config", lambda: object())
    monkeypatch.setattr("agent_code.cli.TelegramHttpApi", lambda _: object())
    monkeypatch.setattr("agent_code.cli.TelegramChannel", FakeChannel)
    monkeypatch.setattr("agent_code.cli.create_agent", lambda **_: object())
    monkeypatch.setattr("agent_code.cli.sleep", lambda _: None)

    result = runner.invoke(app, ["telegram", "run"])

    assert result.exit_code == 0
    assert "5 秒后重试" in result.output
    assert "Telegram 渠道已停止。" in result.output


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


def test_repl_creates_persists_and_restores_a_session(
    tmp_path,
    monkeypatch,
) -> None:
    """新会话应保存对话，并能通过 --session 在新进程中恢复。"""
    monkeypatch.chdir(tmp_path)

    first_result = runner.invoke(app, ["repl"], input="第一句\n/exit\n")

    assert first_result.exit_code == 0
    session_id = first_result.output.split("会话：")[1].split("（")[0]

    store = SessionStore(tmp_path)
    assert store.load_messages(session_id) == (
        Message(role="user", content="第一句"),
        Message(role="assistant", content="演示完成：第一句"),
    )

    restored_result = runner.invoke(
        app,
        ["repl", "--session", session_id],
        input="/sessions\n第二句\n/exit\n",
    )

    assert restored_result.exit_code == 0
    assert "已恢复，已有 2 条对话消息" in restored_result.output
    assert f"{session_id} | 对话消息：2" in restored_result.output
    assert store.load_messages(session_id)[-2:] == (
        Message(role="user", content="第二句"),
        Message(role="assistant", content="演示完成：第二句"),
    )


def test_repl_rejects_unknown_session_id(tmp_path, monkeypatch) -> None:
    """不存在的会话不可伪造为恢复成功。"""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["repl", "--session", "missing"])

    assert result.exit_code == 2
    assert "会话错误：会话不存在，无法恢复。" in result.output


def test_repl_manages_project_memory_explicitly(tmp_path, monkeypatch) -> None:
    """项目记忆只能通过显式 Slash Command 添加、查看和删除。"""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["repl"],
        input=(
            "/memory add 代码注释使用中文。\n"
            "/memory\n"
            "/memory remove invalid\n"
            "/exit\n"
        ),
    )

    assert result.exit_code == 0
    assert "已添加项目记忆：" in result.output
    assert "代码注释使用中文。" in result.output
    assert "项目记忆错误：未找到该项目记忆 ID。" in result.output


def test_repl_supports_help_session_clear_and_permission_commands(
    tmp_path,
    monkeypatch,
) -> None:
    """基础 Slash Commands 应显式显示状态，且 clear 不删除旧会话。"""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["repl"],
        input="/help\n/session\n/clear\n/session list\n/permissions\n/exit\n",
    )

    assert result.exit_code == 0
    assert "/clear：新建空会话" in result.output
    assert "当前会话：" in result.output
    assert "已清空当前对话并新建会话：" in result.output
    assert "对话消息：0" in result.output
    assert "Shell 权限边界：" in result.output


def test_repl_status_shows_aggregate_state_without_message_contents(
    tmp_path,
    monkeypatch,
) -> None:
    """状态命令应显示可审阅的会话和 Todo 汇总，不回显对话正文。"""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["repl"],
        input="秘密提示词\n/todo add 阅读 README\n/status\n/exit\n",
    )

    assert result.exit_code == 0
    assert "Provider：demo" in result.output
    assert "Plan Mode：开启（只读探索）。" in result.output
    assert "pending=1" in result.output
    assert "秘密提示词" not in result.output.split("Provider：demo", 1)[1]


def test_repl_plan_mode_is_on_by_default_and_can_be_explicitly_disabled(
    tmp_path,
    monkeypatch,
) -> None:
    """Plan Mode 状态仅随当前 REPL 会话变化。"""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["repl"],
        input="/plan add 阅读代码\n/plan\n/plan off\n/plan\n/exit\n",
    )

    assert result.exit_code == 0
    assert "Plan Mode：开启（只读探索）。" in result.output
    assert "(pending) 阅读代码" in result.output
    assert "确认计划后，请由用户显式输入 /plan off" in result.output
    assert "Plan Mode：关闭（仍受既有权限引擎与确认流程限制）。" in result.output


def test_repl_manages_persistent_todos(tmp_path, monkeypatch) -> None:
    """Todo 命令应创建、列出并转换任务状态。"""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["repl"],
        input="/todo add 补充测试\n/todo\n/exit\n",
    )

    assert result.exit_code == 0
    assert "已添加 Todo：" in result.output
    assert "pending | 补充测试" in result.output


def test_repl_lists_and_loads_skills_on_demand(tmp_path, monkeypatch) -> None:
    """REPL 列表只显示元数据，显式命令才显示技能正文。"""
    skill = tmp_path / "skills" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: 审查\ndescription: 审查代码\napplies_to: 审查时。\n---\n正文步骤\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["repl"], input="/skills\n/skill load review\n/exit\n")

    assert result.exit_code == 0
    assert "review | 审查 | 审查代码 | skills/review/SKILL.md" in result.output
    assert "已加载技能：审查" in result.output
    assert "正文步骤" in result.output


def test_repl_task_commands_keep_write_tasks_out_of_subagent_dispatch(
    tmp_path,
    monkeypatch,
) -> None:
    """任务图命令可添加和显示任务；写任务不会作为子代理候选。"""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["repl"],
        input="/task add 研究代码\n/task add-write 修改代码\n/task\n/exit\n",
    )

    assert result.exit_code == 0
    assert "已添加只读任务：" in result.output
    assert "已添加主代理串行写任务：" in result.output
    assert "主代理写任务" in result.output


def test_repl_worktree_command_degrades_outside_git_repository(
    tmp_path,
    monkeypatch,
) -> None:
    """非 Git 工作区应给出真实降级说明。"""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["repl"], input="/worktree\n/exit\n")

    assert result.exit_code == 0
    assert "Worktree 不可用：当前目录不是 Git 仓库根目录。" in result.output
