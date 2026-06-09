"""Background scheduler: auto-war, latency monitor, backup, cookie refresh.
Auto-war now per-user: setiap user punya cookie + saldo → auto-war di jam yg diset admin.
"""

import asyncio
import datetime
import logging
import os
import shutil
import glob
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.config import settings
from src.db import AsyncSessionLocal, WarHistoryModel, LatencyLogModel, CookieModel
from src.cookie_service import get_cookie_token, refresh_cookie_status
from src.war_config_service import load_config
from src.engine.api import measure_latency
from src.engine.war import run_war_sync, WarConfig, WarResultReport
from src.user_service import get_user, get_user_by_id, deduct_balance, add_tickets, list_users
from sqlalchemy import select

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
_notifier: Callable | None = None

# ─── Helpers ───────────────────────────────────────────

async def _get_global_war_time(session) -> tuple[int, int, str]:
    """Get global war time from bot_settings. Default 00:00 Asia/Shanghai."""
    from src.db import BotSettingModel
    r = await session.execute(select(BotSettingModel).where(BotSettingModel.key == "war_hour"))
    wh = int(r.scalar_one_or_none().value) if (s := r.scalar_one_or_none()) and s.value else 0
    r = await session.execute(select(BotSettingModel).where(BotSettingModel.key == "war_minute"))
    wm = int(r.scalar_one_or_none().value) if (s := r.scalar_one_or_none()) and s.value else 0
    r = await session.execute(select(BotSettingModel).where(BotSettingModel.key == "war_tz"))
    tz = r.scalar_one_or_none().value if (s := r.scalar_one_or_none()) and s.value else "Asia/Shanghai"
    return wh, wm, tz

# ─── Latency Monitor ────────────────────────────────────

async def _save_latency():
    """Periodic latency measurement → DB."""
    try:
        lat = await asyncio.to_thread(measure_latency)
        async with AsyncSessionLocal() as session:
            log = LatencyLogModel(latency_ms=lat, timestamp=datetime.datetime.utcnow())
            session.add(log)
            await session.commit()
        logger.info(f"Latency logged: {lat}ms")
    except Exception as e:
        logger.error(f"Latency log failed: {e}")

# ─── Per-User War Runner ─────────────────────────────────

async def _run_war_for_user(user_tg_id: str, notify: Callable | None = None) -> bool:
    """
    Run auto-war untuk satu user.
    - Cek balance
    - Load + decrypt cookie user
    - Run war with proxy pool
    - Deduct balance + award tickets
    - Save history with user_id
    - Notify user
    Returns True kalau sukses, False kalau skip/gagal.
    """
    async with AsyncSessionLocal() as session:
        user = await get_user(session, user_tg_id)
        if not user:
            logger.warning(f"Auto-war skip: user not found {user_tg_id}")
            return False

        if user.is_suspended:
            logger.info(f"Auto-war skip: user {user_tg_id} suspended")
            return False

        if not user.war_enabled:
            logger.info(f"Auto-war skip: user {user.first_name or user_tg_id} disabled auto-war")
            return False

        cfg = await load_config(session, user_tg_id)
        selected_ids: list[int] = cfg.get("cookie_ids", [])

        if not selected_ids:
            logger.info(f"Auto-war skip: no cookies for {user.first_name or user_tg_id}")
            return False

        hero_per_cookie: int = cfg.get("hero_per_cookie", 3)
        cost: int = len(selected_ids)  # 1 tiket = 1 cookie

        if user.balance_war < cost:
            logger.info(f"Auto-war skip: insufficient balance for {user.first_name or user_tg_id} ({user.balance_war} < {cost})")
            if notify:
                await notify(user_tg_id, (
                    f"⚠️ <b>Auto-War Dilewati</b>\n\n"
                    f"Tiket tidak cukup untuk war auto.\n"
                    f"🎫 Tiket: <b>{user.balance_war}</b>\n"
                    f"🎯 Butuh: <b>{cost}</b> tiket ({len(selected_ids)} cookie)\n\n"
                    f"<i>Beli tiket dulu di menu 🎫 Beli Tiket War</i>"
                ))
            return False

        # Deduct balance BEFORE war
        try:
            await deduct_balance(session, user.id, cost)
            logger.info(f"Deducted {cost} tiket from {user.first_name or user_tg_id} (balance now {user.balance_war - cost})")
        except Exception as e:
            logger.error(f"Balance deduct failed for {user_tg_id}: {e}")
            return False

        # Load + decrypt cookies
        cookie_list: list[tuple[str, str]] = []
        for cid in selected_ids:
            try:
                token = await get_cookie_token(session, cid, user_tg_id)
                if token:
                    r = await session.execute(select(CookieModel).where(CookieModel.id == cid, CookieModel.owner_chat_id == user_tg_id))
                    c = r.scalar_one_or_none()
                    cookie_list.append((token, c.name if c else f"Cookie #{cid}"))
            except Exception as e:
                logger.error(f"Decrypt failed for cookie {cid} (user {user_tg_id}): {e}")

    if not cookie_list:
        logger.error(f"Auto-war: no cookies loaded for {user.first_name or user_tg_id}")
        if notify:
            await notify(user_tg_id, "❌ <b>Auto-War Gagal</b>\n\nSemua cookie gagal diload. Cek ulang cookie di menu.")
        return False

    wh, wm, tz_name = 0, 0, "Asia/Shanghai"
    async with AsyncSessionLocal() as session:
        wh, wm, tz_name = await _get_global_war_time(session)

    config = WarConfig(
        cookies=cookie_list,
        hero_per_cookie=hero_per_cookie,
        bracket_factor=cfg["bracket_factor"],
        safety_margin=cfg["safety_margin"],
        hero_spacing_ms=cfg.get("hero_spacing_ms", 0),
        use_pool=True,
        owner_chat_id=user_tg_id,
        debug=False,
        war_hour=wh,
        war_minute=wm,
        war_tz=tz_name,
    )

    logger.info(f"Auto-war: {user.first_name or user_tg_id} — {hero_per_cookie} heroes × {len(cookie_list)} cookies ({cost} tiket)")
    report: WarResultReport = await asyncio.to_thread(run_war_sync, config)

    # Save history + award tickets + final balance
    import json
    async with AsyncSessionLocal() as session:
        history = WarHistoryModel(
            user_id=user.id,
            started_at=report.started_at,
            results=json.dumps([{
                "hero_id": r.hero_id, "success": r.success,
                "code": r.code, "msg": r.msg, "drift_ms": r.drift_ms,
                "cookie_name": r.cookie_name,
            } for r in report.hero_results]),
            success_count=report.success_count,
            fail_count=report.fail_count,
            latency_median_ms=report.latency_median_ms,
        )
        session.add(history)
        await session.commit()

        if report.success_count > 0:
            try:
                await add_tickets(session, user.id, report.success_count)
            except Exception:
                pass

        # Ambil final balance
        user_final = await get_user_by_id(session, user.id)
        final_bal = user_final.balance_war if user_final else "?"

    logger.info(f"Auto-war done: {user.first_name or user_tg_id} ✅{report.success_count} ❌{report.fail_count} | balance={final_bal}")

    # Notify user
    if notify:
        summary = (
            f"{report.format_report()}\n"
            f"{'─' * 28}\n"
            f"🎫 Tiket tersisa: <b>{final_bal}</b>"
        )
        await notify(user_tg_id, summary)

    return True


async def _war_warning_for_user(user_tg_id: str, notify: Callable | None = None):
    """Kirim warning ke satu user 5 menit sebelum war."""
    if not notify:
        return

    async with AsyncSessionLocal() as session:
        user = await get_user(session, user_tg_id)
        if not user or user.is_suspended:
            return

        cfg = await load_config(session, user_tg_id)
        selected_ids = cfg.get("cookie_ids", [])
        if not selected_ids:
            return

        hero_per_cookie = cfg.get("hero_per_cookie", 3)
        cost = len(selected_ids)

        if user.balance_war < cost:
            return

        wh, wm, tz_name = await _get_global_war_time(session)

        from sqlalchemy import select as _sel
        r = await session.execute(
            _sel(LatencyLogModel).order_by(LatencyLogModel.timestamp.desc()).limit(1)
        )
        lat = r.scalar_one_or_none()
        lat_text = f"{lat.latency_ms}ms" if lat else "unknown"

    target_label = f"{wh:02d}:{wm:02d} {tz_name}"
    msg = (
        f"⚡ <b>War Otomatis Malam Ini!</b>\n\n"
        f"Auto-war dalam ~5 menit ({target_label})\n\n"
        f"⚡ Latensi: {lat_text}\n"
        f"🥊 Hero/cookie: {hero_per_cookie}\n"
        f"🍪 Cookie: {len(selected_ids)}\n"
        f"🔄 Request: {hero_per_cookie * len(selected_ids)}\n"
        f"🎫 Tiket: {user.balance_war} → {user.balance_war - cost}\n\n"
        f"<i>Pastikan koneksi stabil.</i>"
    )
    await notify(user_tg_id, msg)


# ─── Main Scheduler Setup ───────────────────────────────

def start_scheduler(get_notifier: Callable | None = None):
    """Start all background scheduler jobs."""
    global _notifier
    _notifier = get_notifier

    # 1. Latency monitoring every 15 minutes
    scheduler.add_job(
        _save_latency,
        trigger=IntervalTrigger(minutes=15),
        id="latency_monitor",
        name="Latency Monitor",
        replace_existing=True,
    )

    # 2. Dynamic auto-war checker — runs every minute
    _war_triggered_today: dict[str, bool] = {}
    _warned_today: dict[str, bool] = {}

    async def _dynamic_war_checker():
        """Check every minute: if close to war time → warn or execute for ALL users."""
        async with AsyncSessionLocal() as session:
            wh, wm, tz_name = await _get_global_war_time(session)

        # Calc diff to target
        from datetime import timezone as dt_tz, timedelta
        from src.engine.war import timezone_offset
        offset_h = timezone_offset(tz_name)
        tz = dt_tz(timedelta(hours=offset_h))
        now = datetime.datetime.now(tz)
        now_minutes = now.hour * 60 + now.minute
        target_minutes = wh * 60 + wm

        diff = target_minutes - now_minutes
        if diff < 0:
            diff += 24 * 60

        # Reset daily trackers at midnight
        if now_minutes < 1:
            _war_triggered_today.clear()
            _warned_today.clear()

        # Get ALL users (bukan cuma admin)
        async with AsyncSessionLocal() as session:
            from src.db import UserModel
            r = await session.execute(select(UserModel).where(UserModel.is_suspended == False, UserModel.war_enabled == True))
            users = r.scalars().all()

        for user in users:
            uid_str = user.telegram_id
            try:
                # 5 min warning
                if diff == 5 and not _warned_today.get(uid_str):
                    _warned_today[uid_str] = True
                    await _war_warning_for_user(uid_str, notify=_notifier)

                # 3 min trigger → execute war
                if 0 < diff <= 3 and not _war_triggered_today.get(uid_str):
                    _war_triggered_today[uid_str] = True
                    logger.info(f"Auto-war trigger for {user.first_name or uid_str} ({diff}min to target)")
                    await _run_war_for_user(uid_str, notify=_notifier)

            except Exception as e:
                logger.error(f"Dynamic war checker error for {uid_str}: {e}")

    scheduler.add_job(
        _dynamic_war_checker,
        trigger=IntervalTrigger(minutes=1),
        id="dynamic_war_checker",
        name="Dynamic War Checker (All Users)",
        replace_existing=True,
    )

    # 3. Daily cookie auto-refresh at 10:00 CST — ALL users
    async def _auto_refresh_cookies():
        """Refresh status semua cookie MILIK SEMUA user."""
        async with AsyncSessionLocal() as session:
            r = await session.execute(select(CookieModel))
            cookies = list(r.scalars().all())
            refreshed = 0
            failed = 0
            per_user: dict[str, int] = {}
            for c in cookies:
                try:
                    await refresh_cookie_status(session, c.id, c.owner_chat_id)
                    refreshed += 1
                    per_user[c.owner_chat_id] = per_user.get(c.owner_chat_id, 0) + 1
                except Exception as e:
                    logger.error(f"Auto-refresh failed for cookie {c.id}: {e}")
                    failed += 1
            await session.commit()
            logger.info(f"Auto-refresh done: {refreshed} ok, {failed} failed across {len(per_user)} users")

            # Notify admin aja soal status global
            if _notifier and failed > 0:
                for uid in settings.admin_ids:
                    await _notifier(str(uid), (
                        f"🍪 <b>Auto-Refresh Cookie Harian</b>\n\n"
                        f"✅ {refreshed} berhasil\n"
                        f"❌ {failed} gagal\n"
                        f"👥 {len(per_user)} user terpantau\n\n"
                        f"<i>Cek menu Cookies untuk detail.</i>"
                    ))

    scheduler.add_job(
        _auto_refresh_cookies,
        trigger=CronTrigger(hour=10, minute=0, timezone="Asia/Shanghai"),
        id="cookie_auto_refresh",
        name="Cookie Auto Refresh (All Users)",
        replace_existing=True,
    )

    # 4. Daily DB backup at 02:00 CST
    async def _backup_db():
        """Backup database to data/backups/, keep 7 days."""
        backup_dir = "data/backups"
        os.makedirs(backup_dir, exist_ok=True)
        db_path = "data/kewarmibot.db"

        if not os.path.exists(db_path):
            logger.warning("DB backup skipped: database file not found")
            return

        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = os.path.join(backup_dir, f"kewarmibot-{ts}.db")

        try:
            shutil.copy2(db_path, dest)
            logger.info(f"DB backup created: {dest}")

            pattern = os.path.join(backup_dir, "kewarmibot-*.db")
            backups = sorted(glob.glob(pattern))
            cutoff = datetime.datetime.now() - datetime.timedelta(days=7)
            deleted = 0
            for bkp in backups:
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(bkp))
                if mtime < cutoff:
                    os.remove(bkp)
                    deleted += 1
            if deleted:
                logger.info(f"Cleaned up {deleted} old backup(s)")
        except Exception as e:
            logger.error(f"DB backup failed: {e}")
            if _notifier:
                for uid in settings.admin_ids:
                    await _notifier(str(uid), f"🗄️ <b>DB Backup Gagal!</b>\n\nError: {e}")

    scheduler.add_job(
        _backup_db,
        trigger=CronTrigger(hour=2, minute=0, timezone="Asia/Shanghai"),
        id="db_backup",
        name="Daily DB Backup",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started: latency + per-user auto-war + per-user cookie refresh + DB backup")