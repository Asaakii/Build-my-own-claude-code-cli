"""最小、受限的本地 stdio MCP 客户端。"""

from __future__ import annotations

import json
import os
import selectors
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import count
from typing import Any, Protocol


class McpTransport(Protocol):
    """可替换的 JSON-RPC 传输，便于隔离协议测试。"""

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """发送请求并返回 JSON-RPC result。"""

    def notify(self, method: str, params: dict[str, Any]) -> None:
        """发送不需要响应的通知。"""

    def close(self) -> None:
        """关闭传输和底层连接。"""


@dataclass(frozen=True)
class McpToolSummary:
    """启动阶段可展示的外部工具摘要，不保存 schema 正文。"""

    server_name: str
    name: str
    description: str

    @property
    def qualified_name(self) -> str:
        return f"{self.server_name}.{self.name}"


@dataclass(frozen=True)
class McpToolDefinition:
    """按需加载的工具定义与输入 schema。"""

    summary: McpToolSummary
    input_schema: dict[str, Any]


class McpPermissionEngine:
    """外部 MCP 工具默认需要用户确认，不能自动执行。"""

    def requires_confirmation(self, qualified_name: str) -> bool:
        """所有外部命名空间工具一律归入 Ask 策略。"""
        return bool(qualified_name)


class StdioJsonRpcTransport:
    """以无 shell 子进程运行本地 MCP Server 的逐行 JSON-RPC 传输。"""

    def __init__(self, command: Sequence[str], timeout_seconds: float = 10.0) -> None:
        if not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError("MCP stdio 命令不能为空。")

        self._timeout_seconds = timeout_seconds
        self._next_id = count(1)
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        self._process = subprocess.Popen(
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=environment,
        )

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = next(self._next_id)
        self._write(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )

        while True:
            message = self._read_message()

            if message.get("id") != request_id:
                continue

            if "error" in message:
                raise ValueError(f"MCP 请求失败：{message['error']}")

            result = message.get("result")

            if not isinstance(result, dict):
                raise ValueError("MCP 响应缺少对象类型 result。")

            return result

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()

    def _write(self, message: dict[str, Any]) -> None:
        if self._process.stdin is None:
            raise ValueError("MCP stdin 不可用。")

        self._process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._process.stdin.flush()

    def _read_message(self) -> dict[str, Any]:
        if self._process.stdout is None:
            raise ValueError("MCP stdout 不可用。")

        selector = selectors.DefaultSelector()
        selector.register(self._process.stdout, selectors.EVENT_READ)

        try:
            if not selector.select(timeout=self._timeout_seconds):
                raise ValueError("MCP 请求超时。")

            line = self._process.stdout.readline()
        finally:
            selector.close()

        if not line:
            raise ValueError("MCP Server 已关闭或未返回响应。")

        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError("MCP Server 返回了无效 JSON-RPC。") from error

        if not isinstance(message, dict):
            raise ValueError("MCP Server 返回了无效 JSON-RPC 对象。")

        return message


class McpClient:
    """本地 MCP 会话：连接、发现、按需 schema、调用和断连。"""

    max_output_chars = 8_000
    max_pages = 20

    def __init__(
        self,
        server_name: str,
        transport: McpTransport,
        permission_engine: McpPermissionEngine | None = None,
    ) -> None:
        if not server_name or any(character.isspace() for character in server_name):
            raise ValueError("MCP Server 名称不能为空且不能包含空白字符。")

        self._server_name = server_name
        self._transport = transport
        self._permission_engine = permission_engine or McpPermissionEngine()
        self._connected = False

    def connect(self) -> None:
        """执行最小生命周期握手。"""
        result = self._transport.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "agent-code", "version": "0.1.0"},
            },
        )

        if not isinstance(result.get("protocolVersion"), str):
            raise ValueError("MCP initialize 响应缺少 protocolVersion。")

        self._transport.notify("notifications/initialized", {})
        self._connected = True

    def close(self) -> None:
        """断开 MCP Server，不保留连接状态或工具结果。"""
        self._transport.close()
        self._connected = False

    def list_tool_summaries(self) -> tuple[McpToolSummary, ...]:
        """发现工具时只保留名称和描述，不缓存完整 schema。"""
        return tuple(
            McpToolSummary(
                server_name=self._server_name,
                name=_tool_name(raw_tool),
                description=_tool_description(raw_tool),
            )
            for raw_tool in self._list_raw_tools()
        )

    def search_tools(self, query: str) -> tuple[McpToolDefinition, ...]:
        """按查询重新发现并只返回匹配工具的 schema。"""
        normalized_query = query.strip().lower()

        if not normalized_query:
            raise ValueError("工具搜索词不能为空。")

        definitions: list[McpToolDefinition] = []

        for raw_tool in self._list_raw_tools():
            name = _tool_name(raw_tool)
            description = _tool_description(raw_tool)

            if normalized_query not in f"{name} {description}".lower():
                continue

            definitions.append(
                McpToolDefinition(
                    summary=McpToolSummary(
                        server_name=self._server_name,
                        name=name,
                        description=description,
                    ),
                    input_schema=_input_schema(raw_tool),
                )
            )

        return tuple(definitions)

    def call(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        confirmed: bool,
    ) -> str:
        """在 schema 校验和显式确认后调用外部工具，并限制返回大小。"""
        self._require_connected()
        definition = self._load_definition(tool_name)

        if self._permission_engine.requires_confirmation(
            definition.summary.qualified_name
        ) and not confirmed:
            raise ValueError("外部 MCP 工具默认需要显式确认。")

        _validate_input_schema(definition.input_schema, arguments)
        result = self._transport.request(
            "tools/call",
            {"name": tool_name, "arguments": dict(arguments)},
        )
        return _render_tool_result(result, self.max_output_chars)

    def as_agent_tool(self, definition: McpToolDefinition) -> "McpTool":
        """暴露给 Agent 的外部工具始终维持 Ask，不直接调用 Server。"""
        return McpTool(definition)

    def _load_definition(self, tool_name: str) -> McpToolDefinition:
        for raw_tool in self._list_raw_tools():
            if _tool_name(raw_tool) == tool_name:
                return McpToolDefinition(
                    summary=McpToolSummary(
                        server_name=self._server_name,
                        name=tool_name,
                        description=_tool_description(raw_tool),
                    ),
                    input_schema=_input_schema(raw_tool),
                )

        raise ValueError("MCP Server 未提供该工具。")

    def _list_raw_tools(self) -> tuple[dict[str, Any], ...]:
        self._require_connected()
        cursor: str | None = None
        tools: list[dict[str, Any]] = []

        for _ in range(self.max_pages):
            params = {} if cursor is None else {"cursor": cursor}
            result = self._transport.request("tools/list", params)
            raw_tools = result.get("tools")

            if not isinstance(raw_tools, list) or not all(
                isinstance(raw_tool, dict) for raw_tool in raw_tools
            ):
                raise ValueError("MCP tools/list 响应无效。")

            tools.extend(raw_tools)
            next_cursor = result.get("nextCursor")

            if next_cursor is None:
                return tuple(tools)

            if not isinstance(next_cursor, str) or not next_cursor:
                raise ValueError("MCP tools/list 的 nextCursor 无效。")

            cursor = next_cursor

        raise ValueError("MCP tools/list 分页超过上限。")

    def _require_connected(self) -> None:
        if not self._connected:
            raise ValueError("MCP Client 尚未连接。")


class McpTool:
    """Agent 侧外部工具门面：显示命名空间但不绕过确认边界。"""

    def __init__(self, definition: McpToolDefinition) -> None:
        self._definition = definition
        self.name = "mcp__" + definition.summary.qualified_name.replace(".", "__")
        self.description = f"外部 MCP 工具（需确认）：{definition.summary.description}"
        self.input_schema = definition.input_schema

    def run(self, arguments: Mapping[str, Any]) -> str:
        _validate_input_schema(self.input_schema, arguments)
        return "外部 MCP 工具需要用户显式确认，当前未执行。"


def _tool_name(raw_tool: dict[str, Any]) -> str:
    name = raw_tool.get("name")

    if not isinstance(name, str) or not name:
        raise ValueError("MCP 工具缺少有效名称。")

    return name


def _tool_description(raw_tool: dict[str, Any]) -> str:
    description = raw_tool.get("description", "")

    if not isinstance(description, str):
        raise ValueError("MCP 工具描述无效。")

    return description


def _input_schema(raw_tool: dict[str, Any]) -> dict[str, Any]:
    schema = raw_tool.get("inputSchema")

    if not isinstance(schema, dict):
        raise ValueError("MCP 工具缺少对象类型 inputSchema。")

    return schema


def _validate_input_schema(
    schema: dict[str, Any], arguments: Mapping[str, Any]
) -> None:
    if schema.get("type") != "object":
        raise ValueError("当前仅支持对象类型的 MCP inputSchema。")

    properties = schema.get("properties", {})
    required = schema.get("required", [])

    if not isinstance(properties, dict) or not isinstance(required, list):
        raise ValueError("MCP inputSchema 的 properties 或 required 无效。")

    if not all(isinstance(name, str) for name in required):
        raise ValueError("MCP inputSchema 的 required 无效。")

    missing = [name for name in required if name not in arguments]

    if missing:
        raise ValueError(f"MCP 工具缺少必填参数：{', '.join(missing)}。")

    if schema.get("additionalProperties") is False:
        unexpected = set(arguments) - set(properties)

        if unexpected:
            names = ", ".join(sorted(unexpected))
            raise ValueError(f"MCP 工具不接受额外参数：{names}。")

    for name, value in arguments.items():
        property_schema = properties.get(name)

        if property_schema is None:
            continue

        if not isinstance(property_schema, dict):
            raise ValueError("MCP 工具参数 schema 无效。")

        _validate_value(name, value, property_schema)


def _validate_value(name: str, value: Any, schema: dict[str, Any]) -> None:
    expected_type = schema.get("type")
    type_matches = {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "array": isinstance(value, list),
        "object": isinstance(value, Mapping),
    }

    if expected_type in type_matches and not type_matches[expected_type]:
        raise ValueError(f"MCP 参数 {name} 必须是 {expected_type}。")

    allowed_values = schema.get("enum")

    if isinstance(allowed_values, list) and value not in allowed_values:
        raise ValueError(f"MCP 参数 {name} 不在允许枚举中。")


def _render_tool_result(result: dict[str, Any], max_chars: int) -> str:
    content = result.get("content")

    if not isinstance(content, list):
        raise ValueError("MCP tools/call 响应缺少 content 数组。")

    texts = [
        block["text"]
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    ]
    output = "\n".join(texts) or "MCP 工具未返回文本内容。"

    if result.get("isError") is True:
        output = f"MCP 工具报告错误：{output}"

    if len(output) > max_chars:
        return output[:max_chars] + f"\n[MCP 输出已截断：原始长度 {len(output)} 字符]"

    return output
