"""Unit tests for LIVE-DATA-001 tip freshness (no network)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from live_candles.freshness import (
    clear_data_unsafe,
    clock_skew_excluding_rtt_ms,
    evaluate_tip_freshness,
    expected_closed_open_ms,
    gate_allows_new_entries,
    read_data_unsafe,
    write_data_unsafe,
)


def test_expected_closed_open_15m():
    # 2024-01-01 00:14:30 UTC → forming 00:00, expected closed open = previous = 2023-12-31 23:45
    # Use a known ms: 1704067200000 = 2024-01-01 00:00:00 UTC
    # At 00:07:00 (1704067620000), expected closed open = 23:45 previous day = 1704066300000
    server = 1_704_067_620_000  # 00:07:00
    assert expected_closed_open_ms("15m", server_now_ms=server) == 1_704_066_300_000


def test_tip_pass_stale_ahead_skew(tmp_path: Path):
    server = 1_704_067_620_000  # 00:07
    expected = expected_closed_open_ms("15m", server_now_ms=server)
    wall = server  # no skew

    ok = evaluate_tip_freshness(
        exchange="binance",
        symbol="ETHUSDT",
        timeframe="15m",
        local_tip_ms=expected,
        server_now_ms=server,
        local_wall_ms=wall,
        fetch_server_time=False,
    )
    assert ok.ok and ok.code == "PASS"

    stale = evaluate_tip_freshness(
        exchange="binance",
        symbol="ETHUSDT",
        timeframe="15m",
        local_tip_ms=expected - 15 * 60_000,
        server_now_ms=server,
        local_wall_ms=wall,
        fetch_server_time=False,
    )
    assert not stale.ok and stale.code == "CANDLE_STALE"

    ahead = evaluate_tip_freshness(
        exchange="binance",
        symbol="ETHUSDT",
        timeframe="15m",
        local_tip_ms=expected + 15 * 60_000,
        server_now_ms=server,
        local_wall_ms=wall,
        fetch_server_time=False,
    )
    assert not ahead.ok and ahead.code == "CANDLE_AHEAD"

    skew = evaluate_tip_freshness(
        exchange="binance",
        symbol="ETHUSDT",
        timeframe="15m",
        local_tip_ms=expected,
        server_now_ms=server,
        local_wall_ms=server + 60_000,
        clock_skew_max_ms=5_000,
        fetch_server_time=False,
    )
    assert not skew.ok and skew.code == "CLOCK_SKEW"


def test_clock_skew_excludes_http_round_trip():
    # 5.8s HTTP (the live CancelledDataUnsafe pattern) is not clock drift.
    assert (
        clock_skew_excluding_rtt_ms(
            wall_before_ms=1_787_000_412_438,
            server_now_ms=1_787_000_418_255,
            wall_after_ms=1_787_000_418_400,
        )
        == 0
    )
    # Server 12s ahead of the whole request window is still skew.
    assert (
        clock_skew_excluding_rtt_ms(
            wall_before_ms=1_000_000,
            server_now_ms=1_012_000,
            wall_after_ms=1_002_000,
        )
        == 10_000
    )


def test_data_unsafe_flag_roundtrip(tmp_path: Path):
    db = tmp_path / "shared_candles.db"
    # Ensure meta table via write
    write_data_unsafe(
        exchange="binance",
        symbol="ETHUSDT",
        timeframe="15m",
        reason="COLLECTOR_ERROR",
        detail={"error": "boom"},
        db_path=db,
    )
    flagged = read_data_unsafe(
        exchange="binance", symbol="ETHUSDT", timeframe="15m", db_path=db
    )
    assert flagged is not None
    assert flagged["reason"] == "COLLECTOR_ERROR"
    clear_data_unsafe(
        exchange="binance", symbol="ETHUSDT", timeframe="15m", db_path=db
    )
    assert (
        read_data_unsafe(
            exchange="binance", symbol="ETHUSDT", timeframe="15m", db_path=db
        )
        is None
    )


def test_collector_fleet_flag_blocks_entries(tmp_path: Path):
    db = tmp_path / "shared_candles.db"
    write_data_unsafe(
        exchange="binance",
        symbol="COLLECTOR",
        timeframe="1m",
        reason="COLLECTOR_ERROR",
        db_path=db,
    )
    # Seed a tip row so newest_ts_ms can work if called — gate should still block
    # on collector flag before tip compare when also_check_collector_flag=True.
    con = sqlite3.connect(str(db))
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS candles (
          exchange TEXT, symbol TEXT, timeframe TEXT, ts_ms INTEGER,
          open REAL, high REAL, low REAL, close REAL, volume REAL,
          PRIMARY KEY(exchange, symbol, timeframe, ts_ms)
        )
        """
    )
    con.commit()
    con.close()
    allow, tip_res, flagged = gate_allows_new_entries(
        exchange="binance",
        symbol="ETHUSDT",
        timeframe="15m",
        local_tip_ms=1_704_066_300_000,
        db_path=db,
        persist_flag=False,
        also_check_collector_flag=True,
    )
    assert allow is False
    assert flagged is not None
    assert flagged["reason"] == "COLLECTOR_ERROR"
    _ = tip_res
    _ = json.dumps(flagged)
