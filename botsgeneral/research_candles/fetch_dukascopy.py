"""Dukascopy historical OHLCV via dukascopy-python (chunked by year)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from botsgeneral.research_candles.timestamps import to_ts_ms

log = logging.getLogger(__name__)

_INTERVAL_MAP = {
    "1h": "INTERVAL_HOUR_1",
    "4h": "INTERVAL_HOUR_4",
    "1d": "INTERVAL_DAY_1",
    "1w": "INTERVAL_WEEK_1",
}


def fetch_dukascopy(
    instrument: str,
    timeframe: str,
    start: datetime,
    end: datetime | None = None,
    *,
    offer_side: str = "bid",
    chunk_days: int | None = None,
) -> pd.DataFrame:
    """Fetch Dukascopy candles in date chunks; returns UTC OHLCV DataFrame."""
    import dukascopy_python

    interval_name = _INTERVAL_MAP.get(timeframe)
    if not interval_name:
        raise ValueError(f"Unsupported Dukascopy timeframe: {timeframe}")
    interval = getattr(dukascopy_python, interval_name)
    side = (
        dukascopy_python.OFFER_SIDE_BID
        if offer_side.lower() == "bid"
        else dukascopy_python.OFFER_SIDE_ASK
    )
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = end or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    # API limit ≈ 30_000 bars/request — size chunks to stay under that.
    if chunk_days is None:
        chunk_days = {
            "1h": 900,   # ~21_600 bars
            "4h": 3000,
            "1d": 8000,
            "1w": 20000,
        }.get(timeframe, 180)

    frames: list[pd.DataFrame] = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk_days), end)
        try:
            df = dukascopy_python.fetch(
                instrument,
                interval,
                side,
                cursor.replace(tzinfo=None),
                chunk_end.replace(tzinfo=None),
                max_retries=5,
            )
        except Exception as e:
            log.warning(
                "Dukascopy %s %s %s→%s failed: %s",
                instrument,
                timeframe,
                cursor.date(),
                chunk_end.date(),
                e,
            )
            cursor = chunk_end
            continue
        if df is not None and not df.empty:
            part = df.reset_index()
            # index name may be timestamp
            ts_col = "timestamp" if "timestamp" in part.columns else part.columns[0]
            part = part.rename(columns={ts_col: "timestamp"})
            part["timestamp"] = pd.to_datetime(part["timestamp"], utc=True)
            frames.append(part[["timestamp", "open", "high", "low", "close", "volume"]])
            log.info(
                "Dukascopy %s %s %s→%s: %s bars",
                instrument,
                timeframe,
                cursor.date(),
                chunk_end.date(),
                len(part),
            )
        cursor = chunk_end

    if not frames:
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    out["ts_ms"] = to_ts_ms(out["timestamp"])
    return out[["ts_ms", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
