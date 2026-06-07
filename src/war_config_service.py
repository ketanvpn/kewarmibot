"""War Config persistence — multi-cookie, hero-per-cookie model."""

import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.db import WarConfigModel

MAX_COOKIES_PER_WAR = 6
MAX_HERO_PER_COOKIE = 8
MAX_TOTAL_HEROES = 12

# Allowed multi-cookie modes: num_cookies → hero_per_cookie
COOKIE_MODES = {2: 6, 4: 3, 6: 2}

def hero_for_mode(mode: int) -> int:
    """Auto-calc hero_per_cookie for a given mode (2/4/6)."""
    return COOKIE_MODES.get(mode, 6)


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
    war_hour: int = 0,
    war_minute: int = 0,
    war_tz: str = "Asia/Shanghai",
) -> WarConfigModel:
    """Create or update active config. cookie_ids clamped to MAX_COOKIES_PER_WAR.
    hero_per_cookie auto-adjusted based on selected cookie count."""
    from datetime import datetime
    from src.config import settings

    # Clamp + auto hero
    cookie_ids = cookie_ids[:MAX_COOKIES_PER_WAR]
    num_cookies = len(cookie_ids)
    if num_cookies in COOKIE_MODES:
        hero_per_cookie = COOKIE_MODES[num_cookies]
    else:
        hero_per_cookie = max(1, min(hero_per_cookie, MAX_HERO_PER_COOKIE))

    existing = await get_active_config(session, owner_chat_id)

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