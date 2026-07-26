from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from botsgeneral.collect import default_db_path
from botsgeneral.db import CandleDB
from botsgeneral.discover import bot_runtime_status, detect_vps_id, discover_pairs, load_registry, unique_pairs


def _disk_usage(path: str = "/") -> dict:
    try:
        u = shutil.disk_usage(path)
        return {
            "path": path,
            "total_gb": round(u.total / 1e9, 2),
            "used_gb": round(u.used / 1e9, 2),
            "free_gb": round(u.free / 1e9, 2),
            "used_pct": round(100 * u.used / u.total, 1),
        }
    except Exception as e:
        return {"path": path, "error": str(e)}


def _mem_info() -> dict:
    try:
        if Path("/proc/meminfo").exists():
            data = {}
            for ln in Path("/proc/meminfo").read_text().splitlines():
                parts = ln.split()
                if len(parts) >= 2:
                    data[parts[0].rstrip(":")] = int(parts[1])  # kB
            total = data.get("MemTotal", 0)
            avail = data.get("MemAvailable", 0)
            return {
                "total_gb": round(total / 1e6, 2),
                "available_gb": round(avail / 1e6, 2),
                "used_pct": round(100 * (total - avail) / total, 1) if total else None,
            }
    except Exception as e:
        return {"error": str(e)}
    return {"note": "meminfo unavailable"}


def _load_avg() -> dict:
    try:
        if Path("/proc/loadavg").exists():
            parts = Path("/proc/loadavg").read_text().split()
            return {"load1": float(parts[0]), "load5": float(parts[1]), "load15": float(parts[2])}
    except Exception:
        pass
    return {}


def build_sitrep(registry_path: str | None = None, db_path: str | None = None, vps_id: str | None = None) -> dict:
    registry = load_registry(registry_path)
    vps = vps_id or detect_vps_id(registry) or os.environ.get("BOTSGENERAL_VPS")
    dbp = db_path or default_db_path(registry)
    items, warnings = discover_pairs(registry, vps)
    pairs = unique_pairs(items)
    freshness = []
    discovered = []
    if Path(dbp).exists():
        db = CandleDB(dbp)
        freshness = db.freshness_report()
        discovered = db.list_discovered()
        db.close()

    return {
        "vps": vps,
        "db_path": dbp,
        "db_exists": Path(dbp).exists(),
        "disk": _disk_usage("/" if os.name != "nt" else str(Path(dbp).anchor or "C:\\")),
        "memory": _mem_info(),
        "load": _load_avg(),
        "bots": bot_runtime_status(registry, vps),
        "discovered_pairs": [
            {"exchange": p.exchange, "symbol": p.symbol, "timeframe": p.timeframe, "bot": b}
            for p, b in items
        ],
        "unique_pairs": [str(p) for p in pairs],
        "warnings": warnings,
        "candle_freshness": freshness,
        "db_discovered_snapshot": discovered,
    }


def print_sitrep(report: dict) -> None:
    print(f"=== botsgeneral sitrep ===")
    print(f"VPS: {report.get('vps')}")
    print(f"DB:  {report.get('db_path')} (exists={report.get('db_exists')})")
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
        print(f"  [{flag}] {b['bot']:12} path_ok={b.get('path_exists')} {serve} account={b.get('account')}")
    print("\nDiscovered pairs:")
    for p in report.get("discovered_pairs") or []:
        print(f"  {p['exchange']:7} {p['symbol']:10} {p['timeframe']:4} <- {p['bot']}")
    print("\nCandle freshness (active pairs only):")
    active = {(p["exchange"], p["symbol"], p["timeframe"]) for p in (report.get("discovered_pairs") or [])}
    shown = 0
    for f in report.get("candle_freshness") or []:
        key = (f.get("exchange"), f.get("symbol"), f.get("timeframe"))
        if active and key not in active:
            continue
        shown += 1
        stale = " STALE" if f.get("stale") else ""
        print(
            f"  {f['exchange']:7} {f['symbol']:10} {f['timeframe']:4} "
            f"bars={f['bars']:<5} lag={f.get('lag_sec')}s{stale}"
        )
    if not shown:
        print("  (none)")
    for w in report.get("warnings") or []:
        print(f"WARN: {w}")
