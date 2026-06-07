"""War Config persistence — multi-cookie, hero-per-cookie model."""

import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.db import WarConfigModel

MAX_COOKIES_PER_WAR = 2
MAX_HERO_PER_COOKIE = 8


async def get_active_config(session: AsyncSession, owner_chat_id: str) -> WarConfigModel | None:
    result = await session.execute(
        select(WarConfigModel).where(
            WarConfigModel.active == True,
            WarConfigModel.owner_chat_id == owner_chat_id,
        )
    )
    return result.scalar_one_or_none()


async def save_config(
    session: AsyncSession,
    owner_chat_id: str,
    cookie_ids: list[int],
    hero_per_cookie: int,
    bracket_factor: float,
    safety_margin: int,
) -> WarConfigModel:
    """Create or update active config. cookie_ids clamped to MAX_COOKIES_PER_WAR."""
    from datetime import datetime
    from src.config import settings

    # Clamp
    cookie_ids = cookie_ids[:MAX_COOKIES_PER_WAR]
    hero_per_cookie = max(1, min(hero_per_cookie, MAX_HERO_PER_COOKIE))

    existing = await get_active_config(session, owner_chat_id)

    if existing:
        existing.cookie_ids = json.dumps(cookie_ids)
        existing.hero_per_cookie = hero_per_cookie
        existing.bracket_factor = bracket_factor
        existing.safety_margin = safety_margin
        existing.updated_at = datetime.utcnow()
        config = existing
    else:
        config = WarConfigModel(
            cookie_ids=json.dumps(cookie_ids),
            hero_per_cookie=hero_per_cookie,
            bracket_factor=bracket_factor,
            safety_margin=safety_margin,
            owner_chat_id=owner_chat_id,
            active=True,
        )
        session.add(config)

    await session.commit()
    await session.refresh(config)
    return config


async def load_config(session: AsyncSession, owner_chat_id: str) -> dict:
    """Load config as dict with safe defaults."""
    from src.config import settings
    config = await get_active_config(session, owner_chat_id)

    if not config:
        return {
            "hero_per_cookie": settings.war_hero_count_default,
            "bracket_factor": settings.war_bracket_factor_default,
            "safety_margin": settings.war_safety_margin_default,
            "cookie_ids": [],
        }

    return {
        "hero_per_cookie": config.hero_per_cookie,
        "bracket_factor": config.bracket_factor,
        "safety_margin": config.safety_margin,
        "cookie_ids": json.loads(config.cookie_ids) if config.cookie_ids else [],
    }