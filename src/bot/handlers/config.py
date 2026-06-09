"""KeWarMiBot — War config editor"""
from src.bot.handlers._common import *

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

