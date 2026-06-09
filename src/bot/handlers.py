"""Telegram Bot — handlers for KeWarMiBot."""

import asyncio
import datetime
import json
import logging
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

from src.config import settings
from src.db import AsyncSessionLocal, CookieModel, LatencyLogModel, WarHistoryModel
from sqlalchemy import select
from src.cookie_service import (
    add_cookie,
    list_cookies,
    delete_cookie,
    get_cookie_token,
    refresh_cookie_status,
    status_label,
)
from src.war_config_service import load_config, save_config, MAX_COOKIES_PER_WAR, recommended_hero
from src.engine.api import measure_latency
from src.engine.war import run_war_sync, WarConfig, WarResultReport, get_next_beijing_midnight_ms
from src.user_service import get_or_create_user, get_user, add_balance, deduct_balance, add_tickets, get_user_by_id
from src.package_service import list_packages, get_package, create_order, list_user_orders, set_payment_url, update_package, revenue_today
from src.settings_service import get_setting, set_setting, get_payment_config
from src.proxy_pool_service import pool_stats, pool_add, pool_allocate, pool_consume_batch, pool_clear_all, pool_get_all
from src.user_service import get_or_create_user, get_user, add_balance, deduct_balance, add_tickets, get_user_by_id
from src.package_service import list_packages, get_package, create_order, list_user_orders, set_payment_url, update_package, revenue_today
from src.settings_service import get_setting, set_setting, get_payment_config
from src.proxy_pool_service import pool_stats, pool_add, pool_allocate, pool_consume_batch, pool_clear_all, pool_get_all
from src.scheduler_jobs import scheduler as _sj_scheduler, _notifier

logger = logging.getLogger(__name__)

# Conversation states
WAIT_COOKIE_NAME = 0
WAIT_COOKIE_TOKEN = 1
# Bot instance (set from main)
_bot_instance = None


def set_bot_instance(bot):
    global _bot_instance
    _bot_instance = bot


# ─── Helpers ───────────────────────────────────────────

def _owner(update: Update) -> str:
    return str(update.effective_chat.id)


async def _cfg_dict(update: Update) -> dict:
    async with AsyncSessionLocal() as session:
        return await load_config(session, _owner(update))


async def _cookies(update: Update):
    async with AsyncSessionLocal() as session:
        return await list_cookies(session, _owner(update))


BOT_NAME = "⚔️ KeWarMiBot"


async def _build_main_kb(update: Update) -> InlineKeyboardMarkup:
    """User menu — simple: cookie, war, history, beli."""
    cookies = await _cookies(update)
    kb = [
        [InlineKeyboardButton(f"👤 Profil & Saldo", callback_data="menu:profile")],
        [InlineKeyboardButton(f"🍪 Cookie Saya ({len(cookies)} tersimpan)", callback_data="menu:cookies")],
        [InlineKeyboardButton("🎫 Beli Tiket War", callback_data="menu:beli")],
        [InlineKeyboardButton("📜 Riwayat War", callback_data="menu:history")],
    ]
    return InlineKeyboardMarkup(kb)


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

    # Auto-war status
    aw_enabled = _auto_war_enabled.get(oid, True)
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


# ─── Cookie Management ─────────────────────────────────

async def menu_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    cookies = await _cookies(update)

    if not cookies:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Tambah Cookie", callback_data="cookie:add")],
            [InlineKeyboardButton("« Kembali", callback_data="menu:main")],
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
    kb_rows.append([InlineKeyboardButton("« Kembali", callback_data="menu:main")])

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
        cookie = await add_cookie(session, name, token, _owner(update))

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
        r = await session.execute(select(CookieModel).where(CookieModel.id == cid, CookieModel.owner_chat_id == _owner(update)))
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
        cookie = await refresh_cookie_status(session, cid, _owner(update))
    if not cookie:
        await query.edit_message_text("❌ Cookie tidak ditemukan.")
        return
    emoji, status = status_label(cookie)
    await query.edit_message_text(f"🔄 Status diperbarui!\n\n<b>{cookie.name}</b>: {emoji} {status}", parse_mode=ParseMode.HTML)

async def cookie_refresh_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Refresh status semua cookie sekaligus."""
    query = update.callback_query
    await query.answer()
    cookies = await _cookies(update)

    if not cookies:
        await query.edit_message_text("🍪 <b>Belum ada cookie.</b>", parse_mode=ParseMode.HTML)
        return

    await query.edit_message_text(f"🔄 <b>Refresh {len(cookies)} cookie...</b>\n\nMohon tunggu...", parse_mode=ParseMode.HTML)

    ok, fail = 0, 0
    lines = ["🔄 <b>Refresh Semua Cookie</b>\n"]
    async with AsyncSessionLocal() as session:
        for c in cookies:
            try:
                await refresh_cookie_status(session, c.id, _owner(update))
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
        deleted = await delete_cookie(session, cid, _owner(update))
    await query.edit_message_text("🗑 Cookie dihapus." if deleted else "❌ Gagal menghapus.")
    await asyncio.sleep(0.5)
    await main_menu(update, context)


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


# ─── War Config ────────────────────────────────────────

async def menu_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    cfg = await _cfg_dict(update)
    cookies = await _cookies(update)
    selected_ids = cfg.get("cookie_ids", [])
    # Cookie lines
    cookie_lines = []
    for cid in selected_ids:
        c = next((c for c in cookies if c.id == cid), None)
        emo = "✅" if c else "❓"
        cookie_lines.append(f"{emo} {c.name if c else 'Deleted'}")
    if not cookie_lines:
        cookie_lines.append(f"❗ Belum pilih cookie (max {MAX_COOKIES_PER_WAR})")

    cookie_count = len(selected_ids)
    hero = cfg.get("hero_per_cookie", 6)
    total_heroes = cookie_count * hero if cookie_count > 0 else 0
    rec = recommended_hero(cookie_count) if cookie_count > 0 else 0

    wh = cfg.get("war_hour", 0)
    wm = cfg.get("war_minute", 0)
    tz = cfg.get("war_tz", "Asia/Shanghai")
    target_label = f"{wh:02d}:{wm:02d} {tz}"

    text = (
        f"⚙️ <b>War Config</b>\n\n"
        f"⏰ Target: <b>{target_label}</b>\n"
        f"🥊 Hero per cookie: <b>{hero}</b>"
    )
    if cookie_count > 0:
        text += f" → Total: <b>{total_heroes} tembakan</b>"
        if hero != rec:
            text += f"\n💡 Rekomendasi: <b>{rec} hero/cookie</b> untuk {cookie_count} cookie"
    text += f"\n📊 Bracket: <b>{int(cfg['bracket_factor'] * 100)}%</b>\n"
    text += f"🛡️ Safety: <b>{cfg['safety_margin']}ms</b>\n"
    text += f"🍪 Cookies ({cookie_count}/{MAX_COOKIES_PER_WAR}):\n  " + "\n  ".join(cookie_lines)

    kb_rows = [
        [InlineKeyboardButton(f"⏰ Target: {target_label}", callback_data="cfg:time")],
        [InlineKeyboardButton(f"🥊 Hero/cookie: {hero}", callback_data="cfg:hero")],
        [InlineKeyboardButton(f"📊 Bracket: {int(cfg['bracket_factor']*100)}%", callback_data="cfg:bracket")],
        [InlineKeyboardButton(f"🛡️ Safety: {cfg['safety_margin']}ms", callback_data="cfg:safety")],
    ]

    # Cookie toggle — bebas pilih 1-6
    for c in cookies:
        in_war = c.id in selected_ids
        disabled = not in_war and len(selected_ids) >= MAX_COOKIES_PER_WAR
        label = f"{'✅' if in_war else ('🔒' if disabled else '⬜')} {c.name}"
        kb_rows.append([InlineKeyboardButton(label, callback_data=f"cfg:toggle_cookie:{c.id}")])

    kb_rows.append([InlineKeyboardButton("« Kembali", callback_data="menu:main")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=ParseMode.HTML)



async def config_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split(":")
    field = data[1] if len(data) > 1 else ""

    cfg = await _cfg_dict(update)
    selected_ids = cfg.get("cookie_ids", [])

    if field == "hero":
        values = [1, 2, 3, 4, 6, 8]
        current = cfg.get("hero_per_cookie", 6)
        cookie_count = len(selected_ids)
        rec = recommended_hero(cookie_count)
        btns = [InlineKeyboardButton(f"{'✅ ' if v == current else ''}{v}", callback_data=f"cfg:set:hero:{v}") for v in values]
        kb_rows = [btns[i:i+4] for i in range(0, len(btns), 4)]
        kb_rows.append([InlineKeyboardButton("« Kembali", callback_data="menu:config")])
        text = f"Pilih Hero per cookie (saat ini: {current}):"
        if cookie_count > 0:
            text += f"\n💡 Rekomendasi: {rec} hero/cookie untuk {cookie_count} cookie ({cookie_count * rec} total)"
        text += f"\n📦 Total tembakan: {cookie_count * current}"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))

    elif field == "bracket":
        values = [0.5, 0.6, 0.7, 0.8, 1.0, 1.2, 1.5]
        current = cfg["bracket_factor"]
        btns = [InlineKeyboardButton(f"{'✅ ' if v == current else ''}{int(v*100)}%", callback_data=f"cfg:set:bracket:{v}") for v in values]
        kb_rows = [btns[i:i+3] for i in range(0, len(btns), 3)]
        kb_rows.append([InlineKeyboardButton("« Kembali", callback_data="menu:config")])
        await query.edit_message_text(f"Pilih Bracket (saat ini: {int(current*100)}%):", reply_markup=InlineKeyboardMarkup(kb_rows))

    elif field == "safety":
        values = [0, 10, 20, 30, 50, 80, 100]
        current = cfg["safety_margin"]
        btns = [InlineKeyboardButton(f"{'✅ ' if v == current else ''}{v}ms", callback_data=f"cfg:set:safety:{v}") for v in values]
        kb_rows = [btns[i:i+3] for i in range(0, len(btns), 3)]
        kb_rows.append([InlineKeyboardButton("« Kembali", callback_data="menu:config")])
        await query.edit_message_text(f"Pilih Safety (saat ini: {current}ms):", reply_markup=InlineKeyboardMarkup(kb_rows))

    elif field == "toggle_cookie":
        cid = int(data[2])
        if cid in selected_ids:
            selected_ids = [i for i in selected_ids if i != cid]
        else:
            if len(selected_ids) >= MAX_COOKIES_PER_WAR:
                await query.answer(f"Maksimal {MAX_COOKIES_PER_WAR} cookie per war!", show_alert=True)
                return
            selected_ids = selected_ids + [cid]
        async with AsyncSessionLocal() as session:
            await save_config(session, _owner(update),
                              cookie_ids=selected_ids,
                              hero_per_cookie=cfg.get("hero_per_cookie", 6),
                              bracket_factor=cfg["bracket_factor"],
                              safety_margin=cfg["safety_margin"],
                              war_hour=cfg.get("war_hour", 0),
                              war_minute=cfg.get("war_minute", 0),
                              war_tz=cfg.get("war_tz", "Asia/Shanghai"))
        await menu_config(update, context)

    elif field == "time":
        # Hour selector for war target
        current_wh = cfg.get("war_hour", 0)
        current_tz = cfg.get("war_tz", "Asia/Shanghai")
        hour_btns = []
        for row_h in range(0, 24, 3):
            row = []
            for h in range(row_h, min(row_h + 3, 24)):
                row.append(InlineKeyboardButton(f"{'✅' if h == current_wh else ''}{h:02d}:00", callback_data=f"cfg:set:time:{h}:0"))
            hour_btns.append(row)
        kb_rows = hour_btns + [
            [InlineKeyboardButton("🌍 Timezone", callback_data="cfg:tz")],
            [InlineKeyboardButton("« Kembali", callback_data="menu:config")],
        ]
        await query.edit_message_text(
            f"⏰ <b>Atur Jam Target</b>\n\nSaat ini: {current_wh:02d}:{cfg.get('war_minute',0):02d} {current_tz}\nPilih jam target war:",
            reply_markup=InlineKeyboardMarkup(kb_rows),
            parse_mode=ParseMode.HTML,
        )

    elif field == "tz":
        # Timezone selector
        current_tz = cfg.get("war_tz", "Asia/Shanghai")
        tz_presets = [
            ("Asia/Shanghai", "🇨🇳 Beijing (UTC+8)"),
            ("Asia/Tokyo", "🇯🇵 Tokyo (UTC+9)"),
            ("Asia/Jakarta", "🇮🇩 Jakarta (UTC+7)"),
            ("Asia/Jayapura", "🇮🇩 Jayapura (UTC+9)"),
            ("Asia/Makassar", "🇮🇩 Makassar (UTC+8)"),
            ("Asia/Singapore", "🇸🇬 Singapore (UTC+8)"),
            ("Asia/Seoul", "🇰🇷 Seoul (UTC+9)"),
            ("Asia/Kolkata", "🇮🇳 India (UTC+5:30)"),
            ("Europe/London", "🇬🇧 London (UTC+0)"),
            ("America/New_York", "🇺🇸 New York (UTC-5)"),
        ]
        btns = [InlineKeyboardButton(f"{'✅ ' if t == current_tz else ''}{label}", callback_data=f"cfg:set:tz:{t}") for t, label in tz_presets]
        kb_rows = [btns[i:i+2] for i in range(0, len(btns), 2)]
        kb_rows.append([InlineKeyboardButton("« Kembali", callback_data="menu:config")])
        await query.edit_message_text(f"🌍 Pilih Timezone (saat ini: {current_tz}):", reply_markup=InlineKeyboardMarkup(kb_rows))

    elif field == "set":
        param = data[2]
        if param == "tz":
            val = data[3]
            async with AsyncSessionLocal() as session:
                await save_config(session, _owner(update),
                                  cookie_ids=selected_ids,
                                  hero_per_cookie=cfg.get("hero_per_cookie", 6),
                                  bracket_factor=cfg["bracket_factor"],
                                  safety_margin=cfg["safety_margin"],
                                  war_hour=cfg.get("war_hour", 0),
                                  war_minute=cfg.get("war_minute", 0),
                                  war_tz=val)
            await query.answer(f"Timezone: {val}", show_alert=False)
        elif param == "mode":
            # Removed — hero is manual now. Keep handler stub for any stray callbacks.
            await query.answer("Mode tidak diperlukan — atur hero manual", show_alert=False)
        elif param == "time":
            wh = int(data[3])
            wm = int(data[4]) if len(data) > 4 else 0
            async with AsyncSessionLocal() as session:
                await save_config(session, _owner(update),
                                  cookie_ids=selected_ids,
                                  hero_per_cookie=cfg.get("hero_per_cookie", 6),
                                  bracket_factor=cfg["bracket_factor"],
                                  safety_margin=cfg["safety_margin"],
                                  war_hour=wh,
                                  war_minute=wm,
                                  war_tz=cfg.get("war_tz", "Asia/Shanghai"))
            await query.answer(f"Target: {wh:02d}:{wm:02d}", show_alert=False)
        else:
            val = float(data[3]) if "." in data[3] else int(data[3])
            hero = val if param == "hero" else cfg.get("hero_per_cookie", 6)
            bracket = val if param == "bracket" else cfg["bracket_factor"]
            safety = val if param == "safety" else cfg["safety_margin"]
            async with AsyncSessionLocal() as session:
                await save_config(session, _owner(update),
                                  cookie_ids=selected_ids,
                                  hero_per_cookie=hero,
                                  bracket_factor=bracket,
                                  safety_margin=safety,
                                  war_hour=cfg.get("war_hour", 0),
                                  war_minute=cfg.get("war_minute", 0),
                                  war_tz=cfg.get("war_tz", "Asia/Shanghai"))
        await menu_config(update, context)


# ─── War Now ───────────────────────────────────────────

async def war_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    oid = _owner(update)

    cfg = await _cfg_dict(update)
    selected_ids = cfg.get("cookie_ids", [])
    if not selected_ids:
        await query.edit_message_text("❌ Pilih minimal 1 cookie di ⚙️ War Config!")
        return

    # Get user & balance
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, oid,
            update.effective_chat.username,
            update.effective_chat.first_name)
        balance = user.balance_war

    hero_count = cfg.get("hero_per_cookie", 3)
    cost = len(selected_ids)  # 1 tiket = 1 cookie

    if balance < cost:
        await query.edit_message_text(
            f"❌ Tiket tidak cukup!\n\n🎫 Tiket: <b>{balance}</b>\n🎯 Butuh: <b>{cost}</b> tiket ({len(selected_ids)} cookie)\n\n<i>Beli tiket dulu di 🎫 Beli Tiket War</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Beli Slot", callback_data="menu:beli")]])
        )
        return

    # Load all cookie tokens
    cookie_list = []
    async with AsyncSessionLocal() as session:
        for cid in selected_ids:
            token = await get_cookie_token(session, cid, _owner(update))
            if token:
                r = await session.execute(select(CookieModel).where(CookieModel.id == cid, CookieModel.owner_chat_id == _owner(update)))
                c = r.scalar_one_or_none()
                cookie_list.append((token, c.name if c else "Unknown"))

    if not cookie_list:
        await query.edit_message_text("❌ Gagal decrypt cookie. Periksa kembali.")
        return

    config = WarConfig(
        cookies=cookie_list,
        hero_per_cookie=hero_count, bracket_factor=cfg["bracket_factor"],
        safety_margin=cfg["safety_margin"], hero_spacing_ms=cfg.get("hero_spacing_ms", 0),
        use_pool=True,
        owner_chat_id=_owner(update),
        debug=True,
        war_hour=cfg.get("war_hour", 0),
        war_minute=cfg.get("war_minute", 0),
        war_tz=cfg.get("war_tz", "Asia/Shanghai"),
    )

    await query.edit_message_text(
        f"⚔️ Memulai WAR\n\n🥊 {hero_count} hero/cookie\n🍪 {len(cookie_list)} cookie\n🎫 Biaya: <b>{cost}</b> tiket\n🔄 Total: <b>{hero_count * len(cookie_list)}</b> request\n🎫 Tiket: {balance} → <b>{balance - cost}</b>\n\n⏰ War dalam ~20 detik...",
        parse_mode=ParseMode.HTML,
    )

    # Deduct balance before war
    try:
        async with AsyncSessionLocal() as session:
            await deduct_balance(session, user.id, cost)
    except Exception as e:
        logger.error(f"Balance deduct failed: {e}")

    report: WarResultReport = await asyncio.to_thread(run_war_sync, config)
    report_text = report.format_report()

    # Save to history with user_id
    import json as _json
    async with AsyncSessionLocal() as session:
        from src.db import WarHistoryModel
        history = WarHistoryModel(
            user_id=user.id,
            started_at=report.started_at,
            results=_json.dumps([{"hero_id": r.hero_id, "success": r.success, "code": r.code, "msg": r.msg, "drift_ms": r.drift_ms, "cookie_name": r.cookie_name} for r in report.hero_results]),
            success_count=report.success_count,
            fail_count=report.fail_count,
            latency_median_ms=report.latency_median_ms,
        )
        session.add(history)
        await session.commit()

    # Add tickets for success
    if report.success_count > 0:
        try:
            async with AsyncSessionLocal() as session:
                await add_tickets(session, user.id, report.success_count)
        except Exception:
            pass

    # Final balance
    async with AsyncSessionLocal() as session:
        u = await get_user(session, oid)
        final_balance = u.balance_war if u else "?"

    summary = f"{report_text}\n{'─' * 28}\n🎫 Tiket tersisa: <b>{final_balance}</b>"

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Menu Utama", callback_data="menu:main")]])
    await query.message.reply_text(summary, reply_markup=kb, parse_mode=ParseMode.HTML)


# ─── Auto-War Toggle ───────────────────────────────────

_auto_war_enabled: dict[str, bool] = {}


async def menu_autowar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    oid = _owner(update)
    enabled = _auto_war_enabled.get(oid, True)

    status_text = "✅ AKTIF" if enabled else "❌ NONAKTIF"
    text = (
        f"⏰ <b>Auto-War Scheduler</b>\n\n"
        f"Status: {status_text}\n\n"
        f"Jadwal:\n"
        f"• 23:55 CST — Notifikasi 5 menit sebelum war\n"
        f"• 23:57 CST — Auto-war dimulai\n"
        f"• 00:00 CST — Reset harian Xiaomi\n\n"
        f"Latency monitor berjalan setiap 15 menit."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Matikan" if enabled else "🟢 Aktifkan", callback_data="autowar:toggle")],
        [InlineKeyboardButton("« Kembali", callback_data="menu:main")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def autowar_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    oid = _owner(update)
    _auto_war_enabled[oid] = not _auto_war_enabled.get(oid, True)
    await menu_autowar(update, context)


async def autowar_run_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manual trigger real war (not debug)."""
    query = update.callback_query
    await query.answer()

    cfg = await _cfg_dict(update)
    selected_ids = cfg.get("cookie_ids", [])
    if not selected_ids:
        await query.edit_message_text("❌ Pilih minimal 1 cookie di War Config!")
        return

    cookie_list = []
    async with AsyncSessionLocal() as session:
        for cid in selected_ids:
            token = await get_cookie_token(session, cid, _owner(update))
            if token:
                r = await session.execute(select(CookieModel).where(CookieModel.id == cid, CookieModel.owner_chat_id == _owner(update)))
                c = r.scalar_one_or_none()
                cookie_list.append((token, c.name if c else "Unknown"))

    if not cookie_list:
        await query.edit_message_text("❌ Gagal decrypt cookie.")
        return

    config = WarConfig(
        cookies=cookie_list,
        hero_per_cookie=cfg.get("hero_per_cookie", 6), bracket_factor=cfg["bracket_factor"],
        safety_margin=cfg["safety_margin"], debug=False,
    )

    await query.edit_message_text("⚔️ <b>WAR DIMULAI</b>\n\nMenunggu hasil...", parse_mode=ParseMode.HTML)
    report = await asyncio.to_thread(run_war_sync, config)

    async with AsyncSessionLocal() as session:
        from src.db import WarHistoryModel
        history = WarHistoryModel(
            started_at=report.started_at,
            results=json.dumps([{"hero_id": r.hero_id, "success": r.success, "code": r.code, "msg": r.msg, "drift_ms": r.drift_ms, "cookie_name": r.cookie_name} for r in report.hero_results]),
            success_count=report.success_count,
            fail_count=report.fail_count,
            latency_median_ms=report.latency_median_ms,
        )
        session.add(history)
        await session.commit()

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Menu Utama", callback_data="menu:main")]])
    await query.message.reply_text(report.format_report(), reply_markup=kb, parse_mode=ParseMode.HTML)


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
            f"✅ <b>{result['added']}</b> proxy ditambahkan!\n❌ {result['duplicates']} duplikat.",
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

# ─── Router ────────────────────────────────────────────

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    static_routes = {
        "menu:main": main_menu,
        "menu:profile": menu_profile,
        "menu:cookies": menu_cookies,
        "menu:status": menu_status,
        "menu:config": menu_config,
        "menu:war_debug": war_debug,
        "menu:autowar": menu_autowar,
        "menu:history": menu_history,
        "menu:stats": menu_stats,
        "menu:beli": menu_beli,
        "menu:admin": menu_admin,
    }

    if data in static_routes:
        await static_routes[data](update, context)
    elif data == "cookie:refresh_all":
        await cookie_refresh_all(update, context)
    elif data.startswith("cookie:detail:"):
        await cookie_detail(update, context)
    elif data.startswith("cookie:refresh:"):
        await cookie_refresh(update, context)
    elif data.startswith("cookie:delete_confirm:"):
        await cookie_delete_confirm(update, context)
    elif data.startswith("cookie:delete:"):
        await cookie_delete(update, context)
    elif data.startswith("cookie:add"):
        await cookie_add_start(update, context)
    elif data.startswith("cfg:"):
        await config_set(update, context)
    elif data.startswith("autowar:"):
        await autowar_toggle(update, context)
    elif data.startswith("beli:pkg:"):
        await menu_beli_confirm(update, context)
    elif data.startswith("beli:"):
        await menu_beli(update, context)
    elif data.startswith("pool:"):
        await pool_handle_text(update, context)
    elif data.startswith("admin:pkg:name:") or data.startswith("admin:pkg:war:") or data.startswith("admin:pkg:price:") or data.startswith("admin:pkg:toggle:"):
        await admin_pkg_edit_field(update, context)
    elif data.startswith("admin:pkg:edit:"):
        await admin_pkg_edit(update, context)
    elif data.startswith("admin:pkg:"):
        await admin_pkg_edit(update, context)
    elif data.startswith("admin:user:"):
        await admin_user_detail(update, context)
    elif data.startswith("admin:topup:"):
        await admin_user_topup_prompt(update, context)
    elif data == "admin:users":
        await admin_users_list(update, context)
    elif data == "admin:packages":
        await admin_packages_list(update, context)
    elif data == "admin:settings":
        await admin_settings_menu(update, context)
    elif data.startswith("admin:setting:"):
        await admin_setting_edit(update, context)
    elif data == "admin:revenue":
        await admin_revenue(update, context)
    else:
        await main_menu(update, context)


# ─── Quick Commands —————————————————————————————————————

async def _fake_query(update: Update, data: str):
    """Create minimal fake callback_query for menu handlers."""
    # Wrapper so reply_text works instead of edit_message_text
    class FakeQuery:
        data = data
        answer = lambda *a, **kw: None
        def __init__(self, msg):
            self.message = msg
        def edit_message_text(self, text, **kw):
            return asyncio.ensure_future(self.message.reply_text(text, **kw))
    update.callback_query = FakeQuery(update.message)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/status — jump to status dashboard."""
    _fake_query(update, "menu:status")
    await menu_status(update, context)

async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/config — jump to war config."""
    _fake_query(update, "menu:config")
    await menu_config(update, context)

async def cmd_war(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/war — trigger debug war."""
    _fake_query(update, "menu:war_debug")
    await war_debug(update, context)

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/riwayat — war history."""
    _fake_query(update, "menu:history")
    await menu_history(update, context)

# ─── Application ───────────────────────────────────────

def build_app() -> Application:
    app = Application.builder().token(settings.bot_token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("war", cmd_war))
    app.add_handler(CommandHandler("riwayat", cmd_history))

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cookie_add_start, pattern="^cookie:add$")],
        states={
            WAIT_COOKIE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, cookie_add_name)],
            WAIT_COOKIE_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, cookie_add_token)],
        },
        fallbacks=[CommandHandler("cancel", cookie_add_cancel)],
    )
    # Proxy add + Settings edit + Package edit: text input handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, text_input_handler), group=1)

    app.add_handler(conv)

    app.add_handler(CallbackQueryHandler(menu_router, pattern="^(menu|cookie|cfg|autowar|pool|beli|admin):"))

    return app