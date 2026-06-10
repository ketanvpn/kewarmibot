"""KeWarMiBot — Callback router, quick commands, build_app"""
from src.bot.handlers._common import *

# Cross-module imports for build_app
from src.bot.handlers.menu import start, admin_command, cmd_menu, main_menu
from src.bot.handlers.cookies import (
    cookie_add_start, cookie_add_name, cookie_add_token, cookie_add_cancel,
    cookie_detail, cookie_refresh, cookie_refresh_all,
    cookie_delete_confirm, cookie_delete, menu_cookies, cookie_toggle_war,
)
from src.bot.handlers.info import menu_status, menu_history, menu_stats, menu_profile
from src.bot.handlers.config import menu_config, config_set
from src.bot.handlers.war import war_debug, menu_autowar, autowar_toggle
from src.bot.handlers.payment import menu_beli, menu_beli_confirm
from src.bot.handlers.admin import (
    menu_admin, admin_users_list, admin_user_detail, admin_user_topup_prompt,
    admin_packages_list, admin_pkg_edit, admin_pkg_edit_field,
    admin_settings_menu, admin_setting_edit, admin_revenue,
    text_input_handler,
)
from src.bot.handlers.pool import pool_handle_text
from src.bot.handlers.guide import menu_guide, menu_support, menu_email_copy

# ─── Callback Router ───────────────────────────────────

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    # Strip @admin suffix — sets admin nav context so "Kembali" goes to menu:admin
    admin_context_requested = data.endswith("@admin")
    if admin_context_requested and not is_admin_update(update):
        await query.edit_message_text("⛔ Akses ditolak — admin only.", parse_mode=ParseMode.HTML)
        return

    if admin_context_requested:
        data = data[:-6]
        context.user_data["_nav_admin"] = True
    else:
        context.user_data.pop("_nav_admin", None)

    if (data.startswith("admin:") or data.startswith("pool:")) and not is_admin_update(update):
        await query.edit_message_text("⛔ Akses ditolak — admin only.", parse_mode=ParseMode.HTML)
        return

    static_routes = {
        "menu:main": main_menu,
        "menu:profile": menu_profile,
        "menu:cookies": menu_cookies,
        "menu:status": menu_status,
        "menu:config": menu_config,
        "menu:war_debug": war_debug,
        "menu:autowar": menu_autowar,
        "menu:history": menu_history,
        "menu:stats": menu_stats,
        "menu:beli": menu_beli,
        "menu:admin": menu_admin,
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
    elif data.startswith("autowar:"):
        await autowar_toggle(update, context)
    elif data.startswith("beli:pkg:"):
        await menu_beli_confirm(update, context)
    elif data.startswith("beli:"):
        await menu_beli(update, context)
    elif data.startswith("pool:"):
        await pool_handle_text(update, context)
    elif data.startswith("admin:pkg:name:") or data.startswith("admin:pkg:war:") or data.startswith("admin:pkg:price:") or data.startswith("admin:pkg:toggle:"):
        await admin_pkg_edit_field(update, context)
    elif data.startswith("admin:pkg:edit:"):
        await admin_pkg_edit(update, context)
    elif data.startswith("admin:pkg:"):
        await admin_pkg_edit(update, context)
    elif data.startswith("admin:user:"):
        await admin_user_detail(update, context)
    elif data.startswith("admin:topup:"):
        await admin_user_topup_prompt(update, context)
    elif data == "admin:users":
        await admin_users_list(update, context)
    elif data == "admin:packages":
        await admin_packages_list(update, context)
    elif data == "admin:settings":
        await admin_settings_menu(update, context)
    elif data.startswith("admin:setting:"):
        await admin_setting_edit(update, context)
    elif data == "admin:revenue":
        await admin_revenue(update, context)
    else:
        await main_menu(update, context)


# ─── Quick Commands ────────────────────────────────────

async def _fake_query(update: Update, data: str):
    class FakeQuery:
        data = data
        message = update.message
        async def answer(self, *a, **kw): pass
        async def edit_message_text(self, text, **kw):
            return await self.message.reply_text(text, **kw)
    update.callback_query = FakeQuery()

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _fake_query(update, "menu:status")
    await menu_status(update, context)

async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _fake_query(update, "menu:config")
    await menu_config(update, context)

async def cmd_war(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _fake_query(update, "menu:war_debug")
    await war_debug(update, context)

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _fake_query(update, "menu:history")
    await menu_history(update, context)


# ─── Application Builder ───────────────────────────────

def build_app() -> Application:
    app = Application.builder().token(settings.bot_token).build()

    # User commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    # Admin command
    app.add_handler(CommandHandler("admin", admin_command))
    # Quick jumps
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

    # Text input (admin topup, package edit, proxy add)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        text_input_handler,
    ), group=1)

    # All callback queries
    app.add_handler(CallbackQueryHandler(
        menu_router,
        pattern="^(menu|cookie|cfg|autowar|pool|beli|admin):",
    ))

    return app
