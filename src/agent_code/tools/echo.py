"""用于验证 Agent Loop 的示例 echo 工具。"""

from collections.abc import Mapping
from typing import Any


class EchoTool:
    """原样返回传入文本。"""

    name = "echo"
    description = "原样返回 text 参数，用于测试工具调用流程。"
    input_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "需要原样返回的文本。",
            }
        },
        "required": ["text"],
        "additionalProperties": False,
    }

    def run(self, arguments: Mapping[str, Any]) -> str:
        """读取并返回 text 参数。"""
        text = arguments.get("text")

        if not isinstance(text, str):
            raise ValueError("echo 工具需要字符串类型的 text 参数。")

        return text