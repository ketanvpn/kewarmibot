"""KeWarMiBot — Debug war, auto-war toggle, run-now"""
from src.bot.handlers._common import *

# ─── War Now ───────────────────────────────────────────

async def war_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    oid = owner_id(update)

    from src.engine.war_runner import execute_war

    back = "menu:admin" if context.user_data.get("_nav_admin") else "menu:main"

    async def _notify(chat_id: str, msg: str):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Menu Utama", callback_data=back)]])
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
    oid = owner_id(update)

    is_admin = get_nav_admin(context)

    if is_admin:
        await _menu_autowar_admin(update, context)
        return

    # ─── User: partisipasi personal ───
    async with AsyncSessionLocal() as session:
        user = await get_user(session, oid)
        enabled = user.war_enabled if user else True

    status_text = "🟢 IKUT WAR" if enabled else "💤 TIDAK IKUT"
    text = (
        f"⚔️ <b>Partisipasi War</b>\n\n"
        f"Status: {status_text}\n\n"
        f"Saat aktif, bot akan menjalankan war otomatis\n"
        f"pakai cookie kamu tiap malam saat jadwal.\n\n"
        f"<i>Matikan jika kamu tidak ingin ikut war\n"
        f"sementara (tiket tetap aman).</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💤 Tidak Ikut" if enabled else "⚔️ Ikut War", callback_data="autowar:toggle")],
        [back_button(update, context)],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def _menu_autowar_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin view — global scheduler status + stats."""
    query = update.callback_query

    cfg = await cfg_dict(update)
    wh = cfg.get("war_hour", 0)
    wm = cfg.get("war_minute", 0)
    tz = cfg.get("war_tz", "Asia/Shanghai")

    from src.db import UserModel
    from sqlalchemy import select, func
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(func.count()).select_from(UserModel).where(UserModel.war_enabled == True)
        )
        active_count = r.scalar() or 0
        r = await session.execute(
            select(func.count()).select_from(UserModel)
        )
        total = r.scalar() or 0

    text = (
        f"⏰ <b>Auto-War Scheduler</b>\n\n"
        f"🕐 Jadwal: <b>{wh:02d}:{wm:02d} {tz}</b>\n"
        f"👥 Partisipasi: <b>{active_count}/{total}</b> user ikut war\n\n"
        f"<i>User bisa atur partisipasi personal lewat\n"
        f"menu ⚔️ Ikut War di dashboard masing-masing.</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Edit Jadwal", callback_data="menu:config@admin")],
        [back_button(update, context)],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def autowar_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    oid = owner_id(update)
    async with AsyncSessionLocal() as session:
        new_state = await toggle_war_enabled(session, oid)
    if new_state:
        await query.answer("⚔️ Kamu akan ikut war malam ini!", show_alert=True)
    else:
        await query.answer("💤 Kamu tidak ikut war malam ini. Tiket tetap aman.", show_alert=True)
    await menu_autowar(update, context)

async def autowar_run_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manual trigger real war (not debug)."""
    query = update.callback_query
    await query.answer()
    oid = owner_id(update)

    from src.engine.war_runner import execute_war
    back = "menu:admin" if context.user_data.get("_nav_admin") else "menu:main"

    async def _notify(chat_id: str, msg: str):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Menu Utama", callback_data=back)]])
        try:
            await query.message.reply_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"autowar_run_now notify failed: {e}")

    await query.edit_message_text("⚔️ <b>WAR DIMULAI</b>\n\nMenunggu hasil...", parse_mode=ParseMode.HTML)
    await execute_war(oid, debug=False, deduct=False, notify=_notify)