"""Single entry point for ALL war execution — single-owner mode.

Used by:
  - handlers.war_debug()   (manual debug war)
  - scheduler._run_auto_war()  (auto-war)
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Callable

from sqlalchemy import select, update as sql_update

from src.db import AsyncSessionLocal, CookieModel, WarHistoryModel
from src.cookie_service import get_cookie_token
from src.war_config_service import load_config, get_active_config
from src.proxy_pool_service import pool_allocate, pool_consume_batch
from src.engine.war import run_war_sync, WarConfig, WarResultReport
from src.config import settings

logger = logging.getLogger(__name__)


async def execute_war(
    debug: bool = False,
    notify: Callable | None = None,
) -> WarResultReport | None:
    """
    Central war execution for single owner.

    1. Load war config
    2. Load + decrypt selected cookies (skip won ones)
    3. Run war
    4. Save history
    5. Mark winning cookies
    6. Notify owner

    Returns WarResultReport or None if skipped.
    """
    owner = settings.owner_chat_id

    async with AsyncSessionLocal() as session:
        cfg = await load_config(session)
        selected_ids: list[int] = cfg.get("cookie_ids", [])

        if not selected_ids:
            logger.info("execute_war: no cookies selected")
            if notify:
                await notify(owner, "❌ Pilih minimal 1 cookie di ⚙️ War Config!")
            return None

        hero_per_cookie: int = cfg.get("hero_per_cookie", 6)

        # Load cookies, skip won ones
        cookie_list: list[tuple[str, str]] = []
        for cid in selected_ids:
            try:
                # Check if cookie has_won
                r = await session.execute(
                    select(CookieModel).where(
                        CookieModel.id == cid,
                        CookieModel.owner_chat_id == owner,
                    )
                )
                c = r.scalar_one_or_none()
                if not c:
                    continue
                if c.has_won:
                    logger.info(f"execute_war: skipping won cookie {c.name}")
                    continue

                token = await get_cookie_token(session, cid)
                if token:
                    cookie_list.append((token, c.name))
            except Exception as e:
                logger.error(f"Decrypt failed for cookie {cid}: {e}")

    if not cookie_list:
        logger.error("execute_war: no valid cookies loaded")
        if notify:
            await notify(owner, "❌ Gagal load cookie (semua sudah menang atau decrypt gagal).")
        return None

    # Allocate proxies from pool (if available)
    # Rule: cookie pertama = direct (no proxy), cookie ke-2+ = pake proxy
    proxy_urls: list[str] = []
    num_cookies_need_proxy = len(cookie_list) - 1  # cookie pertama gak perlu
    heroes_need_proxy = hero_per_cookie * num_cookies_need_proxy if num_cookies_need_proxy > 0 else 0

    if heroes_need_proxy > 0:
        async with AsyncSessionLocal() as session:
            proxies = await pool_allocate(session, owner, heroes_need_proxy)
            if proxies:
                proxy_urls = [p.proxy_url for p in proxies]
                proxy_ids = [p.id for p in proxies]
                hero_ids_for_proxy = list(range(1, len(proxies) + 1))
                await pool_consume_batch(session, proxy_ids, hero_ids_for_proxy, war_id=None)
                logger.info(f"execute_war: allocated {len(proxy_urls)} proxies (cookie 2+ only)")
            else:
                logger.info("execute_war: no proxies available for cookie 2+, all direct")
    else:
        logger.info("execute_war: single cookie, direct connection (no proxy needed)")

    # Build config
    config = WarConfig(
        cookies=cookie_list,
        hero_per_cookie=hero_per_cookie,
        bracket_factor=cfg["bracket_factor"],
        safety_margin=cfg["safety_margin"],
        hero_spacing_ms=cfg.get("hero_spacing_ms", 0),
        use_pool=bool(proxy_urls),
        proxies=proxy_urls,
        owner_chat_id=owner,
        debug=debug,
        war_hour=cfg.get("war_hour", 0),
        war_minute=cfg.get("war_minute", 0),
        war_tz=cfg.get("war_tz", "Asia/Shanghai"),
    )

    logger.info(
        f"execute_war: {hero_per_cookie} heroes × {len(cookie_list)} cookies"
        + (" [DEBUG]" if debug else "")
    )

    report: WarResultReport = await asyncio.to_thread(run_war_sync, config)

    # Save history + mark won cookies
    async with AsyncSessionLocal() as session:
        history = WarHistoryModel(
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

        # Mark winning cookies + remove from config
        if report.success_count > 0:
            winning_names = set(
                r.cookie_name for r in report.hero_results if r.success
            )
            for cname in winning_names:
                await session.execute(
                    sql_update(CookieModel)
                    .where(CookieModel.owner_chat_id == owner, CookieModel.name == cname)
                    .values(has_won=True)
                )
            await session.commit()
            logger.info(f"Marked {len(winning_names)} cookie(s) as won")

            # Remove won cookies from active config
            cfg_model = await get_active_config(session)
            if cfg_model:
                current_ids = json.loads(cfg_model.cookie_ids) if cfg_model.cookie_ids else []
                won_ids: set[int] = set()
                for cname in winning_names:
                    r2 = await session.execute(
                        select(CookieModel.id).where(
                            CookieModel.owner_chat_id == owner,
                            CookieModel.name == cname,
                        )
                    )
                    cid = r2.scalar_one_or_none()
                    if cid:
                        won_ids.add(cid)
                new_ids = [cid for cid in current_ids if cid not in won_ids]
                cfg_model.cookie_ids = json.dumps(new_ids)
                await session.commit()
                logger.info(f"Removed {len(won_ids)} won cookie(s) from config, remaining: {len(new_ids)}")

    logger.info(
        f"execute_war done: ✅{report.success_count} ❌{report.fail_count}"
    )

    # Notify
    if notify:
        from src.bot.notify import format_war_notification
        msg = format_war_notification(report)
        await notify(owner, msg)

    return report
