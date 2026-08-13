"""从受控项目配置加载声明式 Hook，不加载任意代码。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent_code.hooks import PreToolUseDecision, PreToolUseEvent, PreToolUseHook


@dataclass(frozen=True)
class LoadedHooks:
    """配置加载后的 Hook 与非致命警告。"""

    pre_tool_use_hooks: tuple[PreToolUseHook, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DenyToolsHook:
    """拒绝配置中明确列出的工具名称。"""

    tool_names: frozenset[str]
    reason: str

    def before_tool_use(self, event: PreToolUseEvent) -> PreToolUseDecision:
        if event.tool_call.name in self.tool_names:
            return PreToolUseDecision(allow=False, reason=self.reason)

        return PreToolUseDecision(allow=True)


def load_project_hooks(workspace_root: Path) -> LoadedHooks:
    """只读取项目根目录 `agent-code-hooks.json`，错误不抛出到会话。"""
    path = workspace_root.resolve() / "agent-code-hooks.json"

    if not path.exists():
        return LoadedHooks()

    try:
        if path.stat().st_size > 16 * 1024:
            raise ValueError("配置文件超过 16 KiB 上限")

        raw_config = json.loads(path.read_text(encoding="utf-8"))
        hooks = _parse_pre_tool_use_hooks(raw_config)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return LoadedHooks(warnings=(f"未加载 Hook 配置：{error}",))

    return LoadedHooks(pre_tool_use_hooks=hooks)


def _parse_pre_tool_use_hooks(raw_config: object) -> tuple[PreToolUseHook, ...]:
    if not isinstance(raw_config, dict) or raw_config.get("version") != 1:
        raise ValueError("仅支持 version 为 1 的对象配置")

    raw_hooks = raw_config.get("pre_tool_use", [])

    if not isinstance(raw_hooks, list):
        raise ValueError("pre_tool_use 必须是数组")

    hooks: list[PreToolUseHook] = []

    for raw_hook in raw_hooks:
        if not isinstance(raw_hook, dict) or raw_hook.get("type") != "deny_tools":
            raise ValueError("仅支持 type 为 deny_tools 的 Hook")

        tool_names = raw_hook.get("tools")
        reason = raw_hook.get("reason")

        if (
            not isinstance(tool_names, list)
            or not tool_names
            or not all(
                isinstance(tool_name, str) and tool_name
                for tool_name in tool_names
            )
            or not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 200
        ):
            raise ValueError("deny_tools Hook 的 tools 或 reason 无效")

        hooks.append(
            DenyToolsHook(tool_names=frozenset(tool_names), reason=reason.strip())
        )

    return tuple(hooks)
