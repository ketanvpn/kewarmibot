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
    mode_label = "🔧 DEBUG" if debug else "⚔️ AUTO-WAR"

    # Notif #1: War dimulai sekarang
    if notify:
        await notify(owner, (
            f"🚀 <b>War Dimulai!</b>\n\n"
            f"Mode: {mode_label}\n"
            f"<i>Loading cookies...</i>"
        ))

    async with AsyncSessionLocal() as session:
        cfg = await load_config(session)
        selected_ids: list[int] = cfg.get("cookie_ids", [])

        if not selected_ids:
            logger.info("execute_war: no cookies selected")
            if notify:
                await notify(owner, "❌ Pilih minimal 1 cookie di ⚙️ War Config!")
            return None

        hero_per_cookie: int = cfg.get("hero_per_cookie", 6)

        # Load cookies, skip won ones — track reasons for notif #2
        cookie_list: list[tuple[str, str]] = []
        skipped_won: list[str] = []
        failed_decrypt: list[str] = []
        not_found: list[str] = []

        for cid in selected_ids:
            try:
                r = await session.execute(
                    select(CookieModel).where(
                        CookieModel.id == cid,
                        CookieModel.owner_chat_id == owner,
                    )
                )
                c = r.scalar_one_or_none()
                if not c:
                    not_found.append(f"ID:{cid}")
                    continue
                if c.has_won:
                    logger.info(f"execute_war: skipping won cookie {c.name}")
                    skipped_won.append(c.name)
                    continue

                token = await get_cookie_token(session, cid)
                if token:
                    cookie_list.append((token, c.name))
                else:
                    failed_decrypt.append(c.name)
            except Exception as e:
                logger.error(f"Decrypt failed for cookie {cid}: {e}")
                # Try to get name for reporting
                try:
                    rr = await session.execute(
                        select(CookieModel.name).where(CookieModel.id == cid)
                    )
                    nm = rr.scalar_one_or_none()
                    failed_decrypt.append(nm or f"ID:{cid}")
                except Exception:
                    failed_decrypt.append(f"ID:{cid}")

    # Notif #2: Cookie pre-war breakdown
    if notify and (skipped_won or failed_decrypt or not_found):
        lines = ["🍪 <b>Cookie Pre-War</b>\n"]
        lines.append(f"✅ Loaded: <b>{len(cookie_list)}</b>")
        if skipped_won:
            lines.append(f"🏆 Skip (udah menang): {', '.join(skipped_won)}")
        if failed_decrypt:
            lines.append(f"🔓 Skip (decrypt gagal): {', '.join(failed_decrypt)}")
        if not_found:
            lines.append(f"❓ Skip (gak ditemukan): {', '.join(not_found)}")
        await notify(owner, "\n".join(lines))

    if not cookie_list:
        logger.error("execute_war: no valid cookies loaded")
        if notify:
            await notify(owner, "❌ Gagal load cookie (semua sudah menang atau decrypt gagal).")
        return None

    # Allocate proxies from pool (if available)
    # Rule: cookie 1 = direct (IP VPS), cookie 2+ = 1 proxy per cookie (semua hero cookie itu pakai 1 IP sama)
    # Opsi C: kalau proxy kurang, cookie yang gak kebagian proxy DI-SKIP (jangan rebutan IP VPS)
    proxy_urls: list[str] = []
    num_cookies_need_proxy = len(cookie_list) - 1  # cookie pertama gak perlu

    if num_cookies_need_proxy > 0:
        async with AsyncSessionLocal() as session:
            proxies = await pool_allocate(session, owner, num_cookies_need_proxy)
            available = len(proxies)

            # Opsi C: trim cookie yang gak kebagian proxy
            skipped_no_proxy: list[str] = []
            if available < num_cookies_need_proxy:
                keep = 1 + available  # cookie 1 (direct) + cookie yang dapat proxy
                skipped_no_proxy = [name for _, name in cookie_list[keep:]]
                cookie_list = cookie_list[:keep]

            if proxies:
                proxy_urls = [p.proxy_url for p in proxies]
                proxy_ids = [p.id for p in proxies]
                # 1 proxy = 1 cookie; tandai used pakai index cookie (1-based) sebagai marker
                await pool_consume_batch(session, proxy_ids, list(range(1, len(proxies) + 1)), war_id=None)
                logger.info(f"execute_war: allocated {len(proxy_urls)} proxy untuk {len(proxy_urls)} cookie (1 proxy/cookie)")
                if notify:
                    note = f"🔌 <b>Proxy</b>: {len(proxy_urls)} dialokasikan (1 IP per cookie)"
                    if skipped_no_proxy:
                        note += f"\n⚠️ Proxy kurang — cookie di-skip: {', '.join(skipped_no_proxy)}"
                    await notify(owner, note)
            else:
                # Pool kosong total: cuma cookie 1 yang jalan (direct), sisanya skip
                skipped_no_proxy = [name for _, name in cookie_list[1:]]
                cookie_list = cookie_list[:1]
                logger.info("execute_war: proxy pool kosong — cuma cookie 1 (direct), sisanya skip")
                if notify:
                    await notify(owner, (
                        "⚠️ <b>Proxy pool kosong</b>\n"
                        f"Cuma cookie 1 jalan (IP VPS). Di-skip: {', '.join(skipped_no_proxy)}"
                    ))
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

    # Collect post-war extras for notification
    post_war_lines: list[str] = []

    # Notif #5: Cookie auto-lock info
    if report.success_count > 0:
        winning_names = set(
            r.cookie_name for r in report.hero_results if r.success
        )
        for cname in winning_names:
            post_war_lines.append(f"🔒 Cookie <b>{cname}</b> di-lock (dapat tiket) — dihapus dari config")

    # Notif #6: Sisa cookie aktif — read after possible removal
    async with AsyncSessionLocal() as session:
        cfg_after = await load_config(session)
        remaining_ids = cfg_after.get("cookie_ids", [])
        remaining_names: list[str] = []
        for rid in remaining_ids:
            r = await session.execute(
                select(CookieModel.name).where(
                    CookieModel.id == rid,
                    CookieModel.owner_chat_id == owner,
                )
            )
            nm = r.scalar_one_or_none()
            if nm:
                remaining_names.append(nm)
        if remaining_names:
            post_war_lines.append(f"📦 Sisa cookie untuk besok: <b>{len(remaining_names)}</b> ({', '.join(remaining_names)})")
        else:
            post_war_lines.append(f"📦 Sisa cookie: <b>0</b> — tambahkan cookie baru untuk war berikutnya")

    # Notif #7: Proxy terpakai count
    if proxy_urls:
        post_war_lines.append(f"🔌 Proxy terpakai: <b>{len(proxy_urls)}</b>")

    # Notify
    if notify:
        from src.bot.notify import format_war_notification
        msg = format_war_notification(report)
        if post_war_lines:
            msg += "\n" + "\n".join(post_war_lines)
        await notify(owner, msg)

    return report
