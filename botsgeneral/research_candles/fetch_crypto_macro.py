"""Crypto macro: total/BTC/ETH market caps, dominance, stablecoin mcap, Fear & Greed.

Stored as close-only OHLCV (open=high=low=close) so the shared warehouse schema
can feed cross-pair / LLM feature builders without a separate table.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np
import pandas as pd
import requests

from botsgeneral.research_candles.timestamps import to_ts_ms

log = logging.getLogger(__name__)

_UA = {"User-Agent": "botsgeneral-research-candles/1.0", "Accept": "application/json"}


def _close_only(ts_ms: np.ndarray | pd.Series, values: np.ndarray | pd.Series) -> pd.DataFrame:
    v = pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)
    t = pd.Series(ts_ms).astype("int64").to_numpy()
    mask = np.isfinite(v) & (t > 0)
    if not mask.any():
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    vv = v[mask]
    out = pd.DataFrame(
        {
            "ts_ms": t[mask],
            "open": vv,
            "high": vv,
            "low": vv,
            "close": vv,
            "volume": 0.0,
        }
    )
    return out.drop_duplicates("ts_ms").sort_values("ts_ms").reset_index(drop=True)


def _get_json(url: str, params: dict[str, Any] | None = None, retries: int = 3) -> Any | None:
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=_UA, timeout=90)
            if r.status_code == 429:
                time.sleep(15 * (i + 1))
                continue
            if r.status_code != 200:
                log.warning("HTTP %s %s: %s", r.status_code, url, r.text[:180])
                return None
            return r.json()
        except requests.RequestException as e:
            log.warning("request failed %s: %s", url, e)
            time.sleep(5 * (i + 1))
    return None


def fetch_coingecko_coin_mcap_daily(coin_id: str, *, years: int = 12) -> pd.DataFrame:
    """Daily USD market-cap for a CoinGecko coin (bitcoin, ethereum, …).

    Free API: `days=365` only (longer windows / range paging are blocked).
    Prefer ``fetch_blockchain_btc_mcap_daily`` for deep BTC history.
    """
    del years  # free tier cannot honor multi-year requests
    data = _get_json(
        f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
        {"vs_currency": "usd", "days": "365", "interval": "daily"},
    )
    if not data or not (data.get("market_caps") or []):
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    arr = np.asarray(data["market_caps"], dtype=float)
    out = _downsample_daily(_close_only(arr[:, 0], arr[:, 1]))
    log.info("CoinGecko %s mcap daily -> %s bars", coin_id, len(out))
    return out


def _downsample_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized last-close-per-UTC-day (handles hourly CoinGecko range payloads)."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    s = df.sort_values("ts_ms").copy()
    day = (s["ts_ms"].to_numpy(dtype=np.int64) // 86_400_000) * 86_400_000
    s = s.assign(_day=day)
    # last observation each day
    last_idx = s.groupby("_day", sort=True)["ts_ms"].idxmax()
    out = s.loc[last_idx, ["ts_ms", "open", "high", "low", "close", "volume"]].copy()
    out["ts_ms"] = s.loc[last_idx, "_day"].to_numpy()
    out["open"] = out["high"] = out["low"] = out["close"]
    return out.reset_index(drop=True)


def fetch_blockchain_btc_mcap_daily() -> pd.DataFrame:
    """Long-history BTC market cap from blockchain.info charts (free)."""
    data = _get_json(
        "https://api.blockchain.info/charts/market-cap",
        {"timespan": "all", "format": "json", "sampled": "false"},
    )
    if not data:
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    values = data.get("values") or []
    if not values:
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    ts = np.asarray([int(p["x"]) * 1000 for p in values], dtype=np.int64)
    val = np.asarray([float(p["y"]) for p in values], dtype=float)
    out = _downsample_daily(_close_only(ts, val))
    log.info("blockchain.info BTC_MCAP daily -> %s bars", len(out))
    return out


def fetch_coingecko_total_mcap_daily() -> pd.DataFrame:
    """Total crypto market cap — free tier often blocked; soft-fail."""
    for days in ("365", "90", "30"):
        data = _get_json(
            "https://api.coingecko.com/api/v3/global/market_cap_chart",
            {"days": days},
        )
        time.sleep(1.2)
        if not data:
            continue
        total = (
            (data.get("market_cap_chart") or {}).get("market_cap")
            or data.get("market_caps")
            or []
        )
        if not total:
            continue
        arr = np.asarray(total, dtype=float)
        out = _downsample_daily(_close_only(arr[:, 0], arr[:, 1]))
        log.info("CoinGecko TOTAL_MCAP daily (%sd) -> %s bars", days, len(out))
        return out
    return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])


def build_dominance_pct(part_mcap: pd.DataFrame, total_mcap: pd.DataFrame) -> pd.DataFrame:
    """Causal nearest-day dominance % = 100 * part / total (vectorized merge_asof)."""
    if part_mcap.empty or total_mcap.empty:
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    left = part_mcap[["ts_ms", "close"]].rename(columns={"close": "part"}).sort_values("ts_ms")
    right = total_mcap[["ts_ms", "close"]].rename(columns={"close": "total"}).sort_values("ts_ms")
    merged = pd.merge_asof(left, right, on="ts_ms", direction="nearest", tolerance=86_400_000)
    dom = (merged["part"] / merged["total"] * 100.0).to_numpy(dtype=float)
    return _close_only(merged["ts_ms"].to_numpy(), dom)


def fetch_defillama_stable_mcap_daily() -> pd.DataFrame:
    """Total stablecoin market cap (USD) — DefiLlama free charts."""
    data = _get_json("https://stablecoins.llama.fi/stablecoincharts/all")
    if not data or not isinstance(data, list):
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    rows = []
    for pt in data:
        if not isinstance(pt, dict):
            continue
        ts = pt.get("date") or pt.get("timestamp")
        # totalCirculatingUSD may be dict by peg type; prefer 'peggedUSD' / sum
        circ = pt.get("totalCirculatingUSD") or pt.get("totalCirculating")
        if isinstance(circ, dict):
            val = circ.get("peggedUSD") or circ.get("total") or next(iter(circ.values()), None)
        else:
            val = circ
        if ts is None or val is None:
            continue
        ts_i = int(ts)
        # Llama often returns seconds
        if ts_i < 10_000_000_000:
            ts_i *= 1000
        rows.append((ts_i, float(val)))
    if not rows:
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    arr = np.asarray(rows, dtype=float)
    out = _close_only(arr[:, 0], arr[:, 1])
    log.info("DefiLlama STABLE_MCAP daily -> %s bars", len(out))
    return out


def fetch_defillama_stablecoin_asset_daily(asset_id: int, symbol: str) -> pd.DataFrame:
    """Single stablecoin circulating USD history (asset id from /stablecoins)."""
    data = _get_json(f"https://stablecoins.llama.fi/stablecoin/{asset_id}")
    if not data or not isinstance(data, dict):
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    tokens = data.get("tokens") or data.get("chainBalances") or []
    # Prefer flat tokens[{date, circulating}] when present
    rows: list[tuple[int, float]] = []
    if isinstance(tokens, list) and tokens and isinstance(tokens[0], dict) and "date" in tokens[0]:
        for pt in tokens:
            ts = pt.get("date")
            circ = pt.get("circulating") or pt.get("circulatingUSD")
            if isinstance(circ, dict):
                val = circ.get("peggedUSD") or next(iter(circ.values()), None)
            else:
                val = circ
            if ts is None or val is None:
                continue
            ts_i = int(ts)
            if ts_i < 10_000_000_000:
                ts_i *= 1000
            rows.append((ts_i, float(val)))
    else:
        # chainBalances: {chain: {tokens: [{date, circulating}]}}
        chain_balances = data.get("chainBalances") or {}
        by_day: dict[int, float] = {}
        for _chain, payload in chain_balances.items():
            for pt in (payload or {}).get("tokens") or []:
                ts = pt.get("date")
                circ = pt.get("circulating")
                if isinstance(circ, dict):
                    val = circ.get("peggedUSD") or next(iter(circ.values()), None)
                else:
                    val = circ
                if ts is None or val is None:
                    continue
                ts_i = int(ts)
                if ts_i < 10_000_000_000:
                    ts_i *= 1000
                by_day[ts_i] = by_day.get(ts_i, 0.0) + float(val)
        rows = sorted(by_day.items())
    if not rows:
        log.warning("DefiLlama stablecoin %s (%s) empty", asset_id, symbol)
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    arr = np.asarray(rows, dtype=float)
    out = _close_only(arr[:, 0], arr[:, 1])
    log.info("DefiLlama %s daily -> %s bars", symbol, len(out))
    return out


def fetch_fear_greed_daily() -> pd.DataFrame:
    """alternative.me Crypto Fear & Greed Index (0–100 daily)."""
    data = _get_json("https://api.alternative.me/fng/", {"limit": 0, "format": "json"})
    if not data:
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    points = data.get("data") or []
    if not points:
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    ts = np.asarray([int(p["timestamp"]) * 1000 for p in points], dtype=np.int64)
    val = np.asarray([float(p["value"]) for p in points], dtype=float)
    out = _close_only(ts, val)
    log.info("Fear&Greed daily -> %s bars", len(out))
    return out


def stablecoin_flow_from_mcap(mcap: pd.DataFrame) -> pd.DataFrame:
    """Day-over-day change in stablecoin mcap (USD flow proxy), vectorized."""
    if mcap.empty:
        return pd.DataFrame(columns=["ts_ms", "open", "high", "low", "close", "volume"])
    s = mcap.sort_values("ts_ms").copy()
    flow = s["close"].diff().to_numpy(dtype=float)
    return _close_only(s["ts_ms"].to_numpy(), flow)


# Resolve DefiLlama IDs by symbol name at runtime (IDs can shift).
STABLECOIN_SYMBOLS: tuple[tuple[str, str], ...] = (
    ("USDT_MCAP", "USDT"),
    ("USDC_MCAP", "USDC"),
    ("DAI_MCAP", "DAI"),
)


def resolve_stablecoin_ids() -> dict[str, int]:
    """Map USDT/USDC/… → DefiLlama numeric id."""
    data = _get_json("https://stablecoins.llama.fi/stablecoins", {"includePrices": "true"})
    out: dict[str, int] = {}
    pegged = (data or {}).get("peggedAssets") if isinstance(data, dict) else None
    if not pegged:
        return out
    want = {sym.upper(): canon for canon, sym in STABLECOIN_SYMBOLS}
    for asset in pegged:
        sym = str(asset.get("symbol") or "").upper()
        if sym in want and "id" in asset:
            out[want[sym]] = int(asset["id"])
    return out
