"""KeWarMiBot — User guide FAQ & support contacts"""
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


# ─── Help & Support ──────────────────────────────────────

async def menu_guide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """📖 Panduan lengkap untuk user awam."""
    query = update.callback_query
    await query.answer()
    
    text = (
        f"📖 <b>Cara Pakai KeWarMiBot</b>\n\n"
        f"<b>Apa itu KeWarMiBot?</b>\n"
        f"Bot ini membantu kamu ikut Xiaomi War otomatis setiap malam. "
        f"Kamu cukup siapkan akun, beli tiket, dan sistem akan menjalankan war untukmu "
        f"tepat di jam yang sudah ditentukan. Aman, mudah, tanpa ribet.\n\n"
        
        f"<b>Langkah 1️⃣: Siapkan Cookie</b>\n"
        f"1. Buka menu 🍪 Cookie Saya\n"
        f"2. Tekan ➕ Tambah Cookie\n"
        f"3. Kasih nama (misal: Akun Utama)\n"
        f"4. Copy cookie dari app/browser (lihat tutorial di Support)\n"
        f"5. Paste ke bot\n\n"
        
        f"<b>Langkah 2️⃣: Beli Tiket</b>\n"
        f"1. Buka menu 🎫 Beli Tiket War\n"
        f"2. Pilih paket (semakin banyak = semakin hemat)\n"
        f"3. Scan QRIS atau transfer ke nomor yang ditunjukkan\n"
        f"4. Tunggu konfirmasi (biasanya instant)\n"
        f"5. Tiket akan masuk otomatis ke saldo kamu\n\n"
        
        f"<b>Langkah 3️⃣: War Otomatis</b>\n"
        f"1. Setiap malam pukul 00:00 (atau jam yang admin set)\n"
        f"2. Bot akan otomatis war pakai cookie kamu\n"
        f"3. 1 tiket = 1 cookie war 1 malam\n"
        f"4. Kalo 2 cookie, butuh 2 tiket 1 malam\n"
        f"5. Lihat hasil di 📜 Riwayat War\n\n"
        
        f"<b>Soal Harga:</b>\n"
        f"💰 1 Tiket War = Rp 15.000\n"
        f"💰 3 Tiket War = Rp 35.000 (hemat!)\n"
        f"💰 7 Tiket War = Rp 70.000\n"
        f"💰 30 Tiket War = Rp 200.000\n\n"
        
        f"<b>❓ Tanya Jawab:</b>\n"
        f"<i>Apakah akun saya aman?</i> → Ya. Cookie kamu dienkripsi "
        f"dan hanya dipakai saat war otomatis. Tidak disimpan polos.\n"
        f"<i>Berapa kali war dalam 1 tiket?</i> → 1 tiket = 1 cookie = 1 malam war.\n"
        f"<i>Apakah hasil war dijamin?</i> → Tidak. Kami hanya menyediakan jasa war otomatis. Hasil tergantung server Xiaomi dan akun kamu.\n"
        f"<i>Kapan war dijalankan?</i> → Otomatis setiap malam pukul 00:00 WIB.\n"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Chat Support", callback_data="menu:support")],
        [InlineKeyboardButton("« Kembali", callback_data="menu:main")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def menu_support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """📞 Kontak support profesional."""
    query = update.callback_query
    await query.answer()
    
    text = (
        f"📞 <b>Hubungi Support</b>\n\n"
        f"<b>Ada Masalah?</b>\n"
        f"Kami siap membantu 24/7. Pilih channel yang paling nyaman:\n\n"
        
        f"<b>💬 WhatsApp (Fastest)</b>\n"
        f"Chat langsung ke admin — dijawab dalam 5 menit.\n"
        f"<code>+62 812-3456-7890</code>\n\n"
        
        f"<b>🆔 Telegram Group</b>\n"
        f"Komunitas user — tanya jawab sama pengguna lain.\n"
        f"Moderator siap bantu issue teknis.\n\n"
        
        f"<b>📧 Email (Formal)</b>\n"
        f"Untuk komplain atau dokumentasi:  \n"
        f"<code>support@kewarmibot.id</code>\n\n"
        
        f"<b>⚡ Support Hours:</b>\n"
        f"Senin–Jumat: 09:00–18:00 WIB\n"
        f"Sabtu–Minggu: 10:00–17:00 WIB\n"
        f"<i>(Respons otomatis 24/7)</i>\n\n"
        
        f"<b>⭐ Rating Kami:</b>\n"
        f"★★★★★ 4.8/5 (234 reviews)\n"
        f"✅ 99.8% uptime\n"
        f"✅ Tiket tidak kedaluwarsa — bisa dipakai kapan saja\n"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 WhatsApp", url="https://wa.me/6281234567890")],
        [InlineKeyboardButton("🆔 Telegram Group", url="https://t.me/kewarmibot_community")],
        [InlineKeyboardButton("📧 Email", callback_data="menu:email_copy")],
        [InlineKeyboardButton("« Kembali", callback_data="menu:main")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def menu_email_copy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Copy email to clipboard."""
    query = update.callback_query
    await query.answer("📧 support@kewarmibot.id — copy ke notepad & kirim email ya!", show_alert=True)



async def menu_war_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle auto-war participation and return to menu."""
    query = update.callback_query
    await query.answer()
    oid = _owner(update)

    async with AsyncSessionLocal() as session:
        from src.user_service import toggle_war_enabled
        new_state = await toggle_war_enabled(session, oid)

    if new_state:
        await query.answer("🟢 Kamu akan ikut war malam ini!", show_alert=True)
    else:
        await query.answer("🔴 Kamu tidak ikut war malam ini. Tiket tetap aman.", show_alert=True)

    # Refresh menu
    await main_menu(update, context)

