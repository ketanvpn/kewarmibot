"""War Engine — N-cookie, hero-per-cookie architecture."""

import logging
import multiprocessing as mp
import time
import json
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

from src.engine.api import WarResult, send_war_request, measure_latency, get_ntp_offset, _get_core_ids

logger = logging.getLogger(__name__)

DEFAULT_WAR_TZ = "Asia/Shanghai"  # Beijing time, default for Xiaomi Community
DEFAULT_WAR_HOUR = 0
DEFAULT_WAR_MINUTE = 0

def get_target_ms(war_hour: int = DEFAULT_WAR_HOUR, war_minute: int = DEFAULT_WAR_MINUTE, tz_name: str = DEFAULT_WAR_TZ) -> int:
    """Calculate next target timestamp in ms. Supports any hour/minute/timezone."""
    tz = timezone(timedelta(hours=timezone_offset(tz_name)))
    now = datetime.now(tz)
    target = now.replace(hour=war_hour, minute=war_minute, second=0, microsecond=0)
    if now >= target:
        target = target + timedelta(days=1)
    return int(target.timestamp() * 1000)

def timezone_offset(tz_name: str) -> int:
    """Get timezone offset in hours from UTC for a given IANA timezone name."""
    # Use pytz if available; fall back to hardcoded common ones
    try:
        import pytz
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)
        return int(now.utcoffset().total_seconds() / 3600)
    except ImportError:
        pass
    # Fallback: common timezones
    offsets = {
        "Asia/Shanghai": 8,
        "Asia/Tokyo": 9,
        "Asia/Seoul": 9,
        "Asia/Singapore": 8,
        "Asia/Jakarta": 7,
        "Asia/Jayapura": 9,
        "Asia/Makassar": 8,
        "Asia/Bangkok": 7,
        "Asia/Ho_Chi_Minh": 7,
        "Asia/Kolkata": 5.5,
        "Asia/Dubai": 4,
        "Europe/London": 0,
        "Europe/Berlin": 1,
        "Europe/Moscow": 3,
        "America/New_York": -5,
        "America/Chicago": -6,
        "America/Denver": -7,
        "America/Los_Angeles": -8,
        "America/Sao_Paulo": -3,
        "Pacific/Auckland": 12,
        "Australia/Sydney": 10,
    }
    return offsets.get(tz_name, 8)  # default to CST

MAX_TOTAL_REQUESTS = 16  # hard cap
MAX_COOKIES = 6
MAX_HERO_PER_COOKIE = 8


def get_next_beijing_midnight_ms() -> int:
    """Deprecated. Use get_target_ms()."""
    return get_target_ms(0, 0, "Asia/Shanghai")


@dataclass
class WarConfig:
    cookies: list[tuple[str, str]] = field(default_factory=list)  # [(token, name), ...]
    hero_per_cookie: int = 6
    bracket_factor: float = 0.8
    safety_margin: int = 30
    debug: bool = False
    war_hour: int = 0       # target hour (0-23)
    war_minute: int = 0     # target minute (0-59)
    war_tz: str = "Asia/Shanghai"  # IANA timezone


@dataclass
class WarResultReport:
    hero_results: list[WarResult] = field(default_factory=list)
    latency_median_ms: int = 0
    started_at: datetime | None = None
    cookie_names: list[str] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.hero_results if r.success)

    @property
    def fail_count(self) -> int:
        return len(self.hero_results) - self.success_count

    def format_report(self) -> str:
        from collections import defaultdict

        started = self.started_at.strftime('%Y-%m-%d %H:%M:%S') if self.started_at else ''

        # ── Per-cookie stats ──
        cookie_stats = defaultdict(lambda: {"success": 0, "fail": 0, "codes": set(), "victory_heroes": []})
        for r in self.hero_results:
            cn = r.cookie_name or "?"
            if r.success:
                cookie_stats[cn]["success"] += 1
                cookie_stats[cn]["victory_heroes"].append(r.hero_id)
            else:
                cookie_stats[cn]["fail"] += 1
            cookie_stats[cn]["codes"].add(r.code)

        has_victory = any(s["success"] > 0 for s in cookie_stats.values())
        has_near_miss = any(3 in s["codes"] for s in cookie_stats.values())  # code 3 = Kuota habis

        lines = []

        # ── VICTORY BANNER ──
        if has_victory:
            lines.append("🏆 <b>WAR BERHASIL!</b>")
            for cn, stats in cookie_stats.items():
                if stats["victory_heroes"]:
                    hero_list = ", ".join(f"{cn}-{h:02d}" for h in stats["victory_heroes"])
                    lines.append(f"🎉 Cookie <b>{cn}</b> dapat TIKET! ({hero_list})")
            lines.append("")

        # ── HEADER ──
        lines.append(f"🎯 <b>Hasil War</b> — {started}")
        lines.append(f"⚡ Latency median: {self.latency_median_ms}ms")
        num_cookies = max(len(self.cookie_names), 1)
        lines.append(f"👥 Cookie ({len(self.cookie_names)}): {', '.join(self.cookie_names)}")
        lines.append(f"🥊 Hero/cookie: {len(self.hero_results) // num_cookies}")
        lines.append(f"✅ Success: {self.success_count} | ❌ Fail: {self.fail_count}")
        lines.append("")

        # ── PER-COOKIE SUMMARY ──
        for cn in (self.cookie_names or list(cookie_stats.keys())):
            stats = cookie_stats.get(cn, {"success": 0, "fail": 0})
            total = stats["success"] + stats["fail"]
            if total == 0:
                continue
            rate = stats["success"] / total * 100 if total > 0 else 0
            bar_len = 5
            green = round(rate / 20)
            green = max(0, min(green, bar_len))
            red = bar_len - green
            bar = "🟩" * green + "🟥" * red
            prefix = "🏆 " if has_victory and stats["success"] > 0 else "🍪 "
            lines.append(f"{prefix}<b>{cn}</b>: {bar} {rate:.0f}% ({stats['success']}/{total})")

        lines.append("")

        # ── DETAIL (tone-aware header) ──
        if has_victory:
            lines.append("⚔️ <b>Detail:</b>")
        elif has_near_miss:
            lines.append("⚠️ <b>Detail:</b>")
        else:
            lines.append("😔 <b>Detail:</b>")

        for r in self.hero_results:
            if r.success:
                lines.append(f"✅ {r.cookie_name}-{r.hero_id:02d}: <b>{r.msg}</b> 🎉")
            else:
                drift_s = f" (+{r.drift_ms}ms)" if r.drift_ms is not None else ""
                lines.append(f"❌ {r.cookie_name}-{r.hero_id:02d}: {r.msg}{drift_s}")

        # ── FOOTER ──
        if has_victory:
            lines.append(f"\n🔥 <b>Total: {self.success_count} tiket berhasil didapat!</b>")
        elif has_near_miss:
            lines.append(f"\n⚠️ Kuota hampir habis — coba lagi reset berikutnya.")

        return "\n".join(lines)


def _war_worker(
    hero_id: int,
    target_wave: int,
    cookie: str,
    cookie_name: str,
    base_time_ms: int,
    perf_base_ns: int,
    ntp_offset: int,
    core_id: int | None,
    result_queue: mp.Queue,
) -> None:
    result = send_war_request(cookie, hero_id, target_wave, base_time_ms, perf_base_ns, ntp_offset, core_id)
    result.cookie_name = cookie_name
    result_queue.put(result)


def run_war_sync(config: WarConfig) -> WarResultReport:
    """
    Run war. Each cookie gets `hero_per_cookie` heroes spawned.
    All heroes fire in the same bracket window, shared across cookies.
    """
    num_cookies = len(config.cookies)
    if num_cookies == 0:
        return WarResultReport(
            hero_results=[WarResult(hero_id=0, success=False, code=-1, tag="Error", msg="No cookies")],
            cookie_names=[],
            started_at=datetime.now(),
        )

    # Clamp total
    hero_per = min(config.hero_per_cookie, MAX_HERO_PER_COOKIE)
    total_heroes = hero_per * num_cookies
    if total_heroes > MAX_TOTAL_REQUESTS:
        hero_per = MAX_TOTAL_REQUESTS // num_cookies
        total_heroes = hero_per * num_cookies

    report = WarResultReport(
        cookie_names=[name for _, name in config.cookies],
        started_at=datetime.now(),
    )

    # 1. Latency measurement
    latency_samples = []
    for i in range(5):
        lat = measure_latency(samples=3)
        latency_samples.append(lat)
        time.sleep(0.8)

    weighted = []
    for i, lat in enumerate(latency_samples):
        weighted.extend([lat] * (i + 1))
    weighted.sort()
    latency_median = weighted[len(weighted) // 2]
    report.latency_median_ms = latency_median

    # 2. Target — use configurable war_time + timezone
    if config.debug:
        target_ms = int(time.time() * 1000) + 20000
    else:
        target_ms = get_target_ms(config.war_hour, config.war_minute, config.war_tz)

    base_send = target_ms - latency_median
    bracket_half = int(latency_median * config.bracket_factor) + config.safety_margin

    # 3. Distribute offsets across ALL heroes (per-cookie, not shared)
    offsets = []
    if total_heroes > 1:
        for i in range(total_heroes):
            offset = int(
                -bracket_half
                + config.safety_margin
                + (2 * (bracket_half - config.safety_margin) * i) / (total_heroes - 1)
            )
            offsets.append(offset)
    else:
        offsets = [0]

    # 4. NTP sync
    ntp_offset = get_ntp_offset()
    logger.info(f"NTP offset: {ntp_offset}ms")

    # 5. Detect performance cores
    core_ids = _get_core_ids()
    if core_ids:
        logger.info(f"Performance cores: {core_ids}")
    else:
        logger.info("No big cores detected — default affinity")

    # 6. Spawn: interleaved round-robin across cookies (hero 1→cookie0, hero 2→cookie1, ...)
    result_queue: mp.Queue = mp.Queue()
    processes = []
    base_perf = time.perf_counter_ns()
    base_time = int(time.time() * 1000)

    for i, offset in enumerate(offsets):
        hero_id = i + 1
        cookie_idx = i % num_cookies
        token, cname = config.cookies[cookie_idx]
        target_wave = base_send + offset
        core_id = core_ids[i % len(core_ids)] if core_ids else None
        p = mp.Process(
            target=_war_worker,
            args=(hero_id, target_wave, token, cname, base_time, base_perf, ntp_offset, core_id, result_queue),
        )
        processes.append(p)
        time.sleep(0.15)

    # 7. Start
    while int(time.time() * 1000) < base_send - 1000:
        time.sleep(0.05)

    for p in processes:
        p.start()
    for p in processes:
        p.join()

    # 8. Results
    hero_results: list[WarResult] = []
    while not result_queue.empty():
        hero_results.append(result_queue.get())

    hero_results.sort(key=lambda r: r.hero_id)
    report.hero_results = hero_results
    return report