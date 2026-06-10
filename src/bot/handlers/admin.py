"""KeWarMiBot — Admin panel: users, packages, settings, revenue"""
from src.bot.handlers._common import *

# ─── Admin Dashboard (callback & /admin command) ────────

async def menu_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback menu:admin — show admin dashboard inline."""
    query = update.callback_query
    await query.answer()
    if not is_admin_update(update):
        await query.edit_message_text("⛔ Akses ditolak — admin only.", parse_mode=ParseMode.HTML)
        return

    set_nav_admin(context, True)  # Ensure admin nav context
    text, kb = await admin_dashboard_text()
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ─── Admin: User Management ──────────────────────────

async def admin_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    async with AsyncSessionLocal() as session:
        from src.user_service import list_users
        users = await list_users(session, limit=10)

    if not users:
        await query.edit_message_text("👥 Belum ada user.", reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("« Kembali", callback_data="menu:admin")
        ]]))
        return

    lines = ["👥 <b>Kelola User</b>", f"{SEP}"]
    kb_rows = []
    for u in users:
        s = "⛔" if u.is_suspended else "✅"
        kb_rows.append([InlineKeyboardButton(
            f"{s} {u.first_name or u.username or u.telegram_id} (🎫{u.balance_war})",
            callback_data=f"admin:user:{u.id}"
        )])
    kb_rows.append([InlineKeyboardButton("« Kembali", callback_data="menu:admin")])
    text = "\n".join(lines) + "\n\n<i>Klik user untuk topup/suspend.</i>"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=ParseMode.HTML)


async def admin_user_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid = int(query.data.split(":")[-1])
    async with AsyncSessionLocal() as session:
        from src.user_service import get_user_by_id
        from src.package_service import list_user_orders
        user = await get_user_by_id(session, uid)
        orders = await list_user_orders(session, uid, 5)
    if not user:
        await query.edit_message_text("❌ User tidak ditemukan.")
        return

    st = "⛔ SUSPENDED" if user.is_suspended else "✅ Aktif"
    text = (
        f"👤 <b>{user.first_name or user.username or user.telegram_id}</b>\n"
        f"{SEP}\n"
        f"🆔 <code>{user.telegram_id}</code>\n"
        f"📛 Status: {st}\n"
        f"🎫 Tiket: <b>{user.balance_war}</b>\n"
        f"⚔️ Total War: <b>{getattr(user, 'total_wars', 0)}</b>\n"
        f"🎫 Sukses: <b>{getattr(user, 'total_tickets', 0)}</b>"
    )
    if orders:
        text += "\n\n<b>Order Terakhir:</b>"
        for o in orders[:3]:
            s = "✅" if o.status == "paid" else "⏳"
            text += f"\n  {s} {o.order_ref} — Rp {o.amount_idr:,}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Topup +5 War", callback_data=f"admin:topup:{uid}:5")],
        [InlineKeyboardButton("➕ Topup +10 War", callback_data=f"admin:topup:{uid}:10")],
        [InlineKeyboardButton("➕ Topup +50 War", callback_data=f"admin:topup:{uid}:50")],
        [InlineKeyboardButton(
            "⛔ Suspend" if not user.is_suspended else "✅ Unsuspend",
            callback_data=f"admin:topup:{uid}:toggle"
        )],
        [InlineKeyboardButton("« User List", callback_data="admin:users")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def admin_user_topup_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    uid = int(parts[2])
    action = parts[3]
    async with AsyncSessionLocal() as session:
        from src.user_service import get_user_by_id, add_balance, set_suspended
        if action == "toggle":
            user = await get_user_by_id(session, uid)
            await set_suspended(session, uid, not user.is_suspended)
            await query.answer(f"User {'disuspend' if not user.is_suspended else 'diaktifkan'}!", show_alert=True)
        else:
            amount = int(action)
            new_balance = await add_balance(session, uid, amount)
            await query.answer(f"✅ +{amount} tiket → saldo {new_balance}", show_alert=True)
    query.data = f"admin:user:{uid}"
    await admin_user_detail(update, context)


# ─── Admin: Packages ─────────────────────────────────

async def admin_packages_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    async with AsyncSessionLocal() as session:
        pkgs = await list_packages(session, active_only=False)
    lines = ["📦 <b>Kelola Paket</b>", f"{SEP}"]
    kb_rows = []
    for p in pkgs:
        s = "🟢" if p.is_active else "🔴"
        lines.append(f"{s} <b>{p.name}</b> — {p.war_count} tiket @ Rp {p.price_idr:,}")
        kb_rows.append([InlineKeyboardButton(f"✏️ {p.name}", callback_data=f"admin:pkg:edit:{p.id}")])
    kb_rows.append([InlineKeyboardButton("« Kembali", callback_data="menu:admin")])
    text = "\n".join(lines) + "\n\n<i>Klik ✏️ untuk edit.</i>"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=ParseMode.HTML)


async def admin_pkg_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    pkg_id = int(query.data.split(":")[-1])
    async with AsyncSessionLocal() as session:
        pkg = await get_package(session, pkg_id)
    if not pkg:
        await query.edit_message_text("❌ Paket tidak ditemukan.")
        return
    s = "🟢 AKTIF" if pkg.is_active else "🔴 NONAKTIF"
    text = (
        f"✏️ <b>Edit Paket</b>\n"
        f"{SEP}\n"
        f"📛 Nama: <b>{pkg.name}</b>\n"
        f"🎫 Tiket: <b>{pkg.war_count}</b> (1 tiket = 1x war)\n"
        f"💰 Harga: <b>Rp {pkg.price_idr:,}</b>\n"
        f"📊 Status: <b>{s}</b>\n"
        f"{SEP}\n"
        f"<i>Klik tombol untuk edit.</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📛 Edit Nama", callback_data=f"admin:pkg:name:{pkg_id}")],
        [InlineKeyboardButton("🎫 Edit Tiket", callback_data=f"admin:pkg:war:{pkg_id}")],
        [InlineKeyboardButton("💰 Edit Harga", callback_data=f"admin:pkg:price:{pkg_id}")],
        [InlineKeyboardButton(
            "🔴 Nonaktifkan" if pkg.is_active else "🟢 Aktifkan",
            callback_data=f"admin:pkg:toggle:{pkg_id}"
        )],
        [InlineKeyboardButton("« Kembali", callback_data="admin:packages")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def admin_pkg_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    field = parts[2]
    pkg_id = int(parts[3])
    if field == "toggle":
        async with AsyncSessionLocal() as session:
            pkg = await get_package(session, pkg_id)
            if pkg:
                await update_package(session, pkg_id, is_active=not pkg.is_active)
                await query.answer(f"Paket {'dinonaktifkan' if pkg.is_active else 'diaktifkan'}!", show_alert=True)
        query.data = f"admin:pkg:edit:{pkg_id}"
        await admin_pkg_edit(update, context)
        return
    labels = {"name": "Nama Paket", "war": "Jumlah Tiket (1 tiket = 1x war)", "price": "Harga (Rp)"}
    context.user_data["editing_pkg"] = {"id": pkg_id, "field": field}
    await query.edit_message_text(
        f"✏️ <b>Edit {labels.get(field, field)}</b>\n\n"
        f"<i>Kirim value baru sekarang.</i>\n"
        f"<code>/cancel</code> untuk batal.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("« Batal", callback_data=f"admin:pkg:edit:{pkg_id}")
        ]])
    )


async def admin_pkg_edit_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pending = context.user_data.get("editing_pkg")
    if not pending:
        return
    pkg_id = pending["id"]
    field = pending["field"]
    raw = update.message.text.strip()
    context.user_data.pop("editing_pkg", None)
    async with AsyncSessionLocal() as session:
        pkg = await get_package(session, pkg_id)
        if not pkg:
            await update.message.reply_text("❌ Paket tidak ditemukan.", parse_mode=ParseMode.HTML)
            return
        try:
            if field == "name":
                pkg.name = raw
            elif field == "war":
                pkg.war_count = int(raw)
            elif field == "price":
                pkg.price_idr = int(raw)
            await session.commit()
            labels = {"name": "Nama", "war": "Tiket", "price": "Harga"}
            await update.message.reply_text(
                f"✅ <b>{labels[field]}</b> paket <b>{pkg.name}</b> diupdate!",
                parse_mode=ParseMode.HTML
            )
        except ValueError:
            await update.message.reply_text("❌ Format angka salah.", parse_mode=ParseMode.HTML)


# ─── Admin: Settings ─────────────────────────────────

async def admin_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    async with AsyncSessionLocal() as session:
        cfg = await get_payment_config(session)

    def mask(value: str | None) -> str:
        return value[:8] + "•••" if value and len(value) > 10 else (value or "(kosong)")

    text = (
        f"💳 <b>Payment Settings</b>\n"
        f"{SEP}\n"
        f"🔗 URL: <code>{cfg['base_url'][:40]}</code>\n"
        f"🔑 Key: <code>{mask(cfg['client_key'])}</code>\n"
        f"🔐 Secret: <code>{mask(cfg['webhook_secret'])}</code>\n"
        f"🌐 Webhook: <code>{cfg['webhook_base'][:40]}</code>\n"
        f"{SEP}\n"
        f"<i>Klik untuk edit.</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Edit Base URL", callback_data="admin:setting:payment_base_url")],
        [InlineKeyboardButton("🔑 Edit Client Key", callback_data="admin:setting:payment_client_key")],
        [InlineKeyboardButton("🔐 Edit Webhook Secret", callback_data="admin:setting:payment_webhook_secret")],
        [InlineKeyboardButton("🌐 Edit Webhook Base", callback_data="admin:setting:webhook_base_url")],
        [InlineKeyboardButton("« Kembali", callback_data="menu:admin")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def admin_setting_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    key = query.data.replace("admin:setting:", "")
    context.user_data["editing_setting"] = key
    labels = {
        "payment_base_url": "Base URL",
        "payment_client_key": "Client Key",
        "payment_webhook_secret": "Webhook Secret",
        "webhook_base_url": "Webhook Base URL",
    }
    await query.edit_message_text(
        f"✏️ <b>Edit {labels.get(key, key)}</b>\n\n"
        f"<i>Kirim value baru.</i>\n"
        f"<code>/cancel</code> batal.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("« Batal", callback_data="admin:settings")
        ]])
    )


# ─── Admin: Revenue ─────────────────────────────────

async def admin_revenue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    async with AsyncSessionLocal() as session:
        from src.package_service import revenue_total, revenue_today
        from src.user_service import user_count as uc
        from sqlalchemy import select, func
        from src.db import OrderModel
        total = await revenue_total(session)
        today = await revenue_today(session)
        users = await uc(session)
        r = await session.execute(select(func.count(OrderModel.id)).where(OrderModel.status == "paid"))
        total_paid = r.scalar()
    text = (
        f"📊 <b>Revenue Report</b>\n"
        f"{SEP}\n"
        f"👥 User: <b>{users}</b>\n"
        f"📦 Order Sukses: <b>{total_paid}</b>\n"
        f"{SEP}\n"
        f"📅 Hari Ini: <b>Rp {today:,}</b>\n"
        f"💰 Total: <b>Rp {total:,}</b>"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="menu:admin")]])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ─── Text Input Handler ─────────────────────────────

async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    key = context.user_data.get("editing_setting")
    pkg = context.user_data.get("editing_pkg")
    if not is_admin_update(update):
        context.user_data.pop("editing_setting", None)
        context.user_data.pop("editing_pkg", None)
        return

    if key:
        await settings_edit_save(update, context)
    elif pkg:
        await admin_pkg_edit_save(update, context)
    else:
        await pool_handle_text(update, context)


async def settings_edit_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    key = context.user_data.get("editing_setting")
    if not key:
        return
    value = update.message.text.strip()
    async with AsyncSessionLocal() as session:
        await set_setting(session, key, value)
    context.user_data.pop("editing_setting", None)
    labels = {
        "payment_base_url": "Base URL",
        "payment_client_key": "Client Key",
        "payment_webhook_secret": "Webhook Secret",
        "webhook_base_url": "Webhook Base URL",
    }
    await update.message.reply_text(
        f"✅ <b>{labels.get(key, key)}</b> tersimpan!",
        parse_mode=ParseMode.HTML
    )
