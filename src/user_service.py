"""User service — balance, tickets, suspend."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.db import UserModel
import logging

logger = logging.getLogger(__name__)

async def get_or_create_user(session: AsyncSession, telegram_id: str, username: str = None, first_name: str = None, last_name: str = None) -> UserModel:
    """Get or auto-create user on first /start."""
    r = await session.execute(select(UserModel).where(UserModel.telegram_id == telegram_id))
    user = r.scalar_one_or_none()
    if user:
        return user
    
    user = UserModel(telegram_id=telegram_id, username=username, first_name=first_name, last_name=last_name)
    session.add(user)
    await session.commit()
    return user

async def get_user(session: AsyncSession, telegram_id: str) -> UserModel | None:
    """Get user by TG ID."""
    r = await session.execute(select(UserModel).where(UserModel.telegram_id == telegram_id))
    return r.scalar_one_or_none()

async def get_user_by_id(session: AsyncSession, user_id: int) -> UserModel | None:
    """Get user by ID."""
    return await session.get(UserModel, user_id)

async def add_balance(session: AsyncSession, user_id: int, amount: int) -> int:
    """Add war slots to balance."""
    user = await session.get(UserModel, user_id)
    if user:
        user.balance_war += amount
        await session.commit()
    return user.balance_war if user else 0

async def deduct_balance(session: AsyncSession, user_id: int, amount: int) -> int:
    """Deduct war slots."""
    user = await session.get(UserModel, user_id)
    if user:
        user.balance_war = max(0, user.balance_war - amount)
        await session.commit()
    return user.balance_war if user else 0

async def add_tickets(session: AsyncSession, user_id: int, count: int) -> int:
    """Add success tickets."""
    user = await session.get(UserModel, user_id)
    if user:
        user.total_tickets += count
        await session.commit()
    return user.total_tickets if user else 0

async def set_suspended(session: AsyncSession, user_id: int, suspended: bool) -> bool:
    """Suspend/unsuspend user."""
    user = await session.get(UserModel, user_id)
    if user:
        user.is_suspended = suspended
        await session.commit()
    return user.is_suspended if user else False

async def list_users(session: AsyncSession, limit: int = 10) -> list[UserModel]:
    """List users."""
    r = await session.execute(select(UserModel).limit(limit))
    return r.scalars().all()

async def user_count(session: AsyncSession) -> int:
    """Total user count."""
    from sqlalchemy import func
    r = await session.execute(select(func.count(UserModel.id)))
    return r.scalar() or 0

async def toggle_war_enabled(session: AsyncSession, telegram_id: str) -> bool:
    """Toggle auto-war on/off for user. Returns new state."""
    r = await session.execute(select(UserModel).where(UserModel.telegram_id == telegram_id))
    user = r.scalar_one_or_none()
    if user:
        user.war_enabled = not user.war_enabled
        await session.commit()
    return user.war_enabled if user else True
