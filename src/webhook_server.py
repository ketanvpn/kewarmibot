"""Webhook sidecar — FastAPI server for KetantechPay payment callbacks."""

import logging
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import asyncio

from src.db import AsyncSessionLocal
from src.package_service import mark_order_paid, get_order
from src.user_service import get_user_by_id

logger = logging.getLogger(__name__)

app = FastAPI(title="KeWarMiBot Webhook Server")

_bot_notifier = None  # Set from main.py


def set_bot_notifier(notifier):
    """Set callback to send Telegram notifications."""
    global _bot_notifier
    _bot_notifier = notifier


@app.get("/health")
async def health():
    return {"status": "ok", "service": "kewarmibot-webhook"}


@app.post("/api/webhook/payment")
async def webhook_payment(request: Request):
    """
    KetantechPay webhook callback.
    Body: {
        "order_ref": "WAR-ABC123",
        "status": "paid" | "failed" | "expired",
        "amount_idr": 50000,
        "paid_at": "2026-06-09T14:22:00Z",
        ...
    }
    Header: X-Signature: HMAC-SHA256
    """
    try:
        body = await request.body()
        signature = request.headers.get("X-Signature", "")

        # Verify signature
        from src.payment_service import get_runtime_payment_config, verify_webhook_signature

        payment_cfg = await get_runtime_payment_config()
        webhook_secret = payment_cfg.get("webhook_secret") or ""
        if not verify_webhook_signature(body.decode(), signature, webhook_secret):
            logger.warning(f"Invalid webhook signature: {signature[:20]}...")
            raise HTTPException(status_code=401, detail="Invalid signature")

        data = json.loads(body)
        order_ref = data.get("order_ref")
        status = data.get("status")
        amount = data.get("amount_idr", 0)

        logger.info(f"Webhook: {order_ref} → {status}")

        # Update order + balance
        async with AsyncSessionLocal() as session:
            order = await get_order(session, order_ref)
            if not order:
                logger.warning(f"Order not found: {order_ref}")
                return JSONResponse({"status": "error", "message": "Order not found"}, status_code=404)

            if status == "paid":
                credited = await mark_order_paid(session, order_ref)
                if not credited:
                    logger.info(f"Order {order_ref} already paid — duplicate webhook ignored")
                    return {"status": "ok", "duplicate": True}

                logger.info(f"Order {order_ref} paid → user {order.user_id} +{order.war_count} balance")

                # Notify user
                if _bot_notifier:
                    from src.bot.notify import format_payment_success
                    pkg_name = f"Order #{order.order_ref}"
                    user = await get_user_by_id(session, order.user_id)
                    new_balance = user.balance_war if user else order.war_count
                    text = format_payment_success(pkg_name, amount, order.war_count, new_balance)
                    try:
                        await _bot_notifier(str(order.user_id), text)
                    except Exception as e:
                        logger.error(f"Notify failed: {e}")
            else:
                logger.info(f"Order {order_ref} → {status}")

        return {"status": "ok"}

    except json.JSONDecodeError:
        logger.error("Invalid JSON in webhook")
        return JSONResponse({"status": "error", "message": "Invalid JSON"}, status_code=400)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


def run_webhook_server(port: int = 8001, notifier=None):
    """
    Run webhook server in background thread.
    Call this from main.py after bot is initialized.
    """
    set_bot_notifier(notifier)

    import uvicorn

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)

    # Run in thread
    import threading

    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    thread.start()
    logger.info(f"Webhook server started on 0.0.0.0:{port}")
    return server
