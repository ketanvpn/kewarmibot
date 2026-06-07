#!/bin/bash
# KeWarMiBot - Setup Script
set -e

echo "=========================================="
echo "  ⚔️ KeWarMiBot Setup"
echo "=========================================="
echo ""

# 1. Python dependencies
echo "[1/4] Installing Python dependencies..."
pip install python-telegram-bot[job-queue] pydantic pydantic-settings sqlalchemy aiosqlite apscheduler requests ntplib cryptography httpx

# 2. Generate encryption key
echo ""
echo "[2/4] Generating encryption key..."
ENC_KEY=$(openssl rand -hex 32)
echo "ENCRYPTION_KEY=${ENC_KEY}"

# 3. .env file
echo ""
echo "[3/4] Creating .env file..."
if [ -f .env ]; then
    echo ".env already exists, updating ENCRYPTION_KEY..."
    grep -q "ENCRYPTION_KEY=" .env && sed -i "s/ENCRYPTION_KEY=.*/ENCRYPTION_KEY=${ENC_KEY}/" .env || echo "ENCRYPTION_KEY=${ENC_KEY}" >> .env
else
    cp .env.example .env
    sed -i "s/ENCRYPTION_KEY=.*/ENCRYPTION_KEY=${ENC_KEY}/" .env
    echo "Created .env — edit BOT_TOKEN and other settings"
fi

# 4. Create data dir
mkdir -p data

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Edit .env: set BOT_TOKEN from @BotFather"
echo "  2. Run: python3 main.py"
echo "  3. Or install service: sudo cp kewarmibot.service /etc/systemd/system/ && sudo systemctl enable --now kewarmibot"
echo ""
echo "IMPORTANT: Save your encryption key: ${ENC_KEY}"