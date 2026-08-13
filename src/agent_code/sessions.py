"""脱敏的本地 JSONL 会话存储。"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agent_code.models import Message

_SESSION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"""(?ix)
    (
        ["']?
        (?:[a-z][a-z0-9_-]*(?:api[_-]?key|auth[_-]?token|secret|password)|api[_-]?key|token|secret|password)
        ["']?
        \s*[:=]\s*
        ["']?
    )
    ([^"'\s,;\]\}]+)
    """
)
_BEARER_TOKEN_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SK_TOKEN_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")


@dataclass(frozen=True)
class SessionInfo:
    """一个本地会话文件的最小摘要。"""

    session_id: str
    message_count: int
    corrupted_line_count: int


class SessionStore:
    """在工作区 `.agent-code/sessions` 下保存脱敏 JSONL 会话。"""

    max_content_chars = 8_000
    max_session_bytes = 1_000_000
    max_tool_summary_chars = 512

    def __init__(self, workspace_root: Path) -> None:
        root = workspace_root.resolve()

        if not root.is_dir():
            raise ValueError("工作区根目录必须是存在的目录。")

        self._root = root
        self._sessions_directory = root / ".agent-code" / "sessions"

    def create(self) -> str:
        """创建一个新的空会话并返回其安全 ID。"""
        self._sessions_directory.mkdir(parents=True, exist_ok=True)
        session_id = uuid4().hex
        self._path_for(session_id).touch(exist_ok=False)
        return session_id

    def ensure(self, session_id: str) -> None:
        """确保一个由受控外部渠道派生的会话存在。"""
        path = self._path_for(session_id)
        self._sessions_directory.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)

    def append_messages(
        self,
        session_id: str,
        messages: Sequence[Message],
    ) -> None:
        """原子追加一组可恢复消息，避免只保存半个对话回合。"""
        records: list[dict[str, object]] = []

        for message in messages:
            if message.role not in {"user", "assistant"}:
                raise ValueError("会话历史只允许保存 user 或 assistant 消息。")

            records.append(
                {
                    "type": "message",
                    "timestamp": self._timestamp(),
                    "role": message.role,
                    "content": self._sanitize_and_limit(
                        message.content,
                        self.max_content_chars,
                    ),
                }
            )

        self._append_records(session_id, records)

    def append_message(self, session_id: str, message: Message) -> None:
        """保存一条可恢复消息，供单条写入场景使用。"""
        self.append_messages(session_id, (message,))

    def append_tool_event(
        self,
        session_id: str,
        *,
        tool_name: str,
        status: str,
        summary: str,
    ) -> None:
        """保存工具事件摘要，调用方不得传入完整工具输出。"""
        if not tool_name or "\x00" in tool_name:
            raise ValueError("tool_name 必须是非空且不含空字节的字符串。")

        if status not in {"completed", "failed", "pending"}:
            raise ValueError("工具事件状态不受支持。")

        self._append_records(
            session_id,
            (
                {
                    "type": "tool_event",
                    "timestamp": self._timestamp(),
                    "tool_name": tool_name,
                    "status": status,
                    "summary": self._sanitize_and_limit(
                        summary,
                        self.max_tool_summary_chars,
                    ),
                },
            ),
        )

    def load_messages(self, session_id: str) -> tuple[Message, ...]:
        """恢复可注入模型的对话消息，跳过损坏行和工具事件。"""
        messages: list[Message] = []

        for record in self._read_records(session_id):
            if record.get("type") != "message":
                continue

            role = record.get("role")
            content = record.get("content")

            if role not in {"user", "assistant"} or not isinstance(content, str):
                continue

            messages.append(Message(role=role, content=content))

        return tuple(messages)

    def list_sessions(self) -> tuple[SessionInfo, ...]:
        """列出会话及其有效消息数量，损坏行不会阻塞其他会话。"""
        if not self._sessions_directory.exists():
            return ()

        sessions: list[SessionInfo] = []

        for path in sorted(self._sessions_directory.glob("*.jsonl")):
            message_count = 0
            corrupted_line_count = 0

            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    corrupted_line_count += 1
                    continue

                if (
                    isinstance(record, dict)
                    and record.get("type") == "message"
                    and record.get("role") in {"user", "assistant"}
                    and isinstance(record.get("content"), str)
                ):
                    message_count += 1

            sessions.append(
                SessionInfo(
                    session_id=path.stem,
                    message_count=message_count,
                    corrupted_line_count=corrupted_line_count,
                )
            )

        return tuple(sessions)

    def _append_records(
        self,
        session_id: str,
        records: Sequence[dict[str, object]],
    ) -> None:
        path = self._path_for(session_id)

        if not path.exists():
            raise ValueError("会话不存在，无法写入。")

        if not records:
            return

        encoded_lines = b"".join(
            (
                json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            ).encode("utf-8")
            for record in records
        )

        if path.stat().st_size + len(encoded_lines) > self.max_session_bytes:
            raise ValueError("会话文件已达到大小上限，拒绝继续保存。")

        with path.open("ab") as session_file:
            session_file.write(encoded_lines)

    def _read_records(self, session_id: str) -> tuple[dict[str, object], ...]:
        path = self._path_for(session_id)

        if not path.exists():
            raise ValueError("会话不存在，无法恢复。")

        records: list[dict[str, object]] = []

        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(record, dict):
                records.append(record)

        return tuple(records)

    def _path_for(self, session_id: str) -> Path:
        if not _SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError("会话 ID 格式无效。")

        return self._sessions_directory / f"{session_id}.jsonl"

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _sanitize_and_limit(content: str, limit: int) -> str:
        sanitized = _SECRET_ASSIGNMENT_PATTERN.sub(
            lambda match: f"{match.group(1)}[REDACTED]",
            content,
        )
        sanitized = _BEARER_TOKEN_PATTERN.sub("Bearer [REDACTED]", sanitized)
        sanitized = _SK_TOKEN_PATTERN.sub("[REDACTED]", sanitized)

        if len(sanitized) <= limit:
            return sanitized

        return sanitized[:limit] + "\n[内容已截断]"
