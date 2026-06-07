"""Cookie CRUD + status check service."""

import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

from src.db import CookieModel
from src.crypto import encrypt, decrypt
from src.engine.api import check_cookie_status


async def add_cookie(
    session: AsyncSession,
    name: str,
    token: str,
    owner_chat_id: str,
) -> CookieModel:
    """Add new cookie (encrypted). Auto-check status on add."""
    token_enc = encrypt(token)

    # Check status immediately
    status = await check_cookie_status(token)
    cookie = CookieModel(
        name=name,
        token_enc=token_enc,
        is_pass=status.get("is_pass"),
        button_state=status.get("button_state"),
        deadline=status.get("deadline_format"),
        owner_chat_id=owner_chat_id,
        last_checked=datetime.datetime.utcnow(),
    )
    session.add(cookie)
    await session.commit()
    await session.refresh(cookie)
    return cookie


async def list_cookies(
    session: AsyncSession, owner_chat_id: str
) -> list[CookieModel]:
    """List all cookies for an owner (token stays encrypted, only metadata exposed)."""
    result = await session.execute(
        select(CookieModel)
        .where(CookieModel.owner_chat_id == owner_chat_id)
        .order_by(CookieModel.created_at.desc())
    )
    return list(result.scalars().all())


async def get_cookie(
    session: AsyncSession, cookie_id: int, owner_chat_id: str
) -> CookieModel | None:
    """Get single cookie (if owned by user)."""
    result = await session.execute(
        select(CookieModel).where(
            CookieModel.id == cookie_id,
            CookieModel.owner_chat_id == owner_chat_id,
        )
    )
    return result.scalar_one_or_none()


async def get_cookie_token(
    session: AsyncSession, cookie_id: int, owner_chat_id: str
) -> str | None:
    """Get decrypted token for a cookie."""
    cookie = await get_cookie(session, cookie_id, owner_chat_id)
    if not cookie:
        return None
    return decrypt(cookie.token_enc)


async def delete_cookie(
    session: AsyncSession, cookie_id: int, owner_chat_id: str
) -> bool:
    """Delete cookie by id."""
    result = await session.execute(
        CookieModel.__table__.delete().where(
            CookieModel.id == cookie_id,
            CookieModel.owner_chat_id == owner_chat_id,
        )
    )
    await session.commit()
    return result.rowcount > 0


async def refresh_cookie_status(
    session: AsyncSession, cookie_id: int, owner_chat_id: str
) -> CookieModel | None:
    """Re-check cookie status against Xiaomi API."""
    cookie = await get_cookie(session, cookie_id, owner_chat_id)
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