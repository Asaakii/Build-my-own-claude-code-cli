"""项目长期记忆测试。"""

import pytest

from agent_code.project_memory import ProjectMemoryStore


def test_memory_can_be_added_reviewed_deleted_and_reopened(tmp_path) -> None:
    """用户显式添加的约定应可审阅、删除并在重启后恢复。"""
    store = ProjectMemoryStore(tmp_path)
    first_item = store.add("代码注释使用中文。")
    second_item = store.add("始终先运行测试。")

    assert store.list_items() == (first_item, second_item)
    assert "代码注释使用中文。" in store.render_context()
    assert "始终先运行测试。" in ProjectMemoryStore(tmp_path).render_context()

    store.remove(first_item.id)

    assert store.list_items() == (second_item,)


def test_memory_rejects_secret_like_content_and_invalid_deletion(tmp_path) -> None:
    """疑似凭据不能落盘，未知记忆 ID 也不能静默删除。"""
    store = ProjectMemoryStore(tmp_path)
    secret = "secret-value-must-not-appear"

    with pytest.raises(ValueError, match="密钥或凭据"):
        store.add(f"API_KEY={secret}")

    assert not (tmp_path / ".agent-code" / "project-memory.json").exists()

    with pytest.raises(ValueError, match="未找到"):
        store.remove("missing")


def test_memory_refuses_corrupted_file_without_overwriting_it(tmp_path) -> None:
    """损坏的长期记忆不能被静默清空或覆盖。"""
    path = tmp_path / ".agent-code" / "project-memory.json"
    path.parent.mkdir()
    path.write_text("{not json}\n", encoding="utf-8")
    store = ProjectMemoryStore(tmp_path)

    with pytest.raises(ValueError, match="已损坏"):
        store.add("不得覆盖损坏文件")

    assert path.read_text(encoding="utf-8") == "{not json}\n"
