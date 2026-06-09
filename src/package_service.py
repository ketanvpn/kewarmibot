"""Package & order service."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from src.db import PackageModel, OrderModel, UserModel
import datetime
import logging

logger = logging.getLogger(__name__)

async def list_packages(session: AsyncSession, active_only: bool = True) -> list[PackageModel]:
    """List packages."""
    if active_only:
        r = await session.execute(select(PackageModel).where(PackageModel.is_active == True))
    else:
        r = await session.execute(select(PackageModel))
    return r.scalars().all()

async def get_package(session: AsyncSession, package_id: int) -> PackageModel | None:
    """Get package by ID."""
    return await session.get(PackageModel, package_id)

async def create_order(session: AsyncSession, user_id: int, package_id: int) -> OrderModel:
    """Create new order."""
    pkg = await session.get(PackageModel, package_id)
    if not pkg:
        raise ValueError("Package not found")
    
    # Generate order ref
    now = datetime.datetime.utcnow()
    order_num = await session.execute(select(func.count(OrderModel.id)))
    count = order_num.scalar() or 0
    order_ref = f"ORD-{now.strftime('%Y%m%d')}-{count + 1:03d}"
    
    order = OrderModel(
        user_id=user_id,
        package_id=package_id,
        order_ref=order_ref,
        amount_idr=pkg.price_idr,
        war_count=pkg.war_count,
        status="pending"
    )
    session.add(order)
    await session.commit()
    return order

async def list_user_orders(session: AsyncSession, user_id: int, limit: int = 5) -> list[OrderModel]:
    """List user orders."""
    r = await session.execute(
        select(OrderModel).where(OrderModel.user_id == user_id).order_by(OrderModel.created_at.desc()).limit(limit)
    )
    return r.scalars().all()

async def mark_order_paid(session: AsyncSession, order_ref: str, user_id: int) -> bool:
    """Mark order paid + add balance to user."""
    r = await session.execute(select(OrderModel).where(OrderModel.order_ref == order_ref, OrderModel.user_id == user_id))
    order = r.scalar_one_or_none()
    if not order:
        return False
    
    order.status = "paid"
    order.paid_at = datetime.datetime.utcnow()
    
    user = await session.get(UserModel, user_id)
    if user:
        user.balance_war += order.war_count
    
    await session.commit()
    return True

async def set_payment_url(session: AsyncSession, order_ref: str, payment_url: str) -> bool:
    """Set payment URL for order."""
    r = await session.execute(select(OrderModel).where(OrderModel.order_ref == order_ref))
    order = r.scalar_one_or_none()
    if order:
        order.payment_url = payment_url
        await session.commit()
    return bool(order)

async def update_package(session: AsyncSession, package_id: int, is_active: bool = None) -> PackageModel | None:
    """Update package."""
    pkg = await session.get(PackageModel, package_id)
    if pkg and is_active is not None:
        pkg.is_active = is_active
        await session.commit()
    return pkg

async def revenue_today(session: AsyncSession) -> int:
    """Revenue from paid orders today."""
    now = datetime.datetime.utcnow()
    start = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    r = await session.execute(
        select(func.sum(OrderModel.amount_idr)).where(
            OrderModel.status == "paid",
            OrderModel.paid_at >= start
        )
    )
    return r.scalar() or 0

async def revenue_total(session: AsyncSession) -> int:
    """Total revenue from all paid orders."""
    r = await session.execute(
        select(func.sum(OrderModel.amount_idr)).where(OrderModel.status == "paid")
    )
    return r.scalar() or 0
