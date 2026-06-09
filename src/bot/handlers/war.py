"""KeWarMiBot — Debug war, auto-war toggle, run-now"""
from src.bot.handlers._common import *

# ─── War Now ───────────────────────────────────────────

async def war_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    oid = _owner(update)

    from src.engine.war_runner import execute_war

    async def _notify(chat_id: str, msg: str):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Menu Utama", callback_data="menu:main")]])
        try:
            await query.message.reply_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"war_debug notify failed: {e}")

    await query.edit_message_text("⚔️ <b>WAR DEBUG</b>\n\n⏰ War dalam ~20 detik...", parse_mode=ParseMode.HTML)
    await execute_war(oid, debug=True, deduct=True, notify=_notify)



# ─── Auto-War Toggle ───────────────────────────────────

async def menu_autowar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    oid = _owner(update)
    async with AsyncSessionLocal() as session:
        user = await get_user(session, oid)
        enabled = user.war_enabled if user else True

    status_text = "✅ AKTIF" if enabled else "❌ NONAKTIF"
    text = (
        f"⏰ <b>Auto-War Scheduler</b>\n\n"
        f"Status: {status_text}\n\n"
        f"Jadwal:\n"
        f"• 23:55 CST — Notifikasi 5 menit sebelum war\n"
        f"• 23:57 CST — Auto-war dimulai\n"
        f"• 00:00 CST — Reset harian Xiaomi\n\n"
        f"Latency monitor berjalan setiap 15 menit."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Matikan" if enabled else "🟢 Aktifkan", callback_data="autowar:toggle")],
        [InlineKeyboardButton("« Kembali", callback_data="menu:main")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def autowar_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    oid = _owner(update)
    async with AsyncSessionLocal() as session:
        new_state = await toggle_war_enabled(session, oid)
    await menu_autowar(update, context)


async def autowar_run_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manual trigger real war (not debug)."""
    query = update.callback_query
    await query.answer()
    oid = _owner(update)

    from src.engine.war_runner import execute_war

    async def _notify(chat_id: str, msg: str):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Menu Utama", callback_data="menu:main")]])
        try:
            await query.message.reply_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"autowar_run_now notify failed: {e}")

    await query.edit_message_text("⚔️ <b>WAR DIMULAI</b>\n\nMenunggu hasil...", parse_mode=ParseMode.HTML)
    await execute_war(oid, debug=False, deduct=False, notify=_notify)

