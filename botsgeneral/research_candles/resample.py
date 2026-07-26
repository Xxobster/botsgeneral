"""Vectorized OHLCV resampling (no Python loops over bars)."""

from __future__ import annotations

import pandas as pd

from botsgeneral.research_candles.timestamps import to_ts_ms

OHLCV_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def _ensure_ts_ms(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    if "ts_ms" not in data.columns:
        if "timestamp" not in data.columns:
            raise ValueError("Need ts_ms or timestamp")
        data["ts_ms"] = to_ts_ms(data["timestamp"])
    return data


def resample_ohlcv(
    df: pd.DataFrame,
    rule: str,
    *,
    origin: str = "epoch",
    offset: str | None = None,
) -> pd.DataFrame:
    """Resample OHLCV to a coarser timeframe. rule e.g. '4h', '1D', 'W-MON'."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    data = _ensure_ts_ms(df)
    data["timestamp"] = pd.to_datetime(data["ts_ms"], unit="ms", utc=True)
    agg = {k: v for k, v in OHLCV_AGG.items() if k in data.columns}
    if "volume" not in agg:
        data["volume"] = 0.0
        agg["volume"] = "sum"
    resample_kwargs: dict[str, object] = {"closed": "left", "label": "left"}
    # Anchored frequencies (weekly/monthly/etc.) ignore origin and warn if supplied.
    frequency_unit = rule.lstrip("0123456789").upper()
    if not frequency_unit.startswith(("D", "W", "M", "Q", "Y")):
        resample_kwargs["origin"] = origin
        resample_kwargs["offset"] = offset
    out = (
        data.sort_values("ts_ms")
        .drop_duplicates("ts_ms", keep="last")
        .set_index("timestamp")
        .resample(rule, **resample_kwargs)
        .agg(agg)
        .dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )
    out["ts_ms"] = to_ts_ms(out["timestamp"])
    return out[["ts_ms", "open", "high", "low", "close", "volume", "timestamp"]]


def derive_4h_from_1h(df_1h: pd.DataFrame) -> pd.DataFrame:
    """UTC 4h buckets aligned to epoch (00:00, 04:00, 08:00, 12:00, 16:00, 20:00)."""
    return resample_ohlcv(df_1h, "4h", origin="epoch")


def derive_1h_from_1m(df_1m: pd.DataFrame) -> pd.DataFrame:
    """UTC 1h buckets from 1m (epoch-aligned)."""
    return resample_ohlcv(df_1m, "1h", origin="epoch")


def derive_1d_from_1m(df_1m: pd.DataFrame) -> pd.DataFrame:
    """UTC calendar-day candles from 1m."""
    return resample_ohlcv(df_1m, "1D", origin="epoch")


def derive_1w_from_1d(df_1d: pd.DataFrame) -> pd.DataFrame:
    """Weekly candles labeled Monday (crypto-style UTC weeks)."""
    return resample_ohlcv(df_1d, "W-MON")


def derive_higher_from_1m(df_1m: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Vectorized 1m → 1h / 4h / 1d / 1w."""
    df_1h = derive_1h_from_1m(df_1m)
    df_4h = derive_4h_from_1h(df_1h)
    df_1d = derive_1d_from_1m(df_1m)
    df_1w = derive_1w_from_1d(df_1d)
    return {"1h": df_1h, "4h": df_4h, "1d": df_1d, "1w": df_1w}
