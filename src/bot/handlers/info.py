"""KeWarMiBot — Status dashboard, history, stats"""
from src.bot.handlers._common import *


# ─── Status Menu ───────────────────────────────────────

async def menu_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_owner(update):
        return

    # Latency live
    lat = measure_latency(samples=3)

    # Latency stats dari DB
    import datetime as _dt
    cutoff = _dt.datetime.utcnow() - _dt.timedelta(hours=6)
    async with AsyncSessionLocal() as sess:
        r = await sess.execute(
            select(LatencyLogModel)
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
    remain_s = (target - int(_time.time() * 1000)) // 1000
    h, rem = divmod(abs(remain_s), 3600)
    m, s = divmod(rem, 60)

    cookies = await cookies_list()

    lines = [
        "📊 <b>Status</b>",
        f"⚡ Latency live: <b>{lat}ms</b>",
        f"⏰ Reset berikutnya: {int(h):02d}:{int(m):02d}:{int(s):02d}",
        "",
    ]

    if stats["latest"] is not None:
        lines.append(f"📈 Latency 6h: min {stats['min']}ms / avg {stats['avg']}ms / max {stats['max']}ms")
        spark = "".join(spark_block(v["ms"], stats["min"], stats["max"]) for v in stats["samples"][-24:])
        lines.append(f"📉 {spark}")
    else:
        lines.append("📈 Belum ada data latency.")

    lines.append("")
    lines.append("<b>Cookies:</b>")
    for c in cookies:
        emoji, status = status_label(c)
        won = "🏆 " if c.has_won else ""
        lines.append(f"{emoji} {won}<b>{c.name}</b>: {status}")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="menu:status"),
         back_button()],
    ])
    await query.edit_message_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML)


# ─── History ───────────────────────────────────────────

async def menu_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_owner(update):
        return

    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(WarHistoryModel)
            .order_by(WarHistoryModel.started_at.desc())
            .limit(15)
        )
        history = list(r.scalars().all())

    if not history:
        kb = InlineKeyboardMarkup([[back_button()]])
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
        [back_button()],
    ])
    await query.edit_message_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML)


# ─── Cookie Statistics ─────────────────────────────────

async def menu_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Akumulasi success rate per cookie dari semua history."""
    query = update.callback_query
    await query.answer()

    if not is_owner(update):
        return

    from collections import defaultdict
    cookie_stats = defaultdict(lambda: {"success": 0, "fail": 0})

    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(WarHistoryModel)
            .order_by(WarHistoryModel.started_at.desc())
            .limit(200)
        )
        history = list(r.scalars().all())

    if not history:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="menu:history")]])
        await query.edit_message_text("📊 <b>Statistik Cookie</b>\n\nBelum ada data war.", reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    # Parse semua results JSON
    for h in history:
        if h.results:
            try:
                heroes = json.loads(h.results)
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
        await query.edit_message_text("📊 <b>Statistik Cookie</b>\n\nTidak ada data.", reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    lines = [
        "📊 <b>Statistik Cookie</b>",
        f"📜 Dari {len(history)} sesi war terakhir\n",
    ]

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
