"""Bulk historical klines from data.binance.vision (monthly/daily zip CSVs).

Much faster than REST pagination for 1m / multi-year history.
REST is still used to fill the recent gap after the last archive day.
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import date, datetime, timezone
from typing import Literal

import pandas as pd
import requests

from market_data.fetch_binance import BinanceBlockedError, fetch_klines

log = logging.getLogger(__name__)

VISION_BASE = "https://data.binance.vision/data"
MARKET_PATH = {
    "binance": "futures/um",
    "binance_spot": "spot",
}
# Vision folder name under monthly/daily/
VISION_DATA_TYPE = {
    "last": "klines",
    "mark": "markPriceKlines",
}


def _month_range(start: date, end: date) -> list[tuple[int, int]]:
    y, m = start.year, start.month
    out: list[tuple[int, int]] = []
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _parse_klines_csv(raw: bytes) -> pd.DataFrame:
    # Newer archives may include a header row; older ones are headerless.
    sample = raw[:200].decode("utf-8", errors="ignore")
    has_header = sample.lower().startswith("open_time")
    df = pd.read_csv(
        io.BytesIO(raw),
        header=0 if has_header else None,
        usecols=[0, 1, 2, 3, 4, 5],
        names=["ts_ms", "open", "high", "low", "close", "volume"],
    )
    # open_time can be ms or microseconds in some dumps
    ts = pd.to_numeric(df["ts_ms"], errors="coerce")
    # if values look like microseconds (> 1e14), convert to ms
    if ts.dropna().size and float(ts.dropna().iloc[0]) > 1e14:
        ts = (ts // 1000).astype("int64")
    else:
        ts = ts.astype("int64")
    out = pd.DataFrame(
        {
            "ts_ms": ts.to_numpy(dtype="int64"),
            "open": pd.to_numeric(df["open"], errors="coerce").to_numpy(dtype=float),
            "high": pd.to_numeric(df["high"], errors="coerce").to_numpy(dtype=float),
            "low": pd.to_numeric(df["low"], errors="coerce").to_numpy(dtype=float),
            "close": pd.to_numeric(df["close"], errors="coerce").to_numpy(dtype=float),
            "volume": pd.to_numeric(df["volume"], errors="coerce").fillna(0).to_numpy(dtype=float),
        }
    )
    return out.dropna(subset=["open", "high", "low", "close"]).drop_duplicates("ts_ms")


def _download_zip_csv(url: str, session: requests.Session) -> pd.DataFrame | None:
    try:
        r = session.get(url, timeout=120)
    except requests.RequestException as e:
        raise BinanceBlockedError(
            f"Binance Vision unreachable ({e}). Activate VPN, then re-run."
        ) from e
    if r.status_code == 404:
        return None
    if r.status_code in (418, 403, 451):
        raise BinanceBlockedError(
            f"Binance Vision blocked HTTP {r.status_code}. Activate VPN, then re-run."
        )
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not names:
            return None
        return _parse_klines_csv(zf.read(names[0]))


def fetch_klines_vision(
    symbol: str,
    timeframe: str,
    *,
    market: Literal["binance", "binance_spot"] = "binance",
    price_type: Literal["last", "mark"] = "last",
    start_ms: int | None = None,
    end_ms: int | None = None,
    fill_recent_via_rest: bool = True,
) -> pd.DataFrame:
    """Download Vision monthly archives, then daily for the current month, then REST gap."""
    if price_type == "mark" and market != "binance":
        raise ValueError("markPriceKlines only available for USD-M futures (market=binance)")
    symbol = symbol.upper()
    path = MARKET_PATH[market]
    data_type = VISION_DATA_TYPE[price_type]
    session = requests.Session()
    now = datetime.now(timezone.utc)
    end_dt = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc) if end_ms else now
    if start_ms is None or start_ms <= 0:
        # markPriceKlines Vision generally from ~2020-01; last-price klines from listing
        start_dt = datetime(2020, 1, 1, tzinfo=timezone.utc) if price_type == "mark" else datetime(
            2019, 9, 1, tzinfo=timezone.utc
        )
    else:
        start_dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)

    frames: list[pd.DataFrame] = []
    # Complete months use monthly zips (exclude current month — may be incomplete)
    last_complete_month = date(now.year, now.month, 1) - pd.Timedelta(days=1)
    last_complete_month = date(last_complete_month.year, last_complete_month.month, 1)
    month_end = min(date(end_dt.year, end_dt.month, 1), last_complete_month)
    month_start = date(start_dt.year, start_dt.month, 1)

    for y, m in _month_range(month_start, month_end):
        url = (
            f"{VISION_BASE}/{path}/monthly/{data_type}/{symbol}/{timeframe}/"
            f"{symbol}-{timeframe}-{y}-{m:02d}.zip"
        )
        df = _download_zip_csv(url, session)
        if df is None or df.empty:
            log.info("Vision miss monthly %s/%s %s %04d-%02d", price_type, symbol, timeframe, y, m)
            continue
        frames.append(df)
        log.info(
            "Vision monthly %s/%s %s %04d-%02d -> %s bars",
            price_type,
            symbol,
            timeframe,
            y,
            m,
            len(df),
        )

    # Current / incomplete month: daily zips from month start (or start_dt) through yesterday
    daily_start = max(date(start_dt.year, start_dt.month, start_dt.day), date(now.year, now.month, 1))
    daily_end = min(end_dt.date(), now.date()) - pd.Timedelta(days=1)
    if daily_end >= daily_start:
        for d in pd.date_range(daily_start, daily_end, freq="D"):
            y, m, day = int(d.year), int(d.month), int(d.day)
            url = (
                f"{VISION_BASE}/{path}/daily/{data_type}/{symbol}/{timeframe}/"
                f"{symbol}-{timeframe}-{y}-{m:02d}-{day:02d}.zip"
            )
            df = _download_zip_csv(url, session)
            if df is None or df.empty:
                continue
            frames.append(df)
            log.info(
                "Vision daily %s/%s %s %04d-%02d-%02d -> %s bars",
                price_type,
                symbol,
                timeframe,
                y,
                m,
                day,
                len(df),
            )

    if frames:
        out = (
            pd.concat(frames, ignore_index=True)
            .drop_duplicates("ts_ms", keep="last")
            .sort_values("ts_ms")
            .reset_index(drop=True)
        )
    else:
        out = pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])

    if fill_recent_via_rest:
        rest_start = int(out["ts_ms"].iloc[-1]) + 1 if not out.empty else (start_ms or 0)
        try:
            rest = fetch_klines(
                symbol,
                timeframe,
                market=market,
                price_type=price_type,
                start_ms=rest_start,
                end_ms=end_ms,
                sleep_s=0.02,
            )
        except BinanceBlockedError as e:
            log.warning(
                "REST gap fill skipped (Binance blocked). Vision data only through last archive day. %s",
                e,
            )
            rest = pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
        if not rest.empty:
            out = (
                pd.concat([out, rest], ignore_index=True)
                .drop_duplicates("ts_ms", keep="last")
                .sort_values("ts_ms")
                .reset_index(drop=True)
            )
            log.info(
                "REST gap fill %s/%s %s -> +%s bars (total %s)",
                price_type,
                symbol,
                timeframe,
                len(rest),
                len(out),
            )

    if start_ms is not None and not out.empty:
        out = out[out["ts_ms"] >= int(start_ms)]
    if end_ms is not None and not out.empty:
        out = out[out["ts_ms"] <= int(end_ms)]
    log.info("Vision+REST %s/%s %s %s -> %s bars", market, price_type, symbol, timeframe, len(out))
    return out.reset_index(drop=True)
