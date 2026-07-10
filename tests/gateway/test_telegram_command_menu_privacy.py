from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.config import HomeChannel, Platform, PlatformConfig
from plugins.platforms.telegram.adapter import TelegramAdapter


@pytest.mark.asyncio
async def test_telegram_command_menu_clears_global_scopes_and_scopes_to_authorized_chats(monkeypatch):
    """Unapproved Telegram users must not see slash commands just by opening a DM."""
    monkeypatch.delenv("TELEGRAM_EXPOSE_COMMAND_MENU", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "12345,not-a-chat,*")
    monkeypatch.setenv("TELEGRAM_GROUP_ALLOWED_CHATS", "-100777")
    monkeypatch.setattr(
        "hermes_cli.commands.telegram_menu_commands",
        lambda max_commands=100: ([ ("help", "Show help") ], 0),
    )

    class FakeBotCommand:
        def __init__(self, command, description):
            self.command = command
            self.description = description

    class FakeScopeDefault:
        pass

    class FakeScopeAllPrivateChats:
        pass

    class FakeScopeAllGroupChats:
        pass

    class FakeScopeChat:
        def __init__(self, chat_id):
            self.chat_id = chat_id

    import telegram

    monkeypatch.setattr(telegram, "BotCommand", FakeBotCommand, raising=False)
    monkeypatch.setattr(telegram, "BotCommandScopeDefault", FakeScopeDefault, raising=False)
    monkeypatch.setattr(telegram, "BotCommandScopeAllPrivateChats", FakeScopeAllPrivateChats, raising=False)
    monkeypatch.setattr(telegram, "BotCommandScopeAllGroupChats", FakeScopeAllGroupChats, raising=False)
    monkeypatch.setattr(telegram, "BotCommandScopeChat", FakeScopeChat, raising=False)

    config = PlatformConfig(
        enabled=True,
        token="token",
        home_channel=HomeChannel(
            platform=Platform.TELEGRAM,
            chat_id="8721459",
            name="Home",
        ),
    )
    adapter = TelegramAdapter(config)
    bot = SimpleNamespace(set_my_commands=AsyncMock())
    adapter._bot = bot
    setattr(
        adapter,
        "_message_handler",
        SimpleNamespace(
            __self__=SimpleNamespace(
                pairing_store=SimpleNamespace(
                    list_approved=lambda platform: [
                        {"user_id": "99999", "user_name": "Paired"},
                        {"user_id": "username", "user_name": "Ignored non-numeric"},
                    ]
                )
            )
        ),
    )

    await adapter._register_command_menu()

    calls = bot.set_my_commands.await_args_list
    assert len(calls) == 7

    # First clear all public Telegram command scopes so unauthenticated DMs do
    # not inherit the default/global command menu.
    cleared_scopes = [call.kwargs["scope"] for call in calls[:3]]
    assert [type(scope) for scope in cleared_scopes] == [
        FakeScopeDefault,
        FakeScopeAllPrivateChats,
        FakeScopeAllGroupChats,
    ]
    assert all(call.args[0] == [] for call in calls[:3])

    # Then publish the menu only to known authorized chat IDs.
    scoped_chat_ids = sorted(str(call.kwargs["scope"].chat_id) for call in calls[3:])
    assert scoped_chat_ids == ["-100777", "12345", "8721459", "99999"]
    assert all(isinstance(call.kwargs["scope"], FakeScopeChat) for call in calls[3:])
    assert all(call.args[0][0].command == "help" for call in calls[3:])
