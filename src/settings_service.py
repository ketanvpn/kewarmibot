"""Settings service — payment config from DB."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.db import BotSettingModel
from src.config import settings
import logging

logger = logging.getLogger(__name__)

async def get_setting(session: AsyncSession, key: str) -> str | None:
    """Get setting from DB, fallback to env."""
    r = await session.execute(select(BotSettingModel).where(BotSettingModel.key == key))
    setting = r.scalar_one_or_none()
    return setting.value if setting else None

async def set_setting(session: AsyncSession, key: str, value: str | None) -> None:
    """Set setting in DB."""
    r = await session.execute(select(BotSettingModel).where(BotSettingModel.key == key))
    s = r.scalar_one_or_none()
    if s:
        s.value = value
    else:
        s = BotSettingModel(key=key, value=value)
        session.add(s)
    await session.commit()

async def get_payment_config(session: AsyncSession) -> dict:
    """Get all payment settings."""
    base_url = await get_setting(session, "payment_base_url") or settings.ketantechpay_base_url
    client_key = await get_setting(session, "payment_client_key") or settings.ketantechpay_client_key
    webhook_secret = await get_setting(session, "payment_webhook_secret") or settings.ketantechpay_webhook_secret
    webhook_base = await get_setting(session, "webhook_base_url") or settings.webhook_base_url
    
    return {
        "base_url": base_url,
        "client_key": client_key,
        "webhook_secret": webhook_secret,
        "webhook_base": webhook_base,
    }
