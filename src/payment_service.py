"""KetantechPay Payment Gateway integration."""

import logging
import httpx
import uuid
from dataclasses import dataclass
from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class CreateOrderRequest:
    order_ref: str
    amount: int  # Rp
    customer_name: str
    expiry_minutes: int = 15


@dataclass
class PaymentResponse:
    order_ref: str
    status: str  # pending, paid, expired, failed
    payment_url: str | None
    amount: int
    message: str | None = None


async def create_payment_order(req: CreateOrderRequest) -> PaymentResponse:
    """
    Create payment order via KetantechPay.
    Returns payment URL + order ref.
    """
    if not settings.ketantechpay_base_url or not settings.ketantechpay_client_key:
        logger.error("KetantechPay config missing")
        raise ValueError("Payment gateway not configured")

    payload = {
        "order_ref": req.order_ref,
        "amount_idr": req.amount,
        "customer_name": req.customer_name,
        "expiry_minutes": req.expiry_minutes,
        "webhook_url": f"{settings.webhook_base_url}/api/webhook/payment" if settings.webhook_base_url else None,
    }

    headers = {
        "X-Client-Key": settings.ketantechpay_client_key,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            url = f"{settings.ketantechpay_base_url}/api/v1/payments/charge"
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        logger.info(f"Payment order created: {req.order_ref} ({req.amount} Rp)")

        return PaymentResponse(
            order_ref=req.order_ref,
            status="pending",
            payment_url=data.get("payment_url") or data.get("qris_url"),
            amount=req.amount,
        )

    except httpx.HTTPError as e:
        logger.error(f"KetantechPay error: {e}")
        raise


async def check_payment_status(order_ref: str) -> PaymentResponse:
    """
    Check payment status via KetantechPay.
    """
    if not settings.ketantechpay_base_url:
        raise ValueError("Payment gateway not configured")

    headers = {"X-Client-Key": settings.ketantechpay_client_key}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{settings.ketantechpay_base_url}/api/v1/payments/{order_ref}"
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        return PaymentResponse(
            order_ref=order_ref,
            status=data.get("status", "unknown"),
            payment_url=data.get("payment_url"),
            amount=data.get("amount_idr", 0),
            message=data.get("message"),
        )

    except httpx.HTTPError as e:
        logger.error(f"KetantechPay status check error: {e}")
        raise


def verify_webhook_signature(body: str, signature: str) -> bool:
    """
    Verify KetantechPay webhook signature.
    Signature = HMAC-SHA256(body, secret).hex()
    """
    import hmac
    import hashlib

    if not settings.ketantechpay_webhook_secret:
        logger.warning("Webhook secret not set — skipping signature verification")
        return True

    expected = hmac.new(
        settings.ketantechpay_webhook_secret.encode(),
        body.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)