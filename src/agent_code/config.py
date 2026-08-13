"""从环境变量和命令行选项加载运行配置。"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from os import environ
from pathlib import Path


class ConfigurationError(ValueError):
    """运行所需配置缺失或无效时抛出的错误。"""


@dataclass(frozen=True)
class AnthropicConfig:
    """调用 Anthropic 或 Anthropic-compatible API 所需的配置。"""

    api_key: str
    model: str
    base_url: str | None = None


_ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_ENV_FILE_BYTES = 16 * 1024


def load_project_environment(
    workspace_root: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """读取受限 `.env`，且不会执行其中的任意 Shell 内容。"""
    merged = dict(environ if environment is None else environment)
    root = (workspace_root or Path.cwd()).resolve()
    dotenv_path = root / ".env"

    if not dotenv_path.exists():
        return merged

    if not dotenv_path.is_file() or dotenv_path.is_symlink():
        raise ConfigurationError(".env 必须是当前工作区中的普通文件。")

    if dotenv_path.stat().st_size > _MAX_ENV_FILE_BYTES:
        raise ConfigurationError(".env 超过 16 KiB 安全上限。")

    try:
        lines = dotenv_path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ConfigurationError(".env 必须为 UTF-8 文本。") from error

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        key, separator, value = line.partition("=")
        key = key.strip()

        if not separator or not _ENV_KEY_PATTERN.fullmatch(key):
            raise ConfigurationError(f".env 第 {line_number} 行格式无效。")

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        merged.setdefault(key, value)

    return merged


def load_anthropic_config(
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> AnthropicConfig:
    """读取命令行选项、终端环境和受限 `.env` 配置。"""
    environment = load_project_environment()
    resolved_api_key = _first_non_empty(
        api_key,
        environment.get("ANTHROPIC_API_KEY"),
        environment.get("ANTHROPIC_AUTH_TOKEN"),
    )
    resolved_model = _first_non_empty(
        model,
        environment.get("AGENT_CODE_MODEL"),
    )
    resolved_base_url = _first_non_empty(
        base_url,
        environment.get("ANTHROPIC_BASE_URL"),
    )

    missing_names: list[str] = []

    if resolved_api_key is None:
        missing_names.append("ANTHROPIC_API_KEY")
    if resolved_model is None:
        missing_names.append("AGENT_CODE_MODEL")

    if missing_names:
        names = "、".join(missing_names)
        raise ConfigurationError(
            f"未配置 {names}。请使用环境变量或对应命令行选项提供。"
        )

    return AnthropicConfig(
        api_key=resolved_api_key,
        model=resolved_model,
        base_url=resolved_base_url,
    )


def _first_non_empty(*values: str | None) -> str | None:
    """返回第一个非空白字符串。"""
    for value in values:
        if value and value.strip():
            return value.strip()

    return None
