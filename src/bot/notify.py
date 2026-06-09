"""Notify utilities — unified notification formatting across all paths."""
import logging
from typing import Callable

logger = logging.getLogger(__name__)

SEPARATOR = "─" * 28


def format_war_notification(report, final_balance: int, title: str = "⚔️ War") -> str:
    """Unified format for ALL war result notifications.

    Used by: war_debug, auto-war, autowar_run_now, webhook
    """
    body = report.format_report() if hasattr(report, 'format_report') else str(report)
    return (
        f"<b>{title}</b>\n"
        f"{SEPARATOR}\n"
        f"{body}\n"
        f"{SEPARATOR}\n"
        f"🎫 Tiket tersisa: <b>{final_balance}</b>"
    )


def format_insufficient_balance(balance: int, needed: int, cookie_count: int) -> str:
    """Unified insufficient balance message."""
    return (
        f"⚠️ <b>Tiket Tidak Cukup</b>\n"
        f"{SEPARATOR}\n"
        f"🎫 Tiket kamu: <b>{balance}</b>\n"
        f"🎯 Butuh: <b>{needed}</b> tiket ({cookie_count} cookie)\n"
        f"{SEPARATOR}\n"
        f"<i>Beli tiket dulu di menu 🎫 Beli Tiket War</i>"
    )


def format_payment_success(package_name: str, amount: int, war_count: int, new_balance: int) -> str:
    """Unified payment success notification."""
    return (
        f"✅ <b>Pembayaran Sukses!</b>\n"
        f"{SEPARATOR}\n"
        f"📦 {package_name}\n"
        f"💰 Rp {amount:,}\n"
        f"{SEPARATOR}\n"
        f"🎫 Saldo baru: <b>{new_balance}</b>\n"
        f"<i>Siap mulai war!</i>"
    )


def format_warning(time_label: str, latency_text: str, hero_count: int, cookie_count: int, balance: int, cost: int) -> str:
    """Unified auto-war warning message."""
    return (
        f"⚡ <b>War Otomatis Malam Ini!</b>\n"
        f"{SEPARATOR}\n"
        f"Auto-war dalam ~5 menit ({time_label})\n\n"
        f"⚡ Latensi: {latency_text}\n"
        f"🥊 Hero/cookie: {hero_count}\n"
        f"🍪 Cookie: {cookie_count}\n"
        f"🔄 Request: {hero_count * cookie_count}\n"
        f"🎫 Tiket: {balance} → {balance - cost}\n\n"
        f"<i>Pastikan koneksi stabil.</i>"
    )