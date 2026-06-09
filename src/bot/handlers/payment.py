"""KeWarMiBot — Package browsing, purchase, payment"""
from src.bot.handlers._common import *

# ─── Beli Paket ───────────────────────────────────────

async def menu_beli(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    oid = owner_id(update)

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, oid,
            update.effective_chat.username, update.effective_chat.first_name)
        pkgs = await list_packages(session)

    text = f"🛒 <b>Beli Slot War</b>\n{'─' * 28}\n🎫 Tiket: <b>{user.balance_war}</b>\n\n1 tiket = 1x auto-war\n\nPilih paket:"

    kb = []
    for p in pkgs:
        kb.append([InlineKeyboardButton(
            f"{p.name} — Rp {p.price_idr:,}",
            callback_data=f"beli:pkg:{p.id}"
        )])
    kb.append([InlineKeyboardButton("« Kembali", callback_data="menu:main")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def menu_beli_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    oid = owner_id(update)
    data = query.data

    try:
        pkg_id = int(data.split(":")[-1])
    except (ValueError, IndexError):
        await query.edit_message_text("❌ Paket tidak valid.", parse_mode=ParseMode.HTML)
        return

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, oid,
            update.effective_chat.username, update.effective_chat.first_name)
        pkg = await get_package(session, pkg_id)
        if not pkg:
            await query.edit_message_text("❌ Paket tidak ditemukan.")
            return
        order = await create_order(session, user.id, pkg.id)

    try:
        from src.payment_service import create_payment_order, CreateOrderRequest
        req = CreateOrderRequest(
            order_ref=order.order_ref, amount=pkg.price_idr,
            customer_name=user.first_name or "User", expiry_minutes=15)
        payment = await create_payment_order(req)
        async with AsyncSessionLocal() as session:
            from src.package_service import set_payment_url
            await set_payment_url(session, order.order_ref, payment.payment_url)
        payment_url = payment.payment_url
    except Exception as e:
        logger.error(f"Payment failed: {e}")
        payment_url = None

    if payment_url:
        text = f"🎫 <b>Pembayaran Tiket War</b>\n{'─' * 28}\n📦 {pkg.name}\n💰 <b>Rp {pkg.price_idr:,}</b>\n⏱️ <i>15 menit</i>\n{'─' * 28}\n📱 <b>Buka link bayar:</b>"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Buka QRIS", url=payment_url)],
            [InlineKeyboardButton("« Kembali", callback_data="menu:beli")],
        ])
    else:
        text = f"🎫 <b>Pembayaran Tiket War</b>\n{'─' * 28}\n📦 {pkg.name}\n💰 <b>Rp {pkg.price_idr:,}</b>\n📋 <code>{order.order_ref}</code>\n{'─' * 28}\n⚠️ <i>Gateway offline. Hubungi admin.</i>"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="menu:beli")]])

    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
