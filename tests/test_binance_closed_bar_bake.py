"""Unit tests for closed-bar Binance fetch policy + shared adapter."""
from __future__ import annotations

import pandas as pd

from botsgeneral.fetch.binance_rest import df_to_candle_rows
from botsgeneral.models import CandlePair
from market_data.fetch_binance import drop_incomplete_bars, drop_junk_bars, tip_ohlc_fingerprint


def test_drop_incomplete_keeps_only_closed():
    # 1h bars: open at T closes at T+3600000
    df = pd.DataFrame(
        {
            "ts_ms": [1_700_000_000_000, 1_700_003_600_000, 1_700_007_200_000],
            "open": [1.0, 2.0, 3.0],
            "high": [1.1, 2.1, 3.1],
            "low": [0.9, 1.9, 2.9],
            "close": [1.05, 2.05, 3.05],
            "volume": [10.0, 11.0, 12.0],
        }
    )
    # now = mid of last bar → last dropped
    out = drop_incomplete_bars(df, "1h", now_ms=1_700_007_200_000 + 1_800_000)
    assert list(out["ts_ms"]) == [1_700_000_000_000, 1_700_003_600_000]


def test_drop_junk_flat_zero_volume():
    df = pd.DataFrame(
        {
            "ts_ms": [1, 2],
            "open": [100.0, 100.0],
            "high": [101.0, 100.0],
            "low": [99.0, 100.0],
            "close": [100.5, 100.0],
            "volume": [5.0, 0.0],
        }
    )
    out = drop_junk_bars(df)
    assert list(out["ts_ms"]) == [1]


def test_df_to_candle_rows_preserves_aux():
    pair = CandlePair("binance", "BTCUSDT", "1h")
    df = pd.DataFrame(
        {
            "ts_ms": [1000],
            "open": [1.0],
            "high": [2.0],
            "low": [0.5],
            "close": [1.5],
            "volume": [10.0],
            "quote_volume": [100.0],
            "trades": [7],
            "taker_buy_base": [4.0],
            "taker_buy_quote": [40.0],
        }
    )
    rows = df_to_candle_rows(pair, df)
    assert len(rows) == 1
    assert rows[0].quote_volume == 100.0
    assert rows[0].trades == 7
    fp = tip_ohlc_fingerprint(df)
    assert fp == {
        "ts_ms": 1000,
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
    }
