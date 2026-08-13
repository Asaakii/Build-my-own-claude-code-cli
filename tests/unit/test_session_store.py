"""脱敏 JSONL 会话存储测试。"""

import json

import pytest

from agent_code.models import Message
from agent_code.sessions import SessionStore


def test_store_restores_conversation_but_not_tool_output(tmp_path) -> None:
    """恢复模型历史时只保留用户和助手消息。"""
    store = SessionStore(tmp_path)
    session_id = store.create()

    store.append_message(session_id, Message(role="user", content="请检查代码"))
    store.append_tool_event(
        session_id,
        tool_name="read_file",
        status="completed",
        summary="已读取 src/main.py，共 42 行。",
    )
    store.append_message(
        session_id,
        Message(role="assistant", content="发现一个问题。"),
    )

    assert store.load_messages(session_id) == (
        Message(role="user", content="请检查代码"),
        Message(role="assistant", content="发现一个问题。"),
    )

    raw_content = (
        tmp_path / ".agent-code" / "sessions" / f"{session_id}.jsonl"
    ).read_text(encoding="utf-8")
    assert '"type":"tool_event"' in raw_content
    assert "src/main.py，共 42 行。" in raw_content


def test_store_redacts_secret_like_content_before_writing(tmp_path) -> None:
    """密钥、Bearer Token 与常见 sk- Token 均不得以原文落盘。"""
    store = SessionStore(tmp_path)
    session_id = store.create()
    secret = "secret-value-must-not-appear"
    bearer = "Bearer abcdefghijklmnop"
    api_token = "sk-abcdefghijklmnop"

    store.append_message(
        session_id,
        Message(
            role="user",
            content=(
                f"ANTHROPIC_API_KEY={secret}\n"
                f"Authorization: {bearer}\n"
                f"token: {api_token}"
            ),
        ),
    )

    stored_content = store.load_messages(session_id)[0].content
    raw_content = (
        tmp_path / ".agent-code" / "sessions" / f"{session_id}.jsonl"
    ).read_text(encoding="utf-8")

    assert secret not in stored_content
    assert "abcdefghijklmnop" not in stored_content
    assert secret not in raw_content
    assert "abcdefghijklmnop" not in raw_content
    assert "[REDACTED]" in stored_content


def test_store_skips_corrupted_jsonl_lines_and_reports_them(tmp_path) -> None:
    """单行损坏不能阻止会话恢复或会话列表展示。"""
    store = SessionStore(tmp_path)
    session_id = store.create()
    path = tmp_path / ".agent-code" / "sessions" / f"{session_id}.jsonl"

    path.write_text(
        "\n".join(
            [
                '{"type":"message","role":"user","content":"第一条"}',
                "{这不是 JSON}",
                json.dumps(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": "第二条",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert store.load_messages(session_id) == (
        Message(role="user", content="第一条"),
        Message(role="assistant", content="第二条"),
    )
    assert store.list_sessions() == (
        type(store.list_sessions()[0])(
            session_id=session_id,
            message_count=2,
            corrupted_line_count=1,
        ),
    )


def test_store_rejects_invalid_id_and_session_size_overflow(tmp_path) -> None:
    """路径穿越 ID 与超出会话上限的追加必须被拒绝。"""
    store = SessionStore(tmp_path)
    session_id = store.create()
    store.max_session_bytes = 1

    with pytest.raises(ValueError, match="大小上限"):
        store.append_message(session_id, Message(role="user", content="内容"))

    with pytest.raises(ValueError, match="ID 格式无效"):
        store.load_messages("../outside")