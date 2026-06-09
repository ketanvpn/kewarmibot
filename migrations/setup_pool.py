#!/usr/bin/env python3
"""Setup migration script for proxy_pool table."""
import sys, asyncio
sys.path.insert(0, "/root/.openclaw/workspace/projects/mchrbl-bot")
from src.db import init_db

asyncio.run(init_db())
print("Migration: proxy_pool table created (if not exists)")