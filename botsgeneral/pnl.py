from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

import requests

from botsgeneral.discover import load_registry
from botsgeneral.keys import resolve_accounts
from botsgeneral.metrics import enrich_open_position, fmt_signed_pct, fmt_ts_utc

log = logging.getLogger(__name__)
BYBIT = "https://api.bybit.com"
# Bybit rejects requests when |server_ts - req_ts| > recv_window.
# VPS clocks can lag a few seconds; keep a wide window and sync offset.
_RECV_WINDOW_MS = "60000"
_time_offset_ms = 0
_offset_fetched_at = 0.0


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _sync_bybit_time_offset(force: bool = False) -> None:
    """Align local timestamps with Bybit server time (refresh every 5 minutes)."""
    global _time_offset_ms, _offset_fetched_at
    now = time.time()
    if not force and _offset_fetched_at and (now - _offset_fetched_at) < 300:
        return
    try:
        r = requests.get(f"{BYBIT}/v5/market/time", timeout=5)
        r.raise_for_status()
        data = r.json()
        result = data.get("result") or {}
        # Prefer millisecond precision when available.
        server_ms = result.get("timeNano")
        if server_ms is not None:
            server_ms = int(server_ms) // 1_000_000
        else:
            server_ms = int(result.get("timeSecond") or 0) * 1000
        if server_ms > 0:
            local_ms = int(time.time() * 1000)
            _time_offset_ms = server_ms - local_ms
            _offset_fetched_at = now
            if abs(_time_offset_ms) > 1000:
                log.warning("Bybit clock offset %sms", _time_offset_ms)
    except Exception as e:
        log.debug("Bybit time sync failed: %s", e)


def _bybit_timestamp_ms() -> int:
    _sync_bybit_time_offset()
    return int(time.time() * 1000) + int(_time_offset_ms)


def bybit_private_get(api_key: str, api_secret: str, path: str, params: dict | None = None) -> dict:
    params = params or {}
    recv = _RECV_WINDOW_MS
    query = urlencode(params)
    url = f"{BYBIT}{path}"
    if query:
        url = f"{url}?{query}"

    last: dict = {}
    for attempt in range(2):
        ts = str(_bybit_timestamp_ms())
        prehash = f"{ts}{api_key}{recv}{query}"
        sign = _sign(api_secret, prehash)
        headers = {
            "X-BAPI-API-KEY": api_key,
            "X-BAPI-SIGN": sign,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": recv,
        }
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        last = r.json()
        msg = str(last.get("retMsg") or "")
        # Retry once after forcing a fresh server-time sync.
        if (
            attempt == 0
            and last.get("retCode") not in (0, None)
            and ("timestamp" in msg.lower() or "recv_window" in msg.lower())
        ):
            _sync_bybit_time_offset(force=True)
            continue
        return last
    return last


def account_summary(name: str, creds: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {"account": name}
    try:
        bal = bybit_private_get(
            creds["api_key"],
            creds["api_secret"],
            "/v5/account/wallet-balance",
            {"accountType": "UNIFIED"},
        )
        out["wallet_raw_ret"] = bal.get("retCode")
        if bal.get("retCode") != 0:
            out["error"] = bal.get("retMsg")
            return out
        lists = (bal.get("result") or {}).get("list") or []
        if not lists:
            out["equity"] = None
            return out
        acc = lists[0]
        out["total_equity"] = float(acc.get("totalEquity") or 0)
        out["total_wallet_balance"] = float(acc.get("totalWalletBalance") or 0)
        out["total_perp_upl"] = float(acc.get("totalPerpUPL") or 0)
        coins = []
        for c in acc.get("coin") or []:
            eq = float(c.get("equity") or 0)
            if abs(eq) > 0:
                coins.append(
                    {
                        "coin": c.get("coin"),
                        "equity": eq,
                        "wallet": float(c.get("walletBalance") or 0),
                        "upl": float(c.get("unrealisedPnl") or 0),
                    }
                )
        out["coins"] = coins
    except Exception as e:
        out["error"] = str(e)

    try:
        pos = bybit_private_get(
            creds["api_key"],
            creds["api_secret"],
            "/v5/position/list",
            {"category": "linear", "settleCoin": "USDT"},
        )
        positions = []
        if pos.get("retCode") == 0:
            for p in (pos.get("result") or {}).get("list") or []:
                size = float(p.get("size") or 0)
                if size == 0:
                    continue
                positions.append(
                    {
                        "symbol": p.get("symbol"),
                        "side": p.get("side"),
                        "size": size,
                        "avgPrice": p.get("avgPrice"),
                        "markPrice": p.get("markPrice"),
                        "unrealisedPnl": p.get("unrealisedPnl"),
                        "leverage": p.get("leverage"),
                        "takeProfit": p.get("takeProfit") or None,
                        "stopLoss": p.get("stopLoss") or None,
                        "createdTime": p.get("createdTime"),
                        "updatedTime": p.get("updatedTime"),
                    }
                )
        out["positions"] = positions
    except Exception as e:
        out["positions_error"] = str(e)
    return out


def build_pnl(keys_path: str | None = None, registry_path: str | None = None) -> dict:
    accounts = resolve_accounts(keys_path)
    registry = load_registry(registry_path)
    # map account -> bot names
    acct_bots: dict[str, list[str]] = {}
    for bot, cfg in (registry.get("bots") or {}).items():
        acc = cfg.get("account")
        if isinstance(acc, list):
            for a in acc:
                acct_bots.setdefault(a, []).append(bot)
        elif acc:
            acct_bots.setdefault(str(acc), []).append(bot)

    rows = []
    for name, creds in sorted(accounts.items()):
        summary = account_summary(name, creds)
        summary["bots"] = acct_bots.get(name, [])
        rows.append(summary)

    total_eq = sum(float(r.get("total_equity") or 0) for r in rows if r.get("total_equity") is not None)
    total_upl = sum(float(r.get("total_perp_upl") or 0) for r in rows if r.get("total_perp_upl") is not None)
    return {"accounts": rows, "total_equity": total_eq, "total_perp_upl": total_upl}


def print_pnl(report: dict) -> None:
    print("=== botsgeneral pnl ===")
    for a in report.get("accounts") or []:
        bots = ",".join(a.get("bots") or []) or "-"
        if a.get("error"):
            print(f"{a['account']:12} bots={bots:20} ERROR {a['error']}")
            continue
        print(
            f"{a['account']:12} bots={bots:20} "
            f"equity={a.get('total_equity')} "
            f"wallet={a.get('total_wallet_balance')} "
            f"upl={a.get('total_perp_upl')}"
        )
        for p in a.get("positions") or []:
            p = enrich_open_position(p)
            opened = fmt_ts_utc(p.get("opened_at_ms"))
            closer = p.get("closer_exit")
            closer_s = (
                f"to_{closer}={fmt_signed_pct(p.get('closer_pct'))}"
                if closer
                else "to_TP/SL=-"
            )
            print(
                f"    pos {p['symbol']:10} {p['side']:5} size={p['size']} "
                f"avg={p['avgPrice']} upl={p['unrealisedPnl']} lev={p['leverage']}  "
                f"opened={opened}  {closer_s}"
            )
    print(f"\nTOTAL equity={report.get('total_equity')} perp_upl={report.get('total_perp_upl')}")
