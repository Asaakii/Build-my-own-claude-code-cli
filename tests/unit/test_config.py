"""运行配置的单元测试。"""

import pytest

from agent_code.config import ConfigurationError, load_anthropic_config


def test_config_reads_required_values_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未传入选项时，应从环境变量读取配置。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_CODE_MODEL", "test-model")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.com")

    config = load_anthropic_config()

    assert config.api_key == "test-key"
    assert config.model == "test-model"
    assert config.base_url == "https://example.com"


def test_explicit_options_override_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """命令行选项应优先于环境变量。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "environment-key")
    monkeypatch.setenv("AGENT_CODE_MODEL", "environment-model")

    config = load_anthropic_config(
        api_key="option-key",
        model="option-model",
        base_url="https://option.example.com",
    )

    assert config.api_key == "option-key"
    assert config.model == "option-model"
    assert config.base_url == "https://option.example.com"


def test_config_rejects_missing_required_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺少密钥和模型名时，应指出具体缺失项。"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("AGENT_CODE_MODEL", raising=False)

    with pytest.raises(
        ConfigurationError,
        match="ANTHROPIC_API_KEY.*AGENT_CODE_MODEL",
    ):
        load_anthropic_config()