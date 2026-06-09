"""User service — CRUD + balance operations."""
import pytest
from src.user_service import (
    get_or_create_user, get_user, get_user_by_id,
    add_balance, deduct_balance, add_tickets,
    set_suspended, list_users, user_count, toggle_war_enabled,
)


@pytest.mark.asyncio
async def test_create_user(db_session):
    u = await get_or_create_user(db_session, "123", first_name="Test")
    assert u.telegram_id == "123"
    assert u.first_name == "Test"
    assert u.balance_war == 0
    assert u.is_suspended is False
    assert u.war_enabled is True


@pytest.mark.asyncio
async def test_get_or_create_idempotent(db_session):
    u1 = await get_or_create_user(db_session, "123", first_name="First")
    u2 = await get_or_create_user(db_session, "123", first_name="Second")
    assert u1.id == u2.id
    assert u2.first_name == "First"  # Not overwritten


@pytest.mark.asyncio
async def test_get_user_not_found(db_session):
    u = await get_user(db_session, "nonexistent")
    assert u is None


@pytest.mark.asyncio
async def test_add_balance(db_session):
    u = await get_or_create_user(db_session, "123")
    new_bal = await add_balance(db_session, u.id, 10)
    assert new_bal == 10


@pytest.mark.asyncio
async def test_deduct_balance(db_session):
    u = await get_or_create_user(db_session, "123")
    await add_balance(db_session, u.id, 10)
    new_bal = await deduct_balance(db_session, u.id, 3)
    assert new_bal == 7


@pytest.mark.asyncio
async def test_deduct_below_zero_clamped(db_session):
    u = await get_or_create_user(db_session, "123")
    new_bal = await deduct_balance(db_session, u.id, 5)
    assert new_bal == 0


@pytest.mark.asyncio
async def test_add_tickets(db_session):
    u = await get_or_create_user(db_session, "123")
    total = await add_tickets(db_session, u.id, 5)
    assert total == 5
    total = await add_tickets(db_session, u.id, 3)
    assert total == 8


@pytest.mark.asyncio
async def test_suspend_unsuspend(db_session):
    u = await get_or_create_user(db_session, "123")
    await set_suspended(db_session, u.id, True)
    u2 = await get_user_by_id(db_session, u.id)
    assert u2.is_suspended is True

    await set_suspended(db_session, u.id, False)
    u3 = await get_user_by_id(db_session, u.id)
    assert u3.is_suspended is False


@pytest.mark.asyncio
async def test_toggle_war_enabled(db_session):
    u = await get_or_create_user(db_session, "123")
    assert u.war_enabled is True
    new_state = await toggle_war_enabled(db_session, "123")
    assert new_state is False
    new_state = await toggle_war_enabled(db_session, "123")
    assert new_state is True


@pytest.mark.asyncio
async def test_list_users(db_session):
    await get_or_create_user(db_session, "1", first_name="A")
    await get_or_create_user(db_session, "2", first_name="B")
    await get_or_create_user(db_session, "3", first_name="C")
    users = await list_users(db_session, limit=10)
    assert len(users) == 3


@pytest.mark.asyncio
async def test_user_count(db_session):
    assert await user_count(db_session) == 0
    await get_or_create_user(db_session, "1")
    await get_or_create_user(db_session, "2")
    assert await user_count(db_session) == 2