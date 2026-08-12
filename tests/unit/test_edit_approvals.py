"""待确认编辑与原子写入的单元测试。"""

import hashlib
import re

import pytest

from agent_code.edits import PendingEditStore, apply_pending_edit
from agent_code.tools.preview_replace import PreviewReplaceTool


def _sha256(text: str) -> str:
    """计算测试文本的 SHA-256。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _approval_id(preview: str) -> str:
    """从预览结果中提取待确认 ID。"""
    matched = re.search(r"待确认 ID：([A-Za-z0-9_-]+)", preview)

    if matched is None:
        raise AssertionError("预览结果中没有待确认 ID。")

    return matched.group(1)


def test_approved_preview_writes_exact_replacement(tmp_path) -> None:
    """用户确认后应写入已预览的一次精确替换。"""
    file_path = tmp_path / "settings.py"
    original_text = "version = 1\n"
    file_path.write_text(original_text, encoding="utf-8")
    pending_edits = PendingEditStore()
    preview_tool = PreviewReplaceTool(
        tmp_path,
        pending_edits=pending_edits,
    )

    preview = preview_tool.run(
        {
            "path": "settings.py",
            "old_text": "version = 1",
            "new_text": "version = 2",
            "expected_sha256": _sha256(original_text),
        }
    )
    result = apply_pending_edit(
        pending_edits,
        workspace_root=tmp_path,
        approval_id=_approval_id(preview),
    )

    assert "已写入：settings.py" in result
    assert file_path.read_text(encoding="utf-8") == "version = 2\n"


def test_pending_edit_is_one_time_and_detects_stale_file(tmp_path) -> None:
    """确认 ID 只能使用一次，文件变化后必须拒绝写入。"""
    file_path = tmp_path / "settings.py"
    original_text = "version = 1\n"
    file_path.write_text(original_text, encoding="utf-8")
    pending_edits = PendingEditStore()
    preview_tool = PreviewReplaceTool(
        tmp_path,
        pending_edits=pending_edits,
    )

    preview = preview_tool.run(
        {
            "path": "settings.py",
            "old_text": "version = 1",
            "new_text": "version = 2",
            "expected_sha256": _sha256(original_text),
        }
    )
    approval_id = _approval_id(preview)
    file_path.write_text("version = 3\n", encoding="utf-8")

    with pytest.raises(ValueError, match="文件内容已变化"):
        apply_pending_edit(
            pending_edits,
            workspace_root=tmp_path,
            approval_id=approval_id,
        )

    assert file_path.read_text(encoding="utf-8") == "version = 3\n"

    with pytest.raises(ValueError, match="不存在"):
        apply_pending_edit(
            pending_edits,
            workspace_root=tmp_path,
            approval_id=approval_id,
        )