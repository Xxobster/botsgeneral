"""Shared translation helpers for grading foreign engines.

These adapters live outside the installed ``tradesim`` distribution on purpose. They are
graders, not products: they exist so the baseline in
``docs/project_memory/ENGINE_CONFORMANCE_BASELINE.md`` is measured rather than asserted,
and they reach into three repositories that will never be dependencies of tradesim.

Two principles govern every adapter here.

*Give the engine its best case.* Where a foreign engine wants a percentage bracket and the
fixture states an absolute price, the adapter computes the percentage that reproduces the
fixture's price at the fill the engine will actually take. Where it wants an instrument
table entry, the adapter registers the fixture's instrument. A failure must be the
engine's behaviour, not the adapter's laziness.

*Decline honestly.* When an engine has no concept a fixture requires — multi-leg exits, a
shared wallet, cross margin — :meth:`supports` returns ``False`` with the reason.
``UNSUPPORTED`` is reported separately from ``PASS`` and never counts as one.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from tradesim.conformance.adapter import NormalisedResult, NormalisedTrade
from tradesim.conformance.fixture_loader import Fixture

XGB_ROOT = Path(r"C:\projects\xgb")
LLM1_ROOT = Path(r"D:\projects\LLM1\src")
TSMVPA_ROOT = Path(r"D:\projects\TSM-VPA\src")


def ensure_path(root: Path) -> None:
    text = str(root)
    if text not in sys.path:
        sys.path.insert(0, text)


# --------------------------------------------------------------------------------------
# Fixture reading
# --------------------------------------------------------------------------------------


class Case:
    """The subset of a simulation fixture the three foreign engines can even see.

    None of them accept the full contract, so this deliberately exposes only single
    symbol, single signal, absolute stop and target, one funding series.
    """

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.instrument = dict(payload["instrument"])
        self.costs = dict(payload["costs"])
        self.margin = dict(payload["margin"])
        self.sizing = dict(payload["sizing"])
        self.sim = dict(payload["sim"])
        self.bars: list[list[float]] = list(payload["bars"]["rows"])
        self.timeframe_ms = int(payload["bars"]["timeframe_ms"])
        touch = payload.get("touch_bars") or None
        self.touch_rows: list[list[float]] | None = (
            list(touch["rows"]) if touch and touch.get("rows") else None
        )
        self.touch_tf_ms = int(touch["timeframe_ms"]) if touch else 0
        self.signals: list[dict[str, Any]] = [dict(s) for s in (payload.get("signals") or [])]
        self.funding: list[list[float]] = [list(r) for r in (payload.get("funding") or [])]

    # -- convenience ---------------------------------------------------------------

    @property
    def signal(self) -> dict[str, Any]:
        return self.signals[0]

    @property
    def symbol(self) -> str:
        return str(self.instrument["symbol"])

    @property
    def tick(self) -> float:
        return float(self.instrument["tick_size"])

    @property
    def taker(self) -> float:
        return float(self.costs.get("taker_rate", 0.0))

    @property
    def entry_slip(self) -> float:
        return float(self.costs.get("entry_slippage", 0.0))

    @property
    def market_exit_slip(self) -> float:
        return float(self.costs.get("market_exit_slippage", 0.0))

    @property
    def leverage(self) -> float:
        return float(self.margin.get("leverage", 1.0))

    @property
    def starting_equity(self) -> float:
        return float(self.sim.get("starting_equity", 10_000.0))

    def bar_index_of(self, ts_ms: int) -> int:
        for i, row in enumerate(self.bars):
            if int(row[0]) == int(ts_ms):
                return i
        raise KeyError(f"no bar at ts {ts_ms}")

    def entry_bar_index(self) -> int:
        """The bar a next-open engine fills on: the one after the signal bar."""
        return self.bar_index_of(int(self.signal["ts_ms"])) + 1

    def expected_fill(self) -> float:
        """The fill price a correct next-open engine produces, rounded to tick."""
        i = self.entry_bar_index()
        side = int(self.signal["side"])
        raw = float(self.bars[i][1]) * (1.0 + side * self.entry_slip)
        return round_to_tick(raw, self.tick)

    def brackets(self) -> tuple[float | None, float | None]:
        """Absolute stop and target, resolving the fraction-offset form if used."""
        side = int(self.signal["side"])
        fill = self.expected_fill()
        stop = self.signal.get("stop_price")
        if stop is None and self.signal.get("stop_offset") is not None:
            stop = fill * (1.0 - side * float(self.signal["stop_offset"]))
        target = self.signal.get("target_price")
        if target is None and self.signal.get("target_offset") is not None:
            target = fill * (1.0 + side * float(self.signal["target_offset"]))
        return (
            round_to_tick(float(stop), self.tick) if stop is not None else None,
            round_to_tick(float(target), self.tick) if target is not None else None,
        )

    def has_stop(self) -> bool:
        return (
            self.signal.get("stop_price") is not None
            or self.signal.get("stop_offset") is not None
        )

    def has_target(self) -> bool:
        return (
            self.signal.get("target_price") is not None
            or self.signal.get("target_offset") is not None
        )

    def bracket_fracs(self) -> tuple[float, float]:
        """Stop and target as positive fractions of the fill, for percentage engines."""
        stop, target = self.brackets()
        fill = self.expected_fill()
        sl = abs(fill - float(stop)) / fill if stop is not None else 1.0
        tp = abs(float(target) - fill) / fill if target is not None else 1.0
        return tp, sl

    def qty(self) -> float:
        mode = str(self.sizing.get("mode", "fixed_qty"))
        if mode == "fixed_qty":
            return float(self.sizing["fixed_qty"])
        if mode == "fixed_notional":
            return float(self.sizing["fixed_notional"]) / self.expected_fill()
        stop, _ = self.brackets()
        risk_cash = self.starting_equity * float(self.sizing["risk_fraction"])
        return risk_cash / abs(self.expected_fill() - float(stop))

    def max_hold_bars(self) -> int | None:
        value = self.signal.get("max_hold_bars", self.sim.get("max_hold_bars"))
        return int(value) if value is not None else None


def round_to_tick(price: float, tick: float) -> float:
    if tick <= 0:
        return float(price)
    n = float(price) / tick
    eps = 1e-9 * max(1.0, abs(n))
    return round(math.floor(n + 0.5 + eps) * tick, 12)


# --------------------------------------------------------------------------------------
# Capability gate shared by all three
# --------------------------------------------------------------------------------------

#: Fixture features none of the three legacy engines model. Declining these is not a
#: mark against the adapter; it is the capability half of the baseline.
def unsupported_reason(fixture: Fixture, *, capabilities: Sequence[str]) -> str:
    payload = fixture.payload
    if fixture.kind == "portfolio":
        if "portfolio" not in capabilities:
            return "engine simulates one symbol at a time; no shared wallet"
        return ""
    if fixture.kind == "metrics":
        if "metrics" not in capabilities:
            return "engine ships no authoritative metric implementation to grade"
        return ""
    if fixture.kind != "simulation":
        return f"unknown fixture kind {fixture.kind!r}"

    signals = payload.get("signals") or []
    if not signals:
        return "fixture has no signal for a single-position engine to take"
    if len(signals) > 1 and "sequential_signals" not in capabilities:
        return "engine takes one signal per run"
    first = signals[0]
    if first.get("tp_legs") and "multi_leg" not in capabilities:
        return "engine has no partial take-profit legs"
    if first.get("trail") and "trailing" not in capabilities:
        return "engine has no trailing stop"
    if first.get("break_even") and "break_even" not in capabilities:
        return "engine has no break-even stop"
    if payload.get("margin", {}).get("mode") == "cross" and "cross" not in capabilities:
        return "engine models isolated margin only"
    if payload.get("sim", {}).get("entry_ref") not in (None, "next_open"):
        if "entry_ref" not in capabilities:
            return "engine fills at the next open and nowhere else"
    if not payload.get("bars", {}).get("rows"):
        return "fixture supplies no bars"
    return ""


# --------------------------------------------------------------------------------------
# Result construction
# --------------------------------------------------------------------------------------

ENTRY_BAR_SUFFIX = "_entry_bar"


def normalised(
    trades: list[NormalisedTrade],
    *,
    starting_equity: float,
    ending_equity: float,
    liquidation_status: str,
    skip_counts: Mapping[str, int] | None = None,
    warnings: Sequence[str] = (),
    summary: Mapping[str, Any] | None = None,
    n_funding_charges: int = 0,
    fill_rates: Sequence[float] = (),
) -> NormalisedResult:
    base_summary = {
        "entry_bar_exits": sum(1 for t in trades if t.entry_bar_exit),
        "ambiguous_intrabar": sum(1 for t in trades if t.ambiguous),
        "n_trades": len(trades),
    }
    base_summary.update(dict(summary or {}))
    return NormalisedResult(
        trades=trades,
        skip_counts=dict(skip_counts or {}),
        starting_equity=starting_equity,
        ending_equity=ending_equity,
        liquidation_status=liquidation_status,
        warnings=list(warnings),
        summary=base_summary,
        fill_rates=list(fill_rates),
        n_funding_charges=n_funding_charges,
        total_fees=sum(t.fees for t in trades),
        total_funding=sum(t.funding for t in trades),
        total_gross_pnl=sum(t.gross_pnl for t in trades),
    )
