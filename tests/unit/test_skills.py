"""Skills 按需加载测试。"""

import pytest

from agent_code.skills import SkillStore


def _write_skill(root, identifier: str, instructions: str = "正文") -> None:
    path = root / "skills" / identifier / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        f"name: {identifier}\n"
        "description: 测试技能\n"
        "applies_to: 测试时。\n"
        "---\n"
        f"{instructions}\n",
        encoding="utf-8",
    )


def test_skill_store_scans_metadata_then_loads_body_on_demand(tmp_path) -> None:
    """列出技能只返回 front matter；显式 load 才返回正文。"""
    _write_skill(tmp_path, "review", instructions="只有加载后才能读取的步骤。")
    store = SkillStore(tmp_path)

    assert store.list_metadata()[0].identifier == "review"
    assert store.list_metadata()[0].source == "skills/review/SKILL.md"
    assert store.load("review").instructions == "只有加载后才能读取的步骤。"


def test_skill_store_rejects_missing_malformed_and_symlink_paths(tmp_path) -> None:
    """缺失、无效 front matter 与符号链接技能都不能加载。"""
    store = SkillStore(tmp_path)

    with pytest.raises(ValueError, match="未找到"):
        store.load("missing")

    malformed = tmp_path / "skills" / "bad" / "SKILL.md"
    malformed.parent.mkdir(parents=True)
    malformed.write_text("not front matter", encoding="utf-8")

    with pytest.raises(ValueError, match="front matter"):
        store.list_metadata()

    malformed.unlink()
    target = tmp_path / "outside.md"
    target.write_text("outside", encoding="utf-8")
    malformed.symlink_to(target)

    with pytest.raises(ValueError, match="符号链接"):
        store.list_metadata()
