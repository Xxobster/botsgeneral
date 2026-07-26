"""Signed historical funding applied at each settlement inside the holding window.

Convention for a linear perpetual::

    cashflow = -side * position_value_at_mark * funding_rate

so a positive rate is paid by the long and received by the short. Never ``abs(rate)``,
never an always-pay approximation, never a post-simulation overlay: funding moves the
wallet chronologically, which means it can change a later liquidation.

Holding window. A position exists over ``[entry_ms, exit_effective_ms)``. When the exit
is resolved only to a bar, the instant inside that bar at which it happened is unknown,
so ``exit_effective_ms`` defaults to the END of the bar that closed it. That is the
adverse-cost reading of the ambiguity, and it is what makes a same-bar round trip pay the
settlements inside its own bar (EXEC-015) instead of paying nothing because
``entry_ms == exit_ms``. With touch bars the exit resolves to a sub-bar, so the window
tightens automatically. Setting ``funding_exit_boundary="bar_start"`` selects the exact
half-open ``[entry, exit)`` reading instead, which undercharges same-bar round trips.

Mark price at a settlement. If a settlement lands exactly on a bar's open timestamp, that
open IS the price at that instant and is used. Otherwise the containing bar's close is
used as an approximation and the result records that funding marks were approximated.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FundingSchedule:
    """Settlement timestamps and signed rates, sorted and de-duplicated."""

    ts_ms: np.ndarray
    rate: np.ndarray

    @classmethod
    def build(
        cls, ts_ms: np.ndarray | None, rate: np.ndarray | None
    ) -> "FundingSchedule":
        if ts_ms is None or rate is None or len(ts_ms) == 0:
            return cls(np.empty(0, dtype=np.int64), np.empty(0, dtype=float))
        ts = np.asarray(ts_ms, dtype=np.int64)
        rt = np.asarray(rate, dtype=float)
        if len(ts) != len(rt):
            raise ValueError("funding timestamps and rates have different lengths")
        order = np.argsort(ts, kind="stable")
        ts, rt = ts[order], rt[order]
        uniq, counts = np.unique(ts, return_counts=True)
        if len(uniq) != len(ts):
            dupes = uniq[counts > 1][:5].tolist()
            raise ValueError(
                f"duplicate funding settlement timestamps: {dupes} — each settlement is "
                "charged exactly once, so the input must not contain duplicates"
            )
        if not np.all(np.isfinite(rt)):
            raise ValueError("funding rates contain non-finite values")
        return cls(ts, rt)

    def __len__(self) -> int:
        return int(len(self.ts_ms))

    @property
    def empty(self) -> bool:
        return len(self.ts_ms) == 0

    def settlements_in(self, start_ms: int, end_ms: int) -> tuple[np.ndarray, np.ndarray]:
        """Settlements in the half-open window ``[start_ms, end_ms)``."""
        if self.empty or end_ms <= start_ms:
            return np.empty(0, dtype=np.int64), np.empty(0, dtype=float)
        lo = int(np.searchsorted(self.ts_ms, start_ms, side="left"))
        hi = int(np.searchsorted(self.ts_ms, end_ms, side="left"))
        return self.ts_ms[lo:hi], self.rate[lo:hi]


def funding_cashflow(*, side: int, qty: float, mark_price: float, rate: float) -> float:
    """Signed cash movement for one settlement. Negative means the position pays."""
    return -float(side) * abs(float(qty)) * float(mark_price) * float(rate)


def mark_at_settlement(
    settlement_ts: int,
    bar_ts_ms: np.ndarray,
    bar_open: np.ndarray,
    bar_close: np.ndarray,
    timeframe_ms: int,
) -> tuple[float, bool]:
    """Return ``(mark, exact)`` for a settlement timestamp.

    ``exact`` is False when the settlement falls strictly inside a bar and the close had
    to stand in for the price at that instant.
    """
    idx = int(np.searchsorted(bar_ts_ms, settlement_ts, side="right")) - 1
    if idx < 0:
        return float(bar_open[0]), False
    if int(bar_ts_ms[idx]) == int(settlement_ts):
        return float(bar_open[idx]), True
    if settlement_ts >= int(bar_ts_ms[idx]) + timeframe_ms:
        return float(bar_close[idx]), False
    return float(bar_close[idx]), False


def holding_window_end(
    exit_bar_ts_ms: int, exit_interval_ms: int, boundary: str
) -> int:
    """Exclusive end of the holding window for funding purposes."""
    if boundary == "bar_start":
        return int(exit_bar_ts_ms)
    if boundary != "bar_end":
        raise ValueError(
            f"funding_exit_boundary must be 'bar_end' or 'bar_start', got {boundary!r}"
        )
    return int(exit_bar_ts_ms) + int(exit_interval_ms)
