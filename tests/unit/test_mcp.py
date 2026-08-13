"""最小受限 MCP Client 测试。"""

import sys

import pytest

from agent_code.mcp import McpClient, McpToolDefinition, StdioJsonRpcTransport


class FakeTransport:
    """模拟固定 MCP Server，而不启动真实子进程。"""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.notifications: list[tuple[str, dict]] = []
        self.closed = False

    def request(self, method: str, params: dict) -> dict:
        self.requests.append((method, params))

        if method == "initialize":
            return {"protocolVersion": "2025-06-18"}

        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": "read_note",
                        "description": "读取一条笔记",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"id": {"type": "string"}},
                            "required": ["id"],
                            "additionalProperties": False,
                        },
                    }
                ]
            }

        if method == "tools/call":
            return {"content": [{"type": "text", "text": "结果" * 5_000}]}

        raise AssertionError(method)

    def notify(self, method: str, params: dict) -> None:
        self.notifications.append((method, params))

    def close(self) -> None:
        self.closed = True


def test_mcp_client_discovers_searches_validates_and_confirms_calls() -> None:
    """默认先发现摘要，按需拿 schema，外部调用必须确认且限制输出。"""
    transport = FakeTransport()
    client = McpClient("notes", transport)
    client.connect()

    assert client.list_tool_summaries()[0].qualified_name == "notes.read_note"
    definition = client.search_tools("读取")[0]
    assert isinstance(definition, McpToolDefinition)

    with pytest.raises(ValueError, match="显式确认"):
        client.call("read_note", {"id": "a"}, confirmed=False)

    with pytest.raises(ValueError, match="缺少必填参数"):
        client.call("read_note", {}, confirmed=True)

    result = client.call("read_note", {"id": "a"}, confirmed=True)
    assert "MCP 输出已截断" in result
    assert client.as_agent_tool(definition).run({"id": "a"}).endswith("当前未执行。")

    client.close()
    assert transport.closed is True
    assert transport.notifications == [("notifications/initialized", {})]


def test_stdio_transport_connects_to_local_json_rpc_server() -> None:
    """真实 stdio 子进程可完成 initialize、发现、调用和断连。"""
    server_code = """
import json
import sys
for line in sys.stdin:
    message = json.loads(line)
    method = message.get('method')
    if 'id' not in message:
        continue
    if method == 'initialize':
        result = {'protocolVersion': '2025-06-18'}
    elif method == 'tools/list':
        result = {
            'tools': [
                {
                    'name': 'read_only',
                    'description': 'read',
                    'inputSchema': {'type': 'object'},
                }
            ]
        }
    elif method == 'tools/call':
        result = {'content': [{'type': 'text', 'text': 'ok'}]}
    else:
        result = {}
    response = {'jsonrpc': '2.0', 'id': message['id'], 'result': result}
    print(json.dumps(response), flush=True)
"""
    transport = StdioJsonRpcTransport([sys.executable, "-c", server_code])
    client = McpClient("local", transport)
    client.connect()

    assert client.call("read_only", {}, confirmed=True) == "ok"
    client.close()


def test_stdio_transport_times_out_when_server_does_not_reply() -> None:
    """本地服务未返回 JSON-RPC 时，客户端在受限时间内失败。"""
    transport = StdioJsonRpcTransport(
        [sys.executable, "-c", "import time; time.sleep(1)"],
        timeout_seconds=0.01,
    )

    with pytest.raises(ValueError, match="超时"):
        transport.request("initialize", {})

    transport.close()
