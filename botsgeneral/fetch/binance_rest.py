"""Binance USD-M Last candles for the live shared collector.

Baked onto ``market_data.fetch_binance.fetch_klines`` so shared_candles.db closed
bars are OHLC-identical to research warehouse ``source=binance`` / ``price_type=last``.
"""

from __future__ import annotations

import logging
import time

import pandas as pd

from botsgeneral.models import TF_MS, CandlePair, CandleRow
from market_data.fetch_binance import (
    BinanceBlockedError,
    drop_incomplete_bars,
    drop_junk_bars,
    fetch_klines as md_fetch_klines,
)

log = logging.getLogger(__name__)

# Re-export for callers that catch geo blocks
__all__ = [
    "BinanceBlockedError",
    "fetch_klines",
    "upsert_pair",
    "poll_recent",
    "df_to_candle_rows",
]


def df_to_candle_rows(pair: CandlePair, df: pd.DataFrame) -> list[CandleRow]:
    """Map research OHLCV(+aux) DataFrame into CandleDB rows (vectorized)."""
    if df is None or df.empty:
        return []
    data = df
    n = len(data)
    ts = data["ts_ms"].astype("int64").to_numpy()
    o = data["open"].astype(float).to_numpy()
    h = data["high"].astype(float).to_numpy()
    l = data["low"].astype(float).to_numpy()
    c = data["close"].astype(float).to_numpy()
    v = data["volume"].astype(float).to_numpy()
    qv = (
        data["quote_volume"].astype(float).to_numpy()
        if "quote_volume" in data.columns
        else [None] * n
    )
    tr = (
        data["trades"].astype("int64").to_numpy()
        if "trades" in data.columns
        else [None] * n
    )
    tb = (
        data["taker_buy_base"].astype(float).to_numpy()
        if "taker_buy_base" in data.columns
        else [None] * n
    )
    tq = (
        data["taker_buy_quote"].astype(float).to_numpy()
        if "taker_buy_quote" in data.columns
        else [None] * n
    )
    rows: list[CandleRow] = []
    for i in range(n):
        rows.append(
            CandleRow(
                exchange="binance",
                symbol=pair.symbol,
                timeframe=pair.timeframe,
                ts_ms=int(ts[i]),
                open=float(o[i]),
                high=float(h[i]),
                low=float(l[i]),
                close=float(c[i]),
                volume=float(v[i]),
                quote_volume=None if qv[i] is None else float(qv[i]),
                trades=None if tr[i] is None else int(tr[i]),
                taker_buy_base=None if tb[i] is None else float(tb[i]),
                taker_buy_quote=None if tq[i] is None else float(tq[i]),
            )
        )
    return rows


def fetch_klines(pair: CandlePair, limit: int = 0) -> list[CandleRow]:
    """Fetch Binance futures Last klines via the research fetcher.

    limit<=0 → full history from listing.
    limit>0  → tip window of ~limit bars (plus one for incomplete drop).
    Always returns closed bars only (forming tip dropped).
    """
    if pair.exchange != "binance":
        raise ValueError(f"binance_rest called for {pair.exchange}")
    tf_ms = TF_MS.get(pair.timeframe)
    if not tf_ms and pair.timeframe == "1w":
        tf_ms = 604_800_000
        # keep local map consistent for age math elsewhere
    if not tf_ms:
        raise ValueError(f"Unsupported Binance timeframe: {pair.timeframe}")

    start_ms: int | None = None
    if limit > 0:
        # Fetch a little extra so drop_incomplete still leaves `limit` closed bars.
        start_ms = int(time.time() * 1000) - int(limit + 2) * int(tf_ms)

    try:
        df = md_fetch_klines(
            pair.symbol,
            pair.timeframe,
            market="binance",
            price_type="last",
            start_ms=start_ms,
            include_aux=True,
            drop_incomplete=True,
            drop_junk=True,
        )
    except BinanceBlockedError:
        raise
    if limit > 0 and len(df) > limit:
        df = df.tail(int(limit)).reset_index(drop=True)
    # Defense in depth — same closed/junk policy even if md defaults change
    df = drop_junk_bars(drop_incomplete_bars(df, pair.timeframe))
    rows = df_to_candle_rows(pair, df)
    log.info("Binance fetched %s bars for %s (market_data Last)", len(rows), pair)
    return rows


def upsert_pair(db, pair: CandlePair, limit: int = 0) -> int:
    rows = fetch_klines(pair, limit=limit)
    return db.upsert_candles(rows)


def poll_recent(pair: CandlePair, limit: int = 5) -> list[CandleRow]:
    """Poll recent *closed* bars (forming tip never written)."""
    return fetch_klines(pair, limit=max(limit, 1))
