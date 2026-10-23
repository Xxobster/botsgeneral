"""Binance USD-M open interest: Vision daily metrics archives + REST tip sync.

Vision (5m, multi-year):
  https://data.binance.vision/data/futures/um/daily/metrics/{SYM}/{SYM}-metrics-{YYYY-MM-DD}.zip

REST tip (last ~30d only):
  GET /futures/data/openInterestHist
"""

from __future__ import annotations

import io
import logging
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable

import pandas as pd
import requests

log = logging.getLogger(__name__)

VISION_METRICS_URL = (
    "https://data.binance.vision/data/futures/um/daily/metrics/"
    "{symbol}/{symbol}-metrics-{day}.zip"
)
OPEN_INTEREST_HIST_URL = "https://fapi.binance.com/futures/data/openInterestHist"
EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"

# Verified earliest Vision metrics days (UTC) as of 2026-08-03
VISION_EARLIEST: dict[str, date] = {
    "BTCUSDT": date(2020, 9, 1),
    "ETHUSDT": date(2021, 12, 1),
    "SOLUSDT": date(2021, 12, 1),
}
VISION_DEFAULT_START = date(2020, 9, 1)

PERIOD_TO_TF = {
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "12h": "12h",
    "1d": "1d",
}


class BinanceOIBlockedError(RuntimeError):
    """Raised when Binance Vision/API is unreachable (often needs VPN)."""


def discover_usdt_perpetuals(session: requests.Session | None = None) -> list[str]:
    sess = session or requests.Session()
    try:
        r = sess.get(EXCHANGE_INFO_URL, timeout=60)
    except requests.RequestException as e:
        raise BinanceOIBlockedError(
            f"Binance exchangeInfo unreachable ({e}). Activate VPN, then re-run."
        ) from e
    if r.status_code in (418, 403, 451):
        raise BinanceOIBlockedError(
            f"Binance exchangeInfo blocked HTTP {r.status_code}. Activate VPN."
        )
    r.raise_for_status()
    info = r.json()
    out: list[str] = []
    for s in info.get("symbols") or []:
        if (
            s.get("contractType") == "PERPETUAL"
            and s.get("quoteAsset") == "USDT"
            and s.get("status") == "TRADING"
        ):
            out.append(str(s["symbol"]).upper())
    return sorted(set(out))


def _parse_metrics_csv(raw: bytes) -> pd.DataFrame:
    sample = raw[:240].decode("utf-8", errors="ignore").lower()
    has_header = "create_time" in sample or "sum_open_interest" in sample
    df = pd.read_csv(io.BytesIO(raw), header=0 if has_header else None)
    if not has_header:
        df.columns = [
            "create_time",
            "symbol",
            "sum_open_interest",
            "sum_open_interest_value",
            "count_toptrader_long_short_ratio",
            "sum_toptrader_long_short_ratio",
            "count_long_short_ratio",
            "sum_taker_long_short_vol_ratio",
        ][: len(df.columns)]
    # normalize column names
    cols = {c.lower().strip(): c for c in df.columns}
    rename = {}
    for want in (
        "create_time",
        "symbol",
        "sum_open_interest",
        "sum_open_interest_value",
        "count_toptrader_long_short_ratio",
        "sum_toptrader_long_short_ratio",
        "count_long_short_ratio",
        "sum_taker_long_short_vol_ratio",
    ):
        if want in cols:
            rename[cols[want]] = want
    df = df.rename(columns=rename)
    if "create_time" not in df.columns or "sum_open_interest" not in df.columns:
        return pd.DataFrame()

    ts = pd.to_datetime(df["create_time"], utc=True, errors="coerce")
    # Unit-agnostic epoch ms (pandas may use ns/us/ms datetime64).
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    ts_ms = ((ts - epoch) / pd.Timedelta(milliseconds=1)).astype("int64")
    out = pd.DataFrame(
        {
            "ts_ms": ts_ms,
            "oi": pd.to_numeric(df["sum_open_interest"], errors="coerce"),
            "oi_usd": pd.to_numeric(
                df.get("sum_open_interest_value"), errors="coerce"
            ),
            "count_toptrader_ls_ratio": pd.to_numeric(
                df.get("count_toptrader_long_short_ratio"), errors="coerce"
            ),
            "sum_toptrader_ls_ratio": pd.to_numeric(
                df.get("sum_toptrader_long_short_ratio"), errors="coerce"
            ),
            "count_ls_ratio": pd.to_numeric(
                df.get("count_long_short_ratio"), errors="coerce"
            ),
            "sum_taker_ls_vol_ratio": pd.to_numeric(
                df.get("sum_taker_long_short_vol_ratio"), errors="coerce"
            ),
        }
    )
    out = out.dropna(subset=["ts_ms", "oi"])
    out["ts_ms"] = out["ts_ms"].astype("int64")
    return out.drop_duplicates(subset=["ts_ms"], keep="last").sort_values("ts_ms")


def _download_vision_day(
    symbol: str,
    day: date,
    session: requests.Session,
    *,
    retries: int = 4,
) -> pd.DataFrame | None:
    url = VISION_METRICS_URL.format(symbol=symbol.upper(), day=day.isoformat())
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=90)
        except requests.RequestException as e:
            last_err = e
            time.sleep(0.5 * (2**attempt))
            continue
        if r.status_code == 404:
            return None
        if r.status_code in (418, 403, 451):
            raise BinanceOIBlockedError(
                f"Binance Vision blocked HTTP {r.status_code}. Activate VPN."
            )
        if r.status_code >= 500:
            last_err = RuntimeError(f"HTTP {r.status_code}")
            time.sleep(0.5 * (2**attempt))
            continue
        try:
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                names = [n for n in zf.namelist() if n.endswith(".csv")]
                if not names:
                    return None
                return _parse_metrics_csv(zf.read(names[0]))
        except (zipfile.BadZipFile, requests.RequestException, ValueError) as e:
            last_err = e
            time.sleep(0.5 * (2**attempt))
            continue
    if last_err is not None:
        raise BinanceOIBlockedError(
            f"Binance Vision unreachable for {symbol} {day} ({last_err}). "
            "Activate VPN / retry later."
        ) from last_err
    return None


def _day_range(start: date, end: date) -> list[date]:
    out: list[date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def fetch_binance_oi_vision(
    symbol: str,
    *,
    start: date | None = None,
    end: date | None = None,
    workers: int = 6,
    session: requests.Session | None = None,
    on_day: Callable[[date, pd.DataFrame], None] | None = None,
) -> pd.DataFrame:
    """Download Vision metrics (native 5m snapshots) for one symbol.

    If ``on_day`` is provided, each successful day is streamed to the callback
    (for incremental DB upserts) and the returned DataFrame may be empty.
    """
    symbol = symbol.upper()
    start = start or VISION_EARLIEST.get(symbol, VISION_DEFAULT_START)
    end = end or (datetime.now(timezone.utc).date() - timedelta(days=1))
    if end < start:
        return pd.DataFrame()

    sess = session or requests.Session()
    # One Session per worker thread to avoid concurrent use races.
    thread_local_sessions: dict[int, requests.Session] = {}

    def _sess() -> requests.Session:
        import threading

        tid = threading.get_ident()
        if tid not in thread_local_sessions:
            thread_local_sessions[tid] = requests.Session()
        return thread_local_sessions[tid]

    days = _day_range(start, end)
    frames: list[pd.DataFrame] = []
    misses = 0
    hits = 0

    def _one(d: date) -> tuple[date, pd.DataFrame | None]:
        return d, _download_vision_day(symbol, d, _sess())

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = [pool.submit(_one, d) for d in days]
        for fut in as_completed(futs):
            day, df = fut.result()
            if df is None or df.empty:
                misses += 1
                continue
            hits += 1
            if on_day is not None:
                on_day(day, df)
            else:
                frames.append(df)

    if on_day is not None:
        log.info(
            "Vision metrics %s 5m streamed hits=%s misses=%s days=%s",
            symbol,
            hits,
            misses,
            len(days),
        )
        return pd.DataFrame()

    if not frames:
        log.info(
            "Vision metrics empty for %s (%s -> %s, misses=%s)",
            symbol,
            start,
            end,
            misses,
        )
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["ts_ms"], keep="last").sort_values("ts_ms")
    log.info(
        "Vision metrics %s 5m -> %s bars (%s misses of %s days)",
        symbol,
        len(out),
        misses,
        len(days),
    )
    return out.reset_index(drop=True)


def fetch_binance_oi_hist(
    symbol: str,
    period: str = "5m",
    *,
    start_ms: int | None = None,
    end_ms: int | None = None,
    limit: int = 500,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Paginate /futures/data/openInterestHist (exchange keeps ~1 month)."""
    if period not in PERIOD_TO_TF:
        raise ValueError(f"Unsupported Binance OI period: {period}")
    symbol = symbol.upper()
    sess = session or requests.Session()
    step = {
        "5m": 5 * 60_000,
        "15m": 15 * 60_000,
        "30m": 30 * 60_000,
        "1h": 60 * 60_000,
        "2h": 2 * 60 * 60_000,
        "4h": 4 * 60 * 60_000,
        "6h": 6 * 60 * 60_000,
        "12h": 12 * 60 * 60_000,
        "1d": 24 * 60 * 60_000,
    }[period]

    cursor = start_ms
    rows: list[dict] = []
    while True:
        params: dict[str, object] = {
            "symbol": symbol,
            "period": period,
            "limit": min(limit, 500),
        }
        if cursor is not None:
            params["startTime"] = int(cursor)
        if end_ms is not None:
            params["endTime"] = int(end_ms)
        try:
            r = sess.get(OPEN_INTEREST_HIST_URL, params=params, timeout=30)
        except requests.RequestException as e:
            raise BinanceOIBlockedError(
                f"Binance openInterestHist unreachable ({e}). Activate VPN."
            ) from e
        if r.status_code in (418, 403, 451):
            raise BinanceOIBlockedError(
                f"Binance openInterestHist blocked HTTP {r.status_code}."
            )
        if r.status_code == 400:
            break
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        last_ts = int(batch[-1]["timestamp"])
        nxt = last_ts + step
        if cursor is not None and nxt <= cursor:
            break
        if len(batch) < min(limit, 500):
            break
        if end_ms is not None and nxt > end_ms:
            break
        cursor = nxt

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    out = pd.DataFrame(
        {
            "ts_ms": pd.to_numeric(df["timestamp"], errors="coerce").astype("int64"),
            "oi": pd.to_numeric(df["sumOpenInterest"], errors="coerce"),
            "oi_usd": pd.to_numeric(df["sumOpenInterestValue"], errors="coerce"),
        }
    )
    out = out.dropna(subset=["ts_ms", "oi"]).drop_duplicates("ts_ms", keep="last")
    return out.sort_values("ts_ms").reset_index(drop=True)


def prioritize_symbols(symbols: Iterable[str], preferred: Iterable[str]) -> list[str]:
    pref = [s.upper() for s in preferred]
    seen = set()
    out: list[str] = []
    for s in list(pref) + sorted({x.upper() for x in symbols}):
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out
