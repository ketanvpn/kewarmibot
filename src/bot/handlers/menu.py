"""KeWarMiBot — Main menu, /start, /admin"""
from src.bot.handlers._common import *

# ─── /start — User Welcome (public) ────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User /start — welcome then main menu."""
    oid = owner_id(update)
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, oid,
            update.effective_chat.username,
            update.effective_chat.first_name,
            update.effective_chat.last_name)
        bal = user.balance_war if user else 0

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
            f"🎫 Tiket kamu: <b>{bal}</b>\n"
            f"📖 <i>Panduan lengkap: tombol 📖 Panduan</i>"
        )
        await update.message.reply_text(welcome, parse_mode=ParseMode.HTML)

    await main_menu(update, context)


# ─── /menu — Quick Main Menu (no welcome) ──────────────

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/menu — langsung ke main menu tanpa welcome."""
    await main_menu(update, context)


# ─── /admin — Admin Dashboard (admin only) ─────────────

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/admin — shows admin dashboard."""
    oid = owner_id(update)
    if oid not in {str(x) for x in settings.admin_ids} and oid != "690744680":
        await update.message.reply_text("⛔ Akses ditolak — admin only.", parse_mode=ParseMode.HTML)
        return

    # Reuse same dashboard as menu_admin callback
    from src.bot.handlers.admin import menu_admin
    # Fake a callback_query from this message
    class FakeQ:
        data = "menu:admin"
        def __init__(self, msg): self.message = msg
        async def answer(self, *a, **kw): pass
        async def edit_message_text(self, text, **kw):
            return await self.message.reply_text(text, **kw)
    update.callback_query = FakeQ(update.message)
    await menu_admin(update, context)


# ─── Main Menu — Public User Panel ─────────────────────

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

    kb = user_main_kb(update, aw_enabled)

    if query:
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ─── User-Only Keyboard ────────────────────────────────

def user_main_kb(update: Update, war_enabled: bool = True) -> InlineKeyboardMarkup:
    """Public user main menu keyboard."""
    toggle = "🟢" if war_enabled else "🔴"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🍪 Cookie Saya", callback_data="menu:cookies"),
         InlineKeyboardButton("🎫 Beli Tiket", callback_data="menu:beli")],
        [InlineKeyboardButton("📜 Riwayat War", callback_data="menu:history"),
         InlineKeyboardButton("👤 Profil Saya", callback_data="menu:profile")],
        [InlineKeyboardButton("📖 Panduan", callback_data="menu:guide"),
         InlineKeyboardButton(f"⏰ {toggle}", callback_data="menu:autowar")],
        [InlineKeyboardButton("💬 Support", callback_data="menu:support")],
    ])