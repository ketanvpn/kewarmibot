"""KeWarMiBot — Polling + Scheduler Mode Entry."""

import logging
import os
import asyncio

from telegram import Bot

from src.config import settings
from src.db import init_db
from src.bot.handlers import build_app, set_bot_instance
from src.scheduler_jobs import start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Starting KeWarMiBot (polling + scheduler)...")

    os.makedirs("data", exist_ok=True)

    await init_db()
    logger.info("Database initialized")

    # Build PTB app
    ptb_app = build_app()
    await ptb_app.initialize()
    await ptb_app.start()

    # Set bot instance for handlers
    set_bot_instance(ptb_app.bot)

    # Set up notifier for scheduler to send Telegram messages
    async def _notify(chat_id: str, message: str):
        try:
            await ptb_app.bot.send_message(chat_id=int(chat_id), text=message, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Notify failed for {chat_id}: {e}")

    # Patch scheduler module to use our notifier
    import src.scheduler_jobs as sj
    sj._notifier = _notify

    # Delete webhook & start polling
    await ptb_app.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook deleted, polling active")

    await ptb_app.updater.start_polling(allowed_updates=["message", "callback_query"])
    logger.info("Bot started")

    # Start background scheduler (latency monitor + auto-war + countdown)
    start_scheduler(get_notifier=_notify)
    logger.info("Scheduler started")

    # Keep alive
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())