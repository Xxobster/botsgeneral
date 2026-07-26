from __future__ import annotations

import logging
import os
import re
import socket
from pathlib import Path
from typing import Any

import yaml

from botsgeneral.discover import parsers
from botsgeneral.discover.process import list_screens, list_systemd_units, process_cmdline_blob
from botsgeneral.models import CandlePair

log = logging.getLogger(__name__)


def load_registry(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        path = os.environ.get("BOTSGENERAL_REGISTRY")
    if path is None:
        here = Path(__file__).resolve().parents[2] / "config" / "bots_registry.yaml"
        alt = Path("/opt/botsgeneral/config/bots_registry.yaml")
        path = here if here.exists() else alt
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def detect_vps_id(registry: dict[str, Any]) -> str | None:
    env = os.environ.get("BOTSGENERAL_VPS")
    if env:
        return env.strip()
    host = socket.gethostname()
    try:
        ips = {socket.gethostbyname(host)}
    except OSError:
        ips = set()
    # also try common interfaces via hostname -I style not portable; check registry keys in /etc
    for vps_id in registry.get("vps", {}):
        if vps_id in ips or vps_id in host:
            return vps_id
    # fallback: if only one vps has paths that exist, use it
    matches = []
    for vps_id, cfg in registry.get("vps", {}).items():
        bots = cfg.get("bots") or []
        hits = 0
        for b in bots:
            bcfg = registry.get("bots", {}).get(b) or {}
            p = Path(bcfg.get("path", ""))
            if p.exists():
                hits += 1
        if hits:
            matches.append((hits, vps_id))
    if matches:
        matches.sort(reverse=True)
        return matches[0][1]
    return None


def discover_pairs(
    registry: dict[str, Any] | None = None,
    vps_id: str | None = None,
) -> tuple[list[tuple[CandlePair, str]], list[str]]:
    """Return (pairs_with_bot, warnings)."""
    registry = registry or load_registry()
    vps_id = vps_id or detect_vps_id(registry)
    warnings: list[str] = []
    if not vps_id:
        warnings.append("Could not detect VPS id; set BOTSGENERAL_VPS")
        bot_names = list(registry.get("bots", {}).keys())
    else:
        bot_names = list((registry.get("vps", {}).get(vps_id) or {}).get("bots") or [])
        if not bot_names:
            warnings.append(f"No bots listed for VPS {vps_id}")

    screens = list_screens()
    systemd = list_systemd_units()
    proc_blob = process_cmdline_blob()

    results: list[tuple[CandlePair, str]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for name in bot_names:
        bcfg = (registry.get("bots") or {}).get(name)
        if not bcfg:
            warnings.append(f"Unknown bot in registry: {name}")
            continue

        running = _is_running(bcfg, screens, systemd, proc_blob)
        pairs = parsers.parse_bot(name, bcfg)
        if bcfg.get("serve_candles", True) and not pairs:
            msg = f"{name}: no candle pairs discovered from config"
            if running:
                msg += " (bot appears RUNNING)"
            warnings.append(msg)
        for p in pairs:
            if not bcfg.get("serve_candles", True):
                continue
            key = (*p.key(), name)
            if key in seen:
                continue
            seen.add(key)
            results.append((p, name))

        if not bcfg.get("serve_candles", True) and not running:
            # informational only for sitrep later
            pass

    results.sort(key=lambda x: (x[0].exchange, x[0].symbol, x[0].timeframe, x[1]))
    return results, warnings


def unique_pairs(items: list[tuple[CandlePair, str]]) -> list[CandlePair]:
    out: list[CandlePair] = []
    seen: set[tuple[str, str, str]] = set()
    for p, _ in items:
        if p.key() in seen:
            continue
        seen.add(p.key())
        out.append(p)
    return out


def path_appears_in_blob(path: str, blob: str) -> bool:
    """True if path appears as its own install root, not as a prefix of a sibling dir.

    `/home/xgb` must not match `/home/xgb_match/...`.
    """
    path = str(path or "").rstrip("/\\")
    if not path:
        return False
    # Require path end or a path separator / quote / whitespace after the match.
    pat = re.escape(path) + r"(?:[/\\]|\s|\"|'|$)"
    return re.search(pat, blob, flags=re.IGNORECASE) is not None


def _is_running(bcfg: dict, screens: list[str], systemd: list[str], proc_blob: str) -> bool:
    # Generic process tokens shared by multiple bots — never enough alone
    generic_proc = {"run_live", "run_live_bot", "live_trade", "python", "python3"}

    for s in bcfg.get("screen_match") or []:
        if any(s.lower() in scr.lower() for scr in screens):
            return True
    prefix = bcfg.get("systemd_prefix")
    if prefix:
        if any(u.startswith(prefix) and u.endswith(".service") for u in systemd):
            return True
    for s in bcfg.get("systemd_match") or []:
        if any(s.lower() in u.lower() for u in systemd):
            return True

    path = str(bcfg.get("path") or "")
    if path_appears_in_blob(path, proc_blob):
        return True

    distinctive = [
        str(m)
        for m in (bcfg.get("process_match") or [])
        if m and str(m).lower() not in generic_proc
    ]
    for m in distinctive:
        if m.lower() in proc_blob.lower():
            return True
    return False


def bot_runtime_status(registry: dict[str, Any], vps_id: str | None = None) -> list[dict]:
    registry = registry or load_registry()
    vps_id = vps_id or detect_vps_id(registry)
    bot_names = list((registry.get("vps", {}).get(vps_id) or {}).get("bots") or [])
    screens = list_screens()
    systemd = list_systemd_units()
    proc_blob = process_cmdline_blob()
    out = []
    for name in bot_names:
        bcfg = (registry.get("bots") or {}).get(name) or {}
        out.append(
            {
                "bot": name,
                "path": bcfg.get("path"),
                "path_exists": Path(bcfg.get("path") or "").exists(),
                "serve_candles": bool(bcfg.get("serve_candles", True)),
                "account": bcfg.get("account"),
                "running": _is_running(bcfg, screens, systemd, proc_blob),
            }
        )
    return out
