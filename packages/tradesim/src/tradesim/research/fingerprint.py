"""Content fingerprints so a saved run can prove it matches the same data."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

import numpy as np

from ..contracts import BarSeries, SimResult, Trade
from ..version import ENGINE_NAME, ENGINE_VERSION, RESULT_SCHEMA_VERSION


def bars_fingerprint(bars: BarSeries) -> str:
    """Stable hash of symbol + timeframe + OHLC(V) arrays (open times included)."""
    h = hashlib.sha256()
    h.update(str(getattr(bars, "symbol", "") or "").encode())
    h.update(b"|")
    h.update(str(int(bars.timeframe_ms)).encode())
    h.update(b"|")
    h.update(np.asarray(bars.ts_ms, dtype=np.int64).tobytes())
    for arr in (bars.open, bars.high, bars.low, bars.close):
        h.update(np.asarray(arr, dtype=np.float64).tobytes())
    if bars.volume is not None:
        h.update(np.asarray(bars.volume, dtype=np.float64).tobytes())
    return h.hexdigest()


def trades_fingerprint(trades: Sequence[Trade]) -> str:
    h = hashlib.sha256()
    for t in trades:
        h.update(
            f"{t.trade_id}|{t.side}|{t.entry_ts_ms}|{t.exit_ts_ms}|"
            f"{t.entry_price:.10g}|{t.exit_price:.10g}|{t.qty:.10g}|"
            f"{t.stop_price:.10g}|{t.target_price}|{t.realized_pnl:.10g}|"
            f"{t.exit_reason}".encode()
        )
    return h.hexdigest()


def run_fingerprint(
    *,
    bars: BarSeries,
    result: SimResult,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """One digest identifying engine + bars + trades + wallet + optional notes.

    Two saves with the same ``run_fingerprint`` are the same chartable run
    (same candles, same fills, same engine identity). Compare this string when
    reloading to confirm you opened the exact artifact you expect.
    """
    payload = {
        "engine": ENGINE_NAME,
        "engine_version": ENGINE_VERSION,
        "result_schema": RESULT_SCHEMA_VERSION,
        "bars_fp": bars_fingerprint(bars),
        "trades_fp": trades_fingerprint(result.trades),
        "starting_equity": float(result.starting_equity),
        "ending_equity": float(result.ending_equity),
        "config_digest": result.config_digest,
        "n_trades": len(result.trades),
        "extra": dict(extra or {}),
    }
    raw = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def short_id(fp: str, n: int = 12) -> str:
    return fp[:n]
