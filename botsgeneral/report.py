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


# Bybit closed-pnl rejects windows longer than 7 days.
_CLOSED_PNL_MAX_WINDOW_MS = 7 * 24 * 60 * 60 * 1000


def _fetch_closed_pnl_window(
    api_key: str,
    api_secret: str,
    start_ms: int,
    end_ms: int,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor = None
    while True:
        params: dict[str, Any] = {
            "category": "linear",
            "startTime": int(start_ms),
            "endTime": int(end_ms),
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


def fetch_closed_pnl(
    api_key: str,
    api_secret: str,
    start_ms: int,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    """Paginate Bybit closed-pnl since start_ms (chunked into <=7d windows)."""
    end_ms = int(time.time() * 1000)
    start_ms = int(start_ms)
    if end_ms <= start_ms:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    window_start = start_ms
    while window_start < end_ms:
        window_end = min(window_start + _CLOSED_PNL_MAX_WINDOW_MS, end_ms)
        rows = _fetch_closed_pnl_window(api_key, api_secret, window_start, window_end, symbol=symbol)
        for t in rows:
            key = (
                str(t.get("orderId") or "")
                + "|"
                + str(t.get("updatedTime") or "")
                + "|"
                + str(t.get("symbol") or "")
                + "|"
                + str(t.get("closedPnl") or "")
                + "|"
                + str(t.get("qty") or "")
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(t)
        window_start = window_end
        time.sleep(0.05)
    return out


def _account_bot_map(registry: dict) -> dict[str, list[str]]:
    from botsgeneral.keys import canonicalize_account_name

    m: dict[str, list[str]] = {}
    for bot, cfg in (registry.get("bots") or {}).items():
        acc = cfg.get("account")
        names = acc if isinstance(acc, list) else ([acc] if acc else [])
        for a in names:
            canon = canonicalize_account_name(str(a))
            m.setdefault(canon, []).append(bot)
    return m


def _registry_symbols(registry: dict, bot_names: list[str]) -> list[str]:
    """Configured symbol list from registry (live universe hint)."""
    out: list[str] = []
    for b in bot_names:
        cfg = (registry.get("bots") or {}).get(b) or {}
        for s in cfg.get("symbols") or []:
            sym = str(s).upper().replace("/", "")
            if sym and sym not in out:
                out.append(sym)
    return out


def _symbols_from_text(blob: str) -> set[str]:
    """Pull SYMBOLUSDT tokens from screen/process text."""
    import re

    out: set[str] = set()
    for m in re.finditer(r"([A-Za-z0-9]+USDT)", blob, flags=re.IGNORECASE):
        out.add(m.group(1).upper())
    return out


def _running_symbols_for_bots(registry: dict, bot_names: list[str]) -> set[str]:
    """Symbols currently running for these bots (matched screens/process + registry)."""
    from botsgeneral.discover.process import list_screens, list_systemd_units, process_cmdline_blob

    screens = list_screens()
    systemd = list_systemd_units()
    proc = process_cmdline_blob()
    found: set[str] = set()

    # Generic tokens that collide across bots — never use alone for symbol scoping
    generic = {"run_live", "run_live_bot", "live_trade", "python", "python3"}

    for bot in bot_names:
        cfg = (registry.get("bots") or {}).get(bot) or {}
        screen_matchers = [str(x).lower() for x in (cfg.get("screen_match") or []) if x]
        process_matchers = [
            str(x).lower()
            for x in (cfg.get("process_match") or [])
            if x and str(x).lower() not in generic
        ]
        path = str(cfg.get("path") or "").lower()
        prefix = str(cfg.get("systemd_prefix") or "").lower()
        systemd_match = [str(x).lower() for x in (cfg.get("systemd_match") or []) if x]

        from botsgeneral.discover import path_appears_in_blob

        bot_blob_parts: list[str] = []
        for scr in screens:
            low = scr.lower()
            if any(m in low for m in screen_matchers):
                bot_blob_parts.append(scr)
        for line in proc.split("\n"):
            low = line.lower()
            if path and path_appears_in_blob(path, line):
                bot_blob_parts.append(line)
            elif any(m in low for m in process_matchers):
                bot_blob_parts.append(line)
        for u in systemd:
            low = u.lower()
            if prefix and (low.startswith(prefix) or prefix.rstrip("@") + "@" in low):
                bot_blob_parts.append(u)
            elif any(m in low for m in systemd_match):
                bot_blob_parts.append(u)

        bot_found = _symbols_from_text("\n".join(bot_blob_parts))
        bot_hint = set(_registry_symbols(registry, [bot]))
        if bot_hint:
            bot_found &= bot_hint
        found |= bot_found or bot_hint

    return found


def _trade_ts_ms(t: dict[str, Any]) -> int:
    try:
        return int(t.get("updatedTime") or t.get("createdTime") or 0)
    except (TypeError, ValueError):
        return 0


def _since_map_for_bots(settings: dict[str, Any], bot_names: list[str]) -> dict[str, str]:
    """Merge since_by_bot overrides for the given bots → {SYMBOL: YYYY-MM-DD}."""
    out: dict[str, str] = {}
    by_bot = settings.get("since_by_bot") or {}
    if not isinstance(by_bot, dict):
        return out
    for bot in bot_names:
        block = by_bot.get(bot) or by_bot.get(str(bot).lower())
        if not isinstance(block, dict):
            continue
        for sym, day in block.items():
            if day:
                out[str(sym).upper().replace("/", "")] = str(day).strip()[:10]
    return out


def _filter_closed_by_since(
    closed: list[dict[str, Any]],
    default_since: str,
    since_by_symbol: dict[str, str],
) -> list[dict[str, Any]]:
    """Drop trades before the applicable since date (default or per-symbol)."""
    default_ms = parse_since_ms(str(default_since))
    sym_ms = {s: parse_since_ms(d) for s, d in since_by_symbol.items()}
    out = []
    for t in closed:
        sym = (t.get("symbol") or "").upper()
        start = sym_ms.get(sym, default_ms)
        if _trade_ts_ms(t) >= start:
            out.append(t)
    return out


def _earliest_since_ms(default_since: str, since_by_symbol: dict[str, str]) -> int:
    dates = [str(default_since)] + list(since_by_symbol.values())
    return min(parse_since_ms(d) for d in dates)


def _active_candle_keys(sitrep: dict) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    for p in sitrep.get("discovered_pairs") or []:
        keys.add((p["exchange"], p["symbol"], p["timeframe"]))
    for p in sitrep.get("unique_pairs") or []:
        # unique_pairs may be "bybit:BTCUSDT:5m" strings
        if isinstance(p, str) and p.count(":") == 2:
            ex, sym, tf = p.split(":")
            keys.add((ex, sym, tf))
    return keys


def build_fleet_report(
    keys_path: str | None = None,
    registry_path: str | None = None,
    report_cfg_path: str | None = None,
    vps_id: str | None = None,
    since_date: str | None = None,
) -> dict[str, Any]:
    settings = load_report_settings(report_cfg_path)
    since = since_date or settings.get("since_date") or "2026-07-09"
    registry = load_registry(registry_path)
    vps = vps_id or detect_vps_id(registry)
    accounts = resolve_accounts(keys_path)
    acct_bots = _account_bot_map(registry)
    sitrep = build_sitrep(registry_path=registry_path, vps_id=vps)

    running_bots = {b["bot"] for b in (sitrep.get("bots") or []) if b.get("running")}
    # Accounts only for bots that are actually running on this host
    preferred = {
        a
        for a, bots in acct_bots.items()
        if any(b in running_bots for b in bots)
    }
    use_accounts = {k: v for k, v in accounts.items() if k in preferred}
    missing = sorted(preferred - set(accounts.keys()))

    # Filter sitrep bots/pairs/freshness to live reality
    sitrep = dict(sitrep)
    sitrep["bots"] = [b for b in (sitrep.get("bots") or []) if b.get("running")]
    active_keys = _active_candle_keys(sitrep)
    sitrep["candle_freshness"] = [
        f
        for f in (sitrep.get("candle_freshness") or [])
        if (f.get("exchange"), f.get("symbol"), f.get("timeframe")) in active_keys
    ]
    sitrep["discovered_pairs"] = [
        p for p in (sitrep.get("discovered_pairs") or []) if p.get("bot") in running_bots
    ]

    rows = []
    for name in sorted(use_accounts.keys()):
        creds = use_accounts[name]
        summary = account_summary(name, creds)
        bots = [b for b in acct_bots.get(name, []) if b in running_bots]
        summary["bots"] = bots
        live_syms = _running_symbols_for_bots(registry, bots)
        since_by_sym = _since_map_for_bots(settings, bots)
        fetch_start_ms = _earliest_since_ms(str(since), since_by_sym)
        try:
            closed = fetch_closed_pnl(creds["api_key"], creds["api_secret"], fetch_start_ms)
        except Exception as e:
            summary["closed_error"] = str(e)
            closed = []
        # Keep closed trades only for live symbols when we know them
        if live_syms:
            closed = [t for t in closed if (t.get("symbol") or "").upper() in live_syms]
        closed = _filter_closed_by_since(closed, str(since), since_by_sym)
        by_sym: dict[str, list] = {}
        for t in closed:
            sym = (t.get("symbol") or "?").upper()
            by_sym.setdefault(sym, []).append(t)
        for p in summary.get("positions") or []:
            sym = (p.get("symbol") or "").upper()
            if sym and (not live_syms or sym in live_syms):
                by_sym.setdefault(sym, [])
        # Show configured live symbols even with 0 closed (so BTC/ETH visible)
        for sym in sorted(live_syms):
            by_sym.setdefault(sym, [])
        # Drop open positions that aren't live symbols
        if live_syms:
            summary["positions"] = [
                p for p in (summary.get("positions") or []) if (p.get("symbol") or "").upper() in live_syms
            ]
        per_coin = []
        for sym in sorted(by_sym.keys()):
            m = trade_metrics(by_sym[sym])
            m["symbol"] = sym
            m["n_closed"] = m["n_trades"]
            m["since"] = since_by_sym.get(sym, since)
            opens = [p for p in (summary.get("positions") or []) if (p.get("symbol") or "").upper() == sym]
            m["open_positions"] = opens
            per_coin.append(m)
        summary["since"] = since
        summary["since_by_symbol"] = since_by_sym
        summary["closed_all"] = trade_metrics(closed)
        summary["per_coin"] = per_coin
        summary["closed_raw_count"] = len(closed)
        summary["live_symbols"] = sorted(live_syms)
        rows.append(summary)

    return {
        "vps": vps,
        "since": since,
        "config_path": settings.get("_config_path"),
        "sitrep": sitrep,
        "accounts": rows,
        "missing_accounts": missing,
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
    from botsgeneral.keys import canonicalize_account_name

    account_name = canonicalize_account_name(target)
    # Resolve bot name → account
    if account_name not in accounts:
        for a, bots in acct_bots.items():
            if target.lower() in {b.lower() for b in bots} or target.lower() == a.lower():
                account_name = a
                break
        else:
            for a in accounts:
                if a.lower() == target.lower() or canonicalize_account_name(a) == account_name:
                    account_name = a
                    break

    if account_name not in accounts:
        # try any canon match
        for a in accounts:
            if canonicalize_account_name(a) == canonicalize_account_name(target):
                account_name = a
                break

    if account_name not in accounts:
        return {"error": f"Unknown account/bot: {target}", "known_accounts": sorted(accounts.keys())}

    creds = accounts[account_name]
    summary = account_summary(account_name, creds)
    bots = acct_bots.get(account_name, [])
    since_by_sym = _since_map_for_bots(settings, bots)
    sym_u = symbol.upper() if symbol else None
    if sym_u and sym_u in since_by_sym:
        since = since_by_sym[sym_u]
        start_ms = parse_since_ms(str(since))
    else:
        start_ms = _earliest_since_ms(str(since), since_by_sym) if not sym_u else parse_since_ms(str(since))
    closed = fetch_closed_pnl(
        creds["api_key"],
        creds["api_secret"],
        start_ms,
        symbol=sym_u,
    )
    closed = _filter_closed_by_since(closed, str(since_date or settings.get("since_date") or "2026-07-09"), since_by_sym)
    if sym_u:
        closed = [t for t in closed if (t.get("symbol") or "").upper() == sym_u]
    # sort newest first
    closed_sorted = sorted(closed, key=lambda t: int(t.get("updatedTime") or t.get("createdTime") or 0), reverse=True)
    metrics = trade_metrics(closed_sorted)
    return {
        "account": account_name,
        "bots": bots,
        "symbol_filter": sym_u,
        "since": since_by_sym.get(sym_u, since) if sym_u else since,
        "since_by_symbol": since_by_sym,
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
    print("\nBot health (running):")
    bots = sitrep.get("bots") or []
    if not bots:
        print("  (none)")
    for b in bots:
        print(f"  [OK ] {b['bot']:12} account={b.get('account')} path_ok={b.get('path_exists')}")
    print("\nCandle pairs (active):")
    fresh = sitrep.get("candle_freshness") or []
    if not fresh:
        print("  (none — collector not serving pairs on this host)")
    for f in fresh:
        stale = " STALE" if f.get("stale") else ""
        print(
            f"  {f['exchange']:7} {f['symbol']:10} {f['timeframe']:4} "
            f"bars={f['bars']:<6} lag={f.get('lag_sec')}s{stale}"
        )
    for w in sitrep.get("warnings") or []:
        print(f"WARN: {w}")
    for m in report.get("missing_accounts") or []:
        print(f"WARN: no API keys loaded for account {m}")

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
            since_tag = c.get("since") or a.get("since")
            since_s = f" since={since_tag}" if since_tag and since_tag != report.get("since") else ""
            print(
                f"    {c['symbol']:10} n={c['n_trades']:<4} "
                f"realized={fmt_num(c.get('realized_pnl'), 4):>10}  "
                f"WR={fmt_pct(c.get('winrate')):>7}  "
                f"PF={fmt_num(c.get('profit_factor'), 2):>6}  "
                f"Sharpe={fmt_num(c.get('sharpe'), 2):>6}{since_s}"
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
    print("Help:             bots --help")


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
