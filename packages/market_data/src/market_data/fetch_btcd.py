"""BTC dominance (BTC.D) helpers.

TradingView CRYPTOCAP:BTC.D is the preferred exact series — export CSV into
D:\\projectsdata\\candles\\imports\\btcd\\ then run ingest_tradingview_csv().

Also builds an approximate daily series from CoinGecko (BTC mcap / total mcap).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd
import requests

from market_data.timestamps import to_ts_ms

log = logging.getLogger(__name__)

from market_data.paths import candles_root

IMPORT_DIR = candles_root() / "imports" / "btcd"


def fetch_coingecko_btcd_daily() -> pd.DataFrame:
    """Approximate daily BTC.D from CoinGecko market charts (free, may rate-limit)."""
    session = requests.Session()
    headers = {"Accept": "application/json", "User-Agent": "botsgeneral-research-candles/1.0"}
    try:
        btc = session.get(
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
            params={"vs_currency": "usd", "days": "365", "interval": "daily"},
            headers=headers,
            timeout=60,
        )
        # global market cap chart (may require higher plan; try anyway)
        glob = session.get(
            "https://api.coingecko.com/api/v3/global/market_cap_chart",
            params={"days": "max"},
            headers=headers,
            timeout=60,
        )
    except requests.RequestException as e:
        log.warning("CoinGecko request failed: %s", e)
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])

    if btc.status_code != 200:
        log.warning("CoinGecko BTC chart HTTP %s: %s", btc.status_code, btc.text[:200])
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])

    btc_caps = btc.json().get("market_caps") or []
    if not btc_caps:
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])

    btc_df = pd.DataFrame(btc_caps, columns=["ts_ms", "btc_mcap"])
    btc_df["ts_ms"] = btc_df["ts_ms"].astype("int64")

    if glob.status_code == 200:
        gjson = glob.json()
        # shape varies: market_cap_chart.market_cap or market_caps
        total = (
            (gjson.get("market_cap_chart") or {}).get("market_cap")
            or gjson.get("market_caps")
            or []
        )
        if total:
            tot_df = pd.DataFrame(total, columns=["ts_ms", "total_mcap"])
            tot_df["ts_ms"] = tot_df["ts_ms"].astype("int64")
            # align to nearest day via merge_asof
            btc_df = btc_df.sort_values("ts_ms")
            tot_df = tot_df.sort_values("ts_ms")
            merged = pd.merge_asof(btc_df, tot_df, on="ts_ms", direction="nearest", tolerance=86_400_000)
            dom = (merged["btc_mcap"] / merged["total_mcap"] * 100.0).astype(float)
            out = pd.DataFrame(
                {
                    "ts_ms": merged["ts_ms"],
                    "open": dom,
                    "high": dom,
                    "low": dom,
                    "close": dom,
                    "volume": 0.0,
                }
            ).dropna()
            log.info("CoinGecko BTC.D daily -> %s bars", len(out))
            return out.reset_index(drop=True)

    # Fallback: current dominance only (single point) — skip
    log.warning(
        "CoinGecko global market_cap_chart unavailable (HTTP %s). "
        "Drop TradingView CRYPTOCAP:BTC.D CSV into %s",
        glob.status_code,
        IMPORT_DIR,
    )
    return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])


def ingest_tradingview_csv(path: str | Path) -> pd.DataFrame:
    """Parse TradingView chart CSV export into OHLCV (close-based if only one price col)."""
    p = Path(path)
    raw = pd.read_csv(p)
    cols = {c.lower().strip(): c for c in raw.columns}
    time_col = cols.get("time") or cols.get("datetime") or cols.get("date") or list(raw.columns)[0]
    ts = pd.to_datetime(raw[time_col], utc=True, errors="coerce")
    def pick(*names: str) -> pd.Series | None:
        for n in names:
            if n in cols:
                return raw[cols[n]].astype(float)
        return None

    o = pick("open")
    h = pick("high")
    l = pick("low")
    c = pick("close") or pick("btc.d") or pick("value")
    if c is None:
        # last numeric column
        num = raw.select_dtypes("number")
        if num.empty:
            raise ValueError(f"No price column in {p}")
        c = num.iloc[:, -1].astype(float)
    if o is None:
        o = h = l = c
    if h is None:
        h = c
    if l is None:
        l = c
    v = pick("volume")
    out = pd.DataFrame(
        {
            "ts_ms": to_ts_ms(ts),
            "open": o.to_numpy(),
            "high": h.to_numpy(),
            "low": l.to_numpy(),
            "close": c.to_numpy(),
            "volume": v.fillna(0).to_numpy() if v is not None else 0.0,
        }
    )
    out = out.dropna(subset=["open", "high", "low", "close"]).drop_duplicates("ts_ms")
    log.info("TradingView CSV %s -> %s bars", p.name, len(out))
    return out.reset_index(drop=True)


def ingest_import_dir(directory: str | Path | None = None) -> dict[str, pd.DataFrame]:
    """Ingest all CSVs in imports/btcd; filename should contain timeframe e.g. BTCD_1h.csv."""
    d = Path(directory) if directory else IMPORT_DIR
    d.mkdir(parents=True, exist_ok=True)
    out: dict[str, pd.DataFrame] = {}
    for p in sorted(d.glob("*.csv")):
        tf = "1d"
        m = re.search(r"(1m|5m|15m|1h|4h|1d|1w)", p.stem, re.I)
        if m:
            tf = m.group(1).lower()
        out[tf] = ingest_tradingview_csv(p)
    return out
