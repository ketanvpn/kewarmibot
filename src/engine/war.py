"""War Engine — N-cookie, hero-per-cookie architecture."""

import multiprocessing as mp
import time
import json
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

from src.engine.api import WarResult, send_war_request, measure_latency

BEIJING_TZ = timezone(timedelta(hours=8))

MAX_TOTAL_REQUESTS = 16  # hard cap
MAX_COOKIES = 2
MAX_HERO_PER_COOKIE = 8


def get_next_beijing_midnight_ms() -> int:
    now = datetime.now(BEIJING_TZ)
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if now >= today_midnight:
        next_midnight = today_midnight + timedelta(days=1)
    else:
        next_midnight = today_midnight
    return int(next_midnight.timestamp() * 1000)


@dataclass
class WarConfig:
    cookies: list[tuple[str, str]] = field(default_factory=list)  # [(token, name), ...]
    hero_per_cookie: int = 6
    bracket_factor: float = 0.8
    safety_margin: int = 30
    debug: bool = False


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
        lines = [
            f"🎯 <b>Hasil War</b> — {self.started_at.strftime('%Y-%m-%d %H:%M:%S') if self.started_at else ''}",
            f"⚡ Latency median: {self.latency_median_ms}ms",
            f"👥 Cookie ({len(self.cookie_names)}): {', '.join(self.cookie_names)}",
            f"🥊 Hero/cookie: {len(self.hero_results) // max(len(self.cookie_names), 1)}",
            f"✅ Success: {self.success_count} | ❌ Fail: {self.fail_count}",
            "",
        ]

        # Per-cookie stat
        from collections import defaultdict
        cookie_stats = defaultdict(lambda: {"success": 0, "fail": 0})
        for r in self.hero_results:
            cn = r.cookie_name or "?"
            if r.success:
                cookie_stats[cn]["success"] += 1
            else:
                cookie_stats[cn]["fail"] += 1

        for cn, stats in cookie_stats.items():
            total = stats["success"] + stats["fail"]
            rate = stats["success"] / total * 100 if total > 0 else 0
            bar = "🟩" * max(1, round(rate / 20)) + "🟥" * (5 - max(1, round(rate / 20)))
            lines.append(f"🍪 <b>{cn}</b>: {bar} {rate:.0f}% ({stats['success']}/{total})")

        lines.append("")
        lines.append("<b>Detail:</b>")
        for r in self.hero_results:
            emoji = "✅" if r.success else "❌"
            drift_s = f" (drift: {r.drift_ms:+.1f}ms)" if r.drift_ms is not None else ""
            lines.append(f"{emoji} {r.cookie_name}-{r.hero_id:02d}: {r.msg}{drift_s}")
        return "\n".join(lines)


def _war_worker(
    hero_id: int,
    target_wave: int,
    cookie: str,
    cookie_name: str,
    base_time_ms: int,
    perf_base_ns: int,
    ntp_offset: int,
    result_queue: mp.Queue,
) -> None:
    result = send_war_request(cookie, hero_id, target_wave, base_time_ms, perf_base_ns, ntp_offset)
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

    # 2. Target
    if config.debug:
        target_ms = int(time.time() * 1000) + 20000
    else:
        target_ms = get_next_beijing_midnight_ms()

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

    # 4. Spawn: hero_0..hero_{hero_per-1} → cookie_0, hero_{hero_per}.. → cookie_1, etc
    result_queue: mp.Queue = mp.Queue()
    processes = []
    base_perf = time.perf_counter_ns()
    base_time = int(time.time() * 1000)
    ntp_offset = 0

    for i, offset in enumerate(offsets):
        hero_id = i + 1
        cookie_idx = i // hero_per
        token, cname = config.cookies[cookie_idx]
        target_wave = base_send + offset
        p = mp.Process(
            target=_war_worker,
            args=(hero_id, target_wave, token, cname, base_time, base_perf, ntp_offset, result_queue),
        )
        processes.append(p)
        time.sleep(0.15)

    # 5. Start
    while int(time.time() * 1000) < base_send - 1000:
        time.sleep(0.05)

    for p in processes:
        p.start()
    for p in processes:
        p.join()

    # 6. Results
    hero_results: list[WarResult] = []
    while not result_queue.empty():
        hero_results.append(result_queue.get())

    hero_results.sort(key=lambda r: r.hero_id)
    report.hero_results = hero_results
    return report