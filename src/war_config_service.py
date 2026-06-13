"""War Config persistence — single-owner, multi-cookie model."""

import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.db import WarConfigModel
from src.config import settings

MAX_COOKIES_PER_WAR = 6
MAX_HERO_PER_COOKIE = 8
MAX_TOTAL_HEROES = 12


def recommended_hero(num_cookies: int) -> int:
    """Rekomendasi hero per cookie berdasarkan jumlah cookie."""
    if num_cookies <= 0:
        return 8
    return min(8, max(1, MAX_TOTAL_HEROES // num_cookies))


async def get_active_config(session: AsyncSession) -> WarConfigModel | None:
    owner = settings.owner_chat_id
    result = await session.execute(
        select(WarConfigModel).where(
            WarConfigModel.active == True,
            WarConfigModel.owner_chat_id == owner,
        )
    )
    return result.scalar_one_or_none()


async def save_config(
    session: AsyncSession,
    cookie_ids: list[int],
    hero_per_cookie: int,
    bracket_factor: float,
    safety_margin: int,
    war_hour: int = 0,
    war_minute: int = 0,
    war_tz: str = "Asia/Shanghai",
) -> WarConfigModel:
    """Create or update active config. cookie_ids clamped to MAX_COOKIES_PER_WAR."""
    from datetime import datetime

    owner = settings.owner_chat_id

    # Clamp
    cookie_ids = cookie_ids[:MAX_COOKIES_PER_WAR]
    hero_per_cookie = max(1, min(hero_per_cookie, MAX_HERO_PER_COOKIE))

    existing = await get_active_config(session)

    if existing:
        existing.cookie_ids = json.dumps(cookie_ids)
        existing.hero_per_cookie = hero_per_cookie
        existing.bracket_factor = bracket_factor
        existing.safety_margin = safety_margin
        existing.war_hour = war_hour
        existing.war_minute = war_minute
        existing.war_tz = war_tz
        existing.updated_at = datetime.utcnow()
        config = existing
    else:
        config = WarConfigModel(
            cookie_ids=json.dumps(cookie_ids),
            hero_per_cookie=hero_per_cookie,
            bracket_factor=bracket_factor,
            safety_margin=safety_margin,
            war_hour=war_hour,
            war_minute=war_minute,
            war_tz=war_tz,
            owner_chat_id=owner,
            active=True,
        )
        session.add(config)

    await session.commit()
    await session.refresh(config)
    return config


async def load_config(session: AsyncSession) -> dict:
    """Load config as dict with safe defaults."""
    config = await get_active_config(session)

    if not config:
        return {
            "hero_per_cookie": settings.war_hero_count_default,
            "bracket_factor": settings.war_bracket_factor_default,
            "safety_margin": settings.war_safety_margin_default,
            "cookie_ids": [],
            "war_hour": 0,
            "war_minute": 0,
            "war_tz": "Asia/Shanghai",
        }

    return {
        "hero_per_cookie": config.hero_per_cookie,
        "bracket_factor": config.bracket_factor,
        "safety_margin": config.safety_margin,
        "cookie_ids": json.loads(config.cookie_ids) if config.cookie_ids else [],
        "war_hour": getattr(config, "war_hour", 0),
        "war_minute": getattr(config, "war_minute", 0),
        "war_tz": getattr(config, "war_tz", "Asia/Shanghai"),
    }
