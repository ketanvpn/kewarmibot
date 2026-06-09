"""Single entry point for ALL war execution — deduplicates 3 code paths.

Used by:
  - handlers.war_debug()   (manual debug war, deduct=True)
  - handlers.autowar_run_now()  (admin manual trigger, deduct=False? no)
  - scheduler._run_war_for_user()  (auto-war, deduct=True)
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Callable

from sqlalchemy import select

from src.db import AsyncSessionLocal, CookieModel, WarHistoryModel
from src.cookie_service import get_cookie_token
from src.war_config_service import load_config
from src.user_service import get_user, get_user_by_id, deduct_balance, add_tickets
from src.engine.war import run_war_sync, WarConfig, WarResultReport

logger = logging.getLogger(__name__)


async def execute_war(
    user_tg_id: str,
    debug: bool = False,
    deduct: bool = True,
    notify: Callable | None = None,
) -> WarResultReport | None:
    """
    Central war execution for any path (debug, auto, admin trigger).

    1. Load user from DB
    2. Load war config
    3. Load + decrypt selected cookies
    4. Check balance (optional deduct)
    5. Run war
    6. Save history (with user_id)
    7. Award tickets for success
    8. Notify user (optional)

    Returns WarResultReport or None if skipped.
    """
    async with AsyncSessionLocal() as session:
        user = await get_user(session, user_tg_id)
        if not user:
            logger.warning(f"execute_war: user not found {user_tg_id}")
            if notify:
                await notify(user_tg_id, "❌ Akun tidak ditemukan.")
            return None

        cfg = await load_config(session, user_tg_id)
        selected_ids: list[int] = cfg.get("cookie_ids", [])

        if not selected_ids:
            logger.info(f"execute_war: no cookies for {user.first_name or user_tg_id}")
            if notify:
                await notify(user_tg_id, "❌ Pilih minimal 1 cookie di ⚙️ War Config!")
            return None

        hero_per_cookie: int = cfg.get("hero_per_cookie", 6)
        cost: int = len(selected_ids)  # 1 tiket = 1 cookie

        # Balance check + optional deduct
        if deduct and user.balance_war < cost:
            logger.info(f"execute_war: insufficient balance for {user.first_name or user_tg_id} ({user.balance_war} < {cost})")
            if notify:
                await notify(user_tg_id, (
                    f"❌ Tiket tidak cukup!\n\n"
                    f"🎫 Tiket: <b>{user.balance_war}</b>\n"
                    f"🎯 Butuh: <b>{cost}</b> tiket ({len(selected_ids)} cookie)\n\n"
                    f"<i>Beli tiket dulu di 🎫 Beli Tiket War</i>"
                ))
            return None

        if deduct:
            await deduct_balance(session, user.id, cost)
            logger.info(f"Deducted {cost} tiket from {user.first_name or user_tg_id}")

        # Load cookie tokens
        cookie_list: list[tuple[str, str]] = []
        for cid in selected_ids:
            try:
                token = await get_cookie_token(session, cid, user_tg_id)
                if token:
                    r = await session.execute(
                        select(CookieModel).where(
                            CookieModel.id == cid,
                            CookieModel.owner_chat_id == user_tg_id,
                        )
                    )
                    c = r.scalar_one_or_none()
                    cookie_list.append((token, c.name if c else f"Cookie #{cid}"))
            except Exception as e:
                logger.error(f"Decrypt failed for cookie {cid}: {e}")

    if not cookie_list:
        logger.error(f"execute_war: no cookies loaded for {user.first_name or user_tg_id}")
        if notify:
            await notify(user_tg_id, "❌ Gagal decrypt cookie.")
        return None

    # Build config
    config = WarConfig(
        cookies=cookie_list,
        hero_per_cookie=hero_per_cookie,
        bracket_factor=cfg["bracket_factor"],
        safety_margin=cfg["safety_margin"],
        hero_spacing_ms=cfg.get("hero_spacing_ms", 0),
        use_pool=True,
        owner_chat_id=user_tg_id,
        debug=debug,
        war_hour=cfg.get("war_hour", 0),
        war_minute=cfg.get("war_minute", 0),
        war_tz=cfg.get("war_tz", "Asia/Shanghai"),
    )

    logger.info(
        f"execute_war: {user.first_name or user_tg_id} — "
        f"{hero_per_cookie} heroes × {len(cookie_list)} cookies"
        + (f" ({cost} tiket)" if deduct else "")
        + (" [DEBUG]" if debug else "")
    )

    report: WarResultReport = await asyncio.to_thread(run_war_sync, config)

    # Save history + award tickets
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

        # Award tickets for success
        if report.success_count > 0:
            try:
                await add_tickets(session, user.id, report.success_count)
            except Exception as e:
                logger.error(f"Ticket award failed: {e}")

        # Final balance
        user_final = await get_user_by_id(session, user.id)
        final_bal = user_final.balance_war if user_final else "?"

    logger.info(
        f"execute_war done: {user.first_name or user_tg_id} "
        f"✅{report.success_count} ❌{report.fail_count} | balance={final_bal}"
    )

    # Notify
    if notify:
        summary = (
            f"{report.format_report()}\n"
            f"{'─' * 28}\n"
            f"🎫 Tiket tersisa: <b>{final_bal}</b>"
        )
        await notify(user_tg_id, summary)

    return report