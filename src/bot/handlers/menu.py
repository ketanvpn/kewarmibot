"""KeWarMiBot — Main menu, /start, /admin"""
from src.bot.handlers._common import *

# ─── Main Menu ─────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User menu — /start command. Auto-register."""
    tg_id = owner_id(update)
    async with AsyncSessionLocal() as session:
        await get_or_create_user(session, tg_id,
            update.effective_chat.username,
            update.effective_chat.first_name,
            update.effective_chat.last_name)
    await main_menu(update, context)

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
    oid = owner_id(update)

    # Fetch all state
    cfg = await cfg_dict(update)
    cookies = await cookies_list(update)

    # Auto-war status from DB
    async with AsyncSessionLocal() as session:
        user = await get_user(session, oid)
        aw_enabled = user.war_enabled if user else True
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

    kb = await build_main_kb(update)

    if query:
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

