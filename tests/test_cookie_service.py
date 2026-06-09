"""Cookie service — encrypt/decrypt lifecycle."""
import pytest
from src.cookie_service import (
    add_cookie, list_cookies, get_cookie, get_cookie_token,
    delete_cookie, status_label,
)
from src.crypto import encrypt, decrypt


@pytest.mark.asyncio
async def test_add_and_list(db_session):
    await add_cookie(db_session, "Akun A", "dummy_token_123", "owner1")
    cookies = await list_cookies(db_session, "owner1")
    assert len(cookies) == 1
    assert cookies[0].name == "Akun A"
    # Token stored encrypted, not plain
    assert cookies[0].token_enc != "dummy_token_123"


@pytest.mark.asyncio
async def test_get_cookie_token_decrypts(db_session):
    await add_cookie(db_session, "Akun A", "my_secret_token", "owner1")
    cookies = await list_cookies(db_session, "owner1")
    token = await get_cookie_token(db_session, cookies[0].id, "owner1")
    assert token == "my_secret_token"


@pytest.mark.asyncio
async def test_get_cookie_wrong_owner_fails(db_session):
    await add_cookie(db_session, "Akun A", "token", "owner1")
    cookies = await list_cookies(db_session, "owner1")
    token = await get_cookie_token(db_session, cookies[0].id, "owner2")
    assert token is None


@pytest.mark.asyncio
async def test_delete_cookie(db_session):
    await add_cookie(db_session, "Akun A", "token", "owner1")
    cookies = await list_cookies(db_session, "owner1")
    assert len(cookies) == 1
    deleted = await delete_cookie(db_session, cookies[0].id, "owner1")
    assert deleted is True
    cookies = await list_cookies(db_session, "owner1")
    assert len(cookies) == 0


@pytest.mark.asyncio
async def test_cookie_isolation(db_session):
    await add_cookie(db_session, "A's Cookie", "token_a", "owner_A")
    await add_cookie(db_session, "B's Cookie", "token_b", "owner_B")
    assert len(await list_cookies(db_session, "owner_A")) == 1
    assert len(await list_cookies(db_session, "owner_B")) == 1


def test_status_label_approved():
    from src.db import CookieModel
    c = CookieModel(is_pass=1, button_state=1, deadline="2026-12-31")
    emoji, text = status_label(c)
    assert emoji == "✅"
    assert "APPROVED" in text


def test_status_label_blocked():
    from src.db import CookieModel
    c = CookieModel(is_pass=0, button_state=2, deadline="2026-01-01")
    emoji, text = status_label(c)
    assert emoji == "🚫"
    assert "BLOCKED" in text


def test_status_label_eligible():
    from src.db import CookieModel
    c = CookieModel(is_pass=0, button_state=1, deadline="2026-12-31")
    emoji, text = status_label(c)
    assert emoji == "🟢"
    assert "ELIGIBLE" in text


def test_status_label_unknown():
    from src.db import CookieModel
    c = CookieModel(is_pass=-1, button_state=-1, deadline="")
    emoji, text = status_label(c)
    assert emoji == "❓"