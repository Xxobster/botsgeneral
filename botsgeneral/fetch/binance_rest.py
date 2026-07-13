from __future__ import annotations

import logging
import time
from typing import Callable

import requests

from botsgeneral.models import BINANCE_INTERVAL, CandlePair, CandleRow

log = logging.getLogger(__name__)
BINANCE_FUTURES = "https://fapi.binance.com"


def fetch_klines(pair: CandlePair, limit: int = 1000) -> list[CandleRow]:
    if pair.exchange != "binance":
        raise ValueError(f"binance_rest called for {pair.exchange}")
    interval = BINANCE_INTERVAL.get(pair.timeframe)
    if not interval:
        raise ValueError(f"Unsupported Binance timeframe: {pair.timeframe}")
    headers = {}
    try:
        from botsgeneral.keys import resolve_binance_keys

        creds = resolve_binance_keys()
        if creds.get("api_key"):
            headers["X-MBX-APIKEY"] = creds["api_key"]
    except Exception:
        pass
    # paginate
    end = None
    all_rows: dict[int, CandleRow] = {}
    remaining = limit
    while remaining > 0:
        batch = min(1500, remaining)
        params = {"symbol": pair.symbol, "interval": interval, "limit": batch}
        if end is not None:
            params["endTime"] = end
        r = requests.get(
            f"{BINANCE_FUTURES}/fapi/v1/klines",
            params=params,
            headers=headers or None,
            timeout=30,
        )
        r.raise_for_status()
        lst = r.json()
        if not lst:
            break
        for item in lst:
            ts = int(item[0])
            all_rows[ts] = CandleRow(
                exchange="binance",
                symbol=pair.symbol,
                timeframe=pair.timeframe,
                ts_ms=ts,
                open=float(item[1]),
                high=float(item[2]),
                low=float(item[3]),
                close=float(item[4]),
                volume=float(item[5]),
                quote_volume=float(item[7]),
                trades=int(item[8]),
                taker_buy_base=float(item[9]),
                taker_buy_quote=float(item[10]),
            )
        oldest = int(lst[0][0])
        if end is not None and oldest >= end:
            break
        end = oldest - 1
        remaining = limit - len(all_rows)
        if len(lst) < batch:
            break
        time.sleep(0.05)
    return [all_rows[k] for k in sorted(all_rows)]


def upsert_pair(db, pair: CandlePair, limit: int = 1000) -> int:
    rows = fetch_klines(pair, limit=limit)
    return db.upsert_candles(rows)


def poll_recent(pair: CandlePair, limit: int = 5) -> list[CandleRow]:
    return fetch_klines(pair, limit=limit)
