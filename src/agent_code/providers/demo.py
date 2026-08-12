"""用于本地端到端演示的确定性 Provider。"""

from collections.abc import Sequence

from agent_code.models import Message, ModelResponse, ToolCall


class DemoProvider:
    """用固定规则模拟一次工具调用后的模型响应。"""

    def respond(self, messages: Sequence[Message]) -> ModelResponse:
        """根据最后一条消息决定请求工具或返回最终文本。"""
        latest_message = messages[-1]

        if latest_message.role == "user":
            return ModelResponse(
                tool_calls=(
                    ToolCall(
                        id="demo-echo-1",
                        name="echo",
                        arguments={"text": latest_message.content},
                    ),
                )
            )

        if latest_message.role == "tool":
            return ModelResponse(text=f"演示完成：{latest_message.content}")

        return ModelResponse(text="演示 Provider 未收到可处理的用户输入或工具结果。")