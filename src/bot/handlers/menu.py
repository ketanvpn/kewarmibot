"""KeWarMiBot — Main menu, /start"""
from src.bot.handlers._common import *


# ─── /start — Welcome ───────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner /start — welcome then main menu."""
    if not is_owner(update):
        await update.message.reply_text("⛔ Bot ini hanya untuk owner.", parse_mode=ParseMode.HTML)
        return

    if update.message:
        welcome = (
            f"<b>⚔️ KeWarMiBot v3.0</b>\n"
            f"<i>Xiaomi Bootloader Unlock — Automated War</i>\n"
            f"{SEP}\n"
            f"👋 Selamat datang, Bos!\n\n"
            f"Bot ini bantu kamu <b>war unlock Xiaomi</b> otomatis tiap malam.\n\n"
            f"<b>2 Langkah:</b>\n"
            f"1️⃣ 🍪 <b>Tambah Cookie</b> — login Xiaomi\n"
            f"2️⃣ ⚔️ <b>War Otomatis</b> — sesuai jadwal\n\n"
            f"📖 <i>Panduan: tombol 📖 Panduan</i>"
        )
        await update.message.reply_text(welcome, parse_mode=ParseMode.HTML)

    await main_menu(update, context)


# ─── /menu — Quick Main Menu ───────────────────────────

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update):
        return
    await main_menu(update, context)


# ─── Main Menu ──────────────────────────────────────────

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    if not is_owner(update):
        return

    cfg = await cfg_dict()
    cookies = await cookies_list()

    # Cookie selection status
    selected_ids = cfg.get("cookie_ids", [])
    cookie_status = []
    for c in cookies:
        sel = "✅" if c.id in selected_ids else "⬜"
        _, st = status_label(c)
        won = "🏆 " if c.has_won else ""
        cookie_status.append(f"  {sel} {won}<b>{c.name}</b> — {st}")
    if not cookies:
        cookie_status.append("  ❗ <i>Belum ada cookie — tambah di 🍪 Cookie</i>")

    # Countdown
    target = get_next_beijing_midnight_ms()
    cd = countdown_text(target)

    selected_count = len(selected_ids)
    hero_per = cfg.get("hero_per_cookie", 6)
    autowar_on = cfg.get("autowar_enabled", True)

    text = (
        f"<b>⚔️ KeWarMiBot</b> <code>v3.0</code>\n"
        f"<i>Xiaomi Bootloader Unlock — Automated War</i>\n"
        f"{SEP}\n"
        f"⏰ Reset: <code>{cd}</code>\n"
        f"🤖 Auto-War: {'🟢 ON' if autowar_on else '🔴 OFF'}\n"
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

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🍪 Cookie", callback_data="menu:cookies"),
         InlineKeyboardButton("⚙️ Config", callback_data="menu:config")],
        [InlineKeyboardButton(
            f"🤖 Auto-War: {'ON' if autowar_on else 'OFF'}",
            callback_data="menu:autowar")],
        [InlineKeyboardButton("⚔️ War Sekarang", callback_data="menu:war_debug"),
         InlineKeyboardButton("🔌 Proxy Pool", callback_data="pool:menu")],
        [InlineKeyboardButton("📜 Riwayat", callback_data="menu:history"),
         InlineKeyboardButton("📊 Status", callback_data="menu:status")],
        [InlineKeyboardButton("📖 Panduan", callback_data="menu:guide")],
    ])

    if query:
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
