"""Pytest fixtures — async SQLite test DB."""
import os
import asyncio
import pytest

# Override DB to file-based SQLite for tests BEFORE any imports
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///data/test_kewarmibot.db"
os.environ["ENCRYPTION_KEY"] = "b3965fea2840ff1ef0a4e3247a3c2c0f308a9cb5d0e06ed2aecf3797f336c616"
os.environ["BOT_TOKEN"] = "dummy:token"
os.environ["ADMIN_CHAT_IDS"] = "690744680"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def clean_db():
    """Wipe + recreate DB. Explicit fixture, not autouse."""
    from src.db import BaseModel, engine
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.drop_all)
        await conn.run_sync(BaseModel.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.drop_all)


@pytest.fixture
async def db_session(clean_db):
    """Fresh async session with clean DB."""
    from src.db import AsyncSessionLocal
    async with AsyncSessionLocal() as s:
        yield s