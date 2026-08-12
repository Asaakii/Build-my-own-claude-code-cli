"""模型 Provider 实现。"""

from agent_code.providers.base import Provider
from agent_code.providers.mock import MockProvider

__all__ = ["MockProvider", "Provider"]