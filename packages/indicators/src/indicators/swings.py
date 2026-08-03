"""Confirmed swing highs and lows (fractal pivots with right-side confirmation).

A swing high at index ``i`` requires ``high[i]`` to be the unique maximum of
``high[i-left : i+right+1]``, and the bar at ``i+right`` must already be closed
before the pivot is treated as known (causality). Same for swing lows on ``low``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view


@dataclass(frozen=True)
class Swing:
    swing_id: int
    kind: str  # "high" | "low"
    pivot_i: int
    confirm_i: int
    pivot_ts_ms: int
    confirm_ts_ms: int
    price: float


def find_swings(
    high: np.ndarray,
    low: np.ndarray,
    ts_ms: np.ndarray,
    *,
    left: int = 2,
    right: int = 2,
) -> list[Swing]:
    """Detect confirmed fractal swings (vectorized window extrema)."""
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    t = np.asarray(ts_ms, dtype=np.int64)
    n = len(h)
    if n == 0 or left < 1 or right < 1:
        return []
    if len(l) != n or len(t) != n:
        raise ValueError("high/low/ts_ms length mismatch")

    win = left + right + 1
    if n < win:
        return []

    wh = sliding_window_view(h, win)
    wl = sliding_window_view(l, win)
    center = left
    # Each row of wh corresponds to pivot candidate at index = row_start + left
    # row_start runs 0 .. n-win → pivot index left .. n-right-1
    h_c = wh[:, center]
    l_c = wl[:, center]
    is_sh_w = (h_c == wh.max(axis=1)) & (np.sum(wh == h_c[:, None], axis=1) == 1)
    is_sl_w = (l_c == wl.min(axis=1)) & (np.sum(wl == l_c[:, None], axis=1) == 1)

    pivots = np.arange(left, left + len(is_sh_w))
    swings: list[Swing] = []
    sid = 0
    for p, sh, sl in zip(pivots.tolist(), is_sh_w.tolist(), is_sl_w.tolist()):
        confirm_i = p + right
        if confirm_i >= n:
            continue
        if sh:
            swings.append(
                Swing(
                    swing_id=sid,
                    kind="high",
                    pivot_i=p,
                    confirm_i=confirm_i,
                    pivot_ts_ms=int(t[p]),
                    confirm_ts_ms=int(t[confirm_i]),
                    price=float(h[p]),
                )
            )
            sid += 1
        if sl:
            swings.append(
                Swing(
                    swing_id=sid,
                    kind="low",
                    pivot_i=p,
                    confirm_i=confirm_i,
                    pivot_ts_ms=int(t[p]),
                    confirm_ts_ms=int(t[confirm_i]),
                    price=float(l[p]),
                )
            )
            sid += 1

    swings.sort(key=lambda s: (s.confirm_i, s.pivot_i, 0 if s.kind == "low" else 1))
    return [
        Swing(
            swing_id=i,
            kind=s.kind,
            pivot_i=s.pivot_i,
            confirm_i=s.confirm_i,
            pivot_ts_ms=s.pivot_ts_ms,
            confirm_ts_ms=s.confirm_ts_ms,
            price=s.price,
        )
        for i, s in enumerate(swings)
    ]


def swings_frame(swings: list[Swing]) -> pd.DataFrame:
    if not swings:
        return pd.DataFrame(
            columns=[
                "swing_id",
                "kind",
                "pivot_i",
                "confirm_i",
                "pivot_ts_ms",
                "confirm_ts_ms",
                "price",
            ]
        )
    return pd.DataFrame(
        [
            {
                "swing_id": s.swing_id,
                "kind": s.kind,
                "pivot_i": s.pivot_i,
                "confirm_i": s.confirm_i,
                "pivot_ts_ms": s.pivot_ts_ms,
                "confirm_ts_ms": s.confirm_ts_ms,
                "price": s.price,
            }
            for s in swings
        ]
    )
