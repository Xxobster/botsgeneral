"""Shared builders for the conformance suite.

Every helper here keeps the arithmetic trivial so an assertion can be checked by hand:
entry at 100.00, quantity 1.0, taker 0.1%, one-minute bars starting at t=0.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pytest

from tradesim import (
    BarSeries,
    BreakEvenConfig,
    CostConfig,
    InstrumentSpec,
    MarginConfig,
    MarginMode,
    Side,
    Signal,
    SimConfig,
    SizingConfig,
    SizingMode,
    TakeProfitLeg,
    TrailConfig,
    simulate,
)

TF = 60_000
SIGNAL_BAR = [0, 100.0, 100.0, 100.0, 100.0]
QUIET_BAR_1 = [TF, 100.0, 101.0, 99.0, 100.0]


@pytest.fixture
def instrument() -> InstrumentSpec:
    return InstrumentSpec(
        symbol="TESTUSDT",
        tick_size=0.01,
        qty_step=0.001,
        min_qty=0.001,
        min_notional=1.0,
        max_leverage=100.0,
        maintenance_rate=0.005,
        funding_interval_ms=28_800_000,
    )


@pytest.fixture
def costs() -> CostConfig:
    return CostConfig(
        taker_rate=0.001,
        maker_rate=0.0004,
        entry_slippage=0.0,
        market_exit_slippage=0.0,
    )


@pytest.fixture
def margin() -> MarginConfig:
    return MarginConfig(mode=MarginMode.ISOLATED, leverage=10.0)


@pytest.fixture
def sizing() -> SizingConfig:
    return SizingConfig(mode=SizingMode.FIXED_QTY, fixed_qty=1.0)


@pytest.fixture
def sim() -> SimConfig:
    return SimConfig(starting_equity=10_000.0, decision_timeframe="1m")


def bars(
    rows: Sequence[Sequence[float]], timeframe_ms: int = TF, symbol: str = "TESTUSDT"
) -> BarSeries:
    return BarSeries.from_rows(rows, timeframe_ms, symbol=symbol)


def _coerce(kw: dict[str, Any]) -> dict[str, Any]:
    """Let a test write ``trail={"distance": 0.02}`` instead of importing three classes."""
    if isinstance(kw.get("trail"), dict):
        kw["trail"] = TrailConfig(**kw["trail"])
    if isinstance(kw.get("break_even"), dict):
        kw["break_even"] = BreakEvenConfig(**kw["break_even"])
    legs = kw.get("tp_legs")
    if legs:
        kw["tp_legs"] = tuple(
            TakeProfitLeg(**leg) if isinstance(leg, dict) else leg for leg in legs
        )
    return kw


def long_signal(
    ts_ms: int = 0, stop: float = 95.0, target: float | None = 110.0, **kw: Any
) -> Signal:
    return Signal(
        ts_ms=ts_ms,
        side=Side.LONG,
        symbol="TESTUSDT",
        stop_price=stop,
        target_price=target,
        **_coerce(kw),
    )


def short_signal(
    ts_ms: int = 0, stop: float = 105.0, target: float | None = 90.0, **kw: Any
) -> Signal:
    return Signal(
        ts_ms=ts_ms,
        side=Side.SHORT,
        symbol="TESTUSDT",
        stop_price=stop,
        target_price=target,
        **_coerce(kw),
    )


def run(
    rows,
    signals,
    *,
    instrument,
    costs,
    margin,
    sizing,
    sim,
    touch_rows=None,
    touch_tf=15_000,
    funding=None,
    **kw: Any,
):
    """Thin wrapper so a test reads as data in, result out."""
    funding = funding or []
    kw.setdefault("run_id", "test")
    kw.setdefault("attach_stamp", False)
    return simulate(
        bars=bars(rows),
        signals=list(signals),
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        touch_bars=bars(touch_rows, touch_tf) if touch_rows else None,
        funding_ts_ms=np.asarray([r[0] for r in funding], dtype=np.int64),
        funding_rate=np.asarray([r[1] for r in funding], dtype=float),
        **kw,
    )


def approx(value: float, expected: float, tol: float = 1e-9) -> bool:
    return abs(float(value) - float(expected)) <= tol
