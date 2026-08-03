"""Limit entry = maker fee + no slippage."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tradesim import (
    CostConfig,
    EntryOrder,
    Liquidity,
    Side,
    Signal,
    SkipReason,
    research_limit_entry_costs,
    research_sim_limit_entry,
)
from tradesim.fees import (
    limit_entry_touched,
    limit_entry_would_cross,
    resolve_limit_entry_price,
)

from conftest import QUIET_BAR_1, SIGNAL_BAR, TF, long_signal, run


def test_resolve_limit_entry_price_passive_offset():
    assert resolve_limit_entry_price(
        ref_price=100.0, side=Side.LONG, tick=0.01, limit_offset=0.01
    ) == pytest.approx(99.0)
    assert resolve_limit_entry_price(
        ref_price=100.0, side=Side.SHORT, tick=0.01, limit_offset=0.01
    ) == pytest.approx(101.0)


def test_limit_cross_and_touch_helpers():
    assert limit_entry_would_cross(side=Side.LONG, ref_price=100.0, limit_price=100.01)
    assert not limit_entry_would_cross(side=Side.LONG, ref_price=100.0, limit_price=100.0)
    assert limit_entry_touched(side=Side.LONG, bar_high=101.0, bar_low=99.5, limit_price=99.8)
    assert not limit_entry_touched(
        side=Side.LONG, bar_high=101.0, bar_low=99.9, limit_price=99.5
    )


def test_limit_entry_at_open_maker_no_slip(instrument, margin, sizing):
    """Limit at next open: fills at 100, maker 0.02%, zero slip even if costs list slip."""
    costs = research_limit_entry_costs()
    # Intentionally leave a market slip rate on the CostConfig — LIMIT must ignore it.
    costs = replace(costs, entry_slippage=0.01)
    sim = research_sim_limit_entry()
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal(target_offset=0.10, stop_offset=0.05)],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )
    assert len(result.trades) == 1
    entry = result.fills[0]
    assert entry.role == "entry"
    assert entry.liquidity == "maker"
    assert entry.fee_rate == pytest.approx(0.0002)
    assert entry.price == pytest.approx(100.0)
    assert entry.slippage_cost == pytest.approx(0.0)
    assert entry.fee == pytest.approx(100.0 * 0.0002)


def test_limit_entry_passive_offset_fills_when_touched(instrument, margin, sizing, costs):
    sim = research_sim_limit_entry()
    # Bar 1: open 100, low 99 → touches buy limit at 99.5
    bars = [
        SIGNAL_BAR,
        [TF, 100.0, 101.0, 99.0, 100.0],
        [2 * TF, 100.0, 111.0, 100.0, 110.0],
    ]
    sig = Signal(
        ts_ms=0,
        side=Side.LONG,
        stop_offset=0.05,
        target_offset=0.10,
        qty=1.0,
        entry_order=EntryOrder.LIMIT,
        limit_offset=0.005,  # 99.5
    )
    result = run(
        bars,
        [sig],
        instrument=instrument,
        costs=research_limit_entry_costs(),
        margin=margin,
        sizing=sizing,
        sim=sim,
    )
    assert result.trades[0].entry_price == pytest.approx(99.5)
    assert result.fills[0].liquidity == "maker"
    assert result.fills[0].slippage_cost == pytest.approx(0.0)


def test_limit_entry_skips_when_not_touched(instrument, margin, sizing):
    sim = research_sim_limit_entry()
    # Quiet bar never goes down to 95
    bars = [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.0, 101.0, 99.5, 100.0]]
    sig = Signal(
        ts_ms=0,
        side=Side.LONG,
        stop_offset=0.05,
        target_offset=0.10,
        qty=1.0,
        entry_order="limit",
        limit_price=95.0,
    )
    result = run(
        bars,
        [sig],
        instrument=instrument,
        costs=research_limit_entry_costs(),
        margin=margin,
        sizing=sizing,
        sim=sim,
    )
    assert result.trades == ()
    assert result.skips[0].reason == SkipReason.LIMIT_NOT_FILLED.value


def test_limit_entry_skips_when_would_cross(instrument, margin, sizing):
    sim = research_sim_limit_entry()
    sig = Signal(
        ts_ms=0,
        side=Side.LONG,
        stop_offset=0.05,
        target_offset=0.10,
        qty=1.0,
        entry_order=EntryOrder.LIMIT,
        limit_price=100.50,  # above next open 100 → marketable
    )
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1],
        [sig],
        instrument=instrument,
        costs=research_limit_entry_costs(),
        margin=margin,
        sizing=sizing,
        sim=sim,
    )
    assert result.trades == ()
    assert result.skips[0].reason == SkipReason.LIMIT_WOULD_CROSS.value


def test_maker_take_profit_still_works_with_market_entry(instrument, margin, sizing, sim):
    """Proven TP maker remains available without switching entry to limit."""
    costs = CostConfig(
        taker_rate=0.001,
        maker_rate=0.0004,
        entry_slippage=0.0,
        role_liquidity={"entry": Liquidity.TAKER, "take_profit": Liquidity.MAKER},
    )
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )
    assert result.fills[0].liquidity == "taker"
    assert result.fills[1].liquidity == "maker"
