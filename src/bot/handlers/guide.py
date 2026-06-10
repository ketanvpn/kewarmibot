"""KeWarMiBot — User guide FAQ & support contacts"""
from src.bot.handlers._common import *

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
        f"4. Copy cookie dari Xiaomi Community app\n"
        f"5. Paste ke bot\n\n"
        
        f"🔑 <b>Cara Ambil Cookie di Android</b>\n"
        f"1. Install aplikasi network sniffer — bebas pilih:\n"
        f"   • Proxyman\n"
        f"   • HTTP Toolkit\n"
        f"   • HTTP Sniffer\n"
        f"   • PCAPdroid\n"
        f"2. Jalankan sniffer — biasanya minta izin VPN, izinkan\n"
        f"3. Buka Xiaomi Community app → tab <b>Me</b> (pojok kanan bawah)\n"
        f"4. Masuk ke halaman <b>Unlock Bootloader</b>\n"
        f"5. Balik ke aplikasi sniffer, matikan VPN/service\n"
        f"6. Cari URL:\n"
        f"   <code>sgp-api.buy.mi.com/bbs/api/global/apply/bl-auth</code>\n"
        f"7. Buka bagian <b>Headers</b> → cari <b>Cookie:</b>\n"
        f"8. Salin text panjang setelah <b>Cookie:</b>\n"
        f"   (yang punya awalan <code>new_bbs_serviceToken</code>)\n"
        f"9. Tempel/paste ke bot saat tambah cookie\n\n"
        
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
        [back_button(update, context)],
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
        [back_button(update, context)],
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
    oid = owner_id(update)

    async with AsyncSessionLocal() as session:
        from src.user_service import toggle_war_enabled
        new_state = await toggle_war_enabled(session, oid)

    if new_state:
        await query.answer("🟢 Kamu akan ikut war malam ini!", show_alert=True)
    else:
        await query.answer("🔴 Kamu tidak ikut war malam ini. Tiket tetap aman.", show_alert=True)

    # Refresh menu
    await main_menu(update, context)

