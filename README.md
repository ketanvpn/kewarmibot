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
5. ⏰ **Auto-War** → Aktifkan scheduler, biarkan bot war tiap 23:57 CST

### 🍪 Cara Ambil Cookie Xiaomi Community

Diperlukan cookie `cUserId`, `passToken`, dan `deviceId` dari situs Xiaomi Community.

**Metode 1: Via Browser DevTools (Desktop)**

1. Buka Chrome/Firefox, login ke https://account.xiaomi.com
2. Buka https://c.mi.com/global → login dengan akun Xiaomi
3. Tekan `F12` → tab **Application** (Chrome) atau **Storage** (Firefox)
4. Di sidebar kiri: **Cookies → https://c.mi.com**
5. Copy value dari cookie berikut:
   - `cUserId`
   - `passToken`
   - `deviceId` (opsional, tapi disarankan)
6. Gabungkan jadi satu string:
   ```
   cUserId=123456789; passToken=xxxxxxxxxxxx; deviceId=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   ```
7. Paste ke bot (token auto-delete + dienkripsi)

**Metode 2: Via Kiwi Browser (Android)**

1. Install [Kiwi Browser](https://play.google.com/store/apps/details?id=com.kiwibrowser.browser)
2. Buka https://c.mi.com/global → login
3. Tap `⋮` → **Developer Tools** → tab **Cookies**
4. Cari dan copy `cUserId`, `passToken`, `deviceId`
5. Gabungkan seperti format di atas, paste ke bot

**Catatan:**
- Cookie expire sekitar 30 hari, perlu update berkala
- Gunakan cookie auto-refresh (10:00 CST) untuk monitor status
- Jangan share cookie ke siapa pun — seperti password
- Device ID penting untuk konsistensi fingerprint

### ⏰ Auto-War: Cara Kerja

Auto-war tidak mengirim request di jam 23:57. **Request dikirim tepat jam 00:00:00.000 CST**.

Alur lengkapnya:

```
23:55 CST  → Notifikasi 5 menit warning via Telegram
             (latensi terbaru, hero, bracket, safety)

23:57 CST  → Persiapan dimulai:
             1. Ukur latency 5× weighted median
             2. Hitung bracket spread per hero
             3. Spawn multiprocess, spin-lock nunggu target

00:00 CST  → SEMUA HERO MELESAT BERSAMAAN
             Presisi timing via spin-lock + perf_counter

Setelah   → Hasil dikirim via Telegram:
             - Per-cookie success rate + progress bar
             - Detail per hero (sukses/gagal + drift ms)
             - Auto simpan ke riwayat
```

**Timeout:** Scheduler memulai persiapan 3 menit sebelum midnight. Pastikan bot tetap jalan dan koneksi stabil di jam 23:55-00:01 CST.

## ⏱️ Scheduler Jobs (Background)

Bot menjalankan 5 background job otomatis. Semua waktu dalam **CST (Beijing/UTC+8)**.

| Job | Jadwal | Fungsi |
|---|---|---|
| 📈 **Latency Monitor** | Setiap 15 menit | Ping server Xiaomi (raw socket) → simpan ke DB. Data dipakai sparkline di `/status` |
| 🍪 **Cookie Auto-Refresh** | 10:00 CST | Refresh status semua cookie (ELIGIBLE/BLOCKED/APPROVED). Notify kalau ada yang gagal |
| 🗄️ **DB Backup** | 02:00 CST | Copy `kewarmibot.db` → `data/backups/`. Keep 7 hari terakhir, hapus otomatis |
| ⚠️ **War Countdown** | 23:55 CST | Kirim notifikasi 5 menit sebelum war (latensi, hero, bracket) |
| ⚔️ **Auto-War** | 23:57 CST | Persiapkan + eksekusi tepat 00:00 CST. Hasil + error dikirim ke Telegram |

### Cara Matikan/Hidupkan Scheduler Jobs

Dari menu bot: **⏰ Auto-War** → toggle ON/OFF. Tapi ini hanya matikan auto-war, job lain (latency, refresh, backup, countdown) tetap jalan.

Edit `src/scheduler_jobs.py` kalau perlu ubah jadwal — semua trigger pakai `CronTrigger` dengan timezone `Asia/Shanghai`.

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