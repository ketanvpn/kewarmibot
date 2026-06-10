"""KeWarMiBot — Proxy pool management"""
from src.bot.handlers._common import *

# ─── Pool Router ─────────────────────────────────────────

async def pool_handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle proxy pool text input or message."""
    if not is_admin_update(update):
        if update.callback_query:
            await update.callback_query.edit_message_text("⛔ Akses ditolak — admin only.", parse_mode=ParseMode.HTML)
        return

    # Jika ini callback → route ke _pool_router
    # Jika ini text input → parse proxy URL
    if update.callback_query:
        # Strip @admin suffix kalau ada
        data = update.callback_query.data
        if data.endswith("@admin"):
            data = data[:-6]
            context.user_data["_nav_admin"] = True
        return await _pool_router(update, context, data)
    elif update.message and update.message.text:
        text = update.message.text.strip()
        lines = [line.strip() for line in text.split("\n") if line.strip() and not line.startswith("/")]
        if not lines:
            await update.message.reply_text("❌ Kirim proxy dlm format:\n<code>user:pass:host:port</code>", parse_mode=ParseMode.HTML)
            return
        oid = owner_id(update)
        async with AsyncSessionLocal() as session:
            result = await pool_add(session, oid, lines)
        await update.message.reply_text(
            f"✅ <b>{result['added']}</b> proxy ditambahkan!\n❌ {result['skipped']} duplikat.",
            parse_mode=ParseMode.HTML
        )

async def _pool_router(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Proxy pool menu router."""
    query = update.callback_query
    oid = owner_id(update)

    if data == "pool:menu":
        context.user_data.setdefault("_nav_admin", True)
        async with AsyncSessionLocal() as s:
            stats = await pool_stats(s, oid)
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
            [InlineKeyboardButton("« Kembali", callback_data="menu:admin")],
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    elif data == "pool:add":
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
        async with AsyncSessionLocal() as s:
            deleted = await pool_clear_all(s, oid)
        await query.answer(f"✅ {deleted} proxy dihapus!", show_alert=True)
        query.data = "pool:menu"
        await _pool_router(update, context)
    else:
        await query.edit_message_text("❌ Unknown pool action.")
