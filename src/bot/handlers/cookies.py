"""KeWarMiBot — Cookie CRUD & ConversationHandler"""
from src.bot.handlers._common import *

# ─── Cookie Management ─────────────────────────────────

async def menu_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    cookies = await cookies_list(update)

    if not cookies:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Tambah Cookie", callback_data="cookie:add")],
            [back_button(update, context)],
        ])
        await query.edit_message_text("🍪 <b>Belum ada cookie</b>\n\nTambah cookie untuk mulai war.", reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    lines = ["🍪 <b>Kelola Cookies</b>\n"]
    kb_rows = []
    for c in cookies:
        emoji, status = status_label(c)
        lines.append(f"{emoji} <b>{c.name}</b> — {status}")
        kb_rows.append([
            InlineKeyboardButton(c.name, callback_data=f"cookie:detail:{c.id}"),
            InlineKeyboardButton("🗑", callback_data=f"cookie:delete_confirm:{c.id}"),
        ])
    kb_rows.append([InlineKeyboardButton("🔄 Refresh Semua Cookie", callback_data="cookie:refresh_all")])
    kb_rows.append([InlineKeyboardButton("➕ Tambah Cookie", callback_data="cookie:add")])
    kb_rows.append([back_button(update, context)])

    await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=ParseMode.HTML)


async def cookie_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📝 Masukkan <b>nama</b> untuk cookie ini (misal: \"Punya Andi\"):\n\nKetik /cancel untuk batal.",
        parse_mode=ParseMode.HTML,
    )
    return WAIT_COOKIE_NAME


async def cookie_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["cookie_name"] = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass
    await update.message.reply_text(
        f"✅ Nama: <b>{context.user_data['cookie_name']}</b>\n\nSekarang kirim <b>cookie token</b>-nya (paste langsung):\n\n⚠️ Token akan dienkripsi. /cancel untuk batal.",
        parse_mode=ParseMode.HTML,
    )
    return WAIT_COOKIE_TOKEN


async def cookie_add_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    token = update.message.text.strip()
    name = context.user_data.pop("cookie_name", "Unnamed")
    try:
        await update.message.delete()
    except Exception:
        pass

    async with AsyncSessionLocal() as session:
        cookie = await add_cookie(session, name, token, owner_id(update))

    emoji, status = status_label(cookie)
    await update.message.reply_text(f"🍪 Cookie tersimpan!\n\n<b>{name}</b>: {emoji} {status}", parse_mode=ParseMode.HTML)
    await main_menu(update, context)
    return ConversationHandler.END


async def cookie_add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Batal.")
    await main_menu(update, context)
    return ConversationHandler.END


async def cookie_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    cid = int(query.data.split(":")[-1])

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        r = await session.execute(select(CookieModel).where(CookieModel.id == cid, CookieModel.owner_chat_id == owner_id(update)))
        cookie = r.scalar_one_or_none()

    if not cookie:
        await query.edit_message_text("❌ Cookie tidak ditemukan.")
        return

    emoji, status = status_label(cookie)
    last_check = cookie.last_checked.strftime("%Y-%m-%d %H:%M:%S") if cookie.last_checked else "never"
    text = (
        f"🍪 <b>{cookie.name}</b>\n\n{emoji} Status: {status}\n"
        f"🕐 Terakhir dicek: {last_check}\n📅 Dibuat: {cookie.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh Status", callback_data=f"cookie:refresh:{cid}")],
        [InlineKeyboardButton("🗑 Hapus Cookie", callback_data=f"cookie:delete_confirm:{cid}")],
        [InlineKeyboardButton("« Kembali", callback_data="menu:cookies")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def cookie_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    cid = int(query.data.split(":")[-1])
    async with AsyncSessionLocal() as session:
        cookie = await refresh_cookie_status(session, cid, owner_id(update))
    if not cookie:
        await query.edit_message_text("❌ Cookie tidak ditemukan.")
        return
    emoji, status = status_label(cookie)
    await query.edit_message_text(f"🔄 Status diperbarui!\n\n<b>{cookie.name}</b>: {emoji} {status}", parse_mode=ParseMode.HTML)

async def cookie_refresh_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Refresh status semua cookie sekaligus."""
    query = update.callback_query
    await query.answer()
    cookies = await cookies_list(update)

    if not cookies:
        await query.edit_message_text("🍪 <b>Belum ada cookie.</b>", parse_mode=ParseMode.HTML)
        return

    await query.edit_message_text(f"🔄 <b>Refresh {len(cookies)} cookie...</b>\n\nMohon tunggu...", parse_mode=ParseMode.HTML)

    ok, fail = 0, 0
    lines = ["🔄 <b>Refresh Semua Cookie</b>\n"]
    async with AsyncSessionLocal() as session:
        for c in cookies:
            try:
                await refresh_cookie_status(session, c.id, owner_id(update))
                ok += 1
                lines.append(f"✅ {c.name}")
            except Exception as e:
                fail += 1
                lines.append(f"❌ {c.name}: {e}")
        await session.commit()

    lines.append(f"\n✅ {ok} berhasil • ❌ {fail} gagal")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali ke Cookies", callback_data="menu:cookies")]])
    await query.message.reply_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML)


async def cookie_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    cid = int(query.data.split(":")[-1])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Ya, hapus", callback_data=f"cookie:delete:{cid}"),
         InlineKeyboardButton("❌ Batal", callback_data="menu:cookies")],
    ])
    await query.edit_message_text("⚠️ Yakin mau hapus cookie ini? Token akan dihapus permanen.", reply_markup=kb)


async def cookie_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    cid = int(query.data.split(":")[-1])
    async with AsyncSessionLocal() as session:
        deleted = await delete_cookie(session, cid, owner_id(update))
    await query.edit_message_text("🗑 Cookie dihapus." if deleted else "❌ Gagal menghapus.")
    await asyncio.sleep(0.5)
    await main_menu(update, context)

