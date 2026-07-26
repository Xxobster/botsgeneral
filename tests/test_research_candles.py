from __future__ import annotations

import pandas as pd

from botsgeneral.research_candles.db import ResearchCandleDB
from botsgeneral.research_candles.resample import (
    derive_4h_from_1h,
    derive_1w_from_1d,
    derive_higher_from_1m,
)
from botsgeneral.research_candles.timestamps import to_ts_ms


def test_to_ts_ms_from_seconds():
    idx = pd.to_datetime(["1986-12-31", "2026-07-16"], utc=True)
    ms = to_ts_ms(idx)
    assert ms[0] == int(idx[0].timestamp() * 1000)
    assert ms[-1] > 1_700_000_000_000


def test_resample_4h_vectorized():
    ts = pd.date_range("2024-01-01", periods=8, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": range(8),
            "high": range(8),
            "low": range(8),
            "close": range(8),
            "volume": 1.0,
        }
    )
    out = derive_4h_from_1h(df)
    assert len(out) == 2
    assert float(out.iloc[0]["open"]) == 0.0
    assert float(out.iloc[0]["close"]) == 3.0


def test_derive_higher_from_1m():
    ts = pd.date_range("2024-01-01", periods=60 * 24 * 8, freq="1min", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 1.0,
        }
    )
    out = derive_higher_from_1m(df)
    assert len(out["1h"]) == 24 * 8
    assert len(out["4h"]) == 6 * 8
    assert len(out["1d"]) == 8
    assert len(out["1w"]) >= 1


def test_resample_1w_from_1d():
    ts = pd.date_range("2024-01-01", periods=14, freq="1D", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 10.0,
        }
    )
    out = derive_1w_from_1d(df)
    assert len(out) >= 2


def test_engine005_provenance_round_trip(tmp_path):
    path = tmp_path / "mark.sqlite"
    df = pd.DataFrame(
        {
            "ts_ms": [1_700_000_000_000],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [0.0],
        }
    )
    db = ResearchCandleDB(path)
    db.upsert_df(
        df,
        source="binance_mark",
        symbol="BTCUSDT",
        timeframe="1m",
        price_type="mark_price",
        product="USDⓈ-M",
        source_endpoint="/fapi/v1/markPriceKlines",
    )
    loaded = db.load("BTCUSDT", "1m", source="binance_mark")
    db.close()
    assert loaded.iloc[0]["price_type"] == "mark_price"
    assert loaded.iloc[0]["product"] == "USDⓈ-M"
    assert loaded.iloc[0]["source_endpoint"] == "/fapi/v1/markPriceKlines"
