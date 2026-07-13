from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import yaml

from botsgeneral.discover import bot_runtime_status, detect_vps_id, load_registry
from botsgeneral.keys import resolve_accounts
from botsgeneral.metrics import fmt_num, fmt_pct, parse_since_ms, trade_metrics
from botsgeneral.pnl import account_summary, bybit_private_get
from botsgeneral.sitrep import build_sitrep

log = logging.getLogger(__name__)


def load_report_settings(path: str | None = None) -> dict[str, Any]:
    candidates = []
    if path:
        candidates.append(path)
    env = os.environ.get("BOTSGENERAL_REPORT_CFG")
    if env:
        candidates.append(env)
    candidates.extend(
        [
            "/etc/botsgeneral/report.yaml",
            str(Path(__file__).resolve().parents[1] / "config" / "report.yaml"),
        ]
    )
    for c in candidates:
        p = Path(c)
        if p.exists():
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            data["_config_path"] = str(p)
            return data
    return {"since_date": "2026-07-09", "_config_path": "(defaults)"}


def fetch_closed_pnl(
    api_key: str,
    api_secret: str,
    start_ms: int,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    """Paginate Bybit closed-pnl since start_ms."""
    out: list[dict[str, Any]] = []
    cursor = None
    end_ms = int(time.time() * 1000)
    while True:
        params: dict[str, Any] = {
            "category": "linear",
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": 100,
        }
        if symbol:
            params["symbol"] = symbol
        if cursor:
            params["cursor"] = cursor
        data = bybit_private_get(api_key, api_secret, "/v5/position/closed-pnl", params)
        if data.get("retCode") != 0:
            raise RuntimeError(data.get("retMsg") or str(data))
        result = data.get("result") or {}
        rows = result.get("list") or []
        out.extend(rows)
        cursor = result.get("nextPageCursor") or None
        if not cursor or not rows:
            break
        time.sleep(0.05)
    return out


def _account_bot_map(registry: dict) -> dict[str, list[str]]:
    m: dict[str, list[str]] = {}
    for bot, cfg in (registry.get("bots") or {}).items():
        acc = cfg.get("account")
        if isinstance(acc, list):
            for a in acc:
                m.setdefault(str(a), []).append(bot)
        elif acc:
            m.setdefault(str(acc), []).append(bot)
    return m


def build_fleet_report(
    keys_path: str | None = None,
    registry_path: str | None = None,
    report_cfg_path: str | None = None,
    vps_id: str | None = None,
    since_date: str | None = None,
) -> dict[str, Any]:
    settings = load_report_settings(report_cfg_path)
    since = since_date or settings.get("since_date") or "2026-07-09"
    start_ms = parse_since_ms(str(since))
    registry = load_registry(registry_path)
    vps = vps_id or detect_vps_id(registry)
    accounts = resolve_accounts(keys_path)
    acct_bots = _account_bot_map(registry)
    # Prefer accounts that map to bots on this VPS; still include all keys if unknown
    vps_bots = set((registry.get("vps", {}).get(vps) or {}).get("bots") or [])
    preferred = {
        a
        for a, bots in acct_bots.items()
        if not vps_bots or any(b in vps_bots for b in bots)
    }
    if preferred:
        use_accounts = {k: v for k, v in accounts.items() if k in preferred}
    else:
        use_accounts = accounts

    sitrep = build_sitrep(registry_path=registry_path, vps_id=vps)
    rows = []
    for name in sorted(use_accounts.keys()):
        creds = use_accounts[name]
        summary = account_summary(name, creds)
        summary["bots"] = acct_bots.get(name, [])
        try:
            closed = fetch_closed_pnl(creds["api_key"], creds["api_secret"], start_ms)
        except Exception as e:
            summary["closed_error"] = str(e)
            closed = []
        # group by symbol
        by_sym: dict[str, list] = {}
        for t in closed:
            sym = t.get("symbol") or "?"
            by_sym.setdefault(sym, []).append(t)
        per_coin = []
        for sym in sorted(by_sym.keys()):
            m = trade_metrics(by_sym[sym])
            m["symbol"] = sym
            m["n_closed"] = m["n_trades"]
            per_coin.append(m)
        summary["since"] = since
        summary["closed_all"] = trade_metrics(closed)
        summary["per_coin"] = per_coin
        summary["closed_raw_count"] = len(closed)
        rows.append(summary)

    return {
        "vps": vps,
        "since": since,
        "config_path": settings.get("_config_path"),
        "sitrep": sitrep,
        "accounts": rows,
    }


def build_trades_report(
    account_or_bot: str,
    symbol: str | None = None,
    keys_path: str | None = None,
    registry_path: str | None = None,
    report_cfg_path: str | None = None,
    since_date: str | None = None,
) -> dict[str, Any]:
    settings = load_report_settings(report_cfg_path)
    since = since_date or settings.get("since_date") or "2026-07-09"
    start_ms = parse_since_ms(str(since))
    registry = load_registry(registry_path)
    accounts = resolve_accounts(keys_path)
    acct_bots = _account_bot_map(registry)

    target = account_or_bot.strip()
    # Resolve bot name → account
    account_name = target
    if target not in accounts:
        for a, bots in acct_bots.items():
            if target.lower() in {b.lower() for b in bots} or target.lower() == a.lower():
                account_name = a
                break
        else:
            # case-insensitive account match
            for a in accounts:
                if a.lower() == target.lower():
                    account_name = a
                    break

    if account_name not in accounts:
        return {"error": f"Unknown account/bot: {target}", "known_accounts": sorted(accounts.keys())}

    creds = accounts[account_name]
    summary = account_summary(account_name, creds)
    closed = fetch_closed_pnl(
        creds["api_key"],
        creds["api_secret"],
        start_ms,
        symbol=symbol.upper() if symbol else None,
    )
    # sort newest first
    closed_sorted = sorted(closed, key=lambda t: int(t.get("updatedTime") or t.get("createdTime") or 0), reverse=True)
    metrics = trade_metrics(closed_sorted)
    return {
        "account": account_name,
        "bots": acct_bots.get(account_name, []),
        "symbol_filter": symbol.upper() if symbol else None,
        "since": since,
        "wallet": summary,
        "metrics": metrics,
        "open_positions": summary.get("positions") or [],
        "trades": closed_sorted,
    }


def print_fleet_report(report: dict[str, Any]) -> None:
    sitrep = report.get("sitrep") or {}
    print("=" * 60)
    print(f"BOTS REPORT  VPS={report.get('vps')}  since={report.get('since')} UTC")
    print(f"config: {report.get('config_path')}")
    print("=" * 60)

    disk = sitrep.get("disk") or {}
    mem = sitrep.get("memory") or {}
    print(
        f"Host: disk {disk.get('used_pct')}% used ({disk.get('free_gb')} GB free) | "
        f"mem {mem.get('used_pct')}% | load {sitrep.get('load')}"
    )
    print("\nBot health:")
    for b in sitrep.get("bots") or []:
        flag = "OK " if b.get("running") else "DOWN"
        print(f"  [{flag}] {b['bot']:12} account={b.get('account')} path_ok={b.get('path_exists')}")
    print("\nCandle freshness:")
    for f in sitrep.get("candle_freshness") or []:
        stale = " STALE" if f.get("stale") else ""
        print(
            f"  {f['exchange']:7} {f['symbol']:10} {f['timeframe']:4} "
            f"bars={f['bars']:<6} lag={f.get('lag_sec')}s{stale}"
        )
    for w in sitrep.get("warnings") or []:
        print(f"WARN: {w}")

    print("\n" + "-" * 60)
    print("PnL by account / coin (closed since date + open UPL)")
    print("-" * 60)
    total_real = 0.0
    total_upl = 0.0
    for a in report.get("accounts") or []:
        bots = ",".join(a.get("bots") or []) or "-"
        if a.get("error"):
            print(f"\n{a['account']}  bots={bots}  ERROR {a['error']}")
            continue
        m = a.get("closed_all") or {}
        upl = float(a.get("total_perp_upl") or 0)
        total_real += float(m.get("realized_pnl") or 0)
        total_upl += upl
        print(
            f"\n{a['account']:12} bots={bots}\n"
            f"  equity={fmt_num(a.get('total_equity'), 4)}  "
            f"wallet={fmt_num(a.get('total_wallet_balance'), 4)}  "
            f"open_upl={fmt_num(upl, 4)}"
        )
        print(
            f"  since closed: n={m.get('n_trades')}  "
            f"realized={fmt_num(m.get('realized_pnl'), 4)}  "
            f"WR={fmt_pct(m.get('winrate'))}  "
            f"PF={fmt_num(m.get('profit_factor'), 3)}  "
            f"Sharpe(trades)={fmt_num(m.get('sharpe'), 3)}  "
            f"MaxDD={fmt_num(m.get('max_drawdown'), 4)}"
        )
        if a.get("closed_error"):
            print(f"  closed-pnl ERROR: {a['closed_error']}")
        for c in a.get("per_coin") or []:
            print(
                f"    {c['symbol']:10} n={c['n_trades']:<4} "
                f"realized={fmt_num(c.get('realized_pnl'), 4):>10}  "
                f"WR={fmt_pct(c.get('winrate')):>7}  "
                f"PF={fmt_num(c.get('profit_factor'), 2):>6}  "
                f"Sharpe={fmt_num(c.get('sharpe'), 2):>6}"
            )
        for p in a.get("positions") or []:
            print(
                f"    OPEN {p.get('symbol'):10} {p.get('side'):5} "
                f"size={p.get('size')} avg={p.get('avgPrice')} "
                f"upl={p.get('unrealisedPnl')} lev={p.get('leverage')}"
            )

    print("\n" + "=" * 60)
    print(
        f"TOTAL realized(since)={fmt_num(total_real, 4)}  "
        f"open_upl={fmt_num(total_upl, 4)}  "
        f"combined={fmt_num(total_real + total_upl, 4)}"
    )
    print("Drilldown:  bots trades <account|bot> [SYMBOL]")
    print("Change since date: edit /etc/botsgeneral/report.yaml")


def print_trades_report(report: dict[str, Any]) -> None:
    if report.get("error"):
        print("ERROR:", report["error"])
        print("Known accounts:", ", ".join(report.get("known_accounts") or []))
        return
    print("=" * 60)
    print(
        f"TRADES  account={report['account']}  bots={','.join(report.get('bots') or [])}  "
        f"symbol={report.get('symbol_filter') or 'ALL'}  since={report.get('since')}"
    )
    print("=" * 60)
    w = report.get("wallet") or {}
    print(
        f"Equity={fmt_num(w.get('total_equity'), 4)}  "
        f"Wallet={fmt_num(w.get('total_wallet_balance'), 4)}  "
        f"OpenUPL={fmt_num(w.get('total_perp_upl'), 4)}"
    )
    m = report.get("metrics") or {}
    print(
        f"Closed: n={m.get('n_trades')}  realized={fmt_num(m.get('realized_pnl'), 4)}  "
        f"WR={fmt_pct(m.get('winrate'))}  PF={fmt_num(m.get('profit_factor'), 3)}  "
        f"Sharpe={fmt_num(m.get('sharpe'), 3)}  Avg={fmt_num(m.get('avg_pnl'), 4)}  "
        f"MaxDD={fmt_num(m.get('max_drawdown'), 4)}"
    )
    print("\nOpen positions:")
    poss = report.get("open_positions") or []
    if not poss:
        print("  (none)")
    for p in poss:
        print(
            f"  {p.get('symbol'):10} {p.get('side'):5} size={p.get('size')} "
            f"avg={p.get('avgPrice')} upl={p.get('unrealisedPnl')} lev={p.get('leverage')}"
        )
    print("\nClosed trades (newest first):")
    trades = report.get("trades") or []
    if not trades:
        print("  (none since date)")
    for t in trades[:200]:
        ts = t.get("updatedTime") or t.get("createdTime")
        try:
            from datetime import datetime, timezone

            ts_s = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        except Exception:
            ts_s = str(ts)
        print(
            f"  {ts_s}  {t.get('symbol'):10} {t.get('side'):5} "
            f"qty={t.get('qty')}  avgEntry={t.get('avgEntryPrice')}  "
            f"avgExit={t.get('avgExitPrice')}  pnl={t.get('closedPnl')}  "
            f"lev={t.get('leverage')}  orderType={t.get('orderType')}"
        )
    if len(trades) > 200:
        print(f"  ... {len(trades) - 200} more")
