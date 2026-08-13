"""持久化 Todo 测试。"""

import pytest

from agent_code.todos import TodoStatus, TodoStore


def test_todos_persist_and_support_all_required_statuses(tmp_path) -> None:
    """任务状态在重启后仍可审阅。"""
    store = TodoStore(tmp_path)
    item = store.add("补充单元测试")

    assert item.status is TodoStatus.PENDING

    for status in (
        TodoStatus.IN_PROGRESS,
        TodoStatus.BLOCKED,
        TodoStatus.COMPLETED,
    ):
        item = store.set_status(item.id, status)
        assert item.status is status

    assert TodoStore(tmp_path).list_items() == (item,)


def test_todos_reject_secret_unknown_id_and_corrupted_file(tmp_path) -> None:
    """Todo 不应成为密钥或损坏数据的静默存储通道。"""
    store = TodoStore(tmp_path)

    with pytest.raises(ValueError, match="密钥或凭据"):
        store.add("API_KEY=secret-value-must-not-appear")

    with pytest.raises(ValueError, match="未找到"):
        store.set_status("missing", TodoStatus.COMPLETED)

    path = tmp_path / ".agent-code" / "todos.json"
    path.parent.mkdir()
    path.write_text("{bad json}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="已损坏"):
        store.list_items()
