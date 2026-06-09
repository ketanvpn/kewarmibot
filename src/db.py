"""Database models — SQLAlchemy async."""

import datetime
from sqlalchemy import Boolean, Integer, String, Text, Float, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

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
    cookie_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list of int (max 2)
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


class UserModel(BaseModel):
    """Multi-tenant user + balance."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    balance_war: Mapped[int] = mapped_column(Integer, default=0)
    total_wars: Mapped[int] = mapped_column(Integer, default=0)
    total_tickets: Mapped[int] = mapped_column(Integer, default=0)
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    war_enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # user can toggle auto-war on/off
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class PackageModel(BaseModel):
    """War slot packages."""
    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    war_count: Mapped[int] = mapped_column(Integer, nullable=False)
    price_idr: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

class OrderModel(BaseModel):
    """Payment orders."""
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), nullable=False)
    order_ref: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    amount_idr: Mapped[int] = mapped_column(Integer, nullable=False)
    war_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    payment_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

class BotSettingModel(BaseModel):
    """Key-value config store."""
    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class ProxyPoolModel(BaseModel):
    """Proxy pool for multi-IP war requests."""
    __tablename__ = "proxy_pool"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proxy_url: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unused")  # unused | used
    owner_chat_id: Mapped[str] = mapped_column(String(64), nullable=False)
    used_by_hero: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_by_war_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

class WarHistoryModel(BaseModel):
    __tablename__ = "war_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    config_id: Mapped[int] = mapped_column(ForeignKey("war_config.id"), nullable=True)
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