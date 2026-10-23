"""Hedge mode: long and short open together, each with own TP/SL."""

from __future__ import annotations

from dataclasses import replace

import pytest

from conftest import QUIET_BAR_1, SIGNAL_BAR, TF, long_signal, run, short_signal
from tradesim import PositionMode, Side, SkipReason, research_sim_hedge
from tradesim.contracts import SimConfig


def test_one_way_blocks_opposite_side(instrument, costs, margin, sizing, sim):
    """Default one-way: a short is refused while a long is already open."""
    result = run(
        [
            SIGNAL_BAR,
            QUIET_BAR_1,
            [2 * TF, 100.0, 101.0, 99.0, 100.0],
            [3 * TF, 100.0, 101.0, 99.0, 100.0],
        ],
        [
            long_signal(ts_ms=0, stop=95.0, target=110.0),
            short_signal(ts_ms=TF, stop=105.0, target=90.0),
        ],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )
    assert result.n_trades == 1
    assert int(result.trades[0].side) > 0
    assert SkipReason.POSITION_LIMIT.value in result.skip_counts


def test_hedge_long_and_short_same_bar_own_tp_sl(instrument, costs, margin, sizing):
    """Hedge: both sides open on the same entry bar; each exits on its own TP."""
    sim = research_sim_hedge(starting_equity=10_000.0, decision_timeframe="1m")
    # 1× leverage so protective stops stay inside the liquidation distance.
    margin = replace(margin, leverage=1.0)
    # Entry at bar1 open=100.
    # Bar2: high 111 hits long TP 110 (short stop 105 would also trip — use 120).
    # Bar3: low 89 hits short TP 90.
    result = run(
        [
            SIGNAL_BAR,
            [TF, 100.0, 101.0, 99.0, 100.0],
            [2 * TF, 100.0, 111.0, 99.0, 110.0],
            [3 * TF, 110.0, 111.0, 89.0, 95.0],
        ],
        [
            long_signal(ts_ms=0, stop=95.0, target=110.0, qty=1.0),
            short_signal(ts_ms=0, stop=120.0, target=90.0, qty=1.0),
        ],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )
    assert result.n_trades == 2
    sides = sorted(int(t.side) for t in result.trades)
    assert sides == [-1, 1]
    by_side = {int(t.side): t for t in result.trades}
    assert by_side[1].exit_reason.startswith("target")
    assert by_side[1].exit_price == pytest.approx(110.0)
    assert by_side[1].stop_price == pytest.approx(95.0)
    assert by_side[-1].exit_reason.startswith("target")
    assert by_side[-1].exit_price == pytest.approx(90.0)
    assert by_side[-1].stop_price == pytest.approx(120.0)
    # Both opened on the same entry bar.
    assert by_side[1].entry_ts_ms == by_side[-1].entry_ts_ms
    assert by_side[1].entry_ts_ms == TF


def test_hedge_second_long_blocked(instrument, costs, margin, sizing):
    sim = research_sim_hedge(starting_equity=10_000.0, decision_timeframe="1m")
    result = run(
        [
            SIGNAL_BAR,
            QUIET_BAR_1,
            [2 * TF, 100.0, 101.0, 99.0, 100.0],
            [3 * TF, 100.0, 111.0, 99.0, 110.0],
        ],
        [
            long_signal(ts_ms=0, stop=95.0, target=110.0),
            long_signal(ts_ms=TF, stop=94.0, target=112.0),
        ],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )
    assert result.n_trades == 1
    assert SkipReason.POSITION_LIMIT.value in result.skip_counts
    assert any("long" in s.detail for s in result.skips)


def test_hedge_mode_via_simconfig_position_mode(instrument, costs, margin, sizing):
    sim = SimConfig(
        starting_equity=10_000.0,
        position_mode=PositionMode.HEDGE,
        allow_concurrent_positions=True,
        max_positions_per_side=1,
        max_positions_per_symbol=2,
        decision_timeframe="1m",
    )
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.0, 101.0, 94.0, 95.0]],
        [
            long_signal(ts_ms=0, stop=95.0, target=110.0),
            short_signal(ts_ms=0, stop=105.0, target=90.0),
        ],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )
    assert result.n_trades == 2
    # Long stopped at 95; short still open until end flatten or continues —
    # bar low 94 takes long stop; short stop 105 not touched, short target 90 not touched.
    longs = [t for t in result.trades if int(t.side) > 0]
    shorts = [t for t in result.trades if int(t.side) < 0]
    assert longs[0].exit_reason.startswith("stop")
    assert shorts[0].side == int(Side.SHORT)
