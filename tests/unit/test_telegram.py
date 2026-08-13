"""Telegram 白名单渠道与会话边界测试。"""

from agent_code.agent import Agent
from agent_code.plan_mode import PlanMode
from agent_code.project_memory import ProjectMemoryStore
from agent_code.providers.demo import DemoProvider
from agent_code.sessions import SessionStore
from agent_code.telegram import (
    TelegramAgentService,
    TelegramChannel,
    TelegramConfig,
    TelegramOffsetStore,
    load_telegram_config,
)
from agent_code.tools.echo import EchoTool


class FakeTelegramApi:
    """不发起网络请求的 Telegram API 替身。"""

    def __init__(self, updates):
        self._updates = updates
        self.requested_offset = None
        self.sent: list[tuple[int, str]] = []

    def get_me(self):
        return {"username": "safe_bot"}

    def get_updates(self, offset, timeout):
        self.requested_offset = offset
        assert timeout == 20
        return self._updates

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


class FakeService:
    """记录渠道实际交给 Agent 的白名单消息。"""

    def __init__(self):
        self.requests: list[tuple[int, str]] = []

    def handle_message(self, user_id, text):
        self.requests.append((user_id, text))
        return "已处理"


def test_telegram_config_requires_private_whitelist() -> None:
    """缺少白名单用户时，不能启动 Telegram 渠道。"""
    try:
        load_telegram_config({"TELEGRAM_BOT_TOKEN": "token"})
    except ValueError as error:
        assert "TELEGRAM_ALLOWED_USER_ID" in str(error)
    else:
        raise AssertionError("应拒绝无白名单 Telegram 配置")


def test_telegram_channel_only_handles_whitelisted_private_text(tmp_path) -> None:
    """群组、其他用户和非文本更新均不会进入 Agent。"""
    updates = [
        {
            "update_id": 10,
            "message": {
                "from": {"id": 7},
                "chat": {"id": 7, "type": "private"},
                "text": "允许消息",
            },
        },
        {
            "update_id": 11,
            "message": {
                "from": {"id": 8},
                "chat": {"id": 8, "type": "private"},
                "text": "其他用户",
            },
        },
        {
            "update_id": 12,
            "message": {
                "from": {"id": 7},
                "chat": {"id": -100, "type": "group"},
                "text": "群组消息",
            },
        },
    ]
    api = FakeTelegramApi(updates)
    service = FakeService()
    channel = TelegramChannel(
        TelegramConfig("token", allowed_user_id=7),
        api,
        service,
        TelegramOffsetStore(tmp_path),
    )

    assert channel.poll_once() == 1
    assert service.requests == [(7, "允许消息")]
    assert api.sent == [(7, "已处理")]
    assert TelegramOffsetStore(tmp_path).load() == 13


def test_telegram_service_persists_a_stable_user_session(tmp_path) -> None:
    """允许用户的消息会进入独立会话；/start 不消耗模型调用。"""
    service = TelegramAgentService(
        Agent(DemoProvider(), [EchoTool()], pre_tool_use_hooks=(PlanMode(),)),
        SessionStore(tmp_path),
        ProjectMemoryStore(tmp_path),
    )

    assert "由你开发" in service.handle_message(7, "/start")
    assert service.handle_message(7, "你好") == "演示完成：你好"
    messages = SessionStore(tmp_path).load_messages("telegram-7")
    assert messages[-1].content == "演示完成：你好"


def test_telegram_identity_answer_is_fixed_and_truthful(tmp_path) -> None:
    """身份问题不交给模型猜测，避免把兼容协议误作模型身份。"""
    service = TelegramAgentService(
        Agent(DemoProvider(), [EchoTool()], pre_tool_use_hooks=(PlanMode(),)),
        SessionStore(tmp_path),
        ProjectMemoryStore(tmp_path),
    )

    answer = service.handle_message(7, "你是什么模型？")

    assert "agent-code" in answer
    assert "DeepSeek" in answer
    assert "不是 Claude" in answer
    assert "Anthropic 开发" in answer
