"""KeWarMiBot — Proxy pool management. Single-owner."""
from src.bot.handlers._common import *


# ─── Pool Menu ───────────────────────────────────────────

async def pool_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_owner(update):
        return

    owner = settings.owner_chat_id
    async with AsyncSessionLocal() as s:
        stats = await pool_stats(s, owner)

    text = (
        f"🔌 <b>Pool Proxy</b>\n"
        f"{'─' * 28}\n"
        f"🟢 Tersedia: <b>{stats['unused']}</b>\n"
        f"🔴 Terpakai: <b>{stats['used']}</b>\n"
        f"📊 Total: <b>{stats['total']}</b>\n"
        f"{'─' * 28}\n"
        f"<i>Kirim proxy dlm format:</i>\n"
        f"<code>user:pass:host:port</code>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Tambah Proxy", callback_data="pool:add")],
        [InlineKeyboardButton("🗑️ Hapus Semua", callback_data="pool:clear")],
        [back_button()],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def pool_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route pool callbacks."""
    query = update.callback_query

    if not is_owner(update):
        await query.answer()
        return

    data = query.data

    if data == "pool:menu":
        await pool_menu(update, context)
    elif data == "pool:add":
        await query.answer()
        context.user_data["_input_mode"] = "pool_add"
        await query.edit_message_text(
            "➕ <b>Tambah Proxy</b>\n\n"
            "Kirim proxy dalam format (satu per baris):\n"
            "<code>user:pass:host:port</code>\n\n"
            "Contoh:\n"
            "<code>admin:12345:192.168.1.1:8080\n"
            "user2:pass2:proxy.example.com:3128</code>",
            parse_mode=ParseMode.HTML
        )
    elif data == "pool:clear":
        await query.answer()
        owner = settings.owner_chat_id
        async with AsyncSessionLocal() as s:
            deleted = await pool_clear_all(s, owner)
        await query.answer(f"✅ {deleted} proxy dihapus!", show_alert=True)
        await pool_menu(update, context)


async def pool_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle proxy text input."""
    if not is_owner(update):
        return

    text = update.message.text.strip()
    lines = [line.strip() for line in text.split("\n") if line.strip() and not line.startswith("/")]
    if not lines:
        await update.message.reply_text("❌ Kirim proxy dlm format:\n<code>user:pass:host:port</code>", parse_mode=ParseMode.HTML)
        return

    owner = settings.owner_chat_id
    async with AsyncSessionLocal() as session:
        result = await pool_add(session, owner, lines)
    context.user_data.pop("_input_mode", None)
    await update.message.reply_text(
        f"✅ <b>{result['added']}</b> proxy ditambahkan!\n❌ {result['skipped']} duplikat.",
        parse_mode=ParseMode.HTML
    )
