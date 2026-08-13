"""仅在当前 REPL 会话生效的 Plan Mode。"""

from dataclasses import dataclass

from agent_code.hooks import PreToolUseDecision, PreToolUseEvent


@dataclass
class PlanMode:
    """将计划期限制为只读探索，显式关闭后才恢复既有权限。"""

    enabled: bool = True

    _blocked_tools = frozenset(
        {"preview_create_file", "preview_replace", "run_shell"}
    )

    def before_tool_use(self, event: PreToolUseEvent) -> PreToolUseDecision:
        """计划期拒绝一切可能写入或执行命令的工具。"""
        if self.enabled and event.tool_call.name in self._blocked_tools:
            return PreToolUseDecision(
                allow=False,
                reason=(
                    "当前处于 Plan Mode；请先由用户输入 /plan off "
                    "再执行写入或命令。"
                ),
            )

        return PreToolUseDecision(allow=True)

    def render_status(self) -> str:
        """显示本会话 Plan Mode 状态与显式切换方法。"""
        if self.enabled:
            return (
                "Plan Mode：开启（只读探索）。"
                "写入预览和 Shell 命令均被拒绝；输入 /plan off 经用户确认后关闭。"
            )

        return "Plan Mode：关闭（仍受既有权限引擎与确认流程限制）。"
