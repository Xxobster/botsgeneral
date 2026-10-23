"""Bybit V5 open interest history (public, no API key).

GET https://api.bybit.com/v5/market/open-interest

As of mid-2026:
  openInterest       = sum of both sides
  singleOpenInterest = conventional one-sided OI (prefer for Binance parity)
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Iterable

import pandas as pd
import requests

log = logging.getLogger(__name__)

BYBIT_OI_URL = "https://api.bybit.com/v5/market/open-interest"
BYBIT_INSTRUMENTS_URL = "https://api.bybit.com/v5/market/instruments-info"

# Earliest dates verified live (UTC day). Others start at listing / first returned bar.
BYBIT_EARLIEST: dict[str, date] = {
    "BTCUSDT": date(2020, 8, 5),
    "ETHUSDT": date(2021, 3, 15),
    "SOLUSDT": date(2021, 10, 15),
}
BYBIT_DEFAULT_START = date(2020, 8, 5)

INTERVAL_MS = {
    "5min": 5 * 60_000,
    "15min": 15 * 60_000,
    "30min": 30 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}

# Map our warehouse timeframe labels -> Bybit intervalTime
TF_TO_BYBIT = {
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}
BYBIT_TO_TF = {v: k for k, v in TF_TO_BYBIT.items()}


class BybitOIError(RuntimeError):
    pass


def discover_usdt_perpetuals(session: requests.Session | None = None) -> list[str]:
    sess = session or requests.Session()
    out: list[str] = []
    cursor = None
    while True:
        params: dict[str, object] = {"category": "linear", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        r = sess.get(BYBIT_INSTRUMENTS_URL, params=params, timeout=60)
        r.raise_for_status()
        body = r.json()
        if body.get("retCode") != 0:
            raise BybitOIError(f"Bybit instruments-info error: {body}")
        result = body.get("result") or {}
        for x in result.get("list") or []:
            if (
                x.get("quoteCoin") == "USDT"
                and x.get("status") == "Trading"
                and x.get("contractType") == "LinearPerpetual"
            ):
                out.append(str(x["symbol"]).upper())
        cursor = result.get("nextPageCursor") or None
        if not cursor:
            break
    return sorted(set(out))


def _to_ms(value: date | datetime | int | float | str) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return int(ts.timestamp() * 1000)


def fetch_bybit_oi(
    symbol: str,
    timeframe: str = "1h",
    *,
    start: date | datetime | int | None = None,
    end: date | datetime | int | None = None,
    category: str = "linear",
    request_delay: float = 0.05,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Paginate Bybit open-interest history for one symbol/timeframe.

    Stores singleOpenInterest as ``oi`` (one-sided) and openInterest as ``oi_sum``.
    """
    symbol = symbol.upper()
    interval = TF_TO_BYBIT.get(timeframe, timeframe)
    if interval not in INTERVAL_MS:
        raise ValueError(f"Unsupported Bybit OI timeframe: {timeframe}")

    start_ms = _to_ms(start) if start is not None else _to_ms(
        BYBIT_EARLIEST.get(symbol, BYBIT_DEFAULT_START)
    )
    end_ms = _to_ms(end) if end is not None else int(
        datetime.now(timezone.utc).timestamp() * 1000
    )
    if end_ms < start_ms:
        return pd.DataFrame()

    sess = session or requests.Session()
    rows: list[dict] = []
    cursor: str | None = None
    # Newest-first pages; keep following nextPageCursor until exhausted.
    safety = 0
    while safety < 100_000:
        safety += 1
        params: dict[str, object] = {
            "category": category,
            "symbol": symbol,
            "intervalTime": interval,
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor
        r = sess.get(BYBIT_OI_URL, params=params, timeout=30)
        r.raise_for_status()
        body = r.json()
        if body.get("retCode") != 0:
            msg = str(body.get("retMsg") or body)
            if "not found" in msg.lower() or body.get("retCode") in (10001, 10002):
                break
            raise BybitOIError(f"Bybit OI error for {symbol}: {body}")
        result = body.get("result") or {}
        batch = result.get("list") or []
        if not batch:
            break
        rows.extend(batch)
        next_cursor = result.get("nextPageCursor") or None
        if not next_cursor:
            break
        cursor = str(next_cursor)
        time.sleep(request_delay)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Prefer one-sided OI for Binance-comparable positioning; keep sum separately.
    oi_single = pd.to_numeric(df.get("singleOpenInterest"), errors="coerce")
    oi_sum = pd.to_numeric(df.get("openInterest"), errors="coerce")
    oi = oi_single.where(oi_single.notna(), oi_sum / 2.0)
    out = pd.DataFrame(
        {
            "ts_ms": pd.to_numeric(df["timestamp"], errors="coerce").astype("int64"),
            "oi": oi,
            "oi_sum": oi_sum,
        }
    )
    out = out.dropna(subset=["ts_ms"]).drop_duplicates("ts_ms", keep="last")
    out = out[(out["ts_ms"] >= start_ms) & (out["ts_ms"] <= end_ms)]
    out = out.sort_values("ts_ms").reset_index(drop=True)
    log.info("Bybit OI %s %s -> %s bars", symbol, BYBIT_TO_TF.get(interval, interval), len(out))
    return out


def prioritize_symbols(symbols: Iterable[str], preferred: Iterable[str]) -> list[str]:
    pref = [s.upper() for s in preferred]
    seen = set()
    out: list[str] = []
    for s in list(pref) + sorted({x.upper() for x in symbols}):
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out
