"""Bybit USDT-perpetual instrument limits for tradesim sizing.

Fetches ``minOrderQty``, ``qtyStep``, ``minNotionalValue``, ``tickSize`` and max leverage
from Bybit V5. Prefers an authenticated session with the local Xxobster keys so the same
credentials the live bots use are exercised; falls back to the public market endpoint
(instrument specs are public).

Secrets are read from disk and never written into the cache or logs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..contracts import InstrumentSpec

# Preferred: %USERPROFILE%\.trading\secrets.env (env-style). Legacy plaintext
# under ~/.trading/legacy is a fallback only.
DEFAULT_SECRETS_ENV = Path.home() / ".trading" / "secrets.env"
DEFAULT_KEYS_PATH = Path.home() / ".trading" / "legacy" / "api keys bybit.txt"
DEFAULT_ACCOUNT = "Xxobster_local"
BYBIT_REST = "https://api.bybit.com"


def _load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _account_token(account: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", account.strip())


@dataclass(frozen=True)
class BybitInstrument:
    symbol: str
    tick_size: float
    qty_step: float
    min_qty: float
    min_notional: float
    max_qty: float
    max_leverage: float
    status: str
    retrieved_at_ms: int

    def to_instrument_spec(self, *, maintenance_rate: float = 0.005) -> InstrumentSpec:
        return InstrumentSpec(
            symbol=self.symbol,
            tick_size=self.tick_size,
            qty_step=self.qty_step,
            min_qty=self.min_qty,
            min_notional=self.min_notional,
            max_qty=self.max_qty,
            max_leverage=self.max_leverage,
            maintenance_rate=maintenance_rate,
            funding_interval_ms=8 * 60 * 60 * 1000,
            snapshot_ts_ms=self.retrieved_at_ms,
            source="bybit_v5_instruments-info",
        )


def load_xxobster_local(
    keys_path: str | Path | None = None,
    account: str = DEFAULT_ACCOUNT,
) -> tuple[str, str]:
    """Return (api_key, api_secret) for the named account. Never log the secret.

    Resolution order:
    1. Process environment ``{ACCOUNT}_API_KEY`` / ``{ACCOUNT}_API_SECRET``
    2. ``%USERPROFILE%\\.trading\\secrets.env`` (or ``TRADING_SECRETS_ENV``)
    3. Plaintext keys file (``keys_path``, defaulting to legacy path)
    """
    token = _account_token(account)
    env_key = os.environ.get(f"{token}_API_KEY")
    env_secret = os.environ.get(f"{token}_API_SECRET")
    if env_key and env_secret:
        return env_key, env_secret

    secrets_path = Path(
        os.environ.get("TRADING_SECRETS_ENV") or DEFAULT_SECRETS_ENV
    )
    env_map = _load_env_file(secrets_path)
    if env_map.get(f"{token}_API_KEY") and env_map.get(f"{token}_API_SECRET"):
        return env_map[f"{token}_API_KEY"], env_map[f"{token}_API_SECRET"]

    path = Path(keys_path) if keys_path is not None else DEFAULT_KEYS_PATH
    try:
        from botsgeneral.keys import parse_bybit_keys_file
    except ImportError:
        parse_bybit_keys_file = _parse_bybit_keys_file_fallback

    accounts = parse_bybit_keys_file(path)
    if account not in accounts:
        raise KeyError(
            f"account {account!r} not found in env/secrets ({secrets_path}) "
            f"or keys file {path}; have {sorted(accounts)}"
        )
    creds = accounts[account]
    return creds["api_key"], creds["api_secret"]


def _parse_bybit_keys_file_fallback(path: Path) -> dict[str, dict[str, str]]:
    """Minimal parser so tradesim works without importing botsgeneral."""
    import re

    text = path.read_text(encoding="utf-8")
    accounts: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in text.splitlines():
        m = re.match(r"^\s*ACCOUNT:\s*(.+)\s*$", line, re.I)
        if m:
            current = m.group(1).strip()
            accounts[current] = {}
            continue
        if current is None:
            continue
        m = re.match(r"^\s*API KEY:\s*(.+)\s*$", line, re.I)
        if m:
            accounts[current]["api_key"] = m.group(1).strip()
            continue
        m = re.match(r"^\s*API SECRET:\s*(.+)\s*$", line, re.I)
        if m:
            accounts[current]["api_secret"] = m.group(1).strip()
    return {
        k: v for k, v in accounts.items() if v.get("api_key") and v.get("api_secret")
    }


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _get_json(
    path: str,
    params: Mapping[str, str],
    *,
    api_key: str | None = None,
    api_secret: str | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    url = f"{BYBIT_REST}{path}?{query}"
    headers = {"User-Agent": "tradesim-venue/1.0"}
    if api_key and api_secret:
        ts = str(int(time.time() * 1000))
        recv = "5000"
        payload = f"{ts}{api_key}{recv}{query}"
        headers.update(
            {
                "X-BAPI-API-KEY": api_key,
                "X-BAPI-TIMESTAMP": ts,
                "X-BAPI-RECV-WINDOW": recv,
                "X-BAPI-SIGN": _sign(api_secret, payload),
            }
        )
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Bybit HTTP {exc.code}: {body[:300]}") from exc


def fetch_instrument(
    symbol: str,
    *,
    category: str = "linear",
    keys_path: str | Path = DEFAULT_KEYS_PATH,
    account: str = DEFAULT_ACCOUNT,
    use_auth: bool = True,
) -> BybitInstrument:
    """Fetch one USDT-perp instrument. ``use_auth`` loads Xxobster_local keys."""
    api_key = api_secret = None
    if use_auth:
        api_key, api_secret = load_xxobster_local(keys_path, account)

    data = _get_json(
        "/v5/market/instruments-info",
        {"category": category, "symbol": symbol.upper()},
        api_key=api_key,
        api_secret=api_secret,
    )
    if int(data.get("retCode", -1)) != 0:
        raise RuntimeError(f"Bybit instruments-info failed: {data.get('retMsg')}")
    rows = data.get("result", {}).get("list") or []
    if not rows:
        raise KeyError(f"symbol {symbol!r} not found on Bybit {category}")
    return _parse_row(rows[0])


def fetch_instruments(
    symbols: Sequence[str] | None = None,
    *,
    category: str = "linear",
    keys_path: str | Path = DEFAULT_KEYS_PATH,
    account: str = DEFAULT_ACCOUNT,
    use_auth: bool = True,
) -> list[BybitInstrument]:
    """Fetch many symbols. If ``symbols`` is None, pull the full linear USDT list."""
    api_key = api_secret = None
    if use_auth:
        api_key, api_secret = load_xxobster_local(keys_path, account)

    wanted = {s.upper() for s in symbols} if symbols else None
    out: list[BybitInstrument] = []
    cursor = ""
    while True:
        params: dict[str, str] = {"category": category, "limit": "1000"}
        if cursor:
            params["cursor"] = cursor
        # Single-symbol shortcut when only one is requested.
        if wanted is not None and len(wanted) == 1:
            params["symbol"] = next(iter(wanted))
        data = _get_json(
            "/v5/market/instruments-info",
            params,
            api_key=api_key,
            api_secret=api_secret,
        )
        if int(data.get("retCode", -1)) != 0:
            raise RuntimeError(f"Bybit instruments-info failed: {data.get('retMsg')}")
        result = data.get("result") or {}
        for row in result.get("list") or []:
            sym = str(row.get("symbol", ""))
            if wanted is not None and sym not in wanted:
                continue
            # USDT perpetuals only for our research default.
            if not sym.endswith("USDT"):
                continue
            if str(row.get("contractType", "")).lower() not in ("", "linearperpetual"):
                # Bybit uses "LinearPerpetual"
                if "perpetual" not in str(row.get("contractType", "")).lower():
                    continue
            out.append(_parse_row(row))
        cursor = str(result.get("nextPageCursor") or "")
        if wanted is not None and len(wanted) == 1:
            break
        if not cursor:
            break
        time.sleep(0.05)

    if wanted is not None:
        missing = wanted - {i.symbol for i in out}
        if missing:
            raise KeyError(f"symbols not returned by Bybit: {sorted(missing)}")
    return sorted(out, key=lambda i: i.symbol)


def _parse_row(row: Mapping[str, Any]) -> BybitInstrument:
    lot = row.get("lotSizeFilter") or {}
    price = row.get("priceFilter") or {}
    lev = row.get("leverageFilter") or {}
    min_notional = lot.get("minNotionalValue") or lot.get("minOrderAmt") or 0.0
    return BybitInstrument(
        symbol=str(row["symbol"]).upper(),
        tick_size=float(price.get("tickSize", 0.01)),
        qty_step=float(lot.get("qtyStep", 0.001)),
        min_qty=float(lot.get("minOrderQty", 0.001)),
        min_notional=float(min_notional),
        max_qty=float(lot.get("maxOrderQty", 1e9)),
        max_leverage=float(lev.get("maxLeverage", 100)),
        status=str(row.get("status", "")),
        retrieved_at_ms=int(time.time() * 1000),
    )
