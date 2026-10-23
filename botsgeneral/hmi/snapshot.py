"""Build a JSON snapshot for one Virtual Private Server (VPS)."""

from __future__ import annotations

import os
import socket
import time
from typing import Any

from botsgeneral.discover import detect_vps_id, load_registry
from botsgeneral.hmi.aliases import vps_alias
from botsgeneral.hmi.host import host_metrics
from botsgeneral.hmi.jsonutil import jsonable
from botsgeneral.hmi.strategy import summaries_for_bots
from botsgeneral.report import build_fleet_report, _running_symbols_for_bots


def build_snapshot(
    keys_path: str | None = None,
    registry_path: str | None = None,
    report_cfg_path: str | None = None,
    vps_id: str | None = None,
    since_date: str | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    registry = load_registry(registry_path)
    vps = vps_id or detect_vps_id(registry) or os.environ.get("BOTSGENERAL_VPS")
    report = build_fleet_report(
        keys_path=keys_path,
        registry_path=registry_path,
        report_cfg_path=report_cfg_path,
        vps_id=vps,
        since_date=since_date,
        include_trades=True,
        sitrep_running_only=False,
    )
    sitrep = report.get("sitrep") or {}
    host = host_metrics(sitrep.get("disk", {}).get("path"))
    # Prefer sitrep CPU (already sampled) then overlay host disk/mem
    if sitrep.get("cpu"):
        host["cpu"] = sitrep["cpu"]
    if sitrep.get("memory"):
        host["memory"] = sitrep["memory"]
    if sitrep.get("disk"):
        host["disk"] = sitrep["disk"]
    if sitrep.get("load"):
        host["load"] = sitrep["load"]
    if sitrep.get("uptime"):
        host["uptime"] = sitrep["uptime"]
    host["vps"] = report.get("vps")
    host["alias"] = vps_alias(str(report.get("vps") or ""))
    try:
        host["hostname"] = socket.gethostname()
    except OSError:
        host["hostname"] = None

    accounts = []
    for a in report.get("accounts") or []:
        bot_ids = list(a.get("bot_ids") or [])
        row = dict(a)
        row["strategies"] = summaries_for_bots(bot_ids, registry)
        row["vps"] = report.get("vps")
        row["vps_alias"] = host["alias"]
        bot_symbols: dict[str, list[str]] = {}
        for bid in bot_ids:
            try:
                bot_symbols[str(bid)] = sorted(_running_symbols_for_bots(registry, [bid]))
            except Exception:
                bot_symbols[str(bid)] = []
        row["bot_symbols"] = bot_symbols
        accounts.append(row)

    elapsed_ms = int((time.time() - t0) * 1000)
    payload = {
        "ok": True,
        "generated_ms": int(time.time() * 1000),
        "elapsed_ms": elapsed_ms,
        "vps": report.get("vps"),
        "alias": host["alias"],
        "hostname": host.get("hostname"),
        "since": report.get("since"),
        "config_path": report.get("config_path"),
        "host": host,
        "sitrep": {
            "bots": sitrep.get("bots") or [],
            "warnings": sitrep.get("warnings") or [],
            "candle_freshness": sitrep.get("candle_freshness") or [],
            "data_unsafe": sitrep.get("data_unsafe") or [],
            "db_exists": sitrep.get("db_exists"),
            "db_path": sitrep.get("db_path"),
        },
        "accounts": accounts,
        "missing_accounts": report.get("missing_accounts") or [],
    }
    return jsonable(payload)


def build_host_only() -> dict[str, Any]:
    host = host_metrics()
    vps = os.environ.get("BOTSGENERAL_VPS")
    if not vps:
        try:
            from botsgeneral.discover import detect_vps_id, load_registry

            vps = detect_vps_id(load_registry())
        except Exception:
            vps = None
    host["vps"] = vps
    host["alias"] = vps_alias(vps)
    try:
        host["hostname"] = socket.gethostname()
    except OSError:
        host["hostname"] = None
    host["generated_ms"] = int(time.time() * 1000)
    return jsonable({"ok": True, "host": host})
