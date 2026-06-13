"""KeWarMiBot — Debug war, auto-war info"""
from src.bot.handlers._common import *


# ─── War Debug ─────────────────────────────────────────

async def war_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_owner(update):
        return

    from src.engine.war_runner import execute_war

    async def _notify(chat_id: str, msg: str):
        kb = InlineKeyboardMarkup([[back_button()]])
        try:
            await query.message.reply_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"war_debug notify failed: {e}")

    await query.edit_message_text("⚔️ <b>WAR DEBUG</b>\n\n⏰ War dalam ~20 detik...", parse_mode=ParseMode.HTML)
    await execute_war(debug=True, notify=_notify)


# ─── Auto-War Info ─────────────────────────────────────

async def menu_autowar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_owner(update):
        return

    cfg = await cfg_dict()
    wh = cfg.get("war_hour", 0)
    wm = cfg.get("war_minute", 0)
    tz = cfg.get("war_tz", "Asia/Shanghai")
    selected_ids = cfg.get("cookie_ids", [])
    hero_per = cfg.get("hero_per_cookie", 6)

    text = (
        f"⏰ <b>Auto-War Status</b>\n\n"
        f"🕐 Jadwal: <b>{wh:02d}:{wm:02d} {tz}</b>\n"
        f"🍪 Cookie: <b>{len(selected_ids)}</b>\n"
        f"🥊 Hero/cookie: <b>{hero_per}</b>\n"
        f"🔄 Total tembakan: <b>{len(selected_ids) * hero_per}</b>\n\n"
        f"<i>Bot akan otomatis war tiap hari sesuai jadwal.\n"
        f"Edit jadwal di ⚙️ Config.</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Edit Config", callback_data="menu:config")],
        [back_button()],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
