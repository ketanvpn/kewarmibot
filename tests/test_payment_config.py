"""Payment runtime config tests."""

import hashlib
import hmac

import pytest

from src.payment_service import get_runtime_payment_config, verify_webhook_signature
from src.settings_service import set_setting


def test_verify_webhook_signature_uses_explicit_secret():
    body = '{"order_ref":"ORD-1","status":"paid"}'
    signature = hmac.new(b"secret-a", body.encode(), hashlib.sha256).hexdigest()

    assert verify_webhook_signature(body, signature, "secret-a") is True
    assert verify_webhook_signature(body, signature, "secret-b") is False


@pytest.mark.asyncio
async def test_runtime_payment_config_prefers_db_settings(db_session):
    await set_setting(db_session, "payment_base_url", "https://pay.example.test")
    await set_setting(db_session, "payment_client_key", "client-from-db")
    await set_setting(db_session, "payment_webhook_secret", "secret-from-db")
    await set_setting(db_session, "webhook_base_url", "https://bot.example.test")

    cfg = await get_runtime_payment_config()

    assert cfg["base_url"] == "https://pay.example.test"
    assert cfg["client_key"] == "client-from-db"
    assert cfg["webhook_secret"] == "secret-from-db"
    assert cfg["webhook_base"] == "https://bot.example.test"
