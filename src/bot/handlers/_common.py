"""KeWarMiBot — shared helpers, imports, constants for all handler modules."""

import asyncio
import datetime
import json
import logging
import time as _time

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
#  BRANDING (ubah disini → berubah di semua halaman)
# ────────────────────────────────────────────────────────

BOT_NAME = "⚔️ KeWarMiBot"
BOT_TAGLINE = "Xiaomi Bootloader Unlock — Automated War"
BOT_VERSION = "v2.0"
SEP = "━" * 30  # Full-width separator
SEP_THIN = "─" * 28  # Thin separator

HEADER = f"""<b>{BOT_NAME}</b>  <code>{BOT_VERSION}</code>
<i>{BOT_TAGLINE}</i>
{SEP}"""

FOOTER = f"""{SEP}
<i>{BOT_NAME} · {BOT_VERSION}</i>"""

PROFILE_EMOJI = "👤"
ADMIN_EMOJI = "🛡️"


# ────────────────────────────────────────────────────────
#  Shared state + helpers
# ────────────────────────────────────────────────────────

_bot = None

def set_bot_instance(bot):
    """Store bot instance for direct message sending."""
    global _bot
    _bot = bot

def owner_id(update: Update) -> str:
    """Extract chat id as string."""
    return str(update.effective_chat.id)

async def cfg_dict(update: Update) -> dict:
    """Load war config for given update's owner."""
    oid = owner_id(update)
    async with AsyncSessionLocal() as session:
        return await load_config(session, oid)

async def cookies_list(update: Update):
    """List cookies for given update's owner."""
    async with AsyncSessionLocal() as session:
        return await list_cookies(session, owner_id(update))

async def build_main_kb(update: Update) -> InlineKeyboardMarkup:
    """Build main menu keyboard. Admin gets full panel, user gets simple panel."""
    oid = owner_id(update)
    is_admin = oid == "690744680" or str(update.effective_chat.id) in settings.admin_ids

    async with AsyncSessionLocal() as session:
        user = await get_user(session, oid)
        w_enabled = user.war_enabled if user else True

    toggle_label = f"⏰ {'🟢' if w_enabled else '🔴'}"

    # ── USER panel (simple, 3 langkah) ──
    user_buttons = [
        [InlineKeyboardButton("🍪 Cookie Saya", callback_data="menu:cookies"),
         InlineKeyboardButton("🎫 Beli Tiket", callback_data="menu:beli")],
        [InlineKeyboardButton("📜 Riwayat War", callback_data="menu:history"),
         InlineKeyboardButton("👤 Profil Saya", callback_data="menu:profile")],
        [InlineKeyboardButton("📖 Panduan", callback_data="menu:guide"),
         InlineKeyboardButton(toggle_label, callback_data="menu:autowar")],
        [InlineKeyboardButton("💬 Support", callback_data="menu:support")],
    ]

    # ── ADMIN panel (full akses) ──
    admin_buttons = [
        [InlineKeyboardButton("🍪 Cookie", callback_data="menu:cookies"),
         InlineKeyboardButton("🎫 Beli Tiket", callback_data="menu:beli")],
        [InlineKeyboardButton("⚔️ War Debug", callback_data="menu:war_debug"),
         InlineKeyboardButton("⚙️ Config", callback_data="menu:config")],
        [InlineKeyboardButton("📊 Dashboard", callback_data="menu:status"),
         InlineKeyboardButton("📜 Riwayat", callback_data="menu:history")],
        [InlineKeyboardButton("👤 Profil", callback_data="menu:profile"),
         InlineKeyboardButton("📖 Panduan", callback_data="menu:guide")],
        [InlineKeyboardButton(toggle_label, callback_data="menu:autowar"),
         InlineKeyboardButton("🛡️ Admin", callback_data="menu:admin")],
        [InlineKeyboardButton("💬 Support", callback_data="menu:support")],
    ]

    return InlineKeyboardMarkup(admin_buttons if is_admin else user_buttons)

# ConversationHandler states
WAIT_COOKIE_NAME, WAIT_COOKIE_TOKEN = range(2)


# ────────────────────────────────────────────────────────
#  UI helpers
# ────────────────────────────────────────────────────────

def back_button(label: str = "« Kembali", callback: str = "menu:main") -> list[InlineKeyboardButton]:
    """Single back button."""
    return [InlineKeyboardButton(label, callback_data=callback)]

def back_kb(callback: str = "menu:main", extra: list[list[InlineKeyboardButton]] | None = None) -> InlineKeyboardMarkup:
    """Keyboard with back button + optional extra row."""
    buttons = extra or []
    buttons.append([InlineKeyboardButton("« Kembali", callback_data=callback)])
    return InlineKeyboardMarkup(buttons)

def countdown_text(target_ms: int) -> str:
    """Format countdown HH:MM:SS until target_ms."""
    remain_s = (target_ms - int(_time.time() * 1000)) // 1000
    h, rem = divmod(abs(remain_s), 3600)
    m, s = divmod(rem, 60)
    sign = "-" if remain_s < 0 else ""
    return f"{sign}{int(h):02d}:{int(m):02d}:{int(s):02d}"

_SPARK_BLOCKS = "▁▂▃▄▅▆▇█"

def spark_block(val: int, vmin: int, vmax: int) -> str:
    """Single block of sparkline."""
    if vmax == vmin:
        return _SPARK_BLOCKS[3]
    idx = int((val - vmin) / (vmax - vmin) * (len(_SPARK_BLOCKS) - 1))
    return _SPARK_BLOCKS[max(0, min(idx, len(_SPARK_BLOCKS) - 1))]

async def quick_back(query, text: str, callback: str = "menu:main"):
    """Show simple message with back button."""
    await query.edit_message_text(text, reply_markup=back_kb(callback), parse_mode=ParseMode.HTML)

async def refresh_menu(query, handler, *args, **kwargs):
    """Answer callback & refresh same menu."""
    await query.answer()
    await handler(query, *args, **kwargs)

# Force export of private helpers (Python's import * skips _-prefixed names)
__all__ = [x for x in dir() if not x.startswith('__')]