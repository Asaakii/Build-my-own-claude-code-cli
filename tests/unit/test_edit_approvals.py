"""待确认编辑、原子写入与审计的单元测试。"""

import hashlib
import re

import pytest

from agent_code.edits import (
    EditAuditLog,
    PendingEditStore,
    apply_pending_edit,
)
from agent_code.tools.preview_create_file import PreviewCreateFileTool
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


def test_approved_preview_writes_exact_replacement_and_audits(
    tmp_path,
) -> None:
    """用户确认后应写入已预览的一次精确替换，并留下不含内容的审计。"""
    file_path = tmp_path / "settings.py"
    original_text = "version = 1\n"
    file_path.write_text(original_text, encoding="utf-8")
    pending_edits = PendingEditStore()
    audit_log = EditAuditLog()
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
        audit_log=audit_log,
    )

    audit = audit_log.render()

    assert "已写入：settings.py" in result
    assert file_path.read_text(encoding="utf-8") == "version = 2\n"
    assert "已完成 | replace | settings.py" in audit
    assert "version = 2" not in audit


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


def test_approved_preview_creates_new_file_without_overwrite(tmp_path) -> None:
    """用户确认后应创建预览的新文件，已存在目标必须拒绝覆盖。"""
    pending_edits = PendingEditStore()
    preview_tool = PreviewCreateFileTool(
        tmp_path,
        pending_edits=pending_edits,
    )

    preview = preview_tool.run(
        {
            "path": "new-note.txt",
            "content": "由 agent-code 创建\n",
        }
    )
    result = apply_pending_edit(
        pending_edits,
        workspace_root=tmp_path,
        approval_id=_approval_id(preview),
    )

    assert "已写入：new-note.txt" in result
    assert "新建文件：1" in result
    assert (tmp_path / "new-note.txt").read_text(encoding="utf-8") == (
        "由 agent-code 创建\n"
    )

    with pytest.raises(ValueError, match="目标文件已存在"):
        preview_tool.run(
            {
                "path": "new-note.txt",
                "content": "不应覆盖",
            }
        )


def test_create_preview_rejects_missing_parent_and_symlink(tmp_path) -> None:
    """不存在的父目录和符号链接路径都必须被拒绝。"""
    outside_directory = tmp_path.parent / "outside-directory"
    outside_directory.mkdir(exist_ok=True)
    (tmp_path / "outside-link").symlink_to(
        outside_directory,
        target_is_directory=True,
    )
    tool = PreviewCreateFileTool(tmp_path)

    for path, expected_message in (
        ("missing/note.txt", "父目录不存在"),
        ("outside-link/note.txt", "符号链接"),
    ):
        with pytest.raises(ValueError, match=expected_message):
            tool.run({"path": path, "content": "内容"})


def test_failed_atomic_replace_preserves_original_and_audits(
    tmp_path,
    monkeypatch,
) -> None:
    """原子替换失败时，原文件与临时文件状态都必须安全。"""
    file_path = tmp_path / "settings.py"
    original_text = "version = 1\n"
    file_path.write_text(original_text, encoding="utf-8")
    pending_edits = PendingEditStore()
    audit_log = EditAuditLog()
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

    def fail_replace(_source, _target) -> None:
        raise OSError("模拟原子替换失败")

    monkeypatch.setattr("agent_code.edits.os.replace", fail_replace)

    with pytest.raises(RuntimeError, match="原子写入失败"):
        apply_pending_edit(
            pending_edits,
            workspace_root=tmp_path,
            approval_id=_approval_id(preview),
            audit_log=audit_log,
        )

    assert file_path.read_text(encoding="utf-8") == original_text
    assert list(tmp_path.glob(".agent-code-*")) == []
    assert "已拒绝 | replace | settings.py" in audit_log.render()


def test_failed_atomic_create_leaves_no_target_or_temp_file(
    tmp_path,
    monkeypatch,
) -> None:
    """原子创建失败时，目标文件和临时文件都不能遗留。"""
    pending_edits = PendingEditStore()
    audit_log = EditAuditLog()
    preview_tool = PreviewCreateFileTool(
        tmp_path,
        pending_edits=pending_edits,
    )
    preview = preview_tool.run(
        {
            "path": "new-note.txt",
            "content": "不应写入\n",
        }
    )

    def fail_link(_source, _target) -> None:
        raise OSError("模拟原子创建失败")

    monkeypatch.setattr("agent_code.edits.os.link", fail_link)

    with pytest.raises(RuntimeError, match="创建新文件失败"):
        apply_pending_edit(
            pending_edits,
            workspace_root=tmp_path,
            approval_id=_approval_id(preview),
            audit_log=audit_log,
        )

    assert not (tmp_path / "new-note.txt").exists()
    assert list(tmp_path.glob(".agent-code-*")) == []
    assert "已拒绝 | create | new-note.txt" in audit_log.render()