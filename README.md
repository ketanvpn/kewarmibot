# ⚔️ KeWarMiBot

**Xiaomi Bootloader Unlock War Telegram Bot**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
![License](https://img.shields.io/badge/License-GPLv3-blue.svg?style=flat-square)
![Status](https://img.shields.io/badge/Status-Production_Ready-success?style=flat-square)

Bot Telegram untuk perang *unlock bootloader* Xiaomi dengan presisi milidetik. Kelola cookie, konfigurasi strategi bracket, auto-war jadwal harian.

---

## ⚡ Fitur

| Fitur | Deskripsi |
|---|---|
| 🍪 **Cookie Manager** | Simpan cookie Xiaomi Community (AES-256-GCM encrypted). Multi-cookie, bisa simpan punya temen |
| 📊 **Live Dashboard** | Status cookie (ELIGIBLE/BLOCKED/APPROVED), countdown reset harian, auto-war status |
| ⚙️ **War Config** | Atur hero per cookie (2-8), bracket factor, safety margin — visual inline keyboard |
| ⚔️ **Multi-Cookie War** | Maks 2 cookie per war. Hero per cookie = tembakan per akun full, bukan diencerkan |
| ⏰ **Auto-War Scheduler** | War otomatis 23:57 CST tiap hari + notifikasi 5 menit sebelumnya |
| 📈 **Latency Monitor** | Ping server Xiaomi tiap 15 menit + sparkline grafik di status |
| 📜 **War History** | Riwayat hasil war (success rate, latency, detail per hero) |
| 🔐 **Security** | Cookie dienkripsi AES-256-GCM, token message auto-delete dari chat |

---

## 🛠️ Arsitektur

```
┌──────────────────────────────────────┐
│           Telegram Bot               │
│  python-telegram-bot (polling mode)  │
│  Menu dashboard, cookie CRUD,        │
│  war config, scheduler               │
└──────────┬───────────────────────────┘
           │
┌──────────▼───────────────────────────┐
│          War Engine                   │
│  Multiprocess, raw socket HTTP,       │
│  weighted median ping, bracket spread │
└──────────┬───────────────────────────┘
           │
┌──────────▼───────────────────────────┐
│         SQLite + SQLAlchemy           │
│  cookies (encrypted), war_config,     │
│  war_history, latency_log             │
└──────────────────────────────────────┘
```

---

## 📦 Setup

```bash
# 1. Clone
git clone https://github.com/ketanvpn/kewarmibot.git
cd kewarmibot

# 2. Install
pip install -e .
# atau manual:
pip install python-telegram-bot[job-queue] pydantic pydantic-settings sqlalchemy aiosqlite apscheduler requests cryptography httpx

# 3. Generate encryption key
openssl rand -hex 32

# 4. Konfigurasi .env
cp .env.example .env
# Edit: BOT_TOKEN (dari @BotFather), ENCRYPTION_KEY, ADMIN_CHAT_IDS

# 5. Database
mkdir -p data

# 6. Jalankan
python main.py
```

### Systemd Service

```bash
sudo cp kewarmibot.service /etc/systemd/system/
sudo systemctl enable --now kewarmibot
```

---

## 🔧 Konfigurasi

| Variable | Default | Deskripsi |
|---|---|---|
| `BOT_TOKEN` | — | Token dari @BotFather |
| `ADMIN_CHAT_IDS` | `690744680` | Chat ID admin (comma-separated) |
| `ENCRYPTION_KEY` | — | 32-byte hex key untuk AES-256-GCM |
| `DATABASE_URL` | `sqlite+aiosqlite:///data/kewarmibot.db` | DB path |

---

## 🎮 Cara Pakai

1. **`/start`** → Dashboard dengan status lengkap
2. 🍪 **Tambah Cookie** → Input nama + paste token (token auto-delete dari chat)
3. ⚙️ **War Config** → Pilih 2 cookie untuk war, atur hero/bracket/safety
4. 🚀 **War Now (Debug)** → Test war +20 detik (untuk testing)
5. ⏰ **Auto-War** → Aktifkan scheduler, biarkan bot war tiap 23:57 CST

---

## 📂 Struktur

```
kewarmibot/
├── main.py              # Entry point
├── setup.sh              # Auto-install script
├── kewarmibot.service    # systemd unit
├── src/
│   ├── config.py         # Settings (env vars)
│   ├── db.py             # DB models
│   ├── crypto.py         # AES-256-GCM
│   ├── cookie_service.py # Cookie CRUD
│   ├── war_config_service.py # War config persistence
│   ├── scheduler_jobs.py # APScheduler jobs
│   ├── bot/
│   │   └── handlers.py  # Telegram handlers (dashboard, config, war)
│   └── engine/
│       ├── api.py        # Xiaomi API (status, latency, send)
│       └── war.py        # War orchestrator
└── data/                 # SQLite DB (auto-created)
```

---

## ⚠️ Disclaimer

Tool ini dibuat untuk tujuan edukasi dan penggunaan personal. Gunakan sesuai ketentuan layanan Xiaomi. Kami tidak bertanggung jawab atas penyalahgunaan.

---

## 📜 License

GPL v3 — lihat [LICENSE](LICENSE)