"""Binance futures (+ optional spot) kline downloader with full history pagination."""

from __future__ import annotations

import logging
import time
from typing import Literal

import pandas as pd
import requests

from market_data.keys_util import resolve_binance_keys

log = logging.getLogger(__name__)

BINANCE_INTERVAL = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "12h": "12h",
    "1d": "1d",
    "1w": "1w",
}

TF_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}

ENDPOINTS = {
    "binance": {
        "last": "https://fapi.binance.com/fapi/v1/klines",
        "mark": "https://fapi.binance.com/fapi/v1/markPriceKlines",
    },
    "binance_spot": {
        "last": "https://api.binance.com/api/v3/klines",
        # spot has no mark price klines
    },
}

OHLCV_COLS = ["ts_ms", "open", "high", "low", "close", "volume"]
AUX_COLS = ["quote_volume", "trades", "taker_buy_base", "taker_buy_quote"]


class BinanceBlockedError(RuntimeError):
    """Raised when Binance endpoints are unreachable (often needs VPN)."""


def _headers() -> dict[str, str]:
    try:
        creds = resolve_binance_keys()
        if creds.get("api_key"):
            return {"X-MBX-APIKEY": creds["api_key"]}
    except Exception:
        pass
    return {}


def drop_incomplete_bars(
    df: pd.DataFrame,
    timeframe: str,
    *,
    now_ms: int | None = None,
) -> pd.DataFrame:
    """Keep only bars whose close time is strictly in the past (closed bars)."""
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame(columns=OHLCV_COLS)
    step = TF_MS.get(timeframe)
    if not step or "ts_ms" not in df.columns:
        return df
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    out = df.loc[df["ts_ms"].astype("int64") + int(step) <= now].copy()
    return out.reset_index(drop=True)


def drop_junk_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Drop flat zero-volume junk rows that are not valid exchange candles."""
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame(columns=OHLCV_COLS)
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    v = df["volume"].astype(float).fillna(0.0)
    flat = (o == h) & (h == l) & (l == c) & (v <= 0.0)
    bad_ohlc = (h < l) | (h < o) | (h < c) | (l > o) | (l > c)
    keep = ~(flat | bad_ohlc)
    return df.loc[keep].reset_index(drop=True)


def fetch_klines(
    symbol: str,
    timeframe: str,
    *,
    market: Literal["binance", "binance_spot"] = "binance",
    price_type: Literal["last", "mark"] = "last",
    start_ms: int | None = None,
    end_ms: int | None = None,
    sleep_s: float = 0.05,
    include_aux: bool = False,
    drop_incomplete: bool = True,
    drop_junk: bool = True,
) -> pd.DataFrame:
    """Paginate Binance klines until history is exhausted. Returns UTC OHLCV DataFrame.

    Closed-bar policy (default): drops the still-forming tip bar and flat/volume-0 junk
    so research warehouse and live shared DB share the same tip OHLC identity.
    """
    interval = BINANCE_INTERVAL.get(timeframe)
    if not interval:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    endpoints = ENDPOINTS.get(market) or {}
    url = endpoints.get(price_type)
    if not url:
        raise ValueError(f"No {price_type} klines endpoint for market={market}")
    headers = _headers()
    # Walk forward from start (0 = listing). Omitting startTime returns only the
    # latest `limit` bars — never do that for a full backfill.
    cursor = 0 if start_ms is None else int(start_ms)
    hard_end = end_ms
    want_aux = bool(include_aux and price_type == "last")
    all_rows: dict[int, tuple] = {}
    session = requests.Session()
    while True:
        params: dict = {"symbol": symbol.upper(), "interval": interval, "limit": 1500}
        params["startTime"] = cursor
        if hard_end is not None:
            params["endTime"] = hard_end
        try:
            r = session.get(url, params=params, headers=headers or None, timeout=45)
        except requests.RequestException as e:
            raise BinanceBlockedError(
                f"Binance unreachable ({e}). Activate VPN, then re-run."
            ) from e
        if r.status_code in (418, 403, 451) or "restricted" in r.text.lower():
            raise BinanceBlockedError(
                f"Binance blocked HTTP {r.status_code}. Activate VPN, then re-run."
            )
        if r.status_code == 400 and "Invalid symbol" in r.text:
            log.warning("Binance %s %s: invalid symbol %s", market, price_type, symbol)
            break
        r.raise_for_status()
        lst = r.json()
        if not lst:
            break
        before = len(all_rows)
        for item in lst:
            ts = int(item[0])
            if want_aux and len(item) >= 11:
                all_rows[ts] = (
                    ts,
                    float(item[1]),
                    float(item[2]),
                    float(item[3]),
                    float(item[4]),
                    float(item[5]),
                    float(item[7]),
                    int(item[8]),
                    float(item[9]),
                    float(item[10]),
                )
            else:
                all_rows[ts] = (
                    ts,
                    float(item[1]),
                    float(item[2]),
                    float(item[3]),
                    float(item[4]),
                    float(item[5]),
                )
        if len(all_rows) == before:
            break
        last_open = int(lst[-1][0])
        next_cursor = last_open + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if hard_end is not None and cursor > hard_end:
            break
        if len(lst) < 1500:
            break
        time.sleep(sleep_s)
    cols = OHLCV_COLS + (AUX_COLS if want_aux else [])
    if not all_rows:
        return pd.DataFrame(columns=cols)
    # Rows may be mixed length if some pages lacked aux — normalize via DataFrame ctor
    df = pd.DataFrame([all_rows[k] for k in sorted(all_rows)])
    if want_aux and df.shape[1] == 10:
        df.columns = cols
    else:
        df = df.iloc[:, :6]
        df.columns = OHLCV_COLS
    if drop_incomplete:
        df = drop_incomplete_bars(df, timeframe)
    if drop_junk:
        df = drop_junk_bars(df)
    log.info("Binance %s/%s %s %s -> %s bars", market, price_type, symbol, timeframe, len(df))
    return df.reset_index(drop=True)


def tip_ohlc_fingerprint(df: pd.DataFrame) -> dict | None:
    """Closed-bar tip identity for shared↔warehouse compare (OHLC only)."""
    if df is None or df.empty or "ts_ms" not in df.columns:
        return None
    row = df.sort_values("ts_ms").iloc[-1]
    return {
        "ts_ms": int(row["ts_ms"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
    }
