"""KeWarMiBot — Panduan singkat (single-owner)"""
from src.bot.handlers._common import *

# ─── Panduan ─────────────────────────────────────────────

async def menu_guide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """📖 Panduan singkat single-owner."""
    query = update.callback_query
    await query.answer()

    if not is_owner(update):
        return

    text = (
        f"📖 <b>Cara Pakai KeWarMiBot</b>\n\n"
        f"Bot ini menjalankan <b>Xiaomi Bootloader Unlock War</b> otomatis tiap malam "
        f"sesuai jadwal yang kamu set.\n\n"
        f"<b>Langkah 1️⃣: Tambah Cookie</b>\n"
        f"1. Buka menu 🍪 Cookie\n"
        f"2. Tekan ➕ Tambah Cookie\n"
        f"3. Kasih nama (misal: Akun Utama)\n"
        f"4. Paste cookie dari Xiaomi Community app\n\n"
        f"🔑 <b>Cara Ambil Cookie di Android</b>\n"
        f"1. Install network sniffer (Proxyman / HTTP Toolkit / HTTP Sniffer / PCAPdroid)\n"
        f"2. Jalankan sniffer — izinkan VPN saat diminta\n"
        f"3. Buka Xiaomi Community app → tab <b>Me</b>\n"
        f"4. Masuk ke halaman <b>Unlock Bootloader</b>\n"
        f"5. Balik ke sniffer, matikan VPN/service\n"
        f"6. Cari URL:\n"
        f"   <code>sgp-api.buy.mi.com/bbs/api/global/apply/bl-auth</code>\n"
        f"7. Buka <b>Headers</b> → cari <b>Cookie:</b>\n"
        f"8. Salin text panjang setelah <b>Cookie:</b>\n"
        f"   (yang berawalan <code>new_bbs_serviceToken</code>)\n"
        f"9. Paste ke bot\n\n"
        f"<b>Langkah 2️⃣: Pilih Cookie buat War</b>\n"
        f"Di menu 🍪 Cookie, tap cookie → toggle ✅ biar ikut war.\n\n"
        f"<b>Langkah 3️⃣: Atur & Aktifkan Auto-War</b>\n"
        f"1. ⚙️ Config — set jam war, hero/cookie, bracket, safety margin\n"
        f"2. 🤖 Auto-War — pastikan status 🟢 ON\n"
        f"3. Bot otomatis war tiap malam sesuai jadwal\n"
        f"4. Mau tes manual? Tap ⚔️ War Sekarang\n"
        f"5. Lihat hasil di 📜 Riwayat\n\n"
        f"<b>🔌 Proxy (opsional, multi-cookie)</b>\n"
        f"Cookie 1 pakai IP VPS langsung. Cookie ke-2+ butuh 1 proxy per cookie "
        f"(tiap cookie 1 IP konsisten). Tambah proxy di 🔌 Proxy Pool.\n\n"
        f"<b>ℹ️ Catatan</b>\n"
        f"• 1 IP biasanya cuma 1 hero yang lolos — multi-hero dipakai sebagai jaring timing\n"
        f"• Cookie yang dapat tiket otomatis di-lock & keluar dari config\n"
        f"• Cookie dienkripsi AES-256, cuma didekripsi saat war\n"
    )

    kb = InlineKeyboardMarkup([[back_button()]])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ─── Deprecated stubs (router compat, single-owner) ──────

async def menu_support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Single-owner: no support desk. Redirect to panduan."""
    await menu_guide(update, context)


async def menu_email_copy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deprecated (single-owner) — kept for router compatibility."""
    query = update.callback_query
    await query.answer()
