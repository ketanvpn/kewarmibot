"""KeWarMiBot handlers — split from single file into modular modules."""
from src.bot.handlers.router import build_app, set_bot_instance

__all__ = ["build_app", "set_bot_instance"]
