"""KeWarMiBot — Main menu, /start, /admin"""
from src.bot.handlers._common import *

# ─── /start — Welcome + Main Menu ──────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User menu — /start command. Register user + show welcome + main menu."""
    oid = owner_id(update)
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, oid,
            update.effective_chat.username,
            update.effective_chat.first_name,
            update.effective_chat.last_name)

    # Welcome message (only for /start command, not callback refreshes)
    if update.message:
        welcome = (
            f"<b>⚔️ KeWarMiBot v2.0</b>\n"
            f"<i>Xiaomi Bootloader Unlock — Automated War</i>\n"
            f"{SEP}\n"
            f"👋 Selamat datang, <b>{user.first_name or 'User'}</b>!\n\n"
            f"Bot ini bantu kamu <b>war unlock Xiaomi</b> otomatis tiap malam.\n\n"
            f"<b>3 Langkah:</b>\n"
            f"1️⃣ 🍪 <b>Tambah Cookie</b> — login Xiaomi\n"
            f"2️⃣ 🎫 <b>Beli Tiket</b> — Rp 15rb via QRIS\n"
            f"3️⃣ ⚔️ <b>War Otomatis</b> — tiap jam 00:00 WIB\n\n"
            f"📖 <i>Panduan lengkap: menu 📖 Panduan</i>"
        )
        await update.message.reply_text(welcome, parse_mode=ParseMode.HTML)

    await main_menu(update, context)


# ─── /admin — Admin Panel (admin-only) ─────────────────

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin panel — /admin command. Locked to admin only."""
    oid = owner_id(update)
    if oid not in {str(x) for x in settings.admin_ids} and oid != "690744680":
        await update.message.reply_text("⛔ Akses ditolak.", parse_mode=ParseMode.HTML)
        return

    async with AsyncSessionLocal() as session:
        from src.user_service import user_count as uc
        from src.package_service import revenue_today as rt
        total_users = await uc(session)
        revenue = await rt(session)

    text = (
        f"🛡️ <b>Admin Panel</b>\n"
        f"{SEP}\n"
        f"👥 Total User: <b>{total_users}</b>\n"
        f"💰 Revenue Hari Ini: <b>Rp {revenue:,}</b>\n"
        f"{SEP}\n"
        f"<i>Panel administrasi lengkap:</i>"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Kelola User", callback_data="admin:users"),
         InlineKeyboardButton("📦 Kelola Paket", callback_data="admin:packages")],
        [InlineKeyboardButton("💳 Payment Settings", callback_data="admin:settings"),
         InlineKeyboardButton("📊 Revenue", callback_data="admin:revenue")],
        [InlineKeyboardButton("🔌 Pool Proxy", callback_data="pool:menu"),
         InlineKeyboardButton("📊 Status Server", callback_data="menu:status")],
        [InlineKeyboardButton("« Menu Utama", callback_data="menu:main")],
    ])
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ─── Main Menu — User Panel ───────────────────────────

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    oid = owner_id(update)

    cfg = await cfg_dict(update)
    cookies = await cookies_list(update)

    async with AsyncSessionLocal() as session:
        user = await get_user(session, oid)
        aw_enabled = user.war_enabled if user else True
        bal = user.balance_war if user else 0
    aw_text = "🟢 AKTIF" if aw_enabled else "🔴 NONAKTIF"

    # Cookie selection status
    selected_ids = cfg.get("cookie_ids", [])
    cookie_status = []
    for c in cookies:
        sel = "✅" if c.id in selected_ids else "⬜"
        _, st = status_label(c)
        cookie_status.append(f"  {sel} <b>{c.name}</b> — {st}")
    if not cookies:
        cookie_status.append("  ❗ <i>Belum ada cookie — tambah di 🍪 Cookie</i>")

    # Countdown
    target = get_next_beijing_midnight_ms()
    cd = countdown_text(target)

    selected_count = len(selected_ids)
    hero_per = cfg.get("hero_per_cookie", 6)

    text = (
        f"<b>⚔️ KeWarMiBot</b> <code>v2.0</code>\n"
        f"<i>Xiaomi Bootloader Unlock — Automated War</i>\n"
        f"{SEP}\n"
        f"⏰ Reset: <code>{cd}</code>\n"
        f"🎫 Tiket: <b>{bal}</b>  ·  ⚡ Auto-War: <b>{aw_text}</b>\n"
    )
    if selected_count > 0:
        text += f"🥊 Siap: <b>{selected_count} cookie</b> × <b>{hero_per} hero</b> = <b>{hero_per * selected_count} tembakan</b>\n"
    text += (
        f"{SEP}\n"
        f"🍪 <b>Cookie War</b> ({selected_count}/{MAX_COOKIES_PER_WAR}):\n" +
        "\n".join(cookie_status) + "\n" +
        f"{SEP}\n"
        f"<b>📋 Menu:</b>"
    )

    kb = await build_main_kb(update)

    if query:
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)