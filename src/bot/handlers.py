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
from src.war_config_service import load_config, save_config, MAX_COOKIES_PER_WAR, MAX_HERO_PER_COOKIE
from src.engine.api import check_cookie_status, measure_latency
from src.engine.war import run_war_sync, WarConfig, WarResultReport, get_next_beijing_midnight_ms
from src.scheduler_jobs import _get_latency_stats, _run_scheduled_war

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
    cookies = await _cookies(update)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🍪 Cookies ({len(cookies)} tersimpan)", callback_data="menu:cookies")],
        [
            InlineKeyboardButton("⚙️ War Config", callback_data="menu:config"),
            InlineKeyboardButton("📊 Status", callback_data="menu:status"),
        ],
        [
            InlineKeyboardButton("🚀 War Now (Debug)", callback_data="menu:war_debug"),
            InlineKeyboardButton("⏰ Auto-War", callback_data="menu:autowar"),
        ],
        [InlineKeyboardButton("📜 Riwayat War", callback_data="menu:history")],
    ])


# ─── Main Menu ─────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await main_menu(update, context)


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
    total_heroes = cfg.get("hero_per_cookie", 6) * max(selected_count, 1) if selected_count else 0

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

    # Latency stats dari DB
    stats = await _get_latency_stats(_owner(update))

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
    hero = cfg.get("hero_per_cookie", 6)

    # Cookie lines
    cookie_lines = []
    for cid in selected_ids:
        c = next((c for c in cookies if c.id == cid), None)
        emo = "✅" if c else "❓"
        cookie_lines.append(f"{emo} {c.name if c else 'Deleted'}")
    if not cookie_lines:
        cookie_lines.append("❗ Belum pilih cookie (max 2)")

    cookie_count = len(selected_ids)

    text = (
        f"⚙️ <b>War Config</b>\n\n"
        f"🥊 Hero per cookie: <b>{hero}</b>\n"
        f"📊 Bracket: <b>{int(cfg['bracket_factor'] * 100)}%</b>\n"
        f"🛡️ Safety: <b>{cfg['safety_margin']}ms</b>\n"
        f"🍪 Cookies ({cookie_count}/{MAX_COOKIES_PER_WAR}):\n  " + "\n  ".join(cookie_lines)
    )

    kb_rows = [
        [InlineKeyboardButton(f"🥊 Hero/cookie: {hero}", callback_data="cfg:hero")],
        [InlineKeyboardButton(f"📊 Bracket: {int(cfg['bracket_factor']*100)}%", callback_data="cfg:bracket")],
        [InlineKeyboardButton(f"🛡️ Safety: {cfg['safety_margin']}ms", callback_data="cfg:safety")],
    ]

    # Cookie toggle with max 2 UI
    for c in cookies:
        in_war = c.id in selected_ids
        disabled = not in_war and len(selected_ids) >= MAX_COOKIES_PER_WAR
        label = f"{'✅' if in_war else ('🔒' if disabled else '⬜')} {c.name}"
        kb_rows.append([InlineKeyboardButton(label, callback_data=f"cfg:toggle_cookie:{c.id}")])

    kb_rows.append([InlineKeyboardButton("« Kembali", callback_data="menu:main")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=ParseMode.HTML)


async def _persist_config(update: Update) -> None:
    """Save current user_data config to DB."""
    ctx = update.callback_query.data if hasattr(update, 'callback_query') else None
    # We use context.user_data from menu_router
    # Actually we need context here — let's refactor config_set to pass context
    pass


async def config_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split(":")
    field = data[1] if len(data) > 1 else ""

    cfg = await _cfg_dict(update)
    selected_ids = cfg.get("cookie_ids", [])

    if field == "hero":
        values = [2, 4, 6, 8]
        current = cfg.get("hero_per_cookie", 6)
        btns = [InlineKeyboardButton(f"{'✅ ' if v == current else ''}{v}", callback_data=f"cfg:set:hero:{v}") for v in values]
        kb_rows = [btns[i:i+3] for i in range(0, len(btns), 3)]
        kb_rows.append([InlineKeyboardButton("« Kembali", callback_data="menu:config")])
        await query.edit_message_text(f"Pilih Hero (saat ini: {current}):", reply_markup=InlineKeyboardMarkup(kb_rows))

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
            selected_ids = [i for i in selected_ids if i != cid]  # un-toggle
        else:
            if len(selected_ids) >= MAX_COOKIES_PER_WAR:
                await query.answer(f"Maksimal {MAX_COOKIES_PER_WAR} cookie per war!", show_alert=True)
                return
            selected_ids = selected_ids + [cid]  # toggle ON
        async with AsyncSessionLocal() as session:
            await save_config(session, _owner(update),
                              cookie_ids=selected_ids,
                              hero_per_cookie=cfg.get("hero_per_cookie", 6),
                              bracket_factor=cfg["bracket_factor"],
                              safety_margin=cfg["safety_margin"])
        await menu_config(update, context)

    elif field == "set":
        param = data[2]
        val = float(data[3]) if "." in data[3] else int(data[3])
        hero = val if param == "hero" else cfg.get("hero_per_cookie", 6)
        bracket = val if param == "bracket" else cfg["bracket_factor"]
        safety = val if param == "safety" else cfg["safety_margin"]
        async with AsyncSessionLocal() as session:
            await save_config(session, _owner(update),
                              cookie_ids=selected_ids,
                              hero_per_cookie=hero,
                              bracket_factor=bracket,
                              safety_margin=safety)
        await menu_config(update, context)


# ─── War Now ───────────────────────────────────────────

async def war_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    cfg = await _cfg_dict(update)
    selected_ids = cfg.get("cookie_ids", [])
    if not selected_ids:
        await query.edit_message_text("❌ Pilih minimal 1 cookie di ⚙️ War Config!")
        return

    # Load all cookie tokens
    cookie_list = []
    async with AsyncSessionLocal() as session:
        for cid in selected_ids:
            token = await get_cookie_token(session, cid, _owner(update))
            if token:
                r = await session.execute(select(CookieModel).where(CookieModel.id == cid))
                c = r.scalar_one_or_none()
                cookie_list.append((token, c.name if c else "Unknown"))

    if not cookie_list:
        await query.edit_message_text("❌ Gagal decrypt cookie. Periksa kembali.")
        return

    config = WarConfig(
        cookies=cookie_list,
        hero_per_cookie=cfg.get("hero_per_cookie", 6), bracket_factor=cfg["bracket_factor"],
        safety_margin=cfg["safety_margin"], debug=True,
    )

    await query.edit_message_text(
        f"⚔️ <b>Memulai WAR (Debug)</b>\n\n🥊 {cfg.get('hero_per_cookie', 6)} hero/cookie\n🍪 {len(cookie_list)} cookie\n📦 Total: {cfg.get('hero_per_cookie', 6) * len(cookie_list)} request\n⏰ War dalam ~20 detik...",
        parse_mode=ParseMode.HTML,
    )

    report: WarResultReport = await asyncio.to_thread(run_war_sync, config)
    report_text = report.format_report()

    # Save to history
    import json as _json
    async with AsyncSessionLocal() as session:
        from src.db import WarHistoryModel
        history = WarHistoryModel(
            started_at=report.started_at,
            results=_json.dumps([{"hero_id": r.hero_id, "success": r.success, "code": r.code, "msg": r.msg, "drift_ms": r.drift_ms} for r in report.hero_results]),
            success_count=report.success_count,
            fail_count=report.fail_count,
            latency_median_ms=report.latency_median_ms,
        )
        session.add(history)
        await session.commit()

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Menu Utama", callback_data="menu:main")]])
    await query.message.reply_text(report_text, reply_markup=kb, parse_mode=ParseMode.HTML)


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
                r = await session.execute(select(CookieModel).where(CookieModel.id == cid))
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
            results=json.dumps([{"hero_id": r.hero_id, "success": r.success, "code": r.code, "msg": r.msg, "drift_ms": r.drift_ms} for r in report.hero_results]),
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

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="menu:main")]])
    await query.edit_message_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML)


# ─── Router ────────────────────────────────────────────

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    static_routes = {
        "menu:main": main_menu,
        "menu:cookies": menu_cookies,
        "menu:status": menu_status,
        "menu:config": menu_config,
        "menu:war_debug": war_debug,
        "menu:autowar": menu_autowar,
        "menu:history": menu_history,
    }

    if data in static_routes:
        await static_routes[data](update, context)
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
    else:
        await main_menu(update, context)


# ─── Application ───────────────────────────────────────

def build_app() -> Application:
    app = Application.builder().token(settings.bot_token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cookie_add_start, pattern="^cookie:add$")],
        states={
            WAIT_COOKIE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, cookie_add_name)],
            WAIT_COOKIE_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, cookie_add_token)],
        },
        fallbacks=[CommandHandler("cancel", cookie_add_cancel)],
    )
    app.add_handler(conv)

    app.add_handler(CallbackQueryHandler(menu_router, pattern="^(menu|cookie|cfg|autowar):"))

    return app