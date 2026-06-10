"""Regression tests for user/admin menu permission boundaries."""

import pytest


class FakeChat:
    def __init__(self, chat_id: int):
        self.id = chat_id


class FakeQuery:
    def __init__(self, data: str):
        self.data = data
        self.answered = False
        self.edited_text = None

    async def answer(self, *args, **kwargs):
        self.answered = True

    async def edit_message_text(self, text, **kwargs):
        self.edited_text = text


class FakeMessage:
    def __init__(self, text: str):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeUpdate:
    def __init__(self, chat_id: int, data: str | None = None, text: str | None = None):
        self.effective_chat = FakeChat(chat_id)
        self.callback_query = FakeQuery(data) if data is not None else None
        self.message = FakeMessage(text) if text is not None else None


class FakeContext:
    def __init__(self):
        self.user_data = {}


@pytest.mark.asyncio
@pytest.mark.parametrize("callback_data", [
    "admin:users",
    "pool:menu",
    "menu:config@admin",
])
async def test_non_admin_callback_cannot_enter_admin_or_pool_routes(callback_data):
    from src.bot.handlers.router import menu_router

    update = FakeUpdate(chat_id=123456, data=callback_data)
    context = FakeContext()

    await menu_router(update, context)

    assert update.callback_query.answered is True
    assert update.callback_query.edited_text == "⛔ Akses ditolak — admin only."
    assert "_nav_admin" not in context.user_data


@pytest.mark.asyncio
async def test_non_admin_text_input_clears_admin_pending_state():
    from src.bot.handlers.admin import text_input_handler

    update = FakeUpdate(chat_id=123456, text="new-secret-value")
    context = FakeContext()
    context.user_data["editing_setting"] = "payment_webhook_secret"
    context.user_data["editing_pkg"] = {"id": 1, "field": "price"}

    await text_input_handler(update, context)

    assert "editing_setting" not in context.user_data
    assert "editing_pkg" not in context.user_data
    assert update.message.replies == []
