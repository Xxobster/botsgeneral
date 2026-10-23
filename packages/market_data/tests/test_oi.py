"""Quick unit checks for OI fetch + upsert (no full history)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from market_data.fetch_binance_oi import fetch_binance_oi_hist, fetch_binance_oi_vision
from market_data.fetch_bybit_oi import fetch_bybit_oi
from market_data.oi_db import ResearchOIDB


def test_binance_vision_one_day():
    df = fetch_binance_oi_vision(
        "BTCUSDT", start=date(2024, 1, 1), end=date(2024, 1, 1), workers=2
    )
    assert not df.empty
    assert "oi" in df.columns and "oi_usd" in df.columns
    assert df["ts_ms"].is_unique
    assert len(df) == 288  # 5m * 24h
    # Must be epoch milliseconds (2024-01-01), not seconds
    assert int(df["ts_ms"].iloc[0]) == 1704067200000


def test_binance_hist_tip():
    df = fetch_binance_oi_hist("ETHUSDT", "5m")
    assert not df.empty
    assert df["ts_ms"].is_unique


def test_bybit_paginate_1d():
    df = fetch_bybit_oi(
        "BTCUSDT",
        "1d",
        start=date(2020, 8, 5),
        end=datetime(2021, 1, 1, tzinfo=timezone.utc),
    )
    assert not df.empty
    assert "oi" in df.columns
    assert df["ts_ms"].is_unique
    assert int(df["ts_ms"].min()) >= 1596585600000


def test_oi_db_upsert_dedupe(tmp_path: Path):
    db = ResearchOIDB(tmp_path / "t.sqlite")
    df = pd.DataFrame(
        {
            "ts_ms": [1, 1, 2],
            "oi": [10.0, 11.0, 12.0],
            "oi_usd": [100.0, 110.0, 120.0],
        }
    )
    n = db.upsert_df(df, exchange="binance", symbol="BTCUSDT", timeframe="5m")
    assert n == 2  # deduped before insert
    cov = db.coverage()
    assert int(cov.iloc[0]["bars"]) == 2
    db.close()
