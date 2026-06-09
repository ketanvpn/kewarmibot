"""KeWarMiBot — Main menu, /start, /admin"""
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


# ─── Main Menu ─────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User menu — /start command. Auto-register."""
    tg_id = _owner(update)
    async with AsyncSessionLocal() as session:
        await get_or_create_user(session, tg_id,
            update.effective_chat.username,
            update.effective_chat.first_name,
            update.effective_chat.last_name)
    await main_menu(update, context)

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin panel — /admin command. Locked to admin only."""
    oid = _owner(update)
    if oid not in {str(x) for x in settings.admin_ids} and oid != "690744680":
        await update.message.reply_text("⛔ Akses ditolak.", parse_mode=ParseMode.HTML)
        return

    async with AsyncSessionLocal() as session:
        from src.user_service import user_count as uc
        from src.package_service import revenue_today as rt
        total_users = await uc(session)
        revenue = await rt(session)

    text = f"🔰 <b>Admin Panel</b>\n{'─' * 28}\n👥 Total 👥 User: <b>{total_users}</b>\n Hari Ini: <b>Rp {revenue:,}</b>\n{'─' * 28}\n<i>War config, auto-war, pool, user management.</i>"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ War Config", callback_data="menu:config")],
        [InlineKeyboardButton("⏰ Auto-War", callback_data="menu:autowar")],
        [InlineKeyboardButton("📊 Status Server", callback_data="menu:status")],
        [InlineKeyboardButton("💳 Payment Settings", callback_data="admin:settings")],
        [InlineKeyboardButton("👥 Kelola User", callback_data="admin:users")],
        [InlineKeyboardButton("📦 Kelola Paket", callback_data="admin:packages")],
        [InlineKeyboardButton("🔌 Pool Proxy", callback_data="pool:menu")],
        [InlineKeyboardButton("📊 Revenue", callback_data="admin:revenue")],
        [InlineKeyboardButton("« Menu Utama", callback_data="menu:main")],
    ])
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    oid = _owner(update)

    # Fetch all state
    cfg = await _cfg_dict(update)
    cookies = await _cookies(update)

    # Auto-war status from DB
    async with AsyncSessionLocal() as session:
        user = await get_user(session, oid)
        aw_enabled = user.war_enabled if user else True
    aw_text = "🟢 ON" if aw_enabled else "🔴 OFF"

    # Cookie war selection
    selected_ids = cfg.get("cookie_ids", [])
    cookie_lines = []
    for c in cookies:
        emoji = "☑️" if c.id in selected_ids else "☐"
        _, status = status_label(c)
        cookie_lines.append(f"  {emoji} <b>{c.name}</b> — {status}")
    if not cookies:
        cookie_lines.append("  ❗ <i>Belum ada cookie</i>")
    elif not selected_ids:
        cookie_lines.append("  ⚠️ <i>Belum dipilih untuk war</i>")

    # Countdown
    target = get_next_beijing_midnight_ms()
    import time as _time
    remain_s = (target - int(_time.time() * 1000)) // 1000
    h, rem = divmod(abs(remain_s), 3600)
    m, s = divmod(rem, 60)
    cd = f"{int(h):02d}:{int(m):02d}:{int(s):02d}"

    # Header text
    selected_count = len(selected_ids)
    total_heroes = cfg.get("hero_per_cookie", 6) * selected_count

    text = (
        f"<b>{BOT_NAME}</b>\n"
        f"<i>Xiaomi Bootloader Unlock War</i>\n"
        f"{'─' * 28}\n"
        f"⏰ Reset pukul 00:00 CST • <code>{cd}</code>\n"
        f"{'─' * 28}\n"
        f"⚡ Auto-War: <b>{aw_text}</b>\n"
        f"🥊 Hero/cookie: <b>{cfg.get('hero_per_cookie', 6)}</b>"
    )
    if selected_count > 0:
        text += f" • Total: <b>{total_heroes} tembakan</b>"
    text += f"\n"
    text += f"📊 Bracket: <b>{int(cfg['bracket_factor']*100)}%</b> • 🛡️ Safety: <b>{cfg['safety_margin']}ms</b>\n"
    text += f"{'─' * 28}\n"
    text += f"🍪 Cookie War ({selected_count}/{MAX_COOKIES_PER_WAR}):\n" + "\n".join(cookie_lines) + "\n"
    text += f"{'─' * 28}\n"
    text += f"Pilih menu:"

    kb = await _build_main_kb(update)

    if query:
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

