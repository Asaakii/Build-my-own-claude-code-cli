"""受限目录中的 SKILL.md 元数据扫描与按需正文加载。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillMetadata:
    """启动时可读取的技能元数据。"""

    identifier: str
    name: str
    description: str
    applies_to: str
    source: str


@dataclass(frozen=True)
class LoadedSkill:
    """用户或模型显式选择后才读取的技能正文。"""

    metadata: SkillMetadata
    instructions: str


class SkillStore:
    """仅允许读取工作区 `skills/*/SKILL.md` 的技能仓库。"""

    max_metadata_bytes = 4 * 1024
    max_skill_bytes = 32 * 1024

    def __init__(self, workspace_root: Path) -> None:
        root = workspace_root.resolve()

        if not root.is_dir():
            raise ValueError("工作区根目录必须是存在的目录。")

        self._skills_root = root / "skills"

    def list_metadata(self) -> tuple[SkillMetadata, ...]:
        """仅扫描前 4 KiB front matter，不加载技能步骤正文。"""
        if not self._skills_root.exists():
            return ()

        if self._skills_root.is_symlink():
            raise ValueError("skills 目录不能是符号链接。")

        metadata: list[SkillMetadata] = []

        for path in sorted(self._skills_root.glob("*/SKILL.md")):
            metadata.append(self._read_metadata(path))

        return tuple(metadata)

    def load(self, identifier: str) -> LoadedSkill:
        """按需读取一份经验证技能的完整正文。"""
        metadata = next(
            (item for item in self.list_metadata() if item.identifier == identifier),
            None,
        )

        if metadata is None:
            raise ValueError("未找到该技能。")

        path = self._path_for_identifier(identifier)

        if path.stat().st_size > self.max_skill_bytes:
            raise ValueError(f"技能正文不能超过 {self.max_skill_bytes} 字节。")

        content = path.read_text(encoding="utf-8")
        _, instructions = _parse_skill_markdown(content)
        return LoadedSkill(metadata=metadata, instructions=instructions)

    def _read_metadata(self, path: Path) -> SkillMetadata:
        checked_path = self._validate_path(path)

        if checked_path.stat().st_size > self.max_skill_bytes:
            raise ValueError(f"技能文件不能超过 {self.max_skill_bytes} 字节。")

        with checked_path.open("rb") as skill_file:
            header = skill_file.read(self.max_metadata_bytes)

        try:
            metadata_values, _ = _parse_skill_markdown(header.decode("utf-8"))
        except UnicodeDecodeError as error:
            raise ValueError("技能文件必须是 UTF-8 文本。") from error

        identifier = checked_path.parent.name
        return SkillMetadata(
            identifier=identifier,
            name=_required(metadata_values, "name"),
            description=_required(metadata_values, "description"),
            applies_to=_required(metadata_values, "applies_to"),
            source=str(checked_path.relative_to(self._skills_root.parent)),
        )

    def _path_for_identifier(self, identifier: str) -> Path:
        if (
            not identifier
            or "/" in identifier
            or "\\" in identifier
            or identifier == "."
        ):
            raise ValueError("技能标识符无效。")

        return self._validate_path(self._skills_root / identifier / "SKILL.md")

    def _validate_path(self, path: Path) -> Path:
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError("技能文件和技能目录不能是符号链接。")

        try:
            resolved_path = path.resolve(strict=True)
            resolved_root = self._skills_root.resolve(strict=False)
            resolved_path.relative_to(resolved_root)
        except (FileNotFoundError, ValueError) as error:
            raise ValueError("技能路径不存在或超出允许目录。") from error

        if resolved_path.name != "SKILL.md":
            raise ValueError("技能文件名必须是 SKILL.md。")

        return resolved_path


def _parse_skill_markdown(content: str) -> tuple[dict[str, str], str]:
    if not content.startswith("---\n"):
        raise ValueError("SKILL.md 必须以 YAML 风格 front matter 开始。")

    try:
        raw_front_matter, instructions = content[4:].split("\n---\n", maxsplit=1)
    except ValueError as error:
        raise ValueError("SKILL.md 缺少 front matter 结束标记。") from error

    values: dict[str, str] = {}

    for line in raw_front_matter.splitlines():
        key, separator, value = line.partition(":")

        if not separator or not key or not value.strip():
            raise ValueError("SKILL.md front matter 格式无效。")

        values[key.strip()] = value.strip()

    return values, instructions.strip()


def _required(values: dict[str, str], key: str) -> str:
    try:
        return values[key]
    except KeyError as error:
        raise ValueError(f"SKILL.md 缺少 {key} 字段。") from error
