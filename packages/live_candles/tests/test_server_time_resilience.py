"""SERVER_TIME_FAIL resilience (2026-11-09): bounded retry + short-lived last-good-offset fallback. No network."""

from __future__ import annotations

import time
import urllib.error

import pytest

import live_candles.freshness as fr
from live_candles.freshness import evaluate_tip_freshness, expected_closed_open_ms


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    fr._OFFSET_CACHE.clear()
    monkeypatch.setattr(fr.time, "sleep", lambda s: None)
    yield
    fr._OFFSET_CACHE.clear()


def _dns_error():
    return urllib.error.URLError(OSError(-3, "Temporary failure in name resolution"))


def _scripted(monkeypatch, outcomes, server_offset_ms=0):
    """fetch_server_time_ms returns/raises the scripted outcomes in order; the server clock = local + offset."""
    calls = {"n": 0}

    def fake(exchange, *, timeout_sec=5.0):
        o = outcomes[min(calls["n"], len(outcomes) - 1)]
        calls["n"] += 1
        if isinstance(o, Exception):
            raise o
        return int(time.time() * 1000) + server_offset_ms

    monkeypatch.setattr(fr, "fetch_server_time_ms", fake)
    return calls


def _eval(tip_offset_bars=0):
    now = int(time.time() * 1000)
    tip = expected_closed_open_ms("15m", server_now_ms=now) + tip_offset_bars * 900_000
    return evaluate_tip_freshness(exchange="binance", symbol="SOLUSDT", timeframe="15m", local_tip_ms=tip)


def test_transient_dns_error_is_retried_and_passes(monkeypatch):
    calls = _scripted(monkeypatch, [_dns_error(), _dns_error(), 0])
    r = _eval()
    assert r.ok and r.code == "PASS", r
    assert calls["n"] == 3
    assert "retried" in r.detail


def test_all_attempts_fail_without_cache_fails_closed(monkeypatch):
    calls = _scripted(monkeypatch, [_dns_error()])
    r = _eval()
    assert not r.ok and r.code == "SERVER_TIME_FAIL"
    assert calls["n"] == fr.SERVER_TIME_ATTEMPTS
    assert "attempts=" in r.detail and "name resolution" in r.detail


def test_fresh_cached_offset_is_used_when_fetch_fails(monkeypatch):
    _scripted(monkeypatch, [0])
    assert _eval().ok                              # good fetch primes the cache
    _scripted(monkeypatch, [_dns_error()])
    r = _eval()
    assert r.ok and r.code == "PASS"
    assert "server_time_cached" in r.detail


def test_stale_cached_offset_fails_closed(monkeypatch):
    _scripted(monkeypatch, [0])
    assert _eval().ok
    mono, off, skew = fr._OFFSET_CACHE["binance"]
    fr._OFFSET_CACHE["binance"] = (mono - fr.SERVER_OFFSET_MAX_AGE_SEC - 1, off, skew)
    _scripted(monkeypatch, [_dns_error()])
    r = _eval()
    assert not r.ok and r.code == "SERVER_TIME_FAIL"


def test_drifted_clock_is_still_blocked_through_the_cache(monkeypatch):
    _scripted(monkeypatch, [0], server_offset_ms=20_000)   # server 20 s ahead of this machine
    first = _eval()
    assert first.code == "CLOCK_SKEW"
    _scripted(monkeypatch, [_dns_error()])
    r = _eval()
    assert not r.ok and r.code == "CLOCK_SKEW", r         # cached skew re-applied: no entry on a drifted clock
    assert r.clock_skew_ms and r.clock_skew_ms > 5_000


def test_cache_does_not_hide_a_stale_candle(monkeypatch):
    _scripted(monkeypatch, [0])
    assert _eval().ok
    _scripted(monkeypatch, [_dns_error()])
    r = _eval(tip_offset_bars=-1)                          # local tip one bar behind
    assert not r.ok and r.code == "CANDLE_STALE"


def test_retry_respects_the_time_budget(monkeypatch):
    _scripted(monkeypatch, [_dns_error()])
    t = {"v": 0.0}
    monkeypatch.setattr(fr.time, "monotonic", lambda: t.__setitem__("v", t["v"] + 4.0) or t["v"])
    with pytest.raises(RuntimeError):
        fr.fetch_server_time_with_retry("binance", attempts=5, budget_sec=8.0)
