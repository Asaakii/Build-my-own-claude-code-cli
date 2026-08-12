"""PreviewReplaceTool 的单元测试。"""

import hashlib

import pytest

from agent_code.tools.preview_replace import PreviewReplaceTool


def _sha256(text: str) -> str:
    """计算测试文本的 SHA-256。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_preview_replace_returns_diff_without_writing(tmp_path) -> None:
    """精确替换应返回 diff，且预览阶段不得修改文件。"""
    file_path = tmp_path / "settings.py"
    original_text = "version = 1\nname = 'agent-code'\n"
    file_path.write_text(original_text, encoding="utf-8")
    tool = PreviewReplaceTool(tmp_path)

    result = tool.run(
        {
            "path": "settings.py",
            "old_text": "version = 1",
            "new_text": "version = 2",
            "expected_sha256": _sha256(original_text),
        }
    )

    assert "预览路径：settings.py" in result
    assert "替换次数：1" in result
    assert "写入状态：未写入" in result
    assert "--- a/settings.py" in result
    assert "+++ b/settings.py" in result
    assert "-version = 1" in result
    assert "+version = 2" in result
    assert file_path.read_text(encoding="utf-8") == original_text


def test_preview_replace_rejects_stale_or_ambiguous_target(tmp_path) -> None:
    """指纹过期或目标出现多次时，预览必须拒绝。"""
    file_path = tmp_path / "settings.py"
    original_text = "enabled = true\nenabled = true\n"
    file_path.write_text(original_text, encoding="utf-8")
    tool = PreviewReplaceTool(tmp_path)

    with pytest.raises(ValueError, match="文件内容已变化"):
        tool.run(
            {
                "path": "settings.py",
                "old_text": "enabled = true",
                "new_text": "enabled = false",
                "expected_sha256": "0" * 64,
            }
        )

    with pytest.raises(ValueError, match="目标不唯一"):
        tool.run(
            {
                "path": "settings.py",
                "old_text": "enabled = true",
                "new_text": "enabled = false",
                "expected_sha256": _sha256(original_text),
            }
        )


def test_preview_replace_rejects_unsafe_paths_and_symlinks(tmp_path) -> None:
    """越界路径和任何符号链接都必须被拒绝。"""
    outside_file = tmp_path.parent / "outside.txt"
    outside_file.write_text("old", encoding="utf-8")
    link = tmp_path / "outside-link.txt"
    link.symlink_to(outside_file)
    tool = PreviewReplaceTool(tmp_path)

    arguments = {
        "old_text": "old",
        "new_text": "new",
        "expected_sha256": _sha256("old"),
    }

    for path, expected_message in (
        ("../outside.txt", "不允许"),
        ("outside-link.txt", "符号链接"),
    ):
        with pytest.raises(ValueError, match=expected_message):
            tool.run({"path": path, **arguments})


def test_preview_replace_rejects_non_text_and_oversized_files(tmp_path) -> None:
    """二进制文件和超出大小上限的文件不能生成预览。"""
    binary_file = tmp_path / "image.bin"
    binary_file.write_bytes(b"\x00old")

    large_file = tmp_path / "large.txt"
    large_file.write_bytes(
        b"a" * (PreviewReplaceTool.max_file_bytes + 1)
    )

    tool = PreviewReplaceTool(tmp_path)

    for path, expected_message in (
        ("image.bin", "二进制文件"),
        ("large.txt", "文件过大"),
    ):
        with pytest.raises(ValueError, match=expected_message):
            tool.run(
                {
                    "path": path,
                    "old_text": "old",
                    "new_text": "new",
                    "expected_sha256": "0" * 64,
                }
            )