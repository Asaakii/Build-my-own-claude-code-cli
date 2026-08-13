"""上下文预算与成本观测测试。"""

from agent_code.context import ContextManager
from agent_code.models import Message


def test_context_manager_truncates_long_tool_result_and_reports_only_metrics() -> None:
    """工具原始输出可被统计，但进入模型的内容有固定上限。"""
    manager = ContextManager()
    long_result = "x" * (manager.max_tool_result_chars + 20)

    limited = manager.limit_tool_result(long_result)
    report = manager.report()

    assert len(limited) < len(long_result) + 100
    assert "工具输出已截断" in limited
    assert report.tool_result_chars == len(long_result)
    assert report.truncated_tool_results == 1


def test_context_manager_summarizes_old_history_with_source_and_reason() -> None:
    """超预算历史保留最近消息，并清楚标出压缩原因。"""
    manager = ContextManager()
    history = tuple(
        Message(role="user", content=f"旧消息 {index} " + "x" * 2_000)
        for index in range(5)
    )

    prepared = manager.prepare_history(history)
    report = manager.report()

    assert "历史摘要（来源：会话较早消息；触发原因：" in prepared[0].content
    assert prepared[-1] == history[-1]
    assert report.summarized_history_messages == 1
    assert report.summary_reason is not None


def test_context_manager_uses_replaceable_token_estimator() -> None:
    """成本估算器可替换，报告仍只保存聚合数字。"""
    class FixedEstimator:
        def estimate(self, text: str) -> int:
            return 7

    manager = ContextManager(FixedEstimator())
    manager.record_request((Message(role="user", content="输入"),))
    manager.record_model_output("输出")
    manager.limit_tool_result("工具")

    report = manager.report()

    assert (report.input_tokens, report.output_tokens, report.tool_result_tokens) == (
        7,
        7,
        7,
    )
