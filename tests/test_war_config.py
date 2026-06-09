"""WarConfig dataclass tests — field validation."""
import pytest
from src.engine.war import WarConfig, WarResultReport, run_war_sync, MAX_TOTAL_REQUESTS


def test_war_config_defaults():
    cfg = WarConfig()
    assert cfg.cookies == []
    assert cfg.hero_per_cookie == 6
    assert cfg.bracket_factor == 0.8
    assert cfg.safety_margin == 30
    assert cfg.debug is False
    assert cfg.war_hour == 0
    assert cfg.war_minute == 0
    assert cfg.war_tz == "Asia/Shanghai"
    assert cfg.hero_spacing_ms == 0
    assert cfg.use_pool is False
    assert cfg.owner_chat_id == ""


def test_war_config_all_fields():
    """Verify all fields we fixed are accepted."""
    cfg = WarConfig(
        cookies=[("token1", "Akun A"), ("token2", "Akun B")],
        hero_per_cookie=4,
        bracket_factor=0.7,
        safety_margin=20,
        hero_spacing_ms=10,
        use_pool=True,
        owner_chat_id="12345",
        debug=True,
        war_hour=23,
        war_minute=57,
        war_tz="Asia/Jakarta",
    )
    assert len(cfg.cookies) == 2
    assert cfg.hero_per_cookie == 4
    assert cfg.bracket_factor == 0.7
    assert cfg.safety_margin == 20
    assert cfg.hero_spacing_ms == 10
    assert cfg.use_pool is True
    assert cfg.owner_chat_id == "12345"
    assert cfg.debug is True
    assert cfg.war_hour == 23
    assert cfg.war_minute == 57
    assert cfg.war_tz == "Asia/Jakarta"


def test_run_war_sync_empty_cookies():
    """Empty cookies → returns error report, doesn't crash."""
    cfg = WarConfig(cookies=[])
    report = run_war_sync(cfg)
    assert isinstance(report, WarResultReport)
    assert len(report.hero_results) == 1
    assert report.hero_results[0].success is False
    assert report.hero_results[0].code == -1


def test_run_war_sync_clamps_total():
    """MAX_TOTAL_REQUESTS should clamp."""
    # 6 cookies × 8 heroes = 48 > 16 → should clamp
    cookies = [(f"token{i}", f"Cookie{i}") for i in range(6)]
    cfg = WarConfig(cookies=cookies, hero_per_cookie=8, debug=True)
    report = run_war_sync(cfg)
    # Total heroes clamped to MAX_TOTAL_REQUESTS (16)
    assert len(report.hero_results) <= MAX_TOTAL_REQUESTS + 1  # +1 for error hero


def test_war_result_report_stats():
    from src.engine.api import WarResult
    report = WarResultReport(
        hero_results=[
            WarResult(hero_id=1, success=True, code=1, tag="Approved", msg="OK"),
            WarResult(hero_id=2, success=False, code=3, tag="Failed", msg="Kuota habis"),
            WarResult(hero_id=3, success=True, code=2, tag="Info", msg="Sudah punya"),
        ],
        latency_median_ms=145,
        cookie_names=["Akun A"],
    )
    assert report.success_count == 2
    assert report.fail_count == 1
    assert "WAR BERHASIL" in report.format_report()
    assert "145ms" in report.format_report()