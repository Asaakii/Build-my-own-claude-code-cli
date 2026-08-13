"""受控声明式 Hook 配置测试。"""

import json

from agent_code.hook_config import DenyToolsHook, load_project_hooks


def test_hook_config_loads_only_project_root_declarative_rules(tmp_path) -> None:
    """根目录配置可加载 deny_tools，但不执行任意 Python 代码。"""
    (tmp_path / "agent-code-hooks.json").write_text(
        json.dumps(
            {
                "version": 1,
                "pre_tool_use": [
                    {
                        "type": "deny_tools",
                        "tools": ["run_shell"],
                        "reason": "本项目禁止 Shell。",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_project_hooks(tmp_path)

    assert loaded.warnings == ()
    assert loaded.pre_tool_use_hooks == (
        DenyToolsHook(
            tool_names=frozenset({"run_shell"}),
            reason="本项目禁止 Shell。",
        ),
    )


def test_hook_config_error_becomes_warning_without_loading_hooks(tmp_path) -> None:
    """不支持的 Hook 类型或损坏 JSON 不应让 REPL 崩溃。"""
    path = tmp_path / "agent-code-hooks.json"
    path.write_text(
        '{"version": 1, "pre_tool_use": [{"type": "python"}]}',
        encoding="utf-8",
    )

    loaded = load_project_hooks(tmp_path)

    assert loaded.pre_tool_use_hooks == ()
    assert len(loaded.warnings) == 1
    assert "未加载 Hook 配置" in loaded.warnings[0]
