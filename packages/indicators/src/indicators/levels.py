"""Confirmed support / resistance from swing highs and lows + distance helpers."""

from __future__ import annotations

import bisect
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .swings import Swing


@dataclass(frozen=True)
class Level:
    level_id: int
    kind: str  # support | resistance
    price: float
    origin_swing_id: int
    origin_ts_ms: int
    confirm_ts_ms: int


def levels_from_swings(swings: list[Swing]) -> list[Level]:
    """Every confirmed swing low is support; every confirmed swing high is resistance."""
    out: list[Level] = []
    for i, s in enumerate(swings):
        out.append(
            Level(
                level_id=i,
                kind="resistance" if s.kind == "high" else "support",
                price=s.price,
                origin_swing_id=s.swing_id,
                origin_ts_ms=s.pivot_ts_ms,
                confirm_ts_ms=s.confirm_ts_ms,
            )
        )
    return out


def levels_frame(levels: list[Level]) -> pd.DataFrame:
    if not levels:
        return pd.DataFrame(
            columns=[
                "level_id",
                "kind",
                "price",
                "origin_swing_id",
                "origin_ts_ms",
                "confirm_ts_ms",
            ]
        )
    return pd.DataFrame(
        [
            {
                "level_id": lv.level_id,
                "kind": lv.kind,
                "price": lv.price,
                "origin_swing_id": lv.origin_swing_id,
                "origin_ts_ms": lv.origin_ts_ms,
                "confirm_ts_ms": lv.confirm_ts_ms,
            }
            for lv in levels
        ]
    )


def nearest_levels_at_bars(
    close: np.ndarray,
    ts_ms: np.ndarray,
    levels: list[Level],
) -> pd.DataFrame:
    """For each bar, nearest confirmed support below and resistance above.

    Only levels whose ``confirm_ts_ms <= bar.ts_ms`` are visible (causal).
    """
    n = len(close)
    nearest_sup = np.full(n, np.nan)
    nearest_res = np.full(n, np.nan)
    dist_sup = np.full(n, np.nan)
    dist_res = np.full(n, np.nan)
    if not levels or n == 0:
        return pd.DataFrame(
            {
                "nearest_support": nearest_sup,
                "nearest_resistance": nearest_res,
                "dist_support_pct": dist_sup,
                "dist_resistance_pct": dist_res,
            }
        )

    ordered = sorted(levels, key=lambda lv: lv.confirm_ts_ms)
    supports: list[float] = []
    resistances: list[float] = []
    j = 0
    m = len(ordered)
    for i in range(n):
        t = int(ts_ms[i])
        c = float(close[i])
        while j < m and ordered[j].confirm_ts_ms <= t:
            lv = ordered[j]
            if lv.kind == "support":
                bisect.insort(supports, lv.price)
            else:
                bisect.insort(resistances, lv.price)
            j += 1
        if supports:
            idx = bisect.bisect_right(supports, c) - 1
            if idx >= 0:
                s = supports[idx]
                nearest_sup[i] = s
                dist_sup[i] = (c - s) / c if c else np.nan
        if resistances:
            idx = bisect.bisect_left(resistances, c)
            if idx < len(resistances):
                r = resistances[idx]
                nearest_res[i] = r
                dist_res[i] = (r - c) / c if c else np.nan

    return pd.DataFrame(
        {
            "nearest_support": nearest_sup,
            "nearest_resistance": nearest_res,
            "dist_support_pct": dist_sup,
            "dist_resistance_pct": dist_res,
        }
    )
