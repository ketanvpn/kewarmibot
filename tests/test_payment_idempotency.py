"""Payment order idempotency tests."""

import pytest

from src.db import PackageModel
from src.package_service import create_order, mark_order_paid
from src.user_service import get_or_create_user, get_user_by_id


@pytest.mark.asyncio
async def test_mark_order_paid_is_idempotent(db_session):
    user = await get_or_create_user(db_session, "123", first_name="Buyer")
    package = PackageModel(name="Starter", war_count=5, price_idr=15000, is_active=True)
    db_session.add(package)
    await db_session.commit()
    await db_session.refresh(package)

    order = await create_order(db_session, user.id, package.id)

    assert await mark_order_paid(db_session, order.order_ref) is True
    paid_once = await get_user_by_id(db_session, user.id)
    assert paid_once.balance_war == 5

    assert await mark_order_paid(db_session, order.order_ref) is False
    paid_twice = await get_user_by_id(db_session, user.id)
    assert paid_twice.balance_war == 5
