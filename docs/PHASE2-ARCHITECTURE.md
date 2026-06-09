# KeWarMiBot — Fase 2: SaaS via Telegram Bot

> **Status:** Blueprint | **Tanggal:** 2026-06-09
> **Prinsip:** Bot-first. Web cuma skeleton (placeholder).
> **Ref:** Fase 1 (Proxy Pool) ✅

---

## 1. Filosofi: Semua Via Bot

Gak perlu web dashboard dulu. Semua lewat inline keyboard:

```
User: semua flow via @KeWarMIbot
Admin: menu ekstra di bot yang sama (hidden dari user biasa)
Web: cuma skeleton Next.js + endpoint webhook KetantechPay (nanti)
```

---

## 2. User Flow (via Bot)

```
/start
  → "Welcome! Mau buka unlock Xiaomi? Siapkan cookie kamu."
  
  Menu Utama:
  ┌─────────────────────┐
  │ 👤 Profil Saya       │
  │ 🍪 Cookie Saya       │
  │ ⚔️ War Now           │
  │ 📊 Riwayat War       │
  │ 🛒 Beli Slot War     │
  │ ℹ️ Bantuan / FAQ     │
  └─────────────────────┘
```

### 2.1 Register (auto)
```
User pertama kali start → auto-register dengan Telegram ID
Tidak perlu input apa-apa. Data dari Telegram otomatis.
```

### 2.2 Cookie Management
```
🍪 Cookie Saya
  → List cookie (nama, status, deadline)
  → [➕ Tambah Cookie]
  → [🔄 Refresh Status]
  → [🗑️ Hapus]

Flow tambah cookie:
  1. Kirim nama: "Poco F5 Bos"
  2. Kirim token cookie (paste dari browser)
  3. Bot encrypt → simpan → "✅ Cookie tersimpan!"
```

### 2.3 Beli Slot War
```
🛒 Beli Slot War
  → Tampilkan paket:
  ┌─────────────────────────┐
  │ 🥉 Bronze — 5 War        │
  │    Rp 25.000 (Rp 5.000/war) │
  │                          │
  │ 🥈 Silver — 10 War       │
  │    Rp 40.000 (Rp 4.000/war) │
  │                          │
  │ 🥇 Gold — 20 War         │
  │    Rp 70.000 (Rp 3.500/war) │
  │                          │
  │ 💎 Platinum — 50 War     │
  │    Rp 150.000 (Rp 3.000/war)│
  └─────────────────────────┘
  
  → Pilih paket → Bot create order via KetantechPay
  → QRIS muncul (gambar)
  → User bayar → Webhook → Balance +X
  → Bot notif: "✅ Pembayaran sukses! Balance: 5 war"
```

### 2.4 Jalankan War
```
⚔️ War Now
  → Pilih cookie (dropdown/list)
  → Pilih jumlah hero: [4] [6] [8]
  → Konfirmasi: "Gunakan 1 war credit? Balance: 5 → 4"
  → [🔥 MULAI WAR]
  → Progress bar (updating message)
  → Hasil: Hero1 ✅ Hero2 ❌ Hero3 ✅ ...
```

---

## 3. Admin Flow (via Bot, Menu Tersembunyi)

Hanya muncul untuk admin (chat ID di settings):

```
🔰 Admin Panel
┌─────────────────────────┐
│ 👥 Kelola User           │
│ 🔌 Pool Proxy            │
│ 📦 Paket & Harga         │
│ 📊 Laporan               │
│ ⚙️ Settings              │
│ 🔙 Menu Utama            │
└─────────────────────────┘
```

### 3.1 Kelola User
```
👥 Kelola User
  → List user (nama, balance, total war, status)
  → [🔍 Cari User]
  → Click user → detail:
    - Balance, total war, sukses rate
    - [➕ Tambah Balance] (manual topup)
    - [⛔ Suspend] / [✅ Aktifkan]
    - Riwayat order + war
```

### 3.2 Pool Proxy (existing, extend)
```
🔌 Pool Proxy
  → Stats: 100 total | 75 available | 25 used
  → [➕ Bulk Import]
  → [📋 List Available]
  → [📋 List Used]
  → [🗑️ Clear All]
  → [📊 Usage History]
```

### 3.3 Paket & Harga
```
📦 Paket & Harga
  → List paket existing
  → [➕ Tambah Paket] / [✏️ Edit] / [❌ Nonaktifkan]
  → Edit: nama, war_count, price_idr
```

---

## 4. Database Tambahan

### `users`
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id TEXT NOT NULL UNIQUE,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    balance_war INTEGER DEFAULT 0,
    total_wars INTEGER DEFAULT 0,
    total_tickets INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    is_suspended BOOLEAN DEFAULT 0,
    is_admin BOOLEAN DEFAULT 0,        -- extra admin flag besides chat_id list
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### `packages`
```sql
CREATE TABLE packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    war_count INTEGER NOT NULL,
    price_idr INTEGER NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### `orders`
```sql
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    package_id INTEGER REFERENCES packages(id),
    order_ref TEXT NOT NULL UNIQUE,      -- "WAR-XXXXXX"
    amount_idr INTEGER NOT NULL,
    war_count INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    payment_url TEXT,
    paid_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Modifikasi Existing

```sql
-- war_config: tambah user_id
ALTER TABLE war_config ADD COLUMN user_id INTEGER REFERENCES users(id);

-- war_history: tambah user_id + order_id + detail
ALTER TABLE war_history ADD COLUMN user_id INTEGER REFERENCES users(id);
ALTER TABLE war_history ADD COLUMN order_id INTEGER REFERENCES orders(id);

-- cookies: sudah ada owner_chat_id, tambah user_id FK
ALTER TABLE cookies ADD COLUMN user_id INTEGER REFERENCES users(id);

-- proxy_pool: tambah used_by_user_id
ALTER TABLE proxy_pool ADD COLUMN used_by_order_id INTEGER REFERENCES orders(id);
```

---

## 5. Payment Integration (KetantechPay)

### Create Order (Bot → KetantechPay)
```python
async def create_payment(user_id, package):
    order_ref = f"WAR-{uuid4().hex[:8].upper()}"
    
    resp = await http_post("https://pay.ketantech.my.id/api/payment/create", {
        "client_key": settings.ketantechpay_client_key,
        "order_ref": order_ref,
        "amount": package.price_idr,
        "customer_name": user.first_name,
        "expiry_minutes": 15,
        "webhook_url": f"{settings.bot_webhook_base}/api/webhook/payment"
    })
    
    # Simpan order ke DB
    # Kirim QRIS ke user
    return qris_url, order_ref
```

### Webhook Handler (KetantechPay → Bot)
```
POST {bot_webhook_base}/api/webhook/payment
  → Verifikasi signature
  → Update order → paid
  → Tambah balance user
  → Notif Telegram: "✅ Pembayaran sukses! Balance +5 war"
```

### Minimal Webhook Server
```
Bot tetap polling (python-telegram-bot),
tapi tambah mini FastAPI/Flask sidecar di port berbeda
hanya untuk terima webhook payment.
```

---

## 6. War Engine Changes (Minimal)

```python
@dataclass
class WarConfig:
    # ... existing fields ...
    user_id: int | None = None       # NEW
    order_id: int | None = None      # NEW

async def war_with_balance(config: WarConfig):
    # 1. Cek balance user
    # 2. Jalankan war
    # 3. Deduct balance setelah sukses (atau tetap deduct?)
    # 4. Update war_history dengan user_id
    ...
```

**Policy:** Balance tetap di-deduct meskipun war gagal (proxy tetap kepakai).

---

## 7. Folder Structure (Updated)

```
mchrbl-bot/
├── main.py                    # Entry point
├── src/
│   ├── bot/
│   │   ├── handlers.py        # Semua handler bot (existing + new)
│   │   ├── admin_handlers.py  # NEW: admin-only handlers
│   │   ├── payment.py         # NEW: payment flow handlers
│   │   └── middleware.py      # NEW: auth middleware (register check)
│   ├── engine/
│   │   ├── war.py             # Existing, extend for balance
│   │   └── api.py             # Existing
│   ├── services/
│   │   ├── user_service.py    # NEW
│   │   ├── order_service.py   # NEW
│   │   ├── package_service.py # NEW
│   │   └── proxy_pool_service.py  # Existing, extend
│   ├── config.py
│   ├── db.py                  # Existing + models baru
│   └── webhook_server.py      # NEW: mini FastAPI for payment webhook
├── web/                       # NEW: Next.js skeleton (placeholder)
│   └── app/
│       └── page.tsx           # Coming soon page
├── migrations/
│   └── 004_phase2_users.sql
├── docs/
│   └── PHASE2-ARCHITECTURE.md
└── data/
    └── kewarmibot.db
```

---

## 8. Execution Plan (Bot-First)

### Sprint 1: Foundation (~4-6 jam)
- [ ] `users` table + auto-register on `/start`
- [ ] User profile menu (balance, stats)
- [ ] `packages` table + seed 4 paket default
- [ ] `orders` table
- [ ] Beli paket flow (bot inline keyboard)
- [ ] KetantechPay order creation
- [ ] Mini webhook server (FastAPI sidecar)
- [ ] Balance system (+ deduct on war)

### Sprint 2: War Integration (~2-3 jam)
- [ ] War config per user (pilih cookie sendiri)
- [ ] Balance cek sebelum war
- [ ] Deduct balance setelah war
- [ ] War history per user
- [ ] Notifikasi hasil war

### Sprint 3: Admin Panel (~3-4 jam)
- [ ] Admin menu (hidden, chat_id based)
- [ ] User management (list, detail, topup, suspend)
- [ ] Package management (CRUD)
- [ ] Pool monitoring extended
- [ ] Revenue report sederhana (total orders, total income)

### Sprint 4: Polish (~1-2 jam)
- [ ] Web skeleton (Next.js "Coming Soon" page)
- [ ] Bantuan / FAQ menu
- [ ] Error handling yang bagus
- [ ] Logging untuk audit

---

## 9. Cost & Pricing (Reality Check)

⚠️ **Masih perlu data cost proxy.** Saat ini:

| Asumsi | Nilai |
|--------|-------|
| Cost per IP (9proxy) | ~Rp 13.000/IP (paket 5 IP = Rp 65.000) |
| 1 war = 8 hero = 8 IP | Rp 104.000/war |
| 1 war = 4 hero = 4 IP | Rp 52.000/war |

Dengan cost segitu, harga jual harus >Rp 100.000/war untuk 8 hero. Mahal.

**Alternatif perlu diteliti:**
- Proxy-Cheap ($1.99/IP trial → Rp 33.000/IP)
- Webshare static residential (mahal, $35/bln)
- Provider lokal Indo?

Tanpa data cost reliable, pricing masih placeholder.

---

## 10. Open Questions

1. **1 war = 1 hero shot atau 1 batch?** Kalau batch (8 hero), cost mahal. Kalau per hero, user musti ngerti.
2. **Refund policy?** Kalau code 6 semua (gagal total), balance balik?
3. **Rate-limit detection?** Kalau semua hero kena code 6, itu rate-limit atau cookie invalid? Perlu smart detection.
4. **Manual topup?** Admin bisa tambah balance user manual (buat tester / temen).