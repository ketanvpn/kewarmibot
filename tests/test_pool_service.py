"""Proxy pool service tests."""
import pytest
from src.proxy_pool_service import (
    pool_stats, pool_add, pool_available,
    pool_get_all, pool_clear_all, pool_allocate,
)


@pytest.mark.asyncio
async def test_pool_add_and_stats(db_session):
    result = await pool_add(db_session, "owner1", [
        "user1:pass1:host1:1000",
        "user2:pass2:host2:2000",
    ])
    assert result["added"] == 2
    assert result["skipped"] == 0
    assert result["total"] == 2
    assert result["unused"] == 2
    assert result["used"] == 0


@pytest.mark.asyncio
async def test_pool_skips_dupes(db_session):
    await pool_add(db_session, "owner1", ["user1:pass1:host1:1000"])
    result = await pool_add(db_session, "owner1", [
        "user1:pass1:host1:1000",  # dupe
        "user2:pass2:host2:2000",  # new
    ])
    assert result["added"] == 1
    assert result["skipped"] == 1
    assert result["total"] == 2


@pytest.mark.asyncio
async def test_pool_available(db_session):
    await pool_add(db_session, "owner1", [
        "user1:pass1:host1:1000",
        "user2:pass2:host2:2000",
    ])
    assert await pool_available(db_session, "owner1") == 2


@pytest.mark.asyncio
async def test_pool_allocate(db_session):
    await pool_add(db_session, "owner1", [
        "user1:pass1:host1:1000",
        "user2:pass2:host2:2000",
        "user3:pass3:host3:3000",
    ])
    proxies = await pool_allocate(db_session, "owner1", 2)
    assert len(proxies) == 2
    assert proxies[0].status == "unused"  # allocate doesn't commit


@pytest.mark.asyncio
async def test_pool_clear_all(db_session):
    await pool_add(db_session, "owner1", [
        "user1:pass1:host1:1000",
        "user2:pass2:host2:2000",
    ])
    deleted = await pool_clear_all(db_session, "owner1")
    assert deleted == 2
    stats = await pool_stats(db_session, "owner1")
    assert stats["total"] == 0


@pytest.mark.asyncio
async def test_pool_isolation_per_owner(db_session):
    await pool_add(db_session, "owner1", ["u:p:h1:1"])
    await pool_add(db_session, "owner2", ["u:p:h2:2", "u:p:h3:3"])
    stats1 = await pool_stats(db_session, "owner1")
    stats2 = await pool_stats(db_session, "owner2")
    assert stats1["total"] == 1
    assert stats2["total"] == 2


@pytest.mark.asyncio
async def test_pool_add_empty_urls(db_session):
    result = await pool_add(db_session, "owner1", ["", "  ", "\n"])
    assert result["added"] == 0
    assert result["total"] == 0