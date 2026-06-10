"""KeWarMiBot — shared helpers, imports, constants for all handler modules."""

import asyncio
import datetime
import json
import logging
import time as _time  # noqa: F401

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
    delete_cookie, refresh_cookie_status, status_label,
)
from src.war_config_service import load_config, save_config, MAX_COOKIES_PER_WAR, recommended_hero
from src.engine.api import measure_latency
from src.engine.war import WarConfig, WarResultReport, get_next_beijing_midnight_ms
from src.user_service import (
    get_or_create_user, get_user, add_balance, deduct_balance,
    add_tickets, get_user_by_id, toggle_war_enabled,
)
from src.package_service import list_packages, get_package, create_order, list_user_orders, set_payment_url, update_package, revenue_today
from src.settings_service import get_setting, set_setting, get_payment_config
from src.proxy_pool_service import pool_stats, pool_add, pool_allocate, pool_consume_batch, pool_clear_all, pool_get_all

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────
#  BRANDING
# ────────────────────────────────────────────────────────

BOT_NAME = "⚔️ KeWarMiBot"
BOT_TAGLINE = "Xiaomi Bootloader Unlock — Automated War"
BOT_VERSION = "v2.0"
SEP = "━" * 30
SEP_THIN = "─" * 28


# ────────────────────────────────────────────────────────
#  Shared state + helpers
# ────────────────────────────────────────────────────────

_bot = None

def set_bot_instance(bot):
    global _bot
    _bot = bot

def owner_id(update: Update) -> str:
    return str(update.effective_chat.id)

def is_admin_update(update: Update) -> bool:
    oid = owner_id(update)
    return oid in {str(x) for x in settings.admin_ids} or oid == "690744680"

async def cfg_dict(update: Update) -> dict:
    oid = owner_id(update)
    async with AsyncSessionLocal() as session:
        return await load_config(session, oid)

async def cookies_list(update: Update):
    async with AsyncSessionLocal() as session:
        return await list_cookies(session, owner_id(update))


# ────────────────────────────────────────────────────────
#  UI helpers
# ────────────────────────────────────────────────────────

SPARK_BLOCKS = "▁▂▃▄▅▆▇█"

async def admin_dashboard_text():
    """Build admin dashboard stats text + keyboard. Shared by /admin and menu:admin."""
    async with AsyncSessionLocal() as session:
        from src.package_service import revenue_today as rt
        from sqlalchemy import select, func
        from src.db import OrderModel
        from src.user_service import user_count
        total_users = await user_count(session)
        revenue = await rt(session)
        r = await session.execute(select(func.count()).select_from(OrderModel).where(OrderModel.status == "paid"))
        paid = r.scalar() or 0
        r = await session.execute(select(func.count()).select_from(OrderModel).where(OrderModel.status == "waiting_payment"))
        waiting = r.scalar() or 0

    text = (
        f"🛡️ <b>Admin Dashboard</b>\n"
        f"{SEP}\n"
        f"👥 User: <b>{total_users}</b>     ·     💰 Hari Ini: <b>Rp {revenue:,}</b>\n"
        f"📦 Order Paid: <b>{paid}</b>     ·     ⏳ Waiting: <b>{waiting}</b>\n"
        f"{SEP}\n"
        f"<b>Panel Admin:</b>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Kelola User", callback_data="admin:users"),
         InlineKeyboardButton("📦 Kelola Paket", callback_data="admin:packages")],
        [InlineKeyboardButton("💳 Payment Settings", callback_data="admin:settings"),
         InlineKeyboardButton("📊 Revenue", callback_data="admin:revenue")],
        [InlineKeyboardButton("🔌 Pool Proxy", callback_data="pool:menu@admin"),
         InlineKeyboardButton("⚙️ War Config", callback_data="menu:config@admin")],
        [InlineKeyboardButton("⚔️ War Debug", callback_data="menu:war_debug@admin"),
         InlineKeyboardButton("📊 Status", callback_data="menu:status@admin")],
        [InlineKeyboardButton("⏰ Auto-War", callback_data="menu:autowar@admin"),
         InlineKeyboardButton("📜 Riwayat", callback_data="menu:history@admin")],
        [InlineKeyboardButton("« Menu Utama", callback_data="menu:main")],
    ])
    return text, kb


def spark_block(val: int, vmin: int, vmax: int) -> str:
    if vmax == vmin:
        return SPARK_BLOCKS[3]
    idx = int((val - vmin) / (vmax - vmin) * (len(SPARK_BLOCKS) - 1))
    return SPARK_BLOCKS[max(0, min(idx, len(SPARK_BLOCKS) - 1))]

def countdown_text(target_ms: int) -> str:
    remain_s = (target_ms - int(_time.time() * 1000)) // 1000
    h, rem = divmod(abs(remain_s), 3600)
    m, s = divmod(rem, 60)
    sign = "-" if remain_s < 0 else ""
    return f"{sign}{int(h):02d}:{int(m):02d}:{int(s):02d}"

def set_nav_admin(context, is_admin: bool):
    """Set admin navigation context. Shared pages use this for back button."""
    context.user_data["_nav_admin"] = is_admin

def get_nav_admin(context) -> bool:
    return context.user_data.get("_nav_admin", False)

def back_cb(update: Update, context) -> str:
    """Return back callback for current nav context."""
    if get_nav_admin(context):
        return "menu:admin"
    return "menu:main"

def back_button(update: Update, context, label: str = "« Kembali") -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=back_cb(update, context))

def back_kb(update: Update, context) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[back_button(update, context)]])

# ConversationHandler states
WAIT_COOKIE_NAME, WAIT_COOKIE_TOKEN = range(2)
