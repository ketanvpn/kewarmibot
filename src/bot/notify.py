"""Notify utilities — unified notification formatting."""
import logging

logger = logging.getLogger(__name__)

SEPARATOR = "─" * 28


def format_war_notification(report, title: str = "⚔️ War") -> str:
    """Unified format for ALL war result notifications."""
    body = report.format_report() if hasattr(report, 'format_report') else str(report)
    return (
        f"<b>{title}</b>\n"
        f"{SEPARATOR}\n"
        f"{body}\n"
        f"{SEPARATOR}"
    )
