"""Background scheduler: auto-war, latency monitor, backup, cookie refresh.
Single-owner mode — no user loop, just run for owner.
"""

import asyncio
import datetime
import logging
import os
import glob
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.config import settings
from src.db import AsyncSessionLocal, WarHistoryModel, LatencyLogModel, CookieModel
from src.cookie_service import refresh_cookie_status
from src.war_config_service import load_config
from src.engine.api import measure_latency
from sqlalchemy import select

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
_notifier: Callable | None = None


# ─── Helpers ───────────────────────────────────────────

async def _get_war_time() -> tuple[int, int, str]:
    """Get war time from config. Default 00:00 Asia/Shanghai."""
    async with AsyncSessionLocal() as session:
        cfg = await load_config(session)
    return cfg.get("war_hour", 0), cfg.get("war_minute", 0), cfg.get("war_tz", "Asia/Shanghai")

async def _get_war_cfg() -> dict:
    """Full war config dict."""
    async with AsyncSessionLocal() as session:
        return await load_config(session)


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


# ─── Auto-War (Single Owner) ─────────────────────────────

async def _run_auto_war(notify: Callable | None = None) -> bool:
    """Run auto-war for owner. Catches errors → notif owner (jangan silent-fail)."""
    from src.engine.war_runner import execute_war
    try:
        report = await execute_war(debug=False, notify=notify)
        return report is not None
    except Exception as e:
        logger.error(f"Auto-war crashed: {e}", exc_info=True)
        if notify:
            try:
                await notify(settings.owner_chat_id, f"❌ <b>Auto-War Gagal!</b>\n\nError: {e}")
            except Exception:
                pass
        return False


async def _war_warning(notify: Callable | None = None):
    """Send warning 5 minutes before war."""
    if not notify:
        return

    owner = settings.owner_chat_id

    async with AsyncSessionLocal() as session:
        cfg = await load_config(session)
        selected_ids = cfg.get("cookie_ids", [])
        if not selected_ids:
            return

        hero_per_cookie = cfg.get("hero_per_cookie", 6)
        wh = cfg.get("war_hour", 0)
        wm = cfg.get("war_minute", 0)
        tz_name = cfg.get("war_tz", "Asia/Shanghai")

        r = await session.execute(
            select(LatencyLogModel).order_by(LatencyLogModel.timestamp.desc()).limit(1)
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
        f"🔄 Request: {hero_per_cookie * len(selected_ids)}\n\n"
        f"<i>Pastikan koneksi stabil.</i>"
    )
    await notify(owner, msg)


# ─── Main Scheduler Setup ───────────────────────────────

_war_triggered_date: str | None = None
_warned_date: str | None = None


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
    async def _dynamic_war_checker():
        """Check every minute: if close to war time → warn or execute."""
        global _war_triggered_date, _warned_date

        wh, wm, tz_name = await _get_war_time()

        # Calc diff to target
        from datetime import timezone as dt_tz, timedelta
        from src.engine.war import timezone_offset
        offset_h = timezone_offset(tz_name)
        tz = dt_tz(timedelta(hours=offset_h))
        now = datetime.datetime.now(tz)
        now_minutes = now.hour * 60 + now.minute
        target_minutes = wh * 60 + wm
        today = now.date().isoformat()

        diff = target_minutes - now_minutes
        if diff < 0:
            diff += 24 * 60

        try:
            # 5 min warning (once per date)
            if diff == 5 and _warned_date != today:
                cfg = await _get_war_cfg()
                if cfg.get("autowar_enabled", True):
                    _warned_date = today
                    asyncio.create_task(_war_warning(notify=_notifier))

            # 3 min trigger → execute war (once per date)
            if 0 < diff <= 3 and _war_triggered_date != today:
                cfg = await _get_war_cfg()
                if cfg.get("autowar_enabled", True):
                    _war_triggered_date = today
                    logger.info(f"Auto-war trigger ({diff}min to target)")
                    asyncio.create_task(_run_auto_war(notify=_notifier))
                else:
                    logger.info("Auto-war disabled — skip trigger")

        except Exception as e:
            logger.error(f"Dynamic war checker error: {e}")

    scheduler.add_job(
        _dynamic_war_checker,
        trigger=IntervalTrigger(minutes=1),
        id="dynamic_war_checker",
        name="Dynamic War Checker",
        replace_existing=True,
    )

    # 3. Daily cookie auto-refresh at 10:00 CST
    async def _auto_refresh_cookies():
        """Refresh status all cookies for owner."""
        async with AsyncSessionLocal() as session:
            from src.cookie_service import list_cookies
            cookies = await list_cookies(session)
            refreshed = 0
            failed = 0
            for c in cookies:
                try:
                    await refresh_cookie_status(session, c.id)
                    refreshed += 1
                except Exception as e:
                    logger.error(f"Auto-refresh failed for cookie {c.id}: {e}")
                    failed += 1
            await session.commit()
            logger.info(f"Auto-refresh done: {refreshed} ok, {failed} failed")

            if _notifier and failed > 0:
                await _notifier(settings.owner_chat_id, (
                    f"🍪 <b>Auto-Refresh Cookie Harian</b>\n\n"
                    f"✅ {refreshed} berhasil\n"
                    f"❌ {failed} gagal\n\n"
                    f"<i>Cek menu Cookies untuk detail.</i>"
                ))

    scheduler.add_job(
        _auto_refresh_cookies,
        trigger=CronTrigger(hour=10, minute=0, timezone="Asia/Shanghai"),
        id="cookie_auto_refresh",
        name="Cookie Auto Refresh",
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
            import sqlite3

            with sqlite3.connect(db_path) as src, sqlite3.connect(dest) as dst:
                src.backup(dst)

            with sqlite3.connect(dest) as check:
                result = check.execute("PRAGMA quick_check").fetchone()
                if not result or result[0] != "ok":
                    raise RuntimeError(f"backup integrity check failed: {result}")

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
                await _notifier(settings.owner_chat_id, f"🗄️ <b>DB Backup Gagal!</b>\n\nError: {e}")

    scheduler.add_job(
        _backup_db,
        trigger=CronTrigger(hour=2, minute=0, timezone="Asia/Shanghai"),
        id="db_backup",
        name="Daily DB Backup",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started: latency + auto-war + cookie refresh + DB backup")
