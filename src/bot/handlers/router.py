"""KeWarMiBot — Callback router, quick commands, build_app. Single-owner."""
from src.bot.handlers._common import *

from src.bot.handlers.menu import start, cmd_menu, main_menu
from src.bot.handlers.cookies import (
    cookie_add_start, cookie_add_name, cookie_add_token, cookie_add_cancel,
    cookie_detail, cookie_refresh, cookie_refresh_all,
    cookie_delete_confirm, cookie_delete, menu_cookies, cookie_toggle_war,
)
from src.bot.handlers.info import menu_status, menu_history, menu_stats
from src.bot.handlers.config import menu_config, config_set
from src.bot.handlers.war import war_debug, menu_autowar, autowar_toggle
from src.bot.handlers.pool import pool_menu, pool_router, pool_text_input
from src.bot.handlers.guide import menu_guide, menu_support, menu_email_copy


# ─── Callback Router ───────────────────────────────────

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if not is_owner(update):
        await query.edit_message_text("⛔ Bot ini hanya untuk owner.", parse_mode=ParseMode.HTML)
        return

    static_routes = {
        "menu:main": main_menu,
        "menu:cookies": menu_cookies,
        "menu:status": menu_status,
        "menu:config": menu_config,
        "menu:war_debug": war_debug,
        "menu:autowar": menu_autowar,
        "menu:autowar_toggle": autowar_toggle,
        "menu:history": menu_history,
        "menu:stats": menu_stats,
        "menu:guide": menu_guide,
        "menu:support": menu_support,
        "menu:email_copy": menu_email_copy,
    }

    if data in static_routes:
        await static_routes[data](update, context)
    elif data == "cookie:refresh_all":
        await cookie_refresh_all(update, context)
    elif data.startswith("cookie:detail:"):
        await cookie_detail(update, context)
    elif data.startswith("cookie:refresh:"):
        await cookie_refresh(update, context)
    elif data.startswith("cookie:delete_confirm:"):
        await cookie_delete_confirm(update, context)
    elif data.startswith("cookie:delete:"):
        await cookie_delete(update, context)
    elif data.startswith("cookie:toggle_war:"):
        await cookie_toggle_war(update, context)
    elif data.startswith("cookie:add"):
        await cookie_add_start(update, context)
    elif data.startswith("cfg:"):
        await config_set(update, context)
    elif data.startswith("pool:"):
        await pool_router(update, context)
    else:
        await main_menu(update, context)


# ─── Quick Commands ────────────────────────────────────

async def _fake_query(update: Update, data: str):
    class FakeQuery:
        message = update.message
        async def answer(self, *a, **kw): pass
        async def edit_message_text(self, text, **kw):
            return await self.message.reply_text(text, **kw)
    fq = FakeQuery()
    fq.data = data
    update.callback_query = fq


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update):
        return
    await _fake_query(update, "menu:status")
    await menu_status(update, context)


async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update):
        return
    await _fake_query(update, "menu:config")
    await menu_config(update, context)


async def cmd_war(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update):
        return
    await _fake_query(update, "menu:war_debug")
    await war_debug(update, context)


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update):
        return
    await _fake_query(update, "menu:history")
    await menu_history(update, context)


# ─── Text Input Handler ─────────────────────────────────

async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text input for proxy pool add."""
    if not is_owner(update):
        return

    input_mode = context.user_data.get("_input_mode")
    if input_mode == "pool_add":
        await pool_text_input(update, context)


# ─── Application Builder ───────────────────────────────

def build_app() -> Application:
    app = Application.builder().token(settings.bot_token).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("war", cmd_war))
    app.add_handler(CommandHandler("riwayat", cmd_history))

    # Cookie add conversation
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cookie_add_start, pattern="^cookie:add$")],
        states={
            WAIT_COOKIE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, cookie_add_name)],
            WAIT_COOKIE_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, cookie_add_token)],
        },
        fallbacks=[CommandHandler("cancel", cookie_add_cancel)],
    )
    app.add_handler(conv)

    # Text input (proxy add)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        text_input_handler,
    ), group=1)

    # All callback queries
    app.add_handler(CallbackQueryHandler(
        menu_router,
        pattern="^(menu|cookie|cfg|pool):",
    ))

    return app
