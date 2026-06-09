"""Webhook sidecar — FastAPI server for KetantechPay payment callbacks."""

import logging
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import asyncio

from src.config import settings
from src.db import AsyncSessionLocal
from src.package_service import mark_order_paid, get_order
from src.user_service import add_balance

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
        from src.payment_service import verify_webhook_signature

        if not verify_webhook_signature(body.decode(), signature):
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
                await mark_order_paid(session, order_ref)
                # Add balance
                await add_balance(session, order.user_id, order.war_count)
                logger.info(f"Order {order_ref} paid → user {order.user_id} +{order.war_count} balance")

                # Notify user
                if _bot_notifier:
                    text = (
                        f"✅ <b>Pembayaran Sukses!</b>\\n"
                        f"━━━━━━━━━━━━━━━━━━\\n"
                        f"📦 {order.package_id} war\\n"
                        f"💰 Rp {amount:,}\\n"
                        f"━━━━━━━━━━━━━━━━━━\\n"
                        f"💳 Saldo baru: <b>{order.war_count}</b>\\n"
                        f"<i>Siap mulai war!</i>"
                    )
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