"""Background scheduler: auto-war, latency monitor."""

import asyncio
import datetime
import logging
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.config import settings
from src.db import AsyncSessionLocal, WarHistoryModel, LatencyLogModel, CookieModel
from src.cookie_service import get_cookie_token
from src.war_config_service import load_config
from src.engine.api import measure_latency
from src.engine.war import run_war_sync, WarConfig, WarResultReport, get_next_beijing_midnight_ms
from sqlalchemy import select

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")


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
            return

        cookie_list = []
        for cid in selected_ids:
            token = await get_cookie_token(session, cid, owner_chat_id)
            if token:
                r = await session.execute(select(CookieModel).where(CookieModel.id == cid))
                c = r.scalar_one_or_none()
                cookie_list.append((token, c.name if c else "Unknown"))

    if not cookie_list:
        logger.error("Scheduled war failed: cannot decrypt any cookies")
        return

    config = WarConfig(
        cookies=cookie_list,
        hero_per_cookie=cfg.get("hero_per_cookie", 6),
        bracket_factor=cfg["bracket_factor"],
        safety_margin=cfg["safety_margin"],
        debug=False,
    )

    logger.info(f"Running scheduled war: {config.hero_per_cookie} heroes/cookie, {len(config.cookies)} cookies")
    report: WarResultReport = await asyncio.to_thread(run_war_sync, config)

    # Save to history
    async with AsyncSessionLocal() as session:
        import json
        history = WarHistoryModel(
            started_at=report.started_at,
            results=json.dumps([{"hero_id": r.hero_id, "success": r.success, "code": r.code, "msg": r.msg, "drift_ms": r.drift_ms} for r in report.hero_results]),
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

    # Auto-war daily at 23:57 Beijing time (3 minutes before midnight)
    # We run pre-war for all admins
    async def _war_for_all_admins():
        for uid in settings.admin_ids:
            await _run_scheduled_war(str(uid))

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
                msg = (
                    f"⚠️ <b>War Warning!</b>\n\n"
                    f"Auto-war akan dimulai dalam ~5 menit (00:00 CST)\n\n"
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

    scheduler.start()
    logger.info("Scheduler started: latency monitor (15min) + auto-war (23:57 CST) + countdown (23:55 CST)")