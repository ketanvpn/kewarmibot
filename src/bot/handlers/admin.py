"""KeWarMiBot — Admin panel: users, packages, settings, revenue"""
import asyncio
import datetime
import json
import logging
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters,
)
from telegram.constants import ParseMode

from src.config import settings
from src.db import AsyncSessionLocal, CookieModel, LatencyLogModel, WarHistoryModel
from sqlalchemy import select
from src.cookie_service import (
    add_cookie, list_cookies, get_cookie, get_cookie_token,
    delete_cookie, refresh_cookie_status, status_label
)
from src.war_config_service import load_config, save_config, MAX_COOKIES_PER_WAR, recommended_hero
from src.engine.api import measure_latency
from src.engine.war import run_war_sync, WarConfig, WarResultReport, get_next_beijing_midnight_ms
from src.user_service import (
    get_or_create_user, get_user, add_balance, deduct_balance,
    add_tickets, get_user_by_id, toggle_war_enabled
)
from src.package_service import list_packages, get_package, create_order, list_user_orders, set_payment_url, update_package, revenue_today
from src.settings_service import get_setting, set_setting, get_payment_config
from src.proxy_pool_service import pool_stats, pool_add, pool_allocate, pool_consume_batch, pool_clear_all, pool_get_all
from src.scheduler_jobs import scheduler as _sj_scheduler, _notifier

logger = logging.getLogger(__name__)

# ─── Global state (set from main.py) ────────────────────
_bot = None

def set_bot_instance(bot):
    """Store bot instance for direct message sending."""
    global _bot
    _bot = bot

# ─── Helpers ───────────────────────────────────────────

def _owner(update: Update) -> str:
    return str(update.effective_chat.id)

async def _cfg_dict(update: Update) -> dict:
    oid = _owner(update)
    async with AsyncSessionLocal() as session:
        return await load_config(session, oid)

async def _cookies(update: Update):
    async with AsyncSessionLocal() as session:
        return await list_cookies(session, _owner(update))

async def _build_main_kb(update: Update) -> InlineKeyboardMarkup:
    oid = _owner(update)
    async with AsyncSessionLocal() as session:
        user = await get_user(session, oid)
        bal = user.balance_war if user else 0
        w_enabled = user.war_enabled if user else True

    toggle_text = "🟢 ON" if w_enabled else "🔴 OFF"
    buttons = [
        [InlineKeyboardButton("🍪 Cookie Saya", callback_data="menu:cookies"),
         InlineKeyboardButton("🎫 Beli Tiket War", callback_data="menu:beli")],
        [InlineKeyboardButton("⚔️ War Now", callback_data="menu:war_debug"),
         InlineKeyboardButton("⚙️ War Config", callback_data="menu:config")],
        [InlineKeyboardButton("📊 Dashboard", callback_data="menu:status"),
         InlineKeyboardButton(f"⏰ Auto-War: {{toggle_text}}", callback_data="menu:autowar")],
        [InlineKeyboardButton("📜 Riwayat War", callback_data="menu:history"),
         InlineKeyboardButton("📈 Statistik Cookie", callback_data="menu:stats")],
        [InlineKeyboardButton("👤 Profil", callback_data="menu:profile"),
         InlineKeyboardButton("📖 Panduan", callback_data="menu:guide")],
    ]
    if str(update.effective_chat.id) in settings.admin_ids:
        buttons.append([InlineKeyboardButton("🛡️ Admin Panel", callback_data="menu:admin")])
    buttons.append([InlineKeyboardButton("💬 Support", callback_data="menu:support")])
    return InlineKeyboardMarkup(buttons)

# State for ConversationHandler
WAIT_COOKIE_NAME, WAIT_COOKIE_TOKEN = range(2)


# ─── Admin Panel ─────────────────────────────────────

async def menu_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    oid = _owner(update)

    if oid not in {str(x) for x in settings.admin_ids} and oid != "690744680":
        await query.edit_message_text("⛔ Akses ditolak.")
        return

    async with AsyncSessionLocal() as session:
        from src.user_service import user_count as uc
        from src.package_service import revenue_today as rt
        total_users = await uc(session)
        revenue = await rt(session)

    text = f"🔰 <b>Admin Panel</b>\n{'─' * 28}\n👥 👥 User: <b>{total_users}</b>\n Hari Ini: <b>Rp {revenue:,}</b>"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ War Config", callback_data="menu:config")],
        [InlineKeyboardButton("⏰ Auto-War", callback_data="menu:autowar")],
        [
            InlineKeyboardButton("📊 Status", callback_data="menu:status"),
            InlineKeyboardButton("💳 Payment", callback_data="admin:settings"),
        ],
        [InlineKeyboardButton("👥 Kelola User", callback_data="admin:users")],
        [
            InlineKeyboardButton("📦 Paket", callback_data="admin:packages"),
            InlineKeyboardButton("🔌 Pool", callback_data="pool:menu"),
        ],
        [
            InlineKeyboardButton("📊 Revenue", callback_data="admin:revenue"),
            InlineKeyboardButton("« Menu", callback_data="menu:main"),
        ],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ─── Admin: User Management ──────────────────────────

async def admin_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    async with AsyncSessionLocal() as session:
        from src.user_service import list_users
        users = await list_users(session, limit=10)

    if not users:
        await query.edit_message_text("👥 Belum ada user.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="menu:admin")]]))
        return

    lines = ["👥 <b>Klik User untuk detail</b>"]
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
    text = f"👤 <b>{user.first_name or user.username or user.telegram_id}</b>\n{'─' * 28}\n🆔 <code>{user.telegram_id}</code>\n📛 {st}\n🎫 Tiket: <b>{user.balance_war}</b>\n⚔️ Total War: <b>{user.total_wars}</b>\n🎫 Tiket: <b>{user.total_tickets}</b>"

    if orders:
        text += f"\n\n<b>Order Terakhir:</b>"
        for o in orders[:3]:
            s = "✅" if o.status == "paid" else "⏳"
            text += f"\n  {s} {o.order_ref} — Rp {o.amount_idr:,}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Topup +5 War", callback_data=f"admin:topup:{uid}:5")],
        [InlineKeyboardButton("➕ Topup +10 War", callback_data=f"admin:topup:{uid}:10")],
        [InlineKeyboardButton("➕ Topup +50 War", callback_data=f"admin:topup:{uid}:50")],
        [InlineKeyboardButton("⛔ Suspend" if not user.is_suspended else "✅ Unsuspend", callback_data=f"admin:topup:{uid}:toggle")],
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

    lines = ["📦 <b>Kelola Paket Tiket War</b>"]
    kb_rows = []
    for p in pkgs:
        s = "🟢" if p.is_active else "🔴"
        lines.append(f"{s} <b>{p.name}</b> — {p.war_count} tiket @ Rp {p.price_idr:,}")
        kb_rows.append([InlineKeyboardButton(
            f"✏️ {p.name}",
            callback_data=f"admin:pkg:edit:{p.id}"
        )])
    kb_rows.append([InlineKeyboardButton("« Kembali", callback_data="menu:admin")])

    text = "\n".join(lines) + "\n\n<i>Klik ✏️ untuk edit nama, tiket, harga.</i>"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=ParseMode.HTML)

async def admin_pkg_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detail edit form: nama, harga, tiket, toggle."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    pkg_id = int(parts[-1])

    async with AsyncSessionLocal() as session:
        pkg = await get_package(session, pkg_id)

    if not pkg:
        await query.edit_message_text("❌ Paket tidak ditemukan.")
        return

    s = "🟢 AKTIF" if pkg.is_active else "🔴 NONAKTIF"
    text = (
        f"✏️ <b>Edit Paket</b>\n"
        f"{'─' * 28}\n"
        f"📛 Nama: <b>{pkg.name}</b>\n"
        f"🎫 Tiket: <b>{pkg.war_count}</b> (1 tiket = 1x war)\n"
        f"💰 Harga: <b>Rp {pkg.price_idr:,}</b>\n"
        f"📊 Status: <b>{s}</b>\n"
        f"{'─' * 28}\n"
        f"<i>Klik tombol di bawah untuk edit.</i>"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📛 Edit Nama", callback_data=f"admin:pkg:name:{pkg_id}")],
        [InlineKeyboardButton("🎫 Edit Tiket", callback_data=f"admin:pkg:war:{pkg_id}")],
        [InlineKeyboardButton("💰 Edit Harga", callback_data=f"admin:pkg:price:{pkg_id}")],
        [
            InlineKeyboardButton(
                "🔴 Nonaktifkan" if pkg.is_active else "🟢 Aktifkan",
                callback_data=f"admin:pkg:toggle:{pkg_id}"
            )
        ],
        [InlineKeyboardButton("« Kembali", callback_data="admin:packages")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def admin_pkg_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt user to enter new value for a package field."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    field = parts[2]  # name, war, price, toggle
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

    # Store pending edit in user_data
    context.user_data["editing_pkg"] = {"id": pkg_id, "field": field}
    labels = {"name": "Nama Paket", "war": "Jumlah Tiket (1 tiket = 1x war)", "price": "Harga (Rp)"}
    label = labels.get(field, field)

    await query.edit_message_text(
        f"✏️ <b>Edit {label}</b>\n\n"
        f"<i>Kirim value baru sekarang.</i>\n"
        f"<code>/cancel</code> untuk batal.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("« Batal", callback_data=f"admin:pkg:edit:{pkg_id}")
        ]])
    )

async def admin_pkg_edit_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save edited package field value."""
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
            await update.message.reply_text("❌ Format angka salah. Coba lagi.", parse_mode=ParseMode.HTML)


# ─── Admin: Settings ─────────────────────────────────

async def admin_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    async with AsyncSessionLocal() as session:
        cfg = await get_payment_config(session)

    mask = lambda v: v[:8] + "•••" if v and len(v) > 10 else (v or "(kosong)")
    text = f"💳 <b>Payment Settings</b>\n{'─' * 28}\n🔗 URL: <code>{cfg['base_url'][:40]}</code>\n🔑 Key: <code>{mask(cfg['client_key'])}</code>\n🔐 Secret: <code>{mask(cfg['webhook_secret'])}</code>\n🌐 Webhook: <code>{cfg['webhook_base'][:40]}</code>\n{'─' * 28}\n<i>Klik untuk edit.</i>"

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

    labels = {"payment_base_url": "Base URL", "payment_client_key": "Client Key", "payment_webhook_secret": "Webhook Secret", "webhook_base_url": "Webhook Base URL"}
    label = labels.get(key, key)

    await query.edit_message_text(f"✏️ <b>Edit {label}</b>\n\n<i>Kirim value baru.</i>\n<code>/cancel</code> batal.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Batal", callback_data="admin:settings")]]))


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

    text = f"📊 <b>Revenue</b>\n{'─' * 28}\n👥 👥 User: <b>{users}</b>\n📦 Order Sukses: <b>{total_paid}</b>\n{'─' * 28}\n📅 Hari Ini: <b>Rp {today:,}</b>\n💰 Total: <b>Rp {total:,}</b>"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="menu:admin")]])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ─── Text Input Handler ─────────────────────────────

async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unified text input: settings edit, package edit, or proxy add."""
    key = context.user_data.get("editing_setting")
    pkg = context.user_data.get("editing_pkg")
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

    labels = {"payment_base_url": "Base URL", "payment_client_key": "Client Key", "payment_webhook_secret": "Webhook Secret", "webhook_base_url": "Webhook Base URL"}
    await update.message.reply_text(f"✅ <b>{labels.get(key, key)}</b> tersimpan!", parse_mode=ParseMode.HTML)
