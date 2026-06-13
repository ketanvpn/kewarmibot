"""KeWarMiBot — Polling + Scheduler Mode Entry. Single-owner."""

import logging
import os
import asyncio
import signal
import re

from src.db import init_db
from src.bot.handlers import build_app, set_bot_instance
from src.scheduler_jobs import start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class TelegramTokenRedactor(logging.Filter):
    """Redact Telegram bot tokens before they reach journald."""

    _token_re = re.compile(r"bot\d{6,}:[A-Za-z0-9_-]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._token_re.sub("bot[REDACTED]", record.msg)
        if record.args:
            record.args = tuple(
                self._token_re.sub("bot[REDACTED]", arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


for handler in logging.getLogger().handlers:
    handler.addFilter(TelegramTokenRedactor())

for noisy_logger in ("httpx", "httpcore"):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def main():
    logger.info("Starting KeWarMiBot v3.0 (single-owner, polling + scheduler)...")

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

    # Start background scheduler
    start_scheduler(get_notifier=_notify)
    logger.info("Scheduler started")

    # Keep alive with graceful shutdown
    stop_event = asyncio.Event()

    def _shutdown_handler(signame: str):
        logger.info(f"Received {signame}, shutting down gracefully...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig.name: _shutdown_handler(s))
        except NotImplementedError:
            pass  # Windows fallback

    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down scheduler...")
        from src.scheduler_jobs import scheduler as sched
        sched.shutdown(wait=False)
        logger.info("Shutting down bot...")
        await ptb_app.updater.stop()
        await ptb_app.stop()
        await ptb_app.shutdown()
        logger.info("KeWarMiBot shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
