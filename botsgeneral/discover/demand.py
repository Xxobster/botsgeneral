"""Runtime candle demand: only pairs that *running* bots on this host need."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from botsgeneral.models import CandlePair, normalize_symbol, normalize_timeframe

log = logging.getLogger(__name__)

_PACK_RE = re.compile(r"--pack(?:\s+|=)(\S+)", re.IGNORECASE)
_SYMBOL_RE = re.compile(r"--symbol(?:\s+|=)(\S+)", re.IGNORECASE)


def pack_pairs_from_strategy(path: Path) -> list[CandlePair]:
    """Read one frozen pack ``strategy.json`` (or a pack dir)."""
    strat_path = path if path.name == "strategy.json" else path / "strategy.json"
    if not strat_path.is_file():
        return []
    try:
        data = json.loads(strat_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("pack read failed %s: %s", strat_path, exc)
        return []
    sym = normalize_symbol(str(data.get("symbol") or ""))
    tf = normalize_timeframe(str(data.get("timeframe") or ""))
    if not sym or not tf:
        return []
    src = str(data.get("signal_source") or data.get("exchange") or "binance").lower()
    if src in ("bybit", "binance"):
        ex = src
    else:
        ex = "binance"
    return [CandlePair(ex, sym, tf)]


def pairs_from_running_packs(proc_blob: str) -> list[CandlePair]:
    """Any ``--pack /path`` on a live command line → that pack's symbol/timeframe."""
    out: list[CandlePair] = []
    seen: set[tuple[str, str, str]] = set()
    for m in _PACK_RE.finditer(proc_blob or ""):
        raw = m.group(1).strip().strip("\"'")
        for p in pack_pairs_from_strategy(Path(raw)):
            if p.key() in seen:
                continue
            seen.add(p.key())
            out.append(p)
    return out


def symbols_from_cmdline(proc_blob: str, *, path_token: str = "") -> set[str]:
    """Symbols from ``--symbol`` flags. If ``path_token`` is set, only those lines."""
    found = set()
    blob = proc_blob or ""
    chunks = blob.splitlines() if path_token else [blob]
    token = path_token.replace("\\", "/").rstrip("/")
    for chunk in chunks:
        hay = chunk.replace("\\", "/")
        if token and token not in hay:
            continue
        for m in _SYMBOL_RE.finditer(chunk):
            s = normalize_symbol(m.group(1))
            if s:
                found.add(s)
    return found


def local_pack_pairs(roots: list[Path]) -> list[CandlePair]:
    """Scan live pack trees on this machine (local collector / backtest prep)."""
    out: list[CandlePair] = []
    seen: set[tuple[str, str, str]] = set()
    for root in roots:
        if not root.exists():
            continue
        for strat in root.rglob("strategy.json"):
            # skip tests / tmp
            parts = {x.lower() for x in strat.parts}
            if parts & {"tests", "__pycache__", ".git"}:
                continue
            for p in pack_pairs_from_strategy(strat):
                if p.key() in seen:
                    continue
                seen.add(p.key())
                out.append(p)
    return out


def refine_bot_pairs(
    *,
    name: str,
    bcfg: dict[str, Any],
    pairs: list[CandlePair],
    proc_blob: str,
    vps_id: str | None,
) -> list[CandlePair]:
    """Replace or narrow static registry pairs using the live process list."""
    pack_pairs = pairs_from_running_packs(proc_blob)
    if name in {"llm2", "llm2_pivot"} and pack_pairs:
        # Pivot/structure packs on the command line are the truth — do not also
        # pull 4h/1w leftovers from the static llm2 stanza.
        return pack_pairs

    if vps_id == "local":
        roots = [Path(x) for x in (bcfg.get("local_pack_roots") or [])]
        if roots:
            local = local_pack_pairs(roots)
            if local:
                return local

    path = str(bcfg.get("path") or "")
    running_syms = symbols_from_cmdline(proc_blob, path_token=path)
    if running_syms:
        narrowed = [p for p in pairs if p.symbol in running_syms]
        if narrowed:
            return narrowed
    return pairs


# Bot must have at least this many closed bars in the shared DB. Not "max
# exchange history". If the pack/bot needs 3000, we fetch 3000 — always.
TF_MIN_HISTORY = {
    "5m": 5_000,
    "15m": 3_000,
    "1h": 500,
    "2h": 400,
    "4h": 500,
    "1d": 400,
    "1w": 200,
}


def required_history_bars(
    bcfg: dict[str, Any] | None,
    timeframe: str,
    *,
    pack_need: int | None = None,
) -> int:
    """Closed bars the live bot needs on this timeframe (max of bot/pack/tf)."""
    tf = normalize_timeframe(timeframe)
    need = int(TF_MIN_HISTORY.get(tf, 500))
    if bcfg:
        per_tf = bcfg.get("min_history_bars_by_tf") or {}
        if tf in per_tf:
            need = max(need, int(per_tf[tf]))
        elif bcfg.get("min_history_bars") not in (None, ""):
            need = max(need, int(bcfg["min_history_bars"]))
    if pack_need not in (None, ""):
        need = max(need, int(pack_need))
    return max(int(need), 1)


def required_bars_by_pair(
    items: list[tuple[CandlePair, str]],
    registry: dict[str, Any],
) -> dict[tuple[str, str, str], int]:
    """Max required history per series when several bots share it."""
    bots = registry.get("bots") or {}
    out: dict[tuple[str, str, str], int] = {}
    for pair, name in items:
        bcfg = bots.get(name) or {}
        n = required_history_bars(bcfg, pair.timeframe)
        key = pair.key()
        out[key] = max(out.get(key, 0), n)
    return out
