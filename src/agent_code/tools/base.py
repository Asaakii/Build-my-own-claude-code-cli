"""工具的统一接口。"""

from collections.abc import Mapping
from typing import Any, Protocol


class Tool(Protocol):
    """供 Agent 调用的最小工具协议。"""

    name: str
    description: str
    input_schema: dict[str, Any]

    def run(self, arguments: Mapping[str, Any]) -> str:
        """执行工具并返回可追加到消息历史的文本结果。"""