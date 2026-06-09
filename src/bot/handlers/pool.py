"""KeWarMiBot — Proxy pool management"""
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


# ─── Pool Router ─────────────────────────────────────────

async def pool_handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle proxy pool text input or message."""
    # Jika ini callback → route ke _pool_router
    # Jika ini text input → parse proxy URL
    if update.callback_query:
        return await _pool_router(update, context)
    elif update.message and update.message.text:
        text = update.message.text.strip()
        lines = [l.strip() for l in text.split("\n") if l.strip() and not l.startswith("/")]
        if not lines:
            await update.message.reply_text("❌ Kirim proxy dlm format:\n<code>user:pass:host:port</code>", parse_mode=ParseMode.HTML)
            return
        oid = _owner(update)
        async with AsyncSessionLocal() as session:
            result = await pool_add(session, oid, lines)
        await update.message.reply_text(
            f"✅ <b>{result['added']}</b> proxy ditambahkan!\n❌ {result['skipped']} duplikat.",
            parse_mode=ParseMode.HTML
        )

async def _pool_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Proxy pool menu router."""
    query = update.callback_query
    data = query.data
    oid = _owner(update)

    if data == "pool:menu":
        async with AsyncSessionLocal() as s:
            stats = await pool_stats(s, oid)
        text = (
            f"🔌 <b>Pool Proxy</b>\n"
            f"{'─' * 28}\n"
            f"🟢 Tersedia: <b>{stats['available']}</b>\n"
            f"🔴 Terpakai: <b>{stats['used']}</b>\n"
            f"📊 Total: <b>{stats['total']}</b>\n"
            f"{'─' * 28}\n"
            f"<i>Kirim proxy dlm format:</i>\n"
            f"<code>user:pass:host:port</code>"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ Hapus Semua", callback_data="pool:clear")],
            [InlineKeyboardButton("« Kembali", callback_data="menu:admin")],
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    elif data == "pool:clear":
        async with AsyncSessionLocal() as s:
            deleted = await pool_clear_all(s, oid)
        await query.answer(f"✅ {deleted} proxy dihapus!", show_alert=True)
        query.data = "pool:menu"
        await _pool_router(update, context)
    else:
        await query.edit_message_text("❌ Unknown pool action.")

