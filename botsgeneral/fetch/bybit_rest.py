from __future__ import annotations

import logging
import time
from typing import Iterable

import requests

from botsgeneral.models import BYBIT_INTERVAL, CandlePair, CandleRow

log = logging.getLogger(__name__)
BYBIT_BASE = "https://api.bybit.com"


def fetch_klines(pair: CandlePair, limit: int = 1000) -> list[CandleRow]:
    if pair.exchange != "bybit":
        raise ValueError(f"bybit_rest called for {pair.exchange}")
    interval = BYBIT_INTERVAL.get(pair.timeframe)
    if not interval:
        raise ValueError(f"Unsupported Bybit timeframe: {pair.timeframe}")
    # paginate backwards for history
    end = int(time.time() * 1000)
    all_rows: dict[int, CandleRow] = {}
    remaining = limit
    while remaining > 0:
        batch = min(1000, remaining)
        params = {
            "category": "linear",
            "symbol": pair.symbol,
            "interval": interval,
            "limit": batch,
            "end": end,
        }
        data = None
        for attempt in range(6):
            r = requests.get(f"{BYBIT_BASE}/v5/market/kline", params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            if data.get("retCode") == 0:
                break
            if data.get("retCode") == 10006:
                wait = 1.5 * (attempt + 1)
                log.warning("Bybit rate limit on %s; sleep %.1fs", pair, wait)
                time.sleep(wait)
                continue
            raise RuntimeError(f"Bybit kline error: {data}")
        if not data or data.get("retCode") != 0:
            raise RuntimeError(f"Bybit kline error after retries: {data}")
        lst = (data.get("result") or {}).get("list") or []
        if not lst:
            break
        for item in lst:
            # [start, open, high, low, close, volume, turnover]
            ts = int(item[0])
            all_rows[ts] = CandleRow(
                exchange="bybit",
                symbol=pair.symbol,
                timeframe=pair.timeframe,
                ts_ms=ts,
                open=float(item[1]),
                high=float(item[2]),
                low=float(item[3]),
                close=float(item[4]),
                volume=float(item[5]),
                quote_volume=float(item[6]) if len(item) > 6 else None,
            )
        oldest = min(int(x[0]) for x in lst)
        if oldest >= end:
            break
        end = oldest - 1
        remaining = limit - len(all_rows)
        if len(lst) < batch:
            break
        time.sleep(0.12)
    return [all_rows[k] for k in sorted(all_rows)]


def upsert_pair(db, pair: CandlePair, limit: int = 1000) -> int:
    rows = fetch_klines(pair, limit=limit)
    return db.upsert_candles(rows)
