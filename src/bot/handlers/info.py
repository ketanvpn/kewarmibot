"""KeWarMiBot — Status dashboard, latency sparkline"""
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


# ─── Status Menu ───────────────────────────────────────

async def menu_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    # Latency live
    lat = measure_latency(samples=3)

    # Latency stats dari DB (inline, no import from scheduler)
    import datetime as _dt
    from sqlalchemy import select as _sel
    cutoff = _dt.datetime.utcnow() - _dt.timedelta(hours=6)
    async with AsyncSessionLocal() as sess:
        r = await sess.execute(
            _sel(LatencyLogModel)
            .where(LatencyLogModel.timestamp >= cutoff)
            .order_by(LatencyLogModel.timestamp.desc())
            .limit(72)
        )
        logs = list(r.scalars().all())
    if not logs:
        stats = {"min": None, "max": None, "avg": None, "latest": None, "samples": []}
    else:
        values = [l.latency_ms for l in logs]
        stats = {
            "min": min(values),
            "max": max(values),
            "avg": sum(values) // len(values),
            "latest": values[0],
            "samples": [{"ts": l.timestamp.strftime("%H:%M"), "ms": l.latency_ms} for l in reversed(logs)],
        }

    # Countdown
    target = get_next_beijing_midnight_ms()
    import time as _time
    remain_s = (target - int(_time.time() * 1000)) // 1000
    h, rem = divmod(abs(remain_s), 3600)
    m, s = divmod(rem, 60)

    cookies = await _cookies(update)

    lines = [
        "📊 <b>Status</b>",
        f"⚡ Latency live: <b>{lat}ms</b>",
        f"⏰ Reset berikutnya: {int(h):02d}:{int(m):02d}:{int(s):02d}",
        "",
    ]

    if stats["latest"] is not None:
        lines.append(f"📈 Latency 6h: min {stats['min']}ms / avg {stats['avg']}ms / max {stats['max']}ms")
        # Sparkline
        spark = "".join(_spark_block(v["ms"], stats["min"], stats["max"]) for v in stats["samples"][-24:])
        lines.append(f"📉 {spark}")
    else:
        lines.append("📈 Belum ada data latency.")

    lines.append("")
    lines.append("<b>Cookies:</b>")
    for c in cookies:
        emoji, status = status_label(c)
        lines.append(f"{emoji} <b>{c.name}</b>: {status}")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="menu:status"),
         InlineKeyboardButton("« Kembali", callback_data="menu:main")],
    ])
    await query.edit_message_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML)


_SPARK_BLOCKS = "▁▂▃▄▅▆▇█"


def _spark_block(val: int, vmin: int, vmax: int) -> str:
    if vmax == vmin:
        return _SPARK_BLOCKS[3]
    idx = int((val - vmin) / (vmax - vmin) * (len(_SPARK_BLOCKS) - 1))
    return _SPARK_BLOCKS[max(0, min(idx, len(_SPARK_BLOCKS) - 1))]



# ─── History ───────────────────────────────────────────

async def menu_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    async with AsyncSessionLocal() as session:
        from src.db import WarHistoryModel
        from sqlalchemy import select
        r = await session.execute(
            select(WarHistoryModel).order_by(WarHistoryModel.started_at.desc()).limit(15)
        )
        history = list(r.scalars().all())

    if not history:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="menu:main")]])
        await query.edit_message_text("📜 <b>Belum ada riwayat war.</b>", reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    lines = ["📜 <b>Riwayat War</b>\n"]
    for h in history:
        total = h.success_count + h.fail_count
        rate = f"{h.success_count}/{total}" if total > 0 else "-"
        ts = h.started_at.strftime("%m/%d %H:%M") if h.started_at else "?"
        lines.append(f"• {ts} — ✅{rate} — {h.latency_median_ms}ms")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistik Cookie", callback_data="menu:stats")],
        [InlineKeyboardButton("« Kembali", callback_data="menu:main")],
    ])
    await query.edit_message_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML)


# ─── Cookie Statistics ─────────────────────────────────

async def menu_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Akumulasi success rate per cookie dari semua history."""
    query = update.callback_query
    await query.answer()

    from collections import defaultdict
    cookie_stats = defaultdict(lambda: {"success": 0, "fail": 0})

    async with AsyncSessionLocal() as session:
        from src.db import WarHistoryModel, CookieModel
        from sqlalchemy import select
        r = await session.execute(
            select(WarHistoryModel).order_by(WarHistoryModel.started_at.desc()).limit(200)
        )
        history = list(r.scalars().all())

        # Fetch cookie names for lookup
        cookies_result = await session.execute(
            select(CookieModel).where(CookieModel.owner_chat_id == _owner(update))
        )
        cookies = {c.id: c.name for c in cookies_result.scalars().all()}

    if not history:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="menu:history")]])
        await query.edit_message_text("📊 <b>Statistik Cookie</b>\n\nBelum ada data war.", reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    # Parse semua results JSON
    for h in history:
        if h.results:
            import json as _j
            try:
                heroes = _j.loads(h.results)
                for hero in heroes:
                    cn = hero.get("cookie_name", "?")
                    if hero.get("success"):
                        cookie_stats[cn]["success"] += 1
                    else:
                        cookie_stats[cn]["fail"] += 1
            except Exception:
                pass

    if not cookie_stats:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="menu:history")]])
        await query.edit_message_text("📊 <b>Statistik Cookie</b>\n\nTidak ada data yang bisa diproses.", reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    lines = [
        "📊 <b>Statistik Cookie</b>",
        f"📜 Dari {len(history)} sesi war terakhir\n",
    ]

    # Sort by total battles desc
    sorted_stats = sorted(cookie_stats.items(), key=lambda x: x[1]["success"] + x[1]["fail"], reverse=True)

    for cn, stats in sorted_stats:
        total = stats["success"] + stats["fail"]
        rate = stats["success"] / total * 100 if total > 0 else 0
        bar = "🟩" * max(1, round(rate / 20)) + "🟥" * (5 - max(1, round(rate / 20)))
        lines.append(f"🍪 <b>{cn}</b>: {bar} {rate:.0f}% ({stats['success']}/{total})")

    total_success = sum(s["success"] for _, s in sorted_stats)
    total_fail = sum(s["fail"] for _, s in sorted_stats)
    total_all = total_success + total_fail
    overall_rate = total_success / total_all * 100 if total_all > 0 else 0

    lines.append(f"\n📈 <b>Overall:</b> {overall_rate:.0f}% ({total_success}/{total_all})")

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="menu:history")]])
    await query.edit_message_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML)


# ─── Profile ─────────────────────────────────────────

async def menu_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    oid = _owner(update)

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, oid,
            update.effective_chat.username,
            update.effective_chat.first_name)
        orders = await list_user_orders(session, user.id, limit=5) if user else []

    if not user:
        await query.edit_message_text("❌ Akun tidak ditemukan.", parse_mode=ParseMode.HTML)
        return

    text = (
        f"👤 <b>Profil Kamu</b>\n"
        f"{'─' * 28}\n"
        f"📛 Nama: <b>{user.first_name or '—'}</b>\n"
        f"💰 Saldo War: <b>{user.balance_war}</b>\n"
        f"⚔️ Total War: <b>{user.total_wars}</b>\n"
        f"🎫 Tiket Sukses: <b>{user.total_tickets}</b>\n"
        f"📅 Bergabung: {user.created_at.strftime('%d/%m/%Y') if user.created_at else '—'}\n"
    )

    if user.is_suspended:
        text += "\n⛔ <b>AKUN DISUSPEND</b>"

    if orders:
        text += f"\n{'─' * 28}\n<b>Pembelian Terakhir:</b>\n"
        for o in orders[:3]:
            s = "✅" if o.status == "paid" else "⏳"
            text += f"  {s} {o.created_at.strftime('%d/%m') if o.created_at else '?'} — +{o.war_count} war (Rp {o.amount_idr:,})\n"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎫 Beli Tiket War", callback_data="menu:beli")],
        [InlineKeyboardButton("« Kembali", callback_data="menu:main")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
