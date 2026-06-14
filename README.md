# ⚔️ KeWarMiBot

**Bot Telegram untuk war unlock bootloader Xiaomi — war otomatis tiap malam. Mode single-owner (dipakai 1 pemilik).**

## 📖 Fitur

| Fitur | Deskripsi |
|-------|-----------|
| 🍪 **Cookie Manager** | Tambah, hapus, toggle, auto-refresh cookie Xiaomi — AES-256-GCM encrypted |
| ⚔️ **Auto-War** | War otomatis tiap malam pada jam yang dikonfigurasi (default 00:00 Beijing) |
| ⚙️ **War Config** | Atur hero/cookie, bracket factor, safety margin, hero spacing, jam + timezone war |
| 🔌 **Proxy Pool** | Pool proxy untuk cookie ke-2+ — 1 cookie = 1 IP konsisten |
| 📊 **Status & History** | Latency live + sparkline, riwayat war, statistik per cookie |
| 🔔 **Notifikasi War** | Pre-war (mulai, cookie breakdown, proxy) + post-war (hasil, auto-lock, sisa cookie) |
| 🔒 **Auto-Lock Cookie** | Cookie yang dapat tiket otomatis di-lock + dikeluarkan dari config |

## 🏗️ Arsitektur

```
src/
├── bot/
│   ├── handlers/
│   │   ├── _common.py    # Shared imports/helpers (is_owner, back_button, dll)
│   │   ├── menu.py       # Main menu, /start
│   │   ├── cookies.py    # Cookie CRUD + toggle in/out war
│   │   ├── war.py        # Debug war, auto-war toggle
│   │   ├── config.py     # War config editor
│   │   ├── info.py       # Status, history, stats
│   │   ├── pool.py       # Proxy pool management
│   │   ├── guide.py      # Panduan + cara dapat cookie
│   │   └── router.py     # Callback router + build_app
│   └── notify.py         # Format notifikasi war
├── engine/
│   ├── war.py            # War engine: multiprocess, timing, bracket window
│   ├── war_runner.py     # Single entry point semua jalur war (debug + auto)
│   └── api.py            # Xiaomi API: send_war_request, latency, NTP, proxy CONNECT
├── cookie_service.py     # Cookie encrypt/decrypt + status refresh
├── war_config_service.py # Load/save war config
├── proxy_pool_service.py # Proxy pool lifecycle (add/allocate/consume)
├── crypto.py             # AES-256-GCM helper
├── config.py             # Settings (env)
├── db.py                 # SQLAlchemy async models
└── scheduler_jobs.py     # Background: auto-war, latency, cookie refresh, DB backup
```

## 🚀 Quick Start

```bash
git clone git@github.com:ketanvpn/kewarmibot.git
cd kewarmibot

cp .env.example .env
# Edit .env → BOT_TOKEN, ADMIN_CHAT_IDS (owner = id terkecil), ENCRYPTION_KEY (hex)

pip install -r requirements.txt
python3 main.py
```

## 🧪 Testing

```bash
python3 -m pytest tests/ -v --asyncio-mode=auto
```

## 📦 Deployment

```bash
sudo cp kewarmibot.service /etc/systemd/system/
sudo systemctl enable kewarmibot
sudo systemctl start kewarmibot
sudo systemctl status kewarmibot
```

## 🔐 Security

- Cookie token dienkripsi AES-256-GCM (random nonce per encrypt)
- Cookie hanya didekripsi saat war berjalan
- Akses dibatasi ke `OWNER_CHAT_ID` (single-owner)

## ⏱️ Timing & Proxy Architecture

```
Scheduler (tiap 60 detik) → cek diff ke jam war (default 00:00 Asia/Shanghai)
  diff=5 → warning ke owner
  diff≤3 → trigger war (asyncio.create_task, crash → notif owner)
  reset harian berbasis tanggal (anti-skip kalau menit 00:00 kelewat)

execute_war() → load + decrypt cookie (skip yang sudah menang)
  → alokasi proxy: cookie 1 = IP VPS direct, cookie 2+ = 1 proxy/cookie
    (proxy kurang → cookie tanpa proxy di-skip, gak rebutan IP VPS)
  → run_war_sync():
      5 latency samples → weighted median
      bracket window ±bracket_half di sekitar target_ms
      NTP sync → core affinity → GC disable → spin-lock
      multiprocess heroes → send_war_request()
  → simpan history → auto-lock cookie menang → notif owner

Distribusi IP (3 cookie × 3 hero, interleaved round-robin):
  Cookie 1 → hero 1,4,7 → IP VPS (direct)
  Cookie 2 → hero 2,5,8 → proxy A (1 IP sama)
  Cookie 3 → hero 3,6,9 → proxy B (1 IP sama)
  Multi-hero = timing insurance (1 dari N pas kena window war)
```

Format proxy yang didukung (pool):
`http(s)/socks5://user:pass@host:port`, `user:pass@host:port`, `user:pass:host:port`, `host:port` (password boleh mengandung `:`).

## 📊 Database

- **SQLite** (`data/kewarmibot.db`) via aiosqlite
- 5 model: `CookieModel`, `WarConfigModel`, `WarHistoryModel`, `LatencyLogModel`, `ProxyPoolModel`
- Auto-backup tiap 02:00 Asia/Shanghai, keep 7 hari (`data/backups/`)

## 🛠️ Tech Stack

- **Python 3.10+** · python-telegram-bot · SQLAlchemy (async) · aiosqlite
- **APScheduler** · ntplib · requests
- **multiprocessing** · SSL raw socket · HTTP CONNECT proxy · AES-256-GCM

## 📝 License

MIT
