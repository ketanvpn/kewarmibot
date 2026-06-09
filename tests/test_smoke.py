"""Smoke test — semua import + DB init + config load."""
import pytest


def test_import_db():
    from src.db import (
        BaseModel, CookieModel, WarConfigModel, UserModel,
        PackageModel, OrderModel, BotSettingModel,
        ProxyPoolModel, WarHistoryModel, LatencyLogModel,
        AsyncSessionLocal, init_db, engine,
    )
    assert AsyncSessionLocal is not None


def test_import_config():
    from src.config import settings
    assert settings.bot_token == "dummy:token"
    assert settings.admin_ids == {690744680}
    assert len(settings.encryption_key_bytes) == 32


def test_import_services():
    from src.cookie_service import add_cookie, get_cookie_token, status_label
    from src.user_service import get_or_create_user, deduct_balance, toggle_war_enabled
    from src.package_service import list_packages, revenue_today
    from src.settings_service import get_setting, set_setting
    from src.payment_service import create_payment_order, CreateOrderRequest
    from src.proxy_pool_service import pool_stats, pool_add


def test_import_engine():
    from src.engine.api import measure_latency, WarResult, get_ntp_offset
    from src.engine.war import WarConfig, WarResultReport, run_war_sync, get_target_ms, timezone_offset


def test_import_handlers():
    from src.bot.handlers import build_app, set_bot_instance
    app = build_app()
    assert app is not None
    assert app.bot is not None


def test_import_scheduler():
    from src.scheduler_jobs import scheduler
    assert scheduler is not None


def test_import_webhook():
    from src.webhook_server import app
    assert app is not None