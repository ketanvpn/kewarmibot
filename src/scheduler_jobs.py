"""Background scheduler: auto-war, latency monitor, backup, cookie refresh."""

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
from src.engine.war import run_war_sync, WarConfig, WarResultReport, get_next_beijing_midnight_ms
from sqlalchemy import select

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
_notifier: Callable | None = None


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


async def _get_latency_stats(owner_chat_id: str) -> dict:
    """Get latency stats for last 6 hours."""
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=6)
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(LatencyLogModel)
            .where(LatencyLogModel.timestamp >= cutoff)
            .order_by(LatencyLogModel.timestamp.desc())
            .limit(72)
        )
        logs = list(result.scalars().all())

    if not logs:
        return {"min": None, "max": None, "avg": None, "latest": None, "samples": []}

    values = [log.latency_ms for log in logs]
    samples = [{"ts": log.timestamp.strftime("%H:%M"), "ms": log.latency_ms} for log in reversed(logs)]
    return {
        "min": min(values),
        "max": max(values),
        "avg": sum(values) // len(values),
        "latest": values[0],
        "samples": samples,
    }


async def _run_scheduled_war(owner_chat_id: str, notify: Callable | None = None):
    """Execute scheduled war for a given owner."""
    async with AsyncSessionLocal() as session:
        cfg = await load_config(session, owner_chat_id)
        selected_ids = cfg.get("cookie_ids", [])
        if not selected_ids:
            logger.warning(f"Scheduled war skipped: no cookies for {owner_chat_id}")
            if notify:
                await notify(owner_chat_id, "⚠️ <b>Auto-War Dilewati</b>\n\nTidak ada cookie yang dipilih di War Config.")
            return

        cookie_list = []
        for cid in selected_ids:
            try:
                token = await get_cookie_token(session, cid, owner_chat_id)
                if token:
                    r = await session.execute(select(CookieModel).where(CookieModel.id == cid))
                    c = r.scalar_one_or_none()
                    cookie_list.append((token, c.name if c else "Unknown"))
            except Exception as e:
                logger.error(f"Failed to decrypt cookie {cid}: {e}")
                if notify:
                    await notify(owner_chat_id, f"⚠️ <b>Auto-War: Gagal decrypt cookie ID {cid}</b>\n\nError: {e}")

    if not cookie_list:
        logger.error("Scheduled war failed: cannot decrypt any cookies")
        if notify:
            await notify(owner_chat_id, "❌ <b>Auto-War Gagal</b>\n\nSemua cookie gagal didecrypt. Cek ulang cookie di menu.")
        return

    config = WarConfig(
        cookies=cookie_list,
        hero_per_cookie=cfg.get("hero_per_cookie", 6),
        bracket_factor=cfg["bracket_factor"],
        safety_margin=cfg["safety_margin"],
        war_hour=cfg.get("war_hour", 0),
        war_minute=cfg.get("war_minute", 0),
        war_tz=cfg.get("war_tz", "Asia/Shanghai"),
        debug=False,
    )

    logger.info(f"Running scheduled war: {config.hero_per_cookie} heroes/cookie, {len(config.cookies)} cookies")
    report: WarResultReport = await asyncio.to_thread(run_war_sync, config)

    # Save to history
    async with AsyncSessionLocal() as session:
        import json
        history = WarHistoryModel(
            started_at=report.started_at,
            results=json.dumps([{"hero_id": r.hero_id, "success": r.success, "code": r.code, "msg": r.msg, "drift_ms": r.drift_ms, "cookie_name": r.cookie_name} for r in report.hero_results]),
            success_count=report.success_count,
            fail_count=report.fail_count,
            latency_median_ms=report.latency_median_ms,
        )
        session.add(history)
        await session.commit()

    logger.info(f"War complete: ✅{report.success_count} ❌{report.fail_count}")

    # Notify if callback provided
    if notify:
        await notify(report.format_report())


def start_scheduler(get_notifier: Callable | None = None):
    """Start background scheduler jobs."""
    # Latency monitoring every 15 minutes
    scheduler.add_job(
        _save_latency,
        trigger=IntervalTrigger(minutes=15),
        id="latency_monitor",
        name="Latency Monitor",
        replace_existing=True,
    )

    # Auto-war — 3 minutes before configured target time
    # Default: 23:57 CST (for Xiaomi Community midnight reset)
    # Change CRON expression below if you change war_time in config
    async def _war_for_all_admins():
        for uid in settings.admin_ids:
            try:
                await _run_scheduled_war(str(uid), notify=_notifier)
            except Exception as e:
                logger.error(f"Auto-war crashed for {uid}: {e}")
                if _notifier:
                    await _notifier(str(uid), f"💥 <b>Auto-War Crash!</b>\n\nError: {e}")

    scheduler.add_job(
        _war_for_all_admins,
        trigger=CronTrigger(hour=23, minute=57, timezone="Asia/Shanghai"),
        id="auto_war",
        name="Auto War Scheduler",
        replace_existing=True,
    )

    # Pre-war countdown check at 23:55 (notify 5 min warning)
    async def _war_countdown_notify():
        """Send 5-min warning to admins."""
        for uid in settings.admin_ids:
            if get_notifier:
                target = get_next_beijing_midnight_ms()
                from src.db import AsyncSessionLocal as S, LatencyLogModel as LL
                from sqlalchemy import select
                async with S() as session:
                    cfg = await load_config(session, str(uid))
                    result = await session.execute(
                        select(LL).order_by(LL.timestamp.desc()).limit(1)
                    )
                    latest_lat = result.scalar_one_or_none()

                lat_text = f"{latest_lat.latency_ms}ms" if latest_lat else "unknown"
                wh = cfg.get("war_hour", 0)
                wm = cfg.get("war_minute", 0)
                tz = cfg.get("war_tz", "Asia/Shanghai")
                target_label = f"{wh:02d}:{wm:02d} {tz}"
                msg = (
                    f"⚠️ <b>War Warning!</b>\n\n"
                    f"Auto-war dalam ~5 menit menuju {target_label}\n\n"
                    f"⚡ Latensi terakhir: {lat_text}\n"
                    f"🥊 Hero/cookie: {cfg.get('hero_per_cookie', 6)}\n"
                    f"📊 Bracket: {int(cfg['bracket_factor'] * 100)}%\n"
                )
                await get_notifier(str(uid), msg)

    scheduler.add_job(
        _war_countdown_notify,
        trigger=CronTrigger(hour=23, minute=55, timezone="Asia/Shanghai"),
        id="war_countdown",
        name="War Countdown Notifier",
        replace_existing=True,
    )

    # Daily cookie auto-refresh at 10:00 CST
    async def _auto_refresh_cookies():
        """Refresh status semua cookie setiap admin."""
        for uid in settings.admin_ids:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select
                r = await session.execute(
                    select(CookieModel).where(CookieModel.owner_chat_id == str(uid))
                )
                cookies = list(r.scalars().all())
                refreshed = 0
                failed = 0
                for c in cookies:
                    try:
                        await refresh_cookie_status(session, c.id, str(uid))
                        refreshed += 1
                    except Exception as e:
                        logger.error(f"Auto-refresh failed for cookie {c.id} ({c.name}): {e}")
                        failed += 1
                await session.commit()
                logger.info(f"Auto-refresh done for {uid}: {refreshed} ok, {failed} failed")
                if _notifier and failed > 0:
                    await _notifier(str(uid), f"🍪 <b>Auto-Refresh Cookie</b>\n\n✅ {refreshed} berhasil\n❌ {failed} gagal\n\nCek menu Cookies untuk detail.")

    scheduler.add_job(
        _auto_refresh_cookies,
        trigger=CronTrigger(hour=10, minute=0, timezone="Asia/Shanghai"),
        id="cookie_auto_refresh",
        name="Cookie Auto Refresh",
        replace_existing=True,
    )

    # Daily DB backup at 02:00 CST
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

            # Clean up backups older than 7 days
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
    logger.info("Scheduler started: latency monitor + cookie refresh + DB backup (02:00) + auto-war + countdown")