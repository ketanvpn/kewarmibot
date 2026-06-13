"""Database models — SQLAlchemy async. Single-owner mode."""

import datetime
from sqlalchemy import Boolean, Integer, String, Text, Float, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.config import settings


class BaseModel(DeclarativeBase):
    pass


class CookieModel(BaseModel):
    __tablename__ = "cookies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    token_enc: Mapped[str] = mapped_column(Text, nullable=False)  # AES-256-GCM encrypted
    is_pass: Mapped[int | None] = mapped_column(Integer, nullable=True)
    button_state: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deadline: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_chat_id: Mapped[str] = mapped_column(String(64), nullable=False)
    last_checked: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )
    has_won: Mapped[bool] = mapped_column(Boolean, default=False)

    def __repr__(self) -> str:
        return f"Cookie(id={self.id}, name={self.name})"


class WarConfigModel(BaseModel):
    __tablename__ = "war_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hero_per_cookie: Mapped[int] = mapped_column(
        Integer, default=settings.war_hero_count_default
    )
    bracket_factor: Mapped[float] = mapped_column(
        Float, default=settings.war_bracket_factor_default
    )
    safety_margin: Mapped[int] = mapped_column(
        Integer, default=settings.war_safety_margin_default
    )
    cookie_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list of int
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    owner_chat_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    war_hour: Mapped[int] = mapped_column(Integer, default=0)
    war_minute: Mapped[int] = mapped_column(Integer, default=0)
    war_tz: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )


class WarHistoryModel(BaseModel):
    __tablename__ = "war_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    results: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_median_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class LatencyLogModel(BaseModel):
    __tablename__ = "latency_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)


class ProxyPoolModel(BaseModel):
    __tablename__ = "proxy_pool"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proxy_url: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unused")  # unused | used
    owner_chat_id: Mapped[str] = mapped_column(String(64), nullable=False)
    used_by_hero: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_by_war_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)


# Async engine & session
engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
