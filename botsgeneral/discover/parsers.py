from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from botsgeneral.models import CandlePair, normalize_symbol, normalize_timeframe

log = logging.getLogger(__name__)


def parse_bot(name: str, bcfg: dict[str, Any]) -> list[CandlePair]:
    parser = bcfg.get("parser") or "none"
    exchange = (bcfg.get("exchange") or "bybit").lower()
    also = [normalize_timeframe(x) for x in (bcfg.get("also_fetch_timeframes") or [])]

    if parser in ("none", None, ""):
        pairs = _parse_static_symbols(bcfg, exchange)
    else:
        root = Path(bcfg.get("path") or ".")
        if parser == "wip_fleet":
            pairs = _parse_wip_fleet(root, exchange)
        elif parser == "news_yaml":
            pairs = _parse_news_yaml(root, exchange)
        elif parser == "divergences_launch":
            pairs = _parse_divergences_launch(root, exchange)
        elif parser == "crypthor_services":
            pairs = _parse_crypthor(root, exchange)
        elif parser == "karmaa_config":
            pairs = _parse_karmaa(root, exchange)
        elif parser == "tsm_vpa_pack":
            pairs = _parse_tsm_vpa_pack(root, exchange)
        else:
            log.warning("Unknown parser %s for bot %s", parser, name)
            return []

    if also:
        extra: list[CandlePair] = []
        for p in pairs:
            for tf in also:
                if tf != p.timeframe:
                    extra.append(CandlePair(p.exchange, p.symbol, tf))
        pairs = pairs + extra
    # dedupe
    seen = set()
    out = []
    for p in pairs:
        if p.key() in seen:
            continue
        seen.add(p.key())
        out.append(p)
    return out


def _parse_static_symbols(bcfg: dict[str, Any], exchange: str) -> list[CandlePair]:
    """Registry-declared symbols/timeframe when parser is none (e.g. ld, xgb)."""
    symbols = bcfg.get("symbols") or []
    if not symbols:
        return []
    tf = normalize_timeframe(bcfg.get("timeframe") or "1h")
    ex = (bcfg.get("exchange") or exchange or "binance").lower()
    out: list[CandlePair] = []
    for s in symbols:
        sym = normalize_symbol(s)
        if sym:
            out.append(CandlePair(ex, sym, tf))
    return out


def _parse_wip_fleet(root: Path, exchange: str) -> list[CandlePair]:
    path = root / "config" / "live_fleet.json"
    if not path.exists():
        return []
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    ex = (data.get("exchange") or exchange).lower()
    out: list[CandlePair] = []
    seen: set[tuple[str, str, str]] = set()
    # Include active + stopped so shared candles stay available for research
    # even when the live fleet is fully decommissioned.
    for bot in list(data.get("bots") or []) + list(data.get("stopped") or []):
        sym = normalize_symbol(bot.get("symbol") or "")
        tf = normalize_timeframe(bot.get("timeframe") or "4h")
        if not sym:
            continue
        key = (ex, sym, tf)
        if key in seen:
            continue
        seen.add(key)
        out.append(CandlePair(ex, sym, tf))
    return out


def _parse_news_yaml(root: Path, exchange: str) -> list[CandlePair]:
    path = root / "config" / "default.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sym = normalize_symbol(data.get("symbol") or "BTCUSDT")
    tf = normalize_timeframe(data.get("interval") or "4h")
    return [CandlePair(exchange, sym, tf)]


def _parse_divergences_launch(root: Path, exchange: str) -> list[CandlePair]:
    path = root / "scripts" / "launch_all_bybit.sh"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    # Match lines like: "ETHUSDT 4h hidden_divergence_continuation bybit_ethusdt_4h_hidden"
    out = []
    for m in re.finditer(
        r'"([A-Z0-9]+)\s+(\d+[mhHdD]|[0-9]+m|[0-9]+h)\s+',
        text,
    ):
        sym = normalize_symbol(m.group(1))
        tf = normalize_timeframe(m.group(2))
        out.append(CandlePair(exchange, sym, tf))
    # Also accept BOTS array without requiring strategy token if pattern differs
    if not out:
        for m in re.finditer(r'"([A-Z]{2,}USDT)\s+(\d+h|\d+m)\s+', text):
            out.append(CandlePair(exchange, normalize_symbol(m.group(1)), normalize_timeframe(m.group(2))))
    return out


def _parse_crypthor(root: Path, exchange: str) -> list[CandlePair]:
    """Prefer active systemd units; else parse deploy/*.service; else oos configs referenced there."""
    pairs: list[CandlePair] = []
    service_files = list((root / "deploy").glob("crypthor-*.service"))
    # Which services are active?
    active_names = set()
    try:
        from botsgeneral.discover.process import list_systemd_units

        for u in list_systemd_units():
            if u.startswith("crypthor-") and u.endswith(".service"):
                active_names.add(u)
    except Exception:
        pass

    config_mods: list[str] = []

    # Prefer running processes
    try:
        from botsgeneral.discover.process import process_cmdline_blob

        blob = process_cmdline_blob()
        for m in re.finditer(r"--config\s+(crypthor\.config\.\S+)", blob):
            config_mods.append(m.group(1))
    except Exception:
        pass

    # Then active systemd units only (not every deploy/*.service on disk)
    if not config_mods and active_names:
        for sf in service_files:
            if sf.name not in active_names:
                continue
            text = sf.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"--config\s+(\S+)", text)
            if m:
                config_mods.append(m.group(1))

    if not config_mods:
        # fallback: known live fleet (not every research deploy unit)
        for name in ("btcusdt_mp_oos", "ethusdt_mp_oos", "bnbusdt_mp_oos", "solusdt_mp_oos"):
            config_mods.append(f"crypthor.config.{name}")

    seen = set()
    for mod in config_mods:
        if mod in seen:
            continue
        seen.add(mod)
        py_name = mod.split(".")[-1] + ".py"
        py_path = root / "crypthor" / "config" / py_name
        if not py_path.exists():
            continue
        text = py_path.read_text(encoding="utf-8", errors="ignore")
        sm = re.search(r'SYMBOL\s*=\s*["\'](\w+)["\']', text)
        tm = re.search(r'SOURCE_INTERVAL\s*=\s*["\']([^"\']+)["\']', text)
        if not sm:
            continue
        sym = normalize_symbol(sm.group(1))
        tf = normalize_timeframe(tm.group(1) if tm else "5m")
        pairs.append(CandlePair(exchange, sym, tf))
    return pairs


def _parse_karmaa(root: Path, exchange: str) -> list[CandlePair]:
    # Prefer live env symbol if present in process; else config module
    candidates = [
        root / "karmaa_mp" / "config" / "btcusdt_mp.py",
        root / "config" / "btcusdt_mp.py",
    ]
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        sm = re.search(r'SYMBOL\s*=\s*["\'](\w+)["\']', text)
        tm = re.search(r'SOURCE_INTERVAL\s*=\s*["\']([^"\']+)["\']', text)
        if sm:
            return [
                CandlePair(
                    exchange,
                    normalize_symbol(sm.group(1)),
                    normalize_timeframe(tm.group(1) if tm else "5m"),
                )
            ]
    return [CandlePair(exchange, "BTCUSDT", "5m")]


def _parse_tsm_vpa_pack(root: Path, exchange: str) -> list[CandlePair]:
    """Read live pack JSON: symbols + timeframe (default configs/live_top4_stack2_rr15_v1.json)."""
    import json

    candidates = [
        root / "configs" / "live_top4_stack2_rr15_v1.json",
        root / "config" / "live_pack.json",
    ]
    # Prefer any configs/live_*.json if default missing
    live_dir = root / "configs"
    if live_dir.is_dir():
        candidates.extend(sorted(live_dir.glob("live_*.json")))

    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    ex = (data.get("candles_exchange") or data.get("venue") or exchange or "bybit").lower()
    if ex in ("usdt_linear_perpetual", "bybit"):
        ex = "bybit"
    tf = normalize_timeframe(data.get("timeframe") or "1d")
    out: list[CandlePair] = []
    for sym in data.get("symbols") or []:
        s = normalize_symbol(str(sym))
        if s:
            out.append(CandlePair(ex, s, tf))
    return out
