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
    enabled = cfg.get("autowar_enabled", True)

    status_line = "🟢 <b>AKTIF</b>" if enabled else "🔴 <b>NONAKTIF</b>"
    text = (
        f"⏰ <b>Auto-War</b>\n\n"
        f"Status: {status_line}\n"
        f"🕐 Jadwal: <b>{wh:02d}:{wm:02d} {tz}</b>\n"
        f"🍪 Cookie: <b>{len(selected_ids)}</b>\n"
        f"🥊 Hero/cookie: <b>{hero_per}</b>\n"
        f"🔄 Total tembakan: <b>{len(selected_ids) * hero_per}</b>\n\n"
    )
    if enabled:
        text += "<i>Bot otomatis war tiap hari sesuai jadwal.</i>"
    else:
        text += "<i>Auto-war dimatikan. War cuma jalan via ⚔️ War Debug manual.</i>"

    toggle_label = "🔴 Matikan Auto-War" if enabled else "🟢 Aktifkan Auto-War"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data="menu:autowar_toggle")],
        [InlineKeyboardButton("⚙️ Edit Jadwal", callback_data="menu:config")],
        [back_button()],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def autowar_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Flip auto-war on/off then re-render the auto-war menu."""
    query = update.callback_query

    if not is_owner(update):
        await query.answer()
        return

    from src.war_config_service import set_autowar_enabled
    cfg = await cfg_dict()
    new_state = not cfg.get("autowar_enabled", True)
    async with AsyncSessionLocal() as session:
        await set_autowar_enabled(session, new_state)

    await query.answer("✅ Auto-war diaktifkan" if new_state else "🔴 Auto-war dimatikan", show_alert=False)
    await menu_autowar(update, context)
