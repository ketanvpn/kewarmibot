"""Xiaomi API interactions — cookie validation, war send."""

import gc
import json
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any

import ntplib
import requests

USER_AGENT = "okhttp/4.12.0"
STATE_URL = "https://sgp-api.buy.mi.com/bbs/api/global/user/bl-switch/state"
UNLOCK_URL = "https://sgp-api.buy.mi.com/bbs/api/global/apply/bl-auth"
HOST = "sgp-api.buy.mi.com"
TIMEOUT = 10


@dataclass
class WarResult:
    hero_id: int
    success: bool
    code: int
    tag: str
    msg: str
    drift_ms: float | None = None
    cookie_name: str = ""


async def check_cookie_status(cookie: str) -> dict[str, Any]:
    """Check cookie eligibility against Xiaomi API."""
    headers = {"Cookie": cookie, "User-Agent": USER_AGENT}
    resp = requests.get(STATE_URL, headers=headers, timeout=TIMEOUT, verify=True)
    data = resp.json()
    code = data.get("code", -1)
    if code == 100004:
        return {"error": "Cookie expired / need login", "code": code}
    inner = data.get("data", {})
    return {
        "is_pass": inner.get("is_pass", -1),
        "button_state": inner.get("button_state", -1),
        "deadline_format": inner.get("deadline_format", ""),
        "code": code,
    }


def get_result_meaning(code: int) -> tuple[bool, str]:
    """Map Xiaomi response code to (success, message)."""
    if code == 1:
        return True, "Tiket didapat!"
    if code == 2:
        return True, "Sudah punya tiket"
    if code == 3:
        return False, "Kuota habis"
    if code == 6:
        return False, "Server sibuk"
    return False, f"Result code: {code}"


def measure_latency(samples: int = 5) -> int:
    """Measure round-trip latency to Xiaomi server. Returns median ms."""
    times = []
    for _ in range(samples):
        try:
            start = time.time()
            sock = socket.create_connection((HOST, 443), timeout=5)
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(sock, server_hostname=HOST):
                pass
            times.append((time.time() - start) * 1000)
        except Exception:
            pass
        time.sleep(0.5)
    if not times:
        return 300  # default fallback
    times.sort()
    return int(times[len(times) // 2])


def get_ntp_offset() -> int:
    """Sync with NTP servers. Returns offset in milliseconds."""
    client = ntplib.NTPClient()
    for server in ["pool.ntp.org", "id.pool.ntp.org", "time.google.com"]:
        try:
            r = client.request(server, version=3, timeout=5)
            return int(r.offset * 1000)
        except Exception:
            continue
    return 0


def _get_core_ids() -> list[int]:
    """Detect performance cores via cpufreq (>2GHz)."""
    cores = []
    cpu_dir = "/sys/devices/system/cpu/"
    import os
    n = os.cpu_count() or 1
    for i in range(n):
        try:
            with open(f"{cpu_dir}cpu{i}/cpufreq/cpuinfo_max_freq") as f:
                maxf = int(f.read().strip())
            if maxf >= 2_000_000:
                cores.append(i)
        except Exception:
            continue
    cores.sort()
    return cores


def _parse_proxy(proxy_url: str) -> tuple[str, int, str | None, str | None]:
    """Parse proxy string into (host, port, user, pass).

    Supports:
      - http://user:pass@host:port  (and https://, socks5://)
      - user:pass@host:port
      - user:pass:host:port
      - host:port
    Password may contain ':' (handled via rsplit on the host:port side).
    """
    s = proxy_url.strip()
    # Strip scheme if present
    if "://" in s:
        s = s.split("://", 1)[1]

    user = pwd = None

    if "@" in s:
        # creds@host:port  — creds may contain ':' in password
        cred, hostport = s.rsplit("@", 1)
        if ":" in cred:
            user, pwd = cred.split(":", 1)
        else:
            user = cred
        host, port = hostport.rsplit(":", 1)
        return host, int(port), user, pwd

    parts = s.split(":")
    if len(parts) == 2:
        # host:port
        return parts[0], int(parts[1]), None, None
    if len(parts) >= 4:
        # user:pass:host:port  (pass may contain ':' → everything between user and host:port)
        user = parts[0]
        host = parts[-2]
        port = parts[-1]
        pwd = ":".join(parts[1:-2])
        return host, int(port), user, pwd
    raise ValueError(f"Invalid proxy format: {proxy_url}")


def _connect_via_proxy(proxy_url: str, target_host: str, target_port: int) -> socket.socket:
    """Connect to target via HTTP CONNECT proxy.

    Accepts multiple proxy formats (see _parse_proxy).
    """
    phost, pport, puser, ppass = _parse_proxy(proxy_url)

    sock = socket.create_connection((phost, pport), timeout=10)

    # CONNECT request
    connect_req = f"CONNECT {target_host}:{target_port} HTTP/1.1\r\nHost: {target_host}:{target_port}\r\n"
    if puser and ppass:
        import base64
        cred = base64.b64encode(f"{puser}:{ppass}".encode()).decode()
        connect_req += f"Proxy-Authorization: Basic {cred}\r\n"
    connect_req += "\r\n"

    sock.sendall(connect_req.encode())

    # Read response
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(1024)
        if not chunk:
            raise ConnectionError("Proxy closed connection")
        resp += chunk

    status_line = resp.split(b"\r\n")[0].decode()
    if "200" not in status_line:
        sock.close()
        raise ConnectionError(f"Proxy CONNECT failed: {status_line}")

    return sock


def send_war_request(
    cookie: str,
    hero_id: int,
    target_time_ms: int,
    base_time_ms: int,
    perf_base_ns: int,
    ntp_offset: int,
    core_id: int | None = None,
    proxy_url: str | None = None,
) -> WarResult:
    """Send a single war request at target_time_ms (± spin-wait).
    
    proxy_url format: user:pass:host:port (HTTP CONNECT proxy)
    """
    # Core affinity — pin to performance core
    if core_id is not None:
        import os
        try:
            os.sched_setaffinity(0, {core_id})
        except Exception:
            pass

    payload_str = '{"is_retry": false}'
    raw_http = (
        f"POST /bbs/api/global/apply/bl-auth HTTP/1.1\r\n"
        f"Host: {HOST}\r\n"
        f"User-Agent: {USER_AGENT}\r\n"
        f"Cookie: {cookie}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(payload_str)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
        f"{payload_str}"
    ).encode("utf-8")

    try:
        if proxy_url:
            sock = _connect_via_proxy(proxy_url, HOST, 443)
        else:
            sock = socket.create_connection((HOST, 443), timeout=5)
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(sock, server_hostname=HOST) as ssock:
            # Sleep until close to target
            while True:
                now = base_time_ms + (time.perf_counter_ns() - perf_base_ns) // 1_000_000 + ntp_offset
                remain = target_time_ms - now
                if remain > 20:
                    time.sleep((remain - 15) / 1000.0)
                elif remain > 2:
                    time.sleep(0)
                else:
                    break

            # Spin-lock — disable GC to prevent jitter
            gc.disable()
            try:
                while (base_time_ms + (time.perf_counter_ns() - perf_base_ns) // 1_000_000 + ntp_offset) < target_time_ms:
                    pass

                ssock.sendall(raw_http)
                drift = (
                    base_time_ms
                    + (time.perf_counter_ns() - perf_base_ns) // 1_000_000
                    + ntp_offset
                    - target_time_ms
                )
            finally:
                gc.enable()

            # Parse response
            resp_bytes = ssock.recv(4096)
            resp_str = resp_bytes.decode("utf-8", errors="ignore")
            if "\r\n\r\n" in resp_str:
                body = resp_str.split("\r\n\r\n", 1)[1]
                resp_json = json.loads(body)
                code = resp_json.get("data", {}).get("apply_result", -1)
            else:
                code = -1

            success, msg = get_result_meaning(code)
            tag = "Info" if code == 2 else ("Approved" if success else "Failed")
            return WarResult(
                hero_id=hero_id,
                success=success,
                code=code,
                tag=tag,
                msg=msg,
                drift_ms=drift,
            )

    except Exception as e:
        return WarResult(
            hero_id=hero_id,
            success=False,
            code=-1,
            tag="Error",
            msg=str(e),
        )