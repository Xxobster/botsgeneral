from __future__ import annotations

import logging
import os
import re
import socket
from pathlib import Path
from typing import Any

import yaml

from botsgeneral.discover import parsers
from botsgeneral.discover.demand import refine_bot_pairs
from botsgeneral.discover.process import (
    list_screens,
    list_systemd_unit_lines,
    list_systemd_units,
    process_cmdline_blob,
)
from botsgeneral.keys import canonicalize_account_name
from botsgeneral.models import CandlePair

log = logging.getLogger(__name__)

_ACCOUNT_FLAG_RE = re.compile(
    r"(?i)--account(?:\s+|=)(Xxobster\d*|xxobster\d*)"
)
_ACCOUNT_TOKEN_RE = re.compile(r"(?i)\b(Xxobster\d+)\b")
# Screen names like xxobster2ETHUSDT (digits may be followed by a symbol).
_ACCOUNT_SCREEN_RE = re.compile(r"(?i)(?:^|[.\s_-])xxobster(\d+)(?=[A-Za-z_\s.-]|$)")


def accounts_mentioned_in_text(text: str) -> set[str]:
    """Pull canonical Xxobster* account names from process/screen/systemd text."""
    out: set[str] = set()
    if not text:
        return out
    for m in _ACCOUNT_FLAG_RE.finditer(text):
        out.add(canonicalize_account_name(m.group(1)))
    for m in _ACCOUNT_TOKEN_RE.finditer(text):
        out.add(canonicalize_account_name(m.group(1)))
    for m in _ACCOUNT_SCREEN_RE.finditer(text):
        out.add(canonicalize_account_name("Xxobster" + m.group(1)))
    return out


def bot_runtime_blob(
    bcfg: dict,
    *,
    screens: list[str],
    systemd_lines: list[str],
    proc_blob: str,
) -> str:
    """Concatenate screen/process/systemd text that belongs to this bot."""
    screen_matchers = [str(x).lower() for x in (bcfg.get("screen_match") or []) if x]
    process_matchers = [str(x).lower() for x in (bcfg.get("process_match") or []) if x]
    path = str(bcfg.get("path") or "")
    prefix = str(bcfg.get("systemd_prefix") or "").lower()
    systemd_match = [str(x).lower() for x in (bcfg.get("systemd_match") or []) if x]
    parts: list[str] = []
    for scr in screens:
        low = scr.lower()
        if any(m in low for m in screen_matchers):
            parts.append(scr)
    for line in (proc_blob or "").split("\n"):
        low = line.lower()
        if path and path_appears_in_blob(path, line):
            parts.append(line)
            continue
        if any(m and m in low for m in process_matchers):
            parts.append(line)
    for ln in systemd_lines:
        ul = ln.lower()
        unit = ln.split()[0].lower() if ln.split() else ""
        if prefix and unit.startswith(prefix):
            parts.append(ln)
            continue
        if any(m and m in ul for m in systemd_match):
            parts.append(ln)
    return "\n".join(parts)


def registry_accounts(bcfg: dict) -> list[str]:
    acc = bcfg.get("account")
    names = acc if isinstance(acc, list) else ([acc] if acc else [])
    return [canonicalize_account_name(str(a)) for a in names if a]


def running_accounts_for_bot(
    bcfg: dict,
    *,
    screens: list[str],
    systemd_lines: list[str],
    proc_blob: str,
    running: bool,
) -> list[str]:
    """Accounts actually used by a live bot instance (not the full registry list).

    Prefer ``--account`` / Xxobster tokens found on matching screens/processes/units.
    If nothing is detectable and the registry has a single account, keep that.
    Multi-account registry entries with no runtime hit return [].
    """
    configured = registry_accounts(bcfg)
    if not running:
        return []
    blob = bot_runtime_blob(
        bcfg, screens=screens, systemd_lines=systemd_lines, proc_blob=proc_blob
    )
    found = accounts_mentioned_in_text(blob)
    if found:
        if configured:
            hit = [a for a in configured if a in found]
            if hit:
                return hit
        # Same pack on another VPS can bind a different --account than the registry.
        return sorted(found)
    if configured and len(configured) == 1:
        return list(configured)
    return []


def load_registry(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        path = os.environ.get("BOTSGENERAL_REGISTRY")
    if path is None:
        here = Path(__file__).resolve().parents[2] / "config" / "bots_registry.yaml"
        alt = Path("/opt/botsgeneral/config/bots_registry.yaml")
        path = here if here.exists() else alt
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _local_ipv4s() -> set[str]:
    """Best-effort set of this host's IPv4 addresses (Linux + fallback)."""
    ips: set[str] = set()
    try:
        host = socket.gethostname()
        ips.add(socket.gethostbyname(host))
    except OSError:
        pass
    # hostname -I (Linux)
    try:
        import subprocess

        r = subprocess.run(
            ["hostname", "-I"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for tok in (r.stdout or "").split():
            if tok.count(".") == 3:
                ips.add(tok.strip())
    except Exception:
        pass
    # parse `ip -4 -o addr`
    try:
        import subprocess

        r = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "scope", "global"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for ln in (r.stdout or "").splitlines():
            parts = ln.split()
            if "inet" in parts:
                i = parts.index("inet")
                if i + 1 < len(parts):
                    ips.add(parts[i + 1].split("/")[0])
    except Exception:
        pass
    ips.discard("127.0.0.1")
    return ips


def detect_vps_id(registry: dict[str, Any]) -> str | None:
    env = os.environ.get("BOTSGENERAL_VPS")
    if env:
        return env.strip()
    # Windows research machine: local collector, not a live VPS pin.
    if os.name == "nt":
        pin = Path.home() / ".botsgeneral" / "vps_id"
        if pin.exists():
            val = pin.read_text(encoding="utf-8", errors="ignore").strip()
            if val:
                return val
        return "local"
    # Persistent pin written at install time
    for pin in (
        Path("/etc/botsgeneral/vps_id"),
        Path.home() / ".botsgeneral" / "vps_id",
    ):
        if pin.exists():
            val = pin.read_text(encoding="utf-8", errors="ignore").strip()
            if val:
                return val
    host = socket.gethostname()
    ips = _local_ipv4s()
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
            # Prefer registry keys that look like this host's IP even on path-tie
            ip_bonus = 1 if vps_id in ips else 0
            matches.append((hits, ip_bonus, vps_id))
    if matches:
        matches.sort(reverse=True)
        return matches[0][2]
    return None


def discover_pairs(
    registry: dict[str, Any] | None = None,
    vps_id: str | None = None,
    *,
    only_running: bool = True,
) -> tuple[list[tuple[CandlePair, str]], list[str]]:
    """Return (pairs_with_bot, warnings).

    ``only_running`` (default): skip bots that are not live on this host so the
    collector does not fetch leftover 1m/4h series nobody is trading.
    """
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
        if only_running and vps_id != "local" and not running:
            continue
        pairs = parsers.parse_bot(name, bcfg)
        pairs = refine_bot_pairs(
            name=name,
            bcfg=bcfg,
            pairs=pairs,
            proc_blob=proc_blob,
            vps_id=vps_id,
        )
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
    systemd_lines = list_systemd_unit_lines()
    proc_blob = process_cmdline_blob()
    out = []
    for name in bot_names:
        bcfg = (registry.get("bots") or {}).get(name) or {}
        running = _is_running(bcfg, screens, systemd, proc_blob)
        live_accounts = running_accounts_for_bot(
            bcfg,
            screens=screens,
            systemd_lines=systemd_lines,
            proc_blob=proc_blob,
            running=running,
        )
        # Display only accounts that are live for this bot; fall back to registry
        # only when the bot is down (so operators still see intended wiring).
        if running:
            account_disp: Any = live_accounts
        else:
            configured = registry_accounts(bcfg)
            account_disp = configured if len(configured) != 1 else configured[0]
            if isinstance(account_disp, list) and len(account_disp) == 0:
                account_disp = bcfg.get("account")
        out.append(
            {
                "bot": name,
                "label": str(bcfg.get("label") or name),
                "path": bcfg.get("path"),
                "path_exists": Path(bcfg.get("path") or "").exists(),
                "serve_candles": bool(bcfg.get("serve_candles", True)),
                "account": account_disp,
                "registry_accounts": registry_accounts(bcfg),
                "running_accounts": live_accounts,
                "running": running,
            }
        )
    return out
