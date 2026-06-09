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
    Run auto-war untuk satu user via execute_war().
    """
    from src.engine.war_runner import execute_war

    # Pre-check: suspended + war_enabled + has cookies
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

    report = await execute_war(user_tg_id, debug=False, deduct=True, notify=notify)
    return report is not None


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
                    asyncio.create_task(_war_warning_for_user(uid_str, notify=_notifier))

                # 3 min trigger → execute war
                if 0 < diff <= 3 and not _war_triggered_today.get(uid_str):
                    _war_triggered_today[uid_str] = True
                    logger.info(f"Auto-war trigger for {user.first_name or uid_str} ({diff}min to target)")
                    asyncio.create_task(_run_war_for_user(uid_str, notify=_notifier))

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