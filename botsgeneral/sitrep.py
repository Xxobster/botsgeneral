from __future__ import annotations

import json
import os
from pathlib import Path

from botsgeneral.db import CandleDB
from botsgeneral.discover import bot_runtime_status, detect_vps_id, discover_pairs, load_registry, unique_pairs
from botsgeneral.hmi.host import cpu_info, disk_usage, load_avg, mem_info, uptime_info


def _default_db_path(registry: dict) -> str:
    env = os.environ.get("SHARED_CANDLES_DB") or os.environ.get("BOTSGENERAL_DB")
    if env:
        return env
    local = Path(__file__).resolve().parents[1] / "data" / "shared_candles.db"
    if os.name == "nt" or not Path("/var/lib/botsgeneral").exists():
        return str(local)
    return registry.get("default_db_path") or "/var/lib/botsgeneral/shared_candles.db"


def _data_unsafe_flags(db: CandleDB) -> list[dict]:
    """Fleet-visible LIVE-DATA-001 flags stored in shared-candle meta."""
    rows = db._conn.execute(  # noqa: SLF001 — CandleDB owns this SQLite connection.
        "SELECT key, value FROM meta WHERE key LIKE 'data_unsafe:%' ORDER BY key"
    ).fetchall()
    out = []
    for key, raw in rows:
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            value = {"ok": False, "reason": "META_PARSE_FAIL", "raw": str(raw)[:200]}
        out.append({"key": str(key), "value": value})
    return out


def _disk_usage(path: str = "/") -> dict:
    return disk_usage(path)


def _mem_info() -> dict:
    return mem_info()


def _load_avg() -> dict:
    return load_avg()


def build_sitrep(registry_path: str | None = None, db_path: str | None = None, vps_id: str | None = None) -> dict:
    registry = load_registry(registry_path)
    vps = vps_id or detect_vps_id(registry) or os.environ.get("BOTSGENERAL_VPS")
    dbp = db_path or _default_db_path(registry)
    items, warnings = discover_pairs(registry, vps)
    pairs = unique_pairs(items)
    freshness = []
    discovered = []
    data_unsafe = []
    if Path(dbp).exists():
        db = CandleDB(dbp)
        freshness = db.freshness_report()
        discovered = db.list_discovered()
        data_unsafe = _data_unsafe_flags(db)
        db.close()

    cpu = cpu_info()
    return {
        "vps": vps,
        "db_path": dbp,
        "db_exists": Path(dbp).exists(),
        "disk": _disk_usage("/" if os.name != "nt" else str(Path(dbp).anchor or "C:\\")),
        "memory": _mem_info(),
        "load": _load_avg(),
        "cpu": cpu,
        "uptime": uptime_info(),
        "nproc": cpu.get("nproc"),
        "bots": bot_runtime_status(registry, vps),
        "discovered_pairs": [
            {"exchange": p.exchange, "symbol": p.symbol, "timeframe": p.timeframe, "bot": b}
            for p, b in items
        ],
        "unique_pairs": [str(p) for p in pairs],
        "warnings": warnings,
        "candle_freshness": freshness,
        "data_unsafe": data_unsafe,
        "db_discovered_snapshot": discovered,
    }


def print_sitrep(report: dict) -> None:
    print(f"=== botsgeneral sitrep ===")
    print(f"VPS: {report.get('vps')}")
    print(f"DB:  {report.get('db_path')} (exists={report.get('db_exists')})")
    cpu = report.get("cpu") or {}
    if cpu.get("cpu_pct") is not None:
        print(f"CPU:  {cpu['cpu_pct']}% busy — {cpu.get('nproc')} cores ({cpu.get('source')})")
    disk = report.get("disk") or {}
    if "free_gb" in disk:
        print(f"Disk: {disk['used_pct']}% used — {disk['free_gb']} GB free / {disk['total_gb']} GB")
    mem = report.get("memory") or {}
    if "used_pct" in mem:
        print(f"Mem:  {mem['used_pct']}% used — {mem.get('available_gb')} GB available")
    load = report.get("load") or {}
    if load:
        print(f"Load: {load}")
    print("\nBots:")
    for b in report.get("bots") or []:
        flag = "UP" if b.get("running") else "DOWN"
        serve = "serve" if b.get("serve_candles") else "no-candles"
        acc = b.get("account")
        if isinstance(acc, list):
            acc = ",".join(str(a) for a in acc)
        print(f"  [{flag}] {(b.get('label') or b['bot']):12} path_ok={b.get('path_exists')} {serve} account={acc}")
    print("\nDiscovered pairs:")
    for p in report.get("discovered_pairs") or []:
        print(f"  {p['exchange']:7} {p['symbol']:10} {p['timeframe']:4} <- {p['bot']}")
    print("\nCandle freshness (active pairs only):")
    active = {(p["exchange"], p["symbol"], p["timeframe"]) for p in (report.get("discovered_pairs") or [])}
    shown = 0
    if not active:
        print("  (none — no bot on this VPS requests shared candles)")
    else:
        for f in report.get("candle_freshness") or []:
            key = (f.get("exchange"), f.get("symbol"), f.get("timeframe"))
            if key not in active:
                continue
            shown += 1
            stale = " STALE" if f.get("stale") else ""
            print(
                f"  {f['exchange']:7} {f['symbol']:10} {f['timeframe']:4} "
                f"bars={f['bars']:<5} lag={f.get('lag_sec')}s{stale}"
            )
        if not shown:
            print("  (none)")
    print("\nLIVE-DATA-001 DATA_UNSAFE:")
    flags = report.get("data_unsafe") or []
    if not flags:
        print("  PASS (no DATA_UNSAFE flags)")
    else:
        for flag in flags:
            value = flag.get("value") or {}
            print(
                f"  UNSAFE {flag.get('key')} reason={value.get('reason')} "
                f"updated_ms={value.get('updated_ms')}"
            )
    for w in report.get("warnings") or []:
        print(f"WARN: {w}")
