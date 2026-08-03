"""Orchestrate price-structure + Fibonacci features for one OHLCV series."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .fibonacci import (
    FIB_ALL,
    FIB_RETRACEMENT,
    fib_label,
    fib_levels,
    levels_to_columns,
)
from .levels import Level, levels_frame, levels_from_swings, nearest_levels_at_bars
from .structure import (
    Leg,
    StructureEvent,
    build_legs,
    label_structure,
    legs_frame,
    structure_frame,
)
from .swings import Swing, find_swings, swings_frame

DEFAULT_SWING_LEFT = 2
DEFAULT_SWING_RIGHT = 2


@dataclass(frozen=True)
class StructureBundle:
    """Everything computed for one (source, symbol, timeframe) series."""

    source: str
    symbol: str
    timeframe: str
    swing_left: int
    swing_right: int
    swings: list[Swing]
    events: list[StructureEvent]
    legs: list[Leg]
    levels: list[Level]
    bar_features: pd.DataFrame
    ohlcv: pd.DataFrame

    @property
    def n_bars(self) -> int:
        return int(len(self.ohlcv))

    @property
    def n_swings(self) -> int:
        return int(len(self.swings))


def _as_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    need = {"ts_ms", "open", "high", "low", "close"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"OHLCV missing columns: {sorted(missing)}")
    out = df.sort_values("ts_ms").drop_duplicates("ts_ms", keep="last").reset_index(drop=True)
    return out


def compute_structure(
    ohlcv: pd.DataFrame,
    *,
    source: str = "",
    symbol: str = "",
    timeframe: str = "",
    swing_left: int = DEFAULT_SWING_LEFT,
    swing_right: int = DEFAULT_SWING_RIGHT,
) -> StructureBundle:
    """Compute confirmed swings, HH/HL structure, legs, fibs, S/R distances.

    All bar features are causal: a swing is visible only from its confirmation bar onward.
    """
    ohlcv = _as_ohlcv(ohlcv)
    ts = ohlcv["ts_ms"].to_numpy(dtype=np.int64)
    high = ohlcv["high"].to_numpy(dtype=float)
    low = ohlcv["low"].to_numpy(dtype=float)
    close = ohlcv["close"].to_numpy(dtype=float)

    swings = find_swings(high, low, ts, left=swing_left, right=swing_right)
    events = label_structure(swings)
    legs = build_legs(swings, events)
    levels = levels_from_swings(swings)
    sr = nearest_levels_at_bars(close, ts, levels)
    bars = _build_bar_features(
        ts_ms=ts,
        close=close,
        swings=swings,
        events=events,
        legs=legs,
        sr=sr,
    )
    return StructureBundle(
        source=source,
        symbol=symbol,
        timeframe=timeframe,
        swing_left=int(swing_left),
        swing_right=int(swing_right),
        swings=swings,
        events=events,
        legs=legs,
        levels=levels,
        bar_features=bars,
        ohlcv=ohlcv,
    )


def tables_from_bundle(bundle: StructureBundle) -> dict[str, pd.DataFrame]:
    """Named tables ready for SQLite upsert / program copy."""
    return {
        "swings": swings_frame(bundle.swings),
        "structure_events": structure_frame(bundle.events),
        "legs": legs_frame(bundle.legs),
        "levels": levels_frame(bundle.levels),
        "bar_features": bundle.bar_features,
    }


def _last_asof(
    event_ts: np.ndarray,
    event_values: np.ndarray,
    bar_ts: np.ndarray,
    *,
    fill=np.nan,
):
    """For each bar_ts, take the last event with event_ts <= bar_ts (vectorized)."""
    if len(event_ts) == 0:
        return np.full(len(bar_ts), fill)
    order = np.argsort(event_ts, kind="mergesort")
    ets = event_ts[order]
    evals = event_values[order]
    idx = np.searchsorted(ets, bar_ts, side="right") - 1
    out = np.full(len(bar_ts), fill, dtype=np.result_type(evals, type(fill)))
    ok = idx >= 0
    out[ok] = evals[idx[ok]]
    return out


def _build_bar_features(
    *,
    ts_ms: np.ndarray,
    close: np.ndarray,
    swings: list[Swing],
    events: list[StructureEvent],
    legs: list[Leg],
    sr: pd.DataFrame,
) -> pd.DataFrame:
    n = len(ts_ms)
    sh = [s for s in swings if s.kind == "high"]
    sl = [s for s in swings if s.kind == "low"]

    last_sh_price = _last_asof(
        np.asarray([s.confirm_ts_ms for s in sh], dtype=np.int64),
        np.asarray([s.price for s in sh], dtype=float),
        ts_ms,
    )
    last_sh_ts = _last_asof(
        np.asarray([s.confirm_ts_ms for s in sh], dtype=np.int64),
        np.asarray([s.pivot_ts_ms for s in sh], dtype=float),
        ts_ms,
    )
    last_sl_price = _last_asof(
        np.asarray([s.confirm_ts_ms for s in sl], dtype=np.int64),
        np.asarray([s.price for s in sl], dtype=float),
        ts_ms,
    )
    last_sl_ts = _last_asof(
        np.asarray([s.confirm_ts_ms for s in sl], dtype=np.int64),
        np.asarray([s.pivot_ts_ms for s in sl], dtype=float),
        ts_ms,
    )

    # Structure label + running bias via event asof + prefix counts.
    last_label = np.array([""] * n, dtype=object)
    structure_bias = np.zeros(n, dtype=np.int8)
    if events:
        ev_ts = np.asarray([e.ts_ms for e in events], dtype=np.int64)
        ev_lab = np.asarray([e.label for e in events], dtype=object)
        order = np.argsort(ev_ts, kind="mergesort")
        ev_ts = ev_ts[order]
        ev_lab = ev_lab[order]
        bull_delta = np.isin(ev_lab, ["HH", "HL"]).astype(np.int32)
        bear_delta = np.isin(ev_lab, ["LH", "LL"]).astype(np.int32)
        bull_c = np.cumsum(bull_delta)
        bear_c = np.cumsum(bear_delta)
        idx = np.searchsorted(ev_ts, ts_ms, side="right") - 1
        ok = idx >= 0
        last_label[ok] = ev_lab[idx[ok]]
        b = np.zeros(n, dtype=np.int32)
        r = np.zeros(n, dtype=np.int32)
        b[ok] = bull_c[idx[ok]]
        r[ok] = bear_c[idx[ok]]
        structure_bias = np.sign(b - r).astype(np.int8)

    # Legs known when end swing is confirmed.
    swing_confirm = {s.swing_id: s.confirm_ts_ms for s in swings}
    last_leg_dir = np.array([""] * n, dtype=object)
    last_leg_kind = np.array([""] * n, dtype=object)
    last_leg_len = np.full(n, np.nan)
    last_retrace = np.full(n, np.nan)
    last_retrace_fib = np.array([""] * n, dtype=object)
    fib_cols = {f"fib_{fib_label(r).replace('.', '')}": np.full(n, np.nan) for r in FIB_ALL}
    dist_fib = {
        f"dist_fib_{fib_label(r).replace('.', '')}_pct": np.full(n, np.nan)
        for r in FIB_RETRACEMENT
    }

    if legs:
        known_ts = np.asarray(
            [
                max(
                    swing_confirm.get(lg.start_swing_id, lg.end_ts_ms),
                    swing_confirm.get(lg.end_swing_id, lg.end_ts_ms),
                )
                for lg in legs
            ],
            dtype=np.int64,
        )
        order = np.argsort(known_ts, kind="mergesort")
        known_ts = known_ts[order]
        legs_o = [legs[i] for i in order.tolist()]
        idx = np.searchsorted(known_ts, ts_ms, side="right") - 1

        # Precompute fib maps per leg.
        fib_maps = [
            levels_to_columns(fib_levels(lg.start_price, lg.end_price, FIB_ALL))
            for lg in legs_o
        ]
        dirs = np.asarray([lg.direction for lg in legs_o], dtype=object)
        kinds = np.asarray([lg.kind for lg in legs_o], dtype=object)
        lens = np.asarray([lg.length_pct for lg in legs_o], dtype=float)
        retr = np.asarray([lg.retrace_pct for lg in legs_o], dtype=float)
        flab = np.asarray([lg.fib_label for lg in legs_o], dtype=object)

        ok = idx >= 0
        last_leg_dir[ok] = dirs[idx[ok]]
        last_leg_kind[ok] = kinds[idx[ok]]
        last_leg_len[ok] = lens[idx[ok]]
        last_retrace[ok] = retr[idx[ok]]
        last_retrace_fib[ok] = flab[idx[ok]]

        # Fill fib columns by contiguous as-of segments (not per-leg full-array masks).
        n_legs = len(legs_o)
        for li in range(n_legs):
            lo = int(np.searchsorted(ts_ms, known_ts[li], side="left"))
            hi = (
                int(np.searchsorted(ts_ms, known_ts[li + 1], side="left"))
                if li + 1 < n_legs
                else n
            )
            if hi <= lo:
                continue
            fmap = fib_maps[li]
            for k, v in fmap.items():
                if k in fib_cols:
                    fib_cols[k][lo:hi] = v
            cslice = close[lo:hi]
            for r in FIB_RETRACEMENT:
                key = f"fib_{fib_label(r).replace('.', '')}"
                dkey = f"dist_fib_{fib_label(r).replace('.', '')}_pct"
                if key in fmap:
                    dist_fib[dkey][lo:hi] = (fmap[key] - cslice) / cslice

    dist_sh = (close - last_sh_price) / close
    dist_sl = (close - last_sl_price) / close

    data: dict[str, Any] = {
        "ts_ms": ts_ms,
        "close": close,
        "last_sh_price": last_sh_price,
        "last_sh_ts_ms": last_sh_ts,
        "dist_last_sh_pct": dist_sh,
        "last_sl_price": last_sl_price,
        "last_sl_ts_ms": last_sl_ts,
        "dist_last_sl_pct": dist_sl,
        "structure_bias": structure_bias,
        "last_structure_label": last_label,
        "last_leg_dir": last_leg_dir,
        "last_leg_kind": last_leg_kind,
        "last_leg_len_pct": last_leg_len,
        "last_retrace_pct": last_retrace,
        "last_retrace_fib": last_retrace_fib,
    }
    data.update(fib_cols)
    data.update(dist_fib)
    data.update(
        {
            "nearest_support": sr["nearest_support"].to_numpy(),
            "nearest_resistance": sr["nearest_resistance"].to_numpy(),
            "dist_support_pct": sr["dist_support_pct"].to_numpy(),
            "dist_resistance_pct": sr["dist_resistance_pct"].to_numpy(),
        }
    )
    return pd.DataFrame(data)
