# KeWarMiBot — Sprint 5-7 Roadmap

> Dibuat: 2026-06-09 | Setelah audit + fix 7 bug Sprint 2-4

---

## Ringkasan Progress

| Sprint | Scope | Status |
|--------|-------|--------|
| **Sprint 1** | Telethon prototype (Clash of Clans style) | ✅ Done |
| **Sprint 2** | Port ke PTB + SQLAlchemy + Cookie Manager + War Config | ✅ Done |
| **Sprint 3** | Admin Panel Extended (multi-tenant, payment, packages) | ✅ Done |
| **Sprint 4** | Auto-War refactor per-user (bukan cuma admin) | ✅ Done |
| **Sprint 5** | Hardening: test + refactor + fix debt | ⏳ NOW |
| **Sprint 6** | Polish: dashboard, reporting, payment live | ⏳ Next |
| **Sprint 7** | Launch readiness + monitoring | ⏳ Final |

**Filosofi:** Sprint 5-6 tidak tambah fitur besar — kita perkuat pondasi supaya Sprint 7 launch aman.

---

## 🏗️ Sprint 5: Hardening (Estimasi: 1-2 hari)

> **Goal:** Gak boleh ada bug runtime lagi. Ada test minimal. Code gak bikin pusing kalau diedit 2 minggu lagi.

### 5.1 — Test Suite Minimum (PRIORITAS #1)

**Kenapa:** 3 critical bugs tadi gak akan lolos kalau ada 5 unit test sederhana.

```
tests/
├── test_war_config.py      # WarConfig instantiation + field validation
├── test_cookie_service.py   # encrypt → decrypt roundtrip
├── test_user_service.py     # get_or_create → balance ops
├── test_pool_service.py     # pool_add → pool_stats → pool_clear
├── test_war_engine.py       # run_war_sync with empty cookies
├── test_smoke.py            # All imports + DB init + config load
└── conftest.py              # Async SQLite test fixture
```

**Tool:** `pytest` + `pytest-asyncio` (udah ada di requirements)

**Target:** ~20 test case, cover semua service + edge case

**Cara jalan:** `python -m pytest tests/ -v` sebelum tiap commit

---

### 5.2 — Extract `_execute_war()` (Deduplikasi)

**Kenapa:** `war_debug`, `autowar_run_now`, `_run_war_for_user` — 3 fungsi yg 80% sama.

```python
# src/engine/war_runner.py (NEW)
async def execute_war(
    user_tg_id: str,
    cfg: dict,
    debug: bool = False,
    deduct: bool = True,
    notify: Callable | None = None,
) -> WarResultReport:
    """
    Single entry point for ALL war execution.
    - Load cookies from DB
    - Check balance (optional deduct)
    - Run war_sync
    - Save history + award tickets
    - Notify user
    """
```

**Impact:**
- `handlers.py` → `war_debug()` jadi 3 baris: `await execute_war(...)`
- `handlers.py` → `autowar_run_now()` jadi 3 baris
- `scheduler_jobs.py` → `_run_war_for_user()` jadi 5 baris
- Bug fix di satu tempat → semua path kebeneran

**Risk: LOW** — logic yg sama, cuma diextract.

---

### 5.3 — Split `handlers.py` (73KB → modular)

**Kenapa:** Sekarang 1700+ baris dalam 1 file. Nambah fitur = tambah pusing.

```
src/bot/
├── handlers/
│   ├── __init__.py
│   ├── menu.py          # /start, main_menu, profile, guide, support
│   ├── cookies.py       # Cookie CRUD handlers
│   ├── war.py           # debug war, auto-war, war_now
│   ├── config.py        # WarConfig editors (hero, bracket, safety, time)
│   ├── admin.py         # User mgmt, packages, settings, revenue
│   ├── payment.py       # beli, payment confirmation
│   └── pool.py          # Proxy pool menu
├── router.py            # menu_router + pattern routing
└── app.py               # build_app()
```

**Risk: LOW** — cuma moving code, gak ganti logic.

**Impact:** Maintenance 10x lebih gampang. File per file max 300 baris.

---

### 5.4 — Fix Notification Inconsistency

**Kenapa:** Format notifikasi beda-beda:
- Auto-war: ada `─` separator + balance
- Debug war: ada `─` separator + balance
- `autowar_run_now`: GAK ADA balance
- Webhook: beda format lagi

**Fix:** Extract `notify_war_result(user_id, report, final_balance)` → dipakai semua path.

---

## 🎨 Sprint 6: Polish & Production (Estimasi: 1-2 hari)

> **Goal:** Bot siap dipake user beneran. Payment live. Dashboard basic.

### 6.1 — Payment Gateway Live

**Yang perlu:**
- [ ] Set `KETANTECHPAY_CLIENT_KEY` beneran di `.env`
- [ ] Set `KETANTECHPAY_WEBHOOK_SECRET` beneran
- [ ] Update `WEBHOOK_BASE_URL` ke domain production
- [ ] Test end-to-end: user beli paket → scan QRIS → webhook → saldo nambah

**Risk: MEDIUM** — tergantung KetantechPay siap terima webhook dari server ini.

---

### 6.2 — Web Dashboard Sederhana

**Kenapa:** Admin panel di Telegram bagus, tapi:
- Revenue chart gak enak di teks
- User growth tracking perlu visual
- War success rate per hari perlu line chart

**Stack rekomendasi:** HTML statis + Chart.js, embed di handler `/stats_web` yg return HTML.

```
GET /dashboard → halaman statis dengan:
  - Revenue chart (line, 30 hari)
  - War success rate (bar, 7 hari)
  - Active users (number)
  - Top users by tickets
```

**Alternatif simpler:** Bikin perintah `/report` yg kirim CSV 30 hari ke admin. No dashboard, no infra tambahan.

---

### 6.3 — Latency Monitor Graph

**Yang ada sekarang:** Sparkline 24 sampel di menu Status.

**Improvement:**
- Simpan latency log 30 hari (sekarang udah ada `latency_log` table)
- `/latency` command → kirim grafik PNG (matplotlib sederhana)
- Alert admin kalau latency spike >500ms

---

### 6.4 — Panduan User (Onboarding Flow)

**Yang ada sekarang:** `/start` langsung main menu.

**Improvement:**
- First-time user → interactive onboarding (3 step)
- "Halo! Kayaknya pertama kali ya? Yuk siapin dulu..."
- Step 1: Tambah cookie (dipandu)
- Step 2: Beli tiket pertama (gratis 1 tiket trial?)
- Step 3: "Siap! War otomatis malam ini jam 00:00"

---

## 🚀 Sprint 7: Launch Readiness (Estimasi: 1 hari)

> **Goal:** Production-grade. Siap di-publish ke komunitas.

### 7.1 — Monitoring & Alerting

- [ ] Healthcheck endpoint: bot + DB + scheduler + latency
- [ ] Alert admin kalau bot crash/restart (via Telegram)
- [ ] Alert kalau auto-war gagal 3x berturut-turut
- [ ] Backup DB restore procedure documented

---

### 7.2 — Rate Limiting & Abuse Prevention

- [ ] Max 1 debug war per user per 5 menit
- [ ] Max cookie add: 6 per user
- [ ] Auto-suspend user yg 5x payment failed
- [ ] Log semua admin action (topup, suspend, edit)

---

### 7.3 — Launch Checklist

- [ ] Domain + HTTPS untuk webhook (atau tunnel Cloudflare)
- [ ] Bot profile photo + description di @BotFather
- [ ] Welcome message dengan panduan singkat
- [ ] Test dengan 2-3 real user (beta)
- [ ] Group support Telegram dibuat
- [ ] Payment terms & refund policy ditulis
- [ ] `.env` production values diverifikasi
- [ ] Backup DB otomatis diverifikasi (jalan tiap 02:00)

---

## 📊 Estimasi Total

| Sprint | Task | Estimasi |
|--------|------|----------|
| **Sprint 5** | Test suite + extract war + split handlers | 4-6 jam |
| **Sprint 6** | Payment live + dashboard + onboarding | 4-6 jam |
| **Sprint 7** | Monitoring + launch checklist | 2-4 jam |
| **Total** | | **10-16 jam** |

**Dengan pace sekarang (2 sprint/hari) → SELESAI DALAM 2-3 HARI.**

---

## 🎯 Hidden Gem: Kenapa Ini Udah Hampir Selesai

1. **Bug environment-dependent (bukan logic)** — QRIS gak muncul karena key kosong, bukan karena flow salah. Tinggal isi key → jalan.
2. **DB schema stabil** — 8 tabel, relasi mature. Gak ada migration breaking.
3. **Core war engine gak disentuh lagi** — multiprocessing, NTP sync, timing udah proven dari versi Telethon.
4. **Yang tersisa itu polish** — bukan "apakah bisa jalan?", tapi "apakah enak dipake?"

---

> **TL;DR:** Project ini 80% selesai. Sprint 5-7 itu 20% terakhir yg bikin dari "jalan" jadi "production-grade". Gak ada arsitektur ulang, gak ada rewrite. Cuma hardening + polish.