"""Cookie CRUD + status check service. Single-owner."""

import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.db import CookieModel
from src.crypto import encrypt, decrypt
from src.engine.api import check_cookie_status
from src.config import settings


async def add_cookie(
    session: AsyncSession,
    name: str,
    token: str,
) -> CookieModel:
    """Add new cookie (encrypted). Auto-check status on add."""
    owner = settings.owner_chat_id
    token_enc = encrypt(token)

    # Check status immediately
    status = await check_cookie_status(token)
    cookie = CookieModel(
        name=name,
        token_enc=token_enc,
        is_pass=status.get("is_pass"),
        button_state=status.get("button_state"),
        deadline=status.get("deadline_format"),
        owner_chat_id=owner,
        last_checked=datetime.datetime.utcnow(),
    )
    session.add(cookie)
    await session.commit()
    await session.refresh(cookie)
    return cookie


async def list_cookies(session: AsyncSession) -> list[CookieModel]:
    """List all cookies for owner."""
    owner = settings.owner_chat_id
    result = await session.execute(
        select(CookieModel)
        .where(CookieModel.owner_chat_id == owner)
        .order_by(CookieModel.created_at.desc())
    )
    return list(result.scalars().all())


async def get_cookie(session: AsyncSession, cookie_id: int) -> CookieModel | None:
    """Get single cookie."""
    owner = settings.owner_chat_id
    result = await session.execute(
        select(CookieModel).where(
            CookieModel.id == cookie_id,
            CookieModel.owner_chat_id == owner,
        )
    )
    return result.scalar_one_or_none()


async def get_cookie_token(session: AsyncSession, cookie_id: int) -> str | None:
    """Get decrypted token for a cookie."""
    cookie = await get_cookie(session, cookie_id)
    if not cookie:
        return None
    return decrypt(cookie.token_enc)


async def delete_cookie(session: AsyncSession, cookie_id: int) -> bool:
    """Delete cookie by id. Also removes from war config."""
    cookie = await get_cookie(session, cookie_id)
    if not cookie:
        return False
    await session.delete(cookie)
    await session.commit()

    # Remove from war config cookie_ids
    from src.war_config_service import get_active_config
    import json
    cfg = await get_active_config(session)
    if cfg and cfg.cookie_ids:
        ids = json.loads(cfg.cookie_ids)
        if cookie_id in ids:
            ids.remove(cookie_id)
            cfg.cookie_ids = json.dumps(ids)
            await session.commit()

    return True


async def refresh_cookie_status(session: AsyncSession, cookie_id: int) -> CookieModel | None:
    """Re-check cookie status against Xiaomi API."""
    cookie = await get_cookie(session, cookie_id)
    if not cookie:
        return None
    token = decrypt(cookie.token_enc)
    status = await check_cookie_status(token)
    cookie.is_pass = status.get("is_pass")
    cookie.button_state = status.get("button_state")
    cookie.deadline = status.get("deadline_format")
    cookie.last_checked = datetime.datetime.utcnow()
    cookie.updated_at = datetime.datetime.utcnow()
    await session.commit()
    await session.refresh(cookie)
    return cookie


def status_label(cookie: CookieModel) -> tuple[str, str]:
    """Return (status_emoji, status_text) for a cookie."""
    if cookie.is_pass == 1:
        return ("✅", f"APPROVED (s/d {cookie.deadline})")
    if cookie.button_state == 2:
        return ("🚫", f"BLOCKED ({cookie.deadline})")
    if cookie.button_state == 3:
        return ("⚠️", "Akun belum 30 hari")
    if cookie.button_state == 1:
        return ("🟢", f"ELIGIBLE (s/d {cookie.deadline})")
    return ("❓", "Unknown status")
