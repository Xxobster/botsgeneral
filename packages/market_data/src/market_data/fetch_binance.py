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


def fetch_klines(
    symbol: str,
    timeframe: str,
    *,
    market: Literal["binance", "binance_spot"] = "binance",
    price_type: Literal["last", "mark"] = "last",
    start_ms: int | None = None,
    end_ms: int | None = None,
    sleep_s: float = 0.05,
) -> pd.DataFrame:
    """Paginate Binance klines until history is exhausted. Returns UTC OHLCV DataFrame."""
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
    if not all_rows:
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(
        [all_rows[k] for k in sorted(all_rows)],
        columns=["ts_ms", "open", "high", "low", "close", "volume"],
    )
    log.info("Binance %s/%s %s %s -> %s bars", market, price_type, symbol, timeframe, len(df))
    return df
