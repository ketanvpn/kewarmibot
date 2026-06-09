# ⚔️ KeWarMiBot

**Bot Telegram untuk jasa perang unlock bootloader Xiaomi — war otomatis setiap malam.**

## 📖 Fitur

| Fitur | Deskripsi |
|-------|-----------|
| 🍪 **Cookie Manager** | Tambah, hapus, auto-refresh cookie Xiaomi — AES-256 encrypted |
| 🎫 **Sistem Tiket** | Beli paket, scan QRIS (KetantechPay), saldo aman |
| ⚔️ **Auto-War** | War otomatis tiap malam — 1 tiket = 1 cookie per malam |
| ⚙️ **War Config** | Atur hero/cookie, bracket factor, safety margin — per user |
| 🔌 **Proxy Pool** | Pool proxy HTTP untuk distribusi beban + anti-IP ban |
| 📊 **Dashboard** | Latency live + sparkline, war history, statistik cookie |
| 🛡️ **Admin Panel** | Kelola user, paket, topup, suspend, setting global |
| 📈 **Reporting** | Revenue hari ini/total, user count, order history |

## 🏗️ Arsitektur

```
src/
├── bot/handlers/     # 10 modular handler files (was 1 file 1592 lines)
│   ├── menu.py       # Main menu, /start, /admin
│   ├── cookies.py    # Cookie CRUD + ConversationHandler
│   ├── war.py        # Debug war, auto-war toggle, run-now
│   ├── config.py     # War config editor
│   ├── payment.py    # Tiket browsing, purchase, payment
│   ├── info.py       # Status, history, stats, profile
│   ├── admin.py      # User mgmt, packages, settings
│   ├── pool.py       # Proxy pool management
│   ├── guide.py      # FAQ + support contacts
│   └── router.py     # Callback router + build_app
├── engine/
│   ├── war.py        # War engine: multiprocess, timing, bracket
│   ├── war_runner.py # Single entry point for all war paths
│   └── api.py        # Xiaomi API: send_war_request, latency, NTP
├── services/         # All service modules
├── scheduler_jobs.py # Background: auto-war, latency, backup
└── webhook_server.py # Payment callback receiver
```

## 🚀 Quick Start

```bash
# Clone
git clone <repo-url>
cd mchrbl-bot

# Setup env
cp .env.example .env
# Edit .env → fill BOT_TOKEN, KETANTECHPAY_CLIENT_KEY, etc.

# Install
pip install -r requirements.txt

# Run
python3 main.py
```

## 🧪 Testing

```bash
# Run full test suite (44 tests)
python3 -m pytest tests/ -v --asyncio-mode=auto

# Run specific module
python3 -m pytest tests/test_war_config.py -v --asyncio-mode=auto
```

## 📦 Deployment

```bash
# Systemd service (production)
sudo cp kewarmibot.service /etc/systemd/system/
sudo systemctl enable kewarmibot
sudo systemctl start kewarmibot

# Check status
sudo systemctl status kewarmibot
```

## 🔐 Security

- Cookie tokens dienkripsi AES-256-GCM (random nonce per encrypt)
- Cookie hanya didekripsi saat war berjalan
- Payment webhook signature verification
- Admin-only access untuk panel, topup, setting

## ⏱️ Timing Architecture

```
Scheduler (tiap 60 detik) → check diff to 00:00 Beijing
  diff=5 → warning ke semua user
  diff≤3 → trigger war PARALLEL (asyncio.create_task)

Per-user war:
  execute_war() → decrypt cookies → check balance → run_war_sync()
    → 5 latency samples → weighted median
    → bracket window ±bracket_half around target_ms
    → NTP sync → core affinity → GC disable
    → multiprocess heroes → send_war_request()
    → save history → award tickets → notify
```

## 📊 Database

- **SQLite** (default) atau **PostgreSQL**
- 8 tabel: users, cookies, war_config, war_history, packages, orders, bot_settings, proxy_pool, latency_log
- Auto-backup tiap 02:00 WIB, keep 7 hari

## 🛠️ Tech Stack

- **Python 3.10+** · python-telegram-bot · SQLAlchemy (async)
- **APScheduler** · aiosqlite · ntplib · requests
- **multiprocessing** · SSL raw socket · AES-GCM
- **KetantechPay** (QRIS payment gateway)

## 📝 License

MIT