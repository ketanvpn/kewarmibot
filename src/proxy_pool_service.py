"""Proxy Pool Service — credential lifecycle management."""

import datetime
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from src.db import ProxyPoolModel


async def pool_stats(session: AsyncSession, owner_chat_id: str) -> dict:
    """Return {total, unused, used} counts."""
    r = await session.execute(
        select(
            func.count(ProxyPoolModel.id).label("total"),
            func.count(ProxyPoolModel.id).filter(ProxyPoolModel.status == "unused").label("unused"),
        ).where(ProxyPoolModel.owner_chat_id == owner_chat_id)
    )
    row = r.one()
    total = row.total or 0
    unused = row.unused or 0
    return {"total": total, "unused": unused, "used": total - unused}


async def pool_available(session: AsyncSession, owner_chat_id: str) -> int:
    """Number of unused proxies."""
    r = await session.execute(
        select(func.count(ProxyPoolModel.id))
        .where(ProxyPoolModel.owner_chat_id == owner_chat_id)
        .where(ProxyPoolModel.status == "unused")
    )
    return r.scalar_one() or 0


async def pool_add(session: AsyncSession, owner_chat_id: str, urls: list[str]) -> dict:
    """Bulk-add proxy URLs (skip dupes). Returns {added, skipped, total, unused}."""
    added, skipped = 0, 0
    for url in urls:
        url = url.strip()
        if not url:
            continue
        # Check dupe
        r = await session.execute(
            select(ProxyPoolModel.id).where(ProxyPoolModel.proxy_url == url)
        )
        if r.scalar_one_or_none():
            skipped += 1
            continue
        session.add(ProxyPoolModel(
            proxy_url=url,
            status="unused",
            owner_chat_id=owner_chat_id,
        ))
        added += 1
    await session.commit()
    stats = await pool_stats(session, owner_chat_id)
    return {**stats, "added": added, "skipped": skipped}


async def pool_allocate(session: AsyncSession, owner_chat_id: str, count: int) -> list[ProxyPoolModel]:
    """Allocate N unused proxies (FIFO). Marks them 'used' but not committed yet — caller commits."""
    r = await session.execute(
        select(ProxyPoolModel)
        .where(ProxyPoolModel.owner_chat_id == owner_chat_id)
        .where(ProxyPoolModel.status == "unused")
        .order_by(ProxyPoolModel.id.asc())
        .limit(count)
    )
    proxies = r.scalars().all()
    return list(proxies)


async def pool_consume_batch(
    session: AsyncSession,
    proxy_ids: list[int],
    hero_ids: list[int],
    war_id: int | None,
) -> int:
    """Mark proxies as used. Returns count updated."""
    now = datetime.datetime.utcnow()
    for pid, hid in zip(proxy_ids, hero_ids):
        await session.execute(
            update(ProxyPoolModel)
            .where(ProxyPoolModel.id == pid)
            .values(status="used", used_by_hero=hid, used_by_war_id=war_id, used_at=now)
        )
    await session.commit()
    return len(proxy_ids)


async def pool_clear_all(session: AsyncSession, owner_chat_id: str) -> int:
    """Delete all proxies for owner. Returns count deleted."""
    r = await session.execute(
        select(func.count(ProxyPoolModel.id))
        .where(ProxyPoolModel.owner_chat_id == owner_chat_id)
    )
    total = r.scalar_one() or 0
    await session.execute(
        select(ProxyPoolModel).where(ProxyPoolModel.owner_chat_id == owner_chat_id)
    )
    proxies = (await session.execute(
        select(ProxyPoolModel).where(ProxyPoolModel.owner_chat_id == owner_chat_id)
    )).scalars().all()
    for p in proxies:
        await session.delete(p)
    await session.commit()
    return total


async def pool_get_all(
    session: AsyncSession, owner_chat_id: str, status: str | None = None
) -> list[ProxyPoolModel]:
    """List all proxies, optional status filter."""
    q = select(ProxyPoolModel).where(ProxyPoolModel.owner_chat_id == owner_chat_id)
    if status:
        q = q.where(ProxyPoolModel.status == status)
    q = q.order_by(ProxyPoolModel.id.asc())
    r = await session.execute(q)
    return list(r.scalars().all())