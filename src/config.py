"""KeWarMiBot — Settings via env vars."""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str = ""
    admin_chat_ids: str = "690744680"
    encryption_key: str = ""
    database_url: str = "sqlite+aiosqlite:///data/kewarmibot.db"
    war_hero_count_default: int = 4
    war_bracket_factor_default: float = 0.8
    war_safety_margin_default: int = 30

    @property
    def admin_ids(self) -> set[int]:
        return {int(x.strip()) for x in self.admin_chat_ids.split(",") if x.strip()}

    @property
    def encryption_key_bytes(self) -> bytes:
        if not self.encryption_key:
            raise ValueError("ENCRYPTION_KEY not set")
        return bytes.fromhex(self.encryption_key)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()