"""Yahoo Finance OHLCV (daily full history; 1h ~730d)."""

from __future__ import annotations

import logging

import pandas as pd

from botsgeneral.research_candles.timestamps import to_ts_ms

log = logging.getLogger(__name__)


def fetch_yahoo(yahoo_symbol: str, timeframe: str = "1d") -> pd.DataFrame:
    import yfinance as yf

    t = yf.Ticker(yahoo_symbol)
    if timeframe in ("1h", "60m"):
        raw = t.history(period="730d", interval="1h", auto_adjust=False)
    elif timeframe in ("1d", "1D", "d"):
        raw = t.history(period="max", interval="1d", auto_adjust=False)
    elif timeframe in ("1w", "1W", "wk"):
        raw = t.history(period="max", interval="1wk", auto_adjust=False)
    else:
        raise ValueError(f"Unsupported Yahoo timeframe: {timeframe}")
    if raw is None or raw.empty:
        log.warning("Yahoo empty: %s %s", yahoo_symbol, timeframe)
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    idx = pd.to_datetime(raw.index, utc=True)
    out = pd.DataFrame(
        {
            "ts_ms": to_ts_ms(idx),
            "open": raw["Open"].astype(float).to_numpy(),
            "high": raw["High"].astype(float).to_numpy(),
            "low": raw["Low"].astype(float).to_numpy(),
            "close": raw["Close"].astype(float).to_numpy(),
            "volume": raw["Volume"].astype(float).fillna(0).to_numpy(),
        }
    )
    out = out.dropna(subset=["open", "high", "low", "close"]).drop_duplicates("ts_ms")
    log.info("Yahoo %s %s -> %s bars", yahoo_symbol, timeframe, len(out))
    return out.reset_index(drop=True)
