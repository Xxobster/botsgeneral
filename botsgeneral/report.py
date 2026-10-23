from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import yaml

from botsgeneral.discover import bot_runtime_status, detect_vps_id, load_registry
from botsgeneral.discover.process import (
    list_screens,
    list_systemd_unit_lines,
    list_systemd_units,
    process_cmdline_blob,
)
from botsgeneral.keys import resolve_accounts
from botsgeneral.metrics import (
    days_active,
    enrich_open_position,
    equity_curve_from_closed,
    equity_curves_by_symbol,
    fmt_num,
    fmt_pct,
    fmt_signed_pct,
    fmt_ts_utc,
    group_closed_legs_to_roundtrips,
    last_open_event,
    parse_since_ms,
    trade_metrics,
    trade_ts_ms,
)
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
    end_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Paginate Bybit closed-pnl since start_ms (chunked into <=7d windows)."""
    end_ms = int(end_ms if end_ms is not None else time.time() * 1000)
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


def fetch_closed_pnl_cached(
    account: str,
    api_key: str,
    api_secret: str,
    start_ms: int,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    """Same as fetch_closed_pnl but incremental SQLite cache when available."""
    from botsgeneral.hmi.cache import closed_pnl_cache

    cache = closed_pnl_cache()
    if cache is None:
        return fetch_closed_pnl(api_key, api_secret, start_ms, symbol=symbol)

    def _fetch(window_start: int, window_end: int) -> list[dict[str, Any]]:
        return fetch_closed_pnl(
            api_key, api_secret, window_start, symbol=None, end_ms=window_end
        )

    rows = cache.get_or_fetch(str(account), int(start_ms), _fetch, symbol=None)
    if symbol:
        su = str(symbol).upper()
        rows = [t for t in rows if (t.get("symbol") or "").upper() == su]
    return rows


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


def drop_generic_parent_bots(bot_names: list[str]) -> list[str]:
    """Hide catch-all `llm2` when a specific llm2_* unit is already listed.

    Autonomy / pivot child keys carry the real coins. The generic `llm2` entry
    lists BTC+ETH+SOL and pollutes the phone report (e.g. Bitcoin on a Solana-only
    filter account).
    """
    names = [str(b) for b in bot_names if b]
    if any(n.startswith("llm2_") for n in names):
        return [n for n in names if n != "llm2"]
    return names


def _live_account_bot_map(registry: dict, sitrep: dict) -> dict[str, list[str]]:
    """account -> bots that are running *and* actually using that account."""
    from botsgeneral.discover import running_accounts_for_bot
    from botsgeneral.keys import canonicalize_account_name

    screens = list_screens()
    systemd = list_systemd_units()
    systemd_lines = list_systemd_unit_lines()
    proc_blob = process_cmdline_blob()
    m: dict[str, list[str]] = {}
    for b in sitrep.get("bots") or []:
        if not b.get("running"):
            continue
        name = str(b.get("bot") or "")
        bcfg = (registry.get("bots") or {}).get(name) or {}
        # Prefer already-computed running_accounts from sitrep/bot_runtime_status
        live = b.get("running_accounts")
        if live is None:
            live = running_accounts_for_bot(
                bcfg,
                screens=screens,
                systemd_lines=systemd_lines,
                proc_blob=proc_blob,
                running=True,
            )
        for a in live or []:
            canon = canonicalize_account_name(str(a))
            m.setdefault(canon, []).append(name)
    return {k: drop_generic_parent_bots(v) for k, v in m.items()}


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


CATCHALL_BOTS = {"llm2"}


def symbols_from_llm2_unit_names(systemd: list[str]) -> set[str]:
    """Map running llm2-pivot-* unit names to coins (paths often lack SYMBOLUSDT)."""
    import re

    out: set[str] = set()
    for u in systemd:
        low = str(u).lower()
        if not low.startswith("llm2-"):
            continue
        if "autonomy" in low:
            continue
        if re.search(r"\bsol\b|[-_]sol[-_]|^llm2-pivot-sol", low):
            out.add("SOLUSDT")
        if re.search(r"\beth\b|[-_]eth[-_]|^llm2-pivot-eth", low):
            out.add("ETHUSDT")
        if re.search(r"\bbtc\b|[-_]btc[-_]|^llm2-pivot-btc", low):
            out.add("BTCUSDT")
    return out


def merge_bot_running_symbols(
    bot_found: set[str],
    bot_hint: set[str],
    bot_name: str,
) -> set[str]:
    """Process/systemd hits win. Catch-all registry lists must not invent coins."""
    if bot_found:
        return set(bot_found)
    if str(bot_name) in CATCHALL_BOTS:
        return set()
    return set(bot_hint)


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

        try:
            from botsgeneral.discover import path_appears_in_blob as _path_in_blob
        except ImportError:
            import re as _re

            def _path_in_blob(p: str, blob: str) -> bool:
                p = str(p or "").rstrip("/\\")
                if not p:
                    return False
                return _re.search(_re.escape(p) + r"(?:[/\\]|\s|\"|'|$)", blob, flags=_re.IGNORECASE) is not None

        bot_blob_parts: list[str] = []
        for scr in screens:
            low = scr.lower()
            if any(m in low for m in screen_matchers):
                bot_blob_parts.append(scr)
        for line in proc.split("\n"):
            low = line.lower()
            if path and _path_in_blob(path, line):
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
        if bot == "llm2":
            bot_found |= symbols_from_llm2_unit_names(bot_blob_parts or systemd)
        bot_hint = set(_registry_symbols(registry, [bot]))
        if bot_hint:
            bot_found &= bot_hint
        found |= merge_bot_running_symbols(bot_found, bot_hint, bot)

    return found


def _trade_ts_ms(t: dict[str, Any]) -> int:
    return trade_ts_ms(t)


def _since_map_for_bots(settings: dict[str, Any], bot_names: list[str]) -> dict[str, str]:
    """Merge since_by_bot overrides for the given bots → {SYMBOL: since stamp}."""
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
                out[str(sym).upper().replace("/", "")] = str(day).strip()
    return out


def _account_since_override(settings: dict[str, Any], account_name: str) -> str | None:
    """Optional per-account since stamp from since_by_account (date or datetime)."""
    from botsgeneral.keys import canonicalize_account_name

    by_acct = settings.get("since_by_account") or {}
    if not isinstance(by_acct, dict):
        return None
    canon = canonicalize_account_name(account_name)
    raw = by_acct.get(canon) or by_acct.get(account_name)
    if raw is None:
        for k, v in by_acct.items():
            if canonicalize_account_name(str(k)) == canon:
                raw = v
                break
    if raw is None:
        return None
    if isinstance(raw, dict):
        # allow {"*": "YYYY-MM-DD"} or ignore symbol map here (use bot map for symbols)
        star = raw.get("*") or raw.get("all")
        return str(star).strip() if star else None
    return str(raw).strip() if raw else None


def _later_iso_date(a: str, b: str) -> str:
    """Return the later since stamp (date-only is UTC midnight)."""
    aa = str(a).strip()
    bb = str(b).strip()
    return aa if parse_since_ms(aa) >= parse_since_ms(bb) else bb


def _effective_since_for_symbol(
    acct_since: str,
    sym: str,
    since_by_symbol: dict[str, str],
) -> str:
    """Per-symbol start cannot be earlier than the account go-live stamp."""
    extra = since_by_symbol.get(str(sym).upper())
    if extra:
        return _later_iso_date(acct_since, extra)
    return str(acct_since).strip()


def _filter_closed_by_since(
    closed: list[dict[str, Any]],
    default_since: str,
    since_by_symbol: dict[str, str],
) -> list[dict[str, Any]]:
    """Drop trades before the applicable since stamp (default or per-symbol).

    ``default_since`` (usually ``since_by_account``) is a floor: a per-bot
    symbol stamp may only make the window *later*, never earlier.
    """
    default_ms = parse_since_ms(str(default_since))
    out = []
    for t in closed:
        sym = (t.get("symbol") or "").upper()
        start = parse_since_ms(_effective_since_for_symbol(str(default_since), sym, since_by_symbol))
        if start < default_ms:
            start = default_ms
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


def _bot_label(registry: dict, bot_name: str) -> str:
    cfg = (registry.get("bots") or {}).get(bot_name) or {}
    return str(cfg.get("label") or bot_name)


def _enrich_account_closed(
    summary: dict[str, Any],
    *,
    name: str,
    bots: list[str],
    registry: dict,
    settings: dict[str, Any],
    since: str,
    creds: dict[str, str],
    include_trades: bool,
) -> dict[str, Any]:
    summary["bot_ids"] = list(bots)
    summary["bots"] = [_bot_label(registry, b) for b in bots]
    live_syms = _running_symbols_for_bots(registry, bots)
    since_by_sym = _since_map_for_bots(settings, bots)
    acct_since = _account_since_override(settings, name) or str(since)
    fetch_start_ms = parse_since_ms(str(acct_since))
    try:
        closed = fetch_closed_pnl_cached(
            name, creds["api_key"], creds["api_secret"], fetch_start_ms
        )
    except Exception as e:
        summary["closed_error"] = str(e)
        closed = []
    if live_syms:
        closed = [t for t in closed if (t.get("symbol") or "").upper() in live_syms]
    closed = _filter_closed_by_since(closed, acct_since, since_by_sym)
    by_sym: dict[str, list] = {}
    for t in closed:
        sym = (t.get("symbol") or "?").upper()
        by_sym.setdefault(sym, []).append(t)
    for p in summary.get("positions") or []:
        sym = (p.get("symbol") or "").upper()
        if sym and (not live_syms or sym in live_syms):
            by_sym.setdefault(sym, [])
    for sym in sorted(live_syms):
        by_sym.setdefault(sym, [])
    if live_syms:
        summary["positions"] = [
            p for p in (summary.get("positions") or []) if (p.get("symbol") or "").upper() in live_syms
        ]
    summary["positions"] = [enrich_open_position(p) for p in (summary.get("positions") or [])]
    per_coin = []
    for sym in sorted(by_sym.keys()):
        m = trade_metrics(by_sym[sym])
        m["symbol"] = sym
        m["n_closed"] = m["n_trades"]
        m["since"] = _effective_since_for_symbol(acct_since, sym, since_by_sym)
        m["days_active"] = days_active(parse_since_ms(str(m["since"])))
        opens = [p for p in (summary.get("positions") or []) if (p.get("symbol") or "").upper() == sym]
        m["open_positions"] = opens
        if include_trades:
            m["equity_curve"] = equity_curve_from_closed(group_closed_legs_to_roundtrips(by_sym[sym]))
        per_coin.append(m)
    summary["since"] = acct_since
    summary["since_ms"] = fetch_start_ms
    summary["days_active"] = days_active(fetch_start_ms)
    summary["since_by_symbol"] = since_by_sym
    summary["closed_all"] = trade_metrics(closed)
    summary["per_coin"] = per_coin
    summary["closed_raw_count"] = len(closed)
    summary["n_open_positions"] = len(
        [p for p in (summary.get("positions") or []) if float(p.get("size") or p.get("qty") or 0) > 0]
    )
    summary["live_symbols"] = sorted(live_syms)
    summary["last_open"] = last_open_event(summary.get("positions") or [], closed)
    if include_trades:
        roundtrips = group_closed_legs_to_roundtrips(closed)
        summary["equity_curve"] = equity_curve_from_closed(roundtrips)
        summary["equity_curve_by_symbol"] = equity_curves_by_symbol(roundtrips)
        summary["trades"] = normalize_closed_trades(roundtrips)
        summary["closed_leg_count"] = len(closed)
        summary["closed_roundtrip_count"] = len(roundtrips)
    try:
        from botsgeneral.hmi.decide_enrich import enrich_trades_and_positions

        enrich_trades_and_positions(
            trades=summary.get("trades") if include_trades else None,
            positions=summary.get("positions"),
            registry=registry,
            bot_ids=list(bots),
        )
    except Exception:
        pass
    return summary


def normalize_closed_trades(closed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable trade rows for the Human-Machine Interface (HMI) and JSON CLI."""
    out: list[dict[str, Any]] = []
    for t in closed:
        ts = trade_ts_ms(t)
        created = 0
        try:
            created = int(t.get("createdTime") or t.get("created_ms") or 0)
        except (TypeError, ValueError):
            created = 0
        row = {
            "order_id": t.get("orderId") or t.get("order_id"),
            "symbol": str(t.get("symbol") or "").upper(),
            "side": t.get("side"),
            "qty": t.get("qty") if t.get("qty") is not None else t.get("closedSize"),
            "closed_size": t.get("closedSize") or t.get("closed_size") or t.get("qty"),
            "entry": t.get("avgEntryPrice") if t.get("avgEntryPrice") is not None else t.get("entry"),
            "exit": t.get("avgExitPrice") if t.get("avgExitPrice") is not None else t.get("exit"),
            "pnl": t.get("closedPnl") if t.get("closedPnl") is not None else t.get("pnl"),
            "leverage": t.get("leverage"),
            "order_type": t.get("orderType"),
            "exec_type": t.get("execType"),
            "open_fee": t.get("openFee") or t.get("cumEntryFee"),
            "close_fee": t.get("closeFee") or t.get("cumExitFee"),
            "fill_count": t.get("fillCount"),
            "created_ms": created or None,
            "updated_ms": ts or None,
            "leg_count": int(t.get("leg_count") or 1),
        }
        if t.get("leg_order_ids"):
            row["leg_order_ids"] = list(t.get("leg_order_ids") or [])
        out.append(row)
    out.sort(key=lambda r: int(r.get("updated_ms") or 0), reverse=True)
    return out


def build_fleet_report(
    keys_path: str | None = None,
    registry_path: str | None = None,
    report_cfg_path: str | None = None,
    vps_id: str | None = None,
    since_date: str | None = None,
    *,
    include_trades: bool = False,
    sitrep_running_only: bool = True,
) -> dict[str, Any]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    settings = load_report_settings(report_cfg_path)
    since = since_date or settings.get("since_date") or "2026-07-09"
    registry = load_registry(registry_path)
    vps = vps_id or detect_vps_id(registry)
    accounts = resolve_accounts(keys_path)
    acct_bots_registry = _account_bot_map(registry)
    sitrep_full = build_sitrep(registry_path=registry_path, vps_id=vps)
    sitrep = dict(sitrep_full)

    running_bots = {b["bot"] for b in (sitrep.get("bots") or []) if b.get("running")}
    # Only accounts that a *running* bot process/unit actually uses (not every
    # account listed under a multi-account registry entry).
    acct_bots = _live_account_bot_map(registry, sitrep)
    preferred = set(acct_bots.keys())
    # Optional report.yaml accounts: allowlist filter (intersect when both set)
    cfg_accounts = settings.get("accounts") or []
    if isinstance(cfg_accounts, list) and cfg_accounts and preferred:
        from botsgeneral.keys import canonicalize_account_name

        wanted = {canonicalize_account_name(str(a)) for a in cfg_accounts if a}
        # Intersect only — never expand to allowlisted accounts when nothing is running.
        filtered = preferred & wanted
        if filtered:
            preferred = filtered
    use_accounts = {k: v for k, v in accounts.items() if k in preferred}
    missing = sorted(preferred - set(accounts.keys()))

    if sitrep_running_only:
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

    def _one(name: str) -> dict[str, Any]:
        creds = use_accounts[name]
        summary = account_summary(name, creds)
        bots = list(acct_bots.get(name) or [])
        reg_order = acct_bots_registry.get(name) or []
        bots = [b for b in reg_order if b in bots] + [b for b in bots if b not in reg_order]
        return _enrich_account_closed(
            summary,
            name=name,
            bots=bots,
            registry=registry,
            settings=settings,
            since=str(since),
            creds=creds,
            include_trades=include_trades,
        )

    rows: list[dict[str, Any]] = []
    names = sorted(use_accounts.keys())
    if len(names) <= 1:
        rows = [_one(n) for n in names]
    else:
        with ThreadPoolExecutor(max_workers=min(8, len(names))) as pool:
            futs = {pool.submit(_one, n): n for n in names}
            by_name: dict[str, dict[str, Any]] = {}
            for fut in as_completed(futs):
                n = futs[fut]
                try:
                    by_name[n] = fut.result()
                except Exception as e:
                    by_name[n] = {"account": n, "error": str(e), "bots": [], "bot_ids": []}
            rows = [by_name[n] for n in names]

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
    acct_since = _account_since_override(settings, account_name) or str(since)
    since = acct_since
    sym_u = symbol.upper() if symbol else None
    if sym_u:
        since = _effective_since_for_symbol(acct_since, sym_u, since_by_sym)
        start_ms = parse_since_ms(str(since))
    else:
        start_ms = parse_since_ms(str(acct_since))
    closed = fetch_closed_pnl_cached(
        account_name,
        creds["api_key"],
        creds["api_secret"],
        start_ms,
        symbol=sym_u,
    )
    closed = _filter_closed_by_since(closed, acct_since, since_by_sym)
    if sym_u:
        closed = [t for t in closed if (t.get("symbol") or "").upper() == sym_u]
    # sort newest first
    closed_sorted = sorted(closed, key=lambda t: int(t.get("updatedTime") or t.get("createdTime") or 0), reverse=True)
    metrics = trade_metrics(closed_sorted)
    since_out = _effective_since_for_symbol(acct_since, sym_u, since_by_sym) if sym_u else acct_since
    return {
        "account": account_name,
        "bots": bots,
        "symbol_filter": sym_u,
        "since": since_out,
        "days_active": days_active(parse_since_ms(str(since_out))),
        "since_by_symbol": since_by_sym,
        "wallet": summary,
        "metrics": metrics,
        "open_positions": summary.get("positions") or [],
        "trades": closed_sorted,
        "trades_normalized": normalize_closed_trades(closed_sorted),
        "equity_curve": equity_curve_from_closed(closed_sorted),
    }


def print_fleet_report(report: dict[str, Any]) -> None:
    sitrep = report.get("sitrep") or {}
    print("=" * 60)
    print(f"BOTS REPORT  VPS={report.get('vps')}  since={report.get('since')} UTC")
    print(f"config: {report.get('config_path')}")
    print("=" * 60)

    disk = sitrep.get("disk") or {}
    mem = sitrep.get("memory") or {}
    cpu = sitrep.get("cpu") or {}
    cpu_s = f"cpu {cpu.get('cpu_pct')}%" if cpu.get("cpu_pct") is not None else "cpu -"
    print(
        f"Host: {cpu_s} ({cpu.get('nproc') or sitrep.get('nproc') or '?'} cores) | "
        f"disk {disk.get('used_pct')}% used ({disk.get('free_gb')} GB free) | "
        f"mem {mem.get('used_pct')}% | load {sitrep.get('load')}"
    )
    print("\nBot health (running):")
    bots = sitrep.get("bots") or []
    if not bots:
        print("  (none)")
    for b in bots:
        acc = b.get("account")
        if isinstance(acc, list):
            acc = ",".join(str(a) for a in acc)
        print(f"  [OK ] {(b.get('label') or b['bot']):12} account={acc} path_ok={b.get('path_exists')}")
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
            f"open_upl={fmt_num(upl, 4)}  "
            f"since={a.get('since')}  days={a.get('days_active')}"
        )
        print(
            f"  since closed: n={m.get('n_trades')}  "
            f"realized={fmt_num(m.get('realized_pnl'), 4)}  "
            f"WR={fmt_pct(m.get('winrate'))}  "
            f"PF={fmt_num(m.get('profit_factor'), 3)}  "
            f"RF={fmt_num(m.get('recovery_factor'), 2)}  "
            f"MaxDD%={fmt_pct(m.get('max_dd_pct'))}  "
            f"MaxDD={fmt_num(m.get('max_drawdown'), 4)}  "
            f"Payoff={fmt_num(m.get('payoff'), 2)}"
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
                f"RF={fmt_num(c.get('recovery_factor'), 2):>5}  "
                f"MaxDD%={fmt_pct(c.get('max_dd_pct')):>7}{since_s}"
            )
        for p in a.get("positions") or []:
            closer = p.get("closer_exit")
            closer_s = (
                f"to_{closer}={fmt_signed_pct(p.get('closer_pct'))}"
                if closer
                else "to_TP/SL=-"
            )
            opened_s = fmt_ts_utc(p.get("opened_at_ms"))
            print(
                f"    OPEN {p.get('symbol'):10} {p.get('side'):5} "
                f"size={p.get('size')} avg={p.get('avgPrice')} "
                f"upl={p.get('unrealisedPnl')} lev={p.get('leverage')}  "
                f"opened={opened_s}  {closer_s}"
            )
        lo = a.get("last_open")
        if lo:
            print(
                f"    last_open {lo.get('symbol')} @ {fmt_ts_utc(lo.get('ts_ms'))}"
                + ("" if lo.get("source") == "open" else " (from closed)")
            )
        elif not (a.get("positions") or []):
            print("    last_open -")

    print("\n" + "=" * 60)
    print(
        f"TOTAL realized(since)={fmt_num(total_real, 4)}  "
        f"open_upl={fmt_num(total_upl, 4)}  "
        f"combined={fmt_num(total_real + total_upl, 4)}"
    )
    print("Drilldown:  bots trades <account|bot> [SYMBOL]")
    print("Change since date/time: edit /etc/botsgeneral/report.yaml")
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
        f"RF={fmt_num(m.get('recovery_factor'), 2)}  MaxDD%={fmt_pct(m.get('max_dd_pct'))}  "
        f"MaxDD={fmt_num(m.get('max_drawdown'), 4)}  Payoff={fmt_num(m.get('payoff'), 2)}  "
        f"Avg={fmt_num(m.get('avg_pnl'), 4)}  days={report.get('days_active')}"
    )
    print("\nOpen positions:")
    poss = [enrich_open_position(p) for p in (report.get("open_positions") or [])]
    if not poss:
        print("  (none)")
    for p in poss:
        closer = p.get("closer_exit")
        closer_s = (
            f"to_{closer}={fmt_signed_pct(p.get('closer_pct'))}"
            if closer
            else "to_TP/SL=-"
        )
        print(
            f"  {p.get('symbol'):10} {p.get('side'):5} size={p.get('size')} "
            f"avg={p.get('avgPrice')} upl={p.get('unrealisedPnl')} lev={p.get('leverage')}  "
            f"opened={fmt_ts_utc(p.get('opened_at_ms'))}  {closer_s}"
        )
    lo = last_open_event(poss, report.get("trades") or [])
    if lo:
        print(
            f"  last_open {lo.get('symbol')} @ {fmt_ts_utc(lo.get('ts_ms'))}"
            + ("" if lo.get("source") == "open" else " (from closed)")
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
