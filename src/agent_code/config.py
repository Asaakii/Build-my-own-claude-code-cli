"""从环境变量和命令行选项加载运行配置。"""

from dataclasses import dataclass
from os import environ


class ConfigurationError(ValueError):
    """运行所需配置缺失或无效时抛出的错误。"""


@dataclass(frozen=True)
class AnthropicConfig:
    """调用 Anthropic 或 Anthropic-compatible API 所需的配置。"""

    api_key: str
    model: str
    base_url: str | None = None


def load_anthropic_config(
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> AnthropicConfig:
    """读取命令行选项，未提供时再读取环境变量。"""
    resolved_api_key = _first_non_empty(
        api_key,
        environ.get("ANTHROPIC_API_KEY"),
        environ.get("ANTHROPIC_AUTH_TOKEN"),
    )
    resolved_model = _first_non_empty(
        model,
        environ.get("AGENT_CODE_MODEL"),
    )
    resolved_base_url = _first_non_empty(
        base_url,
        environ.get("ANTHROPIC_BASE_URL"),
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