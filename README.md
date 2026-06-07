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
| ⏰ **Configurable Auto-War** | Target war bisa diatur jam + timezone (default 00:00 Beijing). Dynamic scheduler adaptif |
| 📈 **Latency Monitor** | Ping server Xiaomi tiap 15 menit + sparkline grafik di status |
| 📊 **Cookie Statistics** | Akumulasi success rate per cookie dari semua history. Tau cookie mana yang jago |
| 📜 **War History** | Riwayat hasil war (success rate, latency, detail per hero + per-cookie progress bar) |
| 🔐 **Security** | Cookie dienkripsi AES-256-GCM, token message auto-delete dari chat |
| 🎯 **HFT Precision** | Core affinity, NTP sync (3 server), GC disable saat spin-lock — presisi milidetik |

---

## 🛠️ Arsitektur

```
┌──────────────────────────────────────┐
│           Telegram Bot               │
│  python-telegram-bot (polling mode)  │
│  Menu dashboard, cookie CRUD,        │
│  war config, scheduler, stats        │
└──────────┬───────────────────────────┘
           │
┌──────────▼───────────────────────────┐
│          War Engine                   │
│  Multiprocess, raw socket HTTP,       │
│  weighted median ping, bracket spread │
│  NTP sync, core affinity, GC disable  │
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

### Perintah Cepat

| Command | Fungsi |
|---|---|
| `/start` | Dashboard utama |
| `/status` | Dashboard latency + status cookie |
| `/config` | Atur hero, bracket, safety, pilih cookie |
| `/war` | Trigger debug war (+20 detik, buat testing) |
| `/riwayat` | Riwayat hasil war terakhir |

### Alur Manual

1. **`/start`** → Dashboard dengan status lengkap
2. 🍪 **Tambah Cookie** → Input nama + paste token (token auto-delete dari chat)
3. ⚙️ **War Config** → Pilih 2 cookie untuk war, atur hero/bracket/safety
4. 🚀 **War Now (Debug)** → Test war +20 detik (untuk testing)
5. ⏰ **Auto-War** → Aktifkan scheduler. Default target 00:00 Beijing. Bisa diganti jam + timezone di War Config

### 🍪 Cara Ambil Cookie Xiaomi Community

Cookie diambil dari aplikasi Xiaomi Community di HP, bukan dari browser.

**Langkah-langkah:**

1. Install aplikasi **network sniffer**, pilih salah satu:
   - [HTTP Toolkit](https://httptoolkit.com/) (PC, rekomendasi)
   - [Proxyman](https://proxyman.io/) (macOS)
   - [PCAPdroid](https://play.google.com/store/apps/details?id=com.emanuelef.remote_capture) (Android, no root)
   - HTTP Sniffer lainnya

2. Jalankan sniffer → biasanya akan minta izin VPN/CA certificate. Izinkan.

3. Buka aplikasi **Xiaomi Community** di HP:
   - Masuk ke tab **Me** (pojok kanan bawah)
   - Tap **Unlock Bootloader**

4. Kembali ke aplikasi sniffer, matikan capture/VPN, lalu **cari request** berikut:
   ```
   https://sgp-api.buy.mi.com/bbs/api/global/apply/bl-auth
   ```

5. Di bagian **Headers**, cari header `Cookie:`. Copy **semua teks setelah `Cookie:`** — biasanya diawali `new_bbs_serviceToken=...`

6. Paste/tempel langsung ke bot saat tambah cookie.

**Contoh format cookie:**
```
new_bbs_serviceToken=xxxxxxxxxxxxxxxxxxxx; cUserId=123456789; deviceId=xxxx-xxxx-xxxx-xxxx
```

**Catatan:**
- Cookie expire sekitar 30 hari, perlu update berkala
- Gunakan cookie auto-refresh (10:00 CST) untuk monitor status
- Jangan share cookie ke siapa pun — seperti password
- Satu akun Xiaomi = satu cookie

### ⏰ Auto-War: Cara Kerja

Target war bisa diatur di **⚙️ War Config → ⏰ Target**. Default 00:00 Asia/Shanghai (Xiaomi Community).

Alur (dengan contoh target 00:00 Beijing):

```
T-5 menit  → Notifikasi warning via Telegram
             (latensi terbaru, hero, bracket, safety, target label)

T-3 menit  → Persiapan dimulai:
             1. NTP sync — kalibrasi clock ke 3 server
             2. Ukur latency 5× weighted median
             3. Hitung bracket spread per hero
             4. Deteksi performance core → pin hero process
             5. Spawn multiprocess, spin-lock nunggu target
             6. GC disable — zero jitter saat spin-lock

TARGET     → SEMUA HERO MELESAT BERSAMAAN
             Presisi timing via spin-lock + perf_counter + NTP

Setelah    → Hasil dikirim via Telegram:
             - Per-cookie success rate + progress bar
             - Detail per hero (sukses/gagal + drift ms)
             - Auto simpan ke riwayat
```

Scheduler mengecek tiap 1 menit apakah sudah waktunya war berdasarkan config. Gak perlu edit kode kalau ganti jam target.

## ⏱️ Scheduler Jobs (Background)

Bot menjalankan 4 background job otomatis.

| Job | Jadwal | Fungsi |
|---|---|---|
| 📈 **Latency Monitor** | Setiap 15 menit | Ping server Xiaomi (raw socket) → simpan ke DB. Data dipakai sparkline di `/status` |
| 🎯 **Dynamic War Checker** | Setiap 1 menit | Cek apakah sudah T-5 menit (warning) atau T-3 menit (eksekusi war) dari target config. Adaptif terhadap `war_hour`/`war_minute`/`war_tz` |
| 🍪 **Cookie Auto-Refresh** | 10:00 Asia/Shanghai | Refresh status semua cookie (ELIGIBLE/BLOCKED/APPROVED). Notify kalau ada yang gagal |
| 🗄️ **DB Backup** | 02:00 Asia/Shanghai | Copy `kewarmibot.db` → `data/backups/`. Keep 7 hari terakhir, hapus otomatis |

### Cara Matikan/Hidupkan Scheduler Jobs

Dari menu bot: **⏰ Auto-War** → toggle ON/OFF. Ini hanya matikan auto-war checker.

Edit `src/scheduler_jobs.py` kalau perlu ubah jadwal.

### Notifikasi Kegagalan

Setiap job yang kritikal akan kirim notif kalau gagal:
- Cookie refresh gagal → ada yang BLOCKED/EXPIRED
- Auto-war crash → error detail dikirim
- DB backup gagal → notifikasi error

Latency monitor **tidak** kirim notif — cuma log ke journal.

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