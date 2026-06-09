"""KeWarMiBot — Package browsing, purchase, payment"""
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


# ─── Beli Paket ───────────────────────────────────────

async def menu_beli(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    oid = _owner(update)

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
    oid = _owner(update)
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
