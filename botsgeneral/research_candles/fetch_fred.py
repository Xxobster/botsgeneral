"""FRED daily series (Treasury yields, etc.) via public CSV export — no API key required."""

from __future__ import annotations

import logging
from io import StringIO

import pandas as pd
import requests

from botsgeneral.research_candles.timestamps import to_ts_ms

log = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "botsgeneral-research-candles/1.0", "Accept": "text/csv"}


def fetch_fred_daily(series_id: str) -> pd.DataFrame:
    """Download a FRED series as daily OHLCV (close=value; OHLC collapsed to close)."""
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    try:
        r = requests.get(url, params={"id": series_id}, headers=_HEADERS, timeout=60)
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("FRED %s failed: %s", series_id, e)
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])

    raw = pd.read_csv(StringIO(r.text))
    if raw.empty or len(raw.columns) < 2:
        log.warning("FRED %s empty response", series_id)
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])

    date_col, val_col = raw.columns[0], raw.columns[1]
    ts = pd.to_datetime(raw[date_col], utc=True, errors="coerce")
    val = pd.to_numeric(raw[val_col], errors="coerce")
    # FRED uses '.' for missing observations
    mask = ts.notna() & val.notna()
    if not mask.any():
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    v = val[mask].astype(float).to_numpy()
    out = pd.DataFrame(
        {
            "ts_ms": to_ts_ms(ts[mask]),
            "open": v,
            "high": v,
            "low": v,
            "close": v,
            "volume": 0.0,
        }
    )
    out = out.drop_duplicates("ts_ms").sort_values("ts_ms").reset_index(drop=True)
    log.info("FRED %s daily -> %s bars", series_id, len(out))
    return out
