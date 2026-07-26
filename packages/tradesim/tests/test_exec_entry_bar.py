"""EXEC-010 .. EXEC-016 — the jointly non-negotiable entry-bar behaviours.

A position is exposed from the instant it fills, so the bar that fills the entry must be
resolved for stop, target, liquidation and funding in the same step that opens it.

These seven were written before the engine, and the engine was developed against them.
The defect they exist to catch is a bar loop that opens a position and starts exit
checking on the *following* bar. On a daily strategy whose stop sat just beyond the
signal bar's extreme, that granted immunity to 47.6% of 1278 trades and was the entire
apparent edge of the project: removing it moved the stitched out-of-sample profit factor
from 1.50 to 0.90 and the annualised Sharpe from +1.32 to -0.31.

EXEC-014 is the paired negative control. Without it, an engine passes EXEC-010 by closing
every position immediately.
"""

from __future__ import annotations

import pytest

from conftest import QUIET_BAR_1, SIGNAL_BAR, TF, long_signal, run, short_signal
from tradesim.contracts import MarginConfig, MarginMode


@pytest.mark.conformance("EXEC-010")
def test_exec_010_entry_bar_stop_closes_on_entry_bar(
    instrument, costs, margin, sizing, sim
):
    """EXEC-010: the entry bar's own range takes out the stop, so the trade closes on it.

    Entry fills at bar 1's open of 100.00; bar 1's low of 94.00 is through the 95.00
    stop. exit_ts must equal entry_ts, both fills' fees are charged, and the reason is
    distinguishable as an entry-bar exit.

        entry fee = 1 * 100.00 * 0.001 = 0.100
        exit  fee = 1 *  95.00 * 0.001 = 0.095
        realized  = -5.00 - 0.100 - 0.095 = -5.195
    """
    result = run(
        [SIGNAL_BAR, [TF, 100.0, 101.0, 94.0, 99.0], [2 * TF, 99.0, 100.0, 98.0, 99.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.entry_ts_ms == TF
    assert t.exit_ts_ms == t.entry_ts_ms, "the trade did not close on its entry bar"
    assert t.entry_price == 100.0
    assert t.exit_price == 95.0
    assert t.exit_reason == "stop_entry_bar"
    assert t.entry_bar_exit is True
    assert t.fees == pytest.approx(0.195)
    assert t.gross_pnl == pytest.approx(-5.0)
    assert t.realized_pnl == pytest.approx(-5.195)
    assert result.ending_equity == pytest.approx(9994.805)

    entry_fills = [f for f in result.fills if f.role == "entry"]
    exit_fills = [f for f in result.fills if f.role == "stop"]
    assert len(entry_fills) == 1 and len(exit_fills) == 1
    assert entry_fills[0].fee == pytest.approx(0.1)
    assert exit_fills[0].fee == pytest.approx(0.095)


@pytest.mark.conformance("EXEC-010")
def test_exec_010_entry_bar_stop_short_side(instrument, costs, margin, sizing, sim):
    """EXEC-010: the short mirror, so the branch is not only correct for longs.

        exit fee = 1 * 105.00 * 0.001 = 0.105
        realized = -5.00 - 0.100 - 0.105 = -5.205
    """
    result = run(
        [SIGNAL_BAR, [TF, 100.0, 106.0, 99.0, 101.0], [2 * TF, 101.0, 102.0, 100.0, 101.0]],
        [short_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.exit_ts_ms == t.entry_ts_ms
    assert t.exit_price == 105.0
    assert t.exit_reason == "stop_entry_bar"
    assert t.realized_pnl == pytest.approx(-5.205)


@pytest.mark.conformance("EXEC-011")
def test_exec_011_entry_bar_target_closes_on_entry_bar(
    instrument, costs, margin, sizing, sim
):
    """EXEC-011: the entry bar's own range reaches the target.

        exit fee = 1 * 110.00 * 0.001 = 0.110
        realized = 10.00 - 0.100 - 0.110 = 9.79
    """
    result = run(
        [SIGNAL_BAR, [TF, 100.0, 111.0, 99.0, 110.0], [2 * TF, 110.0, 111.0, 109.0, 110.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    t = result.trades[0]
    assert t.exit_ts_ms == t.entry_ts_ms
    assert t.exit_price == 110.0
    assert t.exit_reason == "target_entry_bar"
    assert t.entry_bar_exit is True
    assert t.realized_pnl == pytest.approx(9.79)
    assert result.ending_equity == pytest.approx(10009.79)


@pytest.mark.conformance("EXEC-012")
def test_exec_012_entry_bar_both_takes_adverse_and_labels_ambiguous(
    instrument, costs, margin, sizing, sim
):
    """EXEC-012: the entry bar spans 94..111, containing both stop and target.

    Without lower-timeframe data the adverse branch is taken and the trade is labelled
    ambiguous so its frequency and its PnL sensitivity are reportable.
    """
    result = run(
        [SIGNAL_BAR, [TF, 100.0, 111.0, 94.0, 100.0], [2 * TF, 100.0, 101.0, 99.0, 100.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    t = result.trades[0]
    assert t.exit_ts_ms == t.entry_ts_ms
    assert t.exit_price == 95.0
    assert t.exit_reason == "stop_entry_bar"
    assert t.ambiguous_intrabar is True
    assert t.realized_pnl == pytest.approx(-5.195)
    assert result.meta["summary"]["ambiguous_intrabar"] == 1


@pytest.mark.conformance("EXEC-012")
def test_exec_012_entry_bar_both_resolved_by_touch_data(
    instrument, costs, margin, sizing, sim
):
    """EXEC-012: the same entry bar, resolved by 15-second data showing the target first.

    The ambiguity is settled by evidence rather than by policy, so the answer flips to
    the target and the trade is no longer marked ambiguous.
    """
    touch = [
        [0, 100.0, 100.0, 100.0, 100.0],
        [15_000, 100.0, 100.0, 100.0, 100.0],
        [30_000, 100.0, 100.0, 100.0, 100.0],
        [45_000, 100.0, 100.0, 100.0, 100.0],
        [TF + 0, 100.0, 111.0, 100.0, 110.5],
        [TF + 15_000, 110.5, 111.0, 94.0, 95.0],
        [TF + 30_000, 95.0, 96.0, 94.0, 95.0],
        [TF + 45_000, 95.0, 101.0, 94.5, 100.0],
        [2 * TF + 0, 100.0, 101.0, 99.0, 100.0],
        [2 * TF + 15_000, 100.0, 101.0, 99.0, 100.0],
        [2 * TF + 30_000, 100.0, 101.0, 99.0, 100.0],
        [2 * TF + 45_000, 100.0, 101.0, 99.0, 100.0],
    ]
    result = run(
        [SIGNAL_BAR, [TF, 100.0, 111.0, 94.0, 100.0], [2 * TF, 100.0, 101.0, 99.0, 100.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        touch_rows=touch,
    )

    t = result.trades[0]
    assert t.exit_ts_ms == t.entry_ts_ms
    assert t.exit_price == 110.0
    assert t.exit_reason == "target_entry_bar"
    assert t.ambiguous_intrabar is False
    assert t.resolved_by_touch is True
    assert t.realized_pnl == pytest.approx(9.79)


@pytest.mark.conformance("EXEC-013")
def test_exec_013_entry_bar_liquidation_resolves_before_the_stop(
    instrument, costs, sizing, sim
):
    """EXEC-013: the entry bar reaches the liquidation price.

    At leverage 50 the isolated liquidation solves to 98.60:

        P_liq = (qty*entry - margin) / (qty * (1 - mm_rate - close_fee_rate))
              = (100 - 2) / (1 - 0.005 - 0.001) = 98.5915... -> 98.60 (ceil, adverse)

    The 90.00 stop sits *beyond* it, so on the continuous path down to 89.00 liquidation
    is reached first and must resolve on the entry bar.

        exit fee = 98.60 * 0.001 = 0.0986
        realized = -1.40 - 0.100 - 0.0986 = -1.5986
    """
    margin = MarginConfig(
        mode=MarginMode.ISOLATED, leverage=50.0, require_stop_inside_liquidation=False
    )
    result = run(
        [SIGNAL_BAR, [TF, 100.0, 100.5, 89.0, 90.0], [2 * TF, 90.0, 91.0, 89.0, 90.0]],
        [long_signal(stop=90.0)],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    t = result.trades[0]
    assert t.exit_ts_ms == t.entry_ts_ms
    assert t.liquidation_price == pytest.approx(98.60)
    assert t.exit_price == pytest.approx(98.60)
    assert t.exit_reason == "liquidation_entry_bar"
    assert t.realized_pnl == pytest.approx(-1.5986)
    assert result.liquidation_status in ("MODELLED", "SIMPLIFIED")


@pytest.mark.conformance("EXEC-014")
def test_exec_014_quiet_entry_bar_does_not_close(instrument, costs, margin, sizing, sim):
    """EXEC-014: THE NEGATIVE CONTROL.

    Bar 1 spans 99..101 and touches neither the 95 stop nor the 110 target, so the
    position must survive its entry bar. Bar 2 then takes the stop.

    An engine that closes everything on the entry bar passes EXEC-010 and fails here.
    An engine with the original defect passes here and fails EXEC-010. Only an engine
    that resolves the entry bar *correctly* passes both.
    """
    result = run(
        [
            SIGNAL_BAR,
            [TF, 100.0, 101.0, 99.0, 100.5],
            [2 * TF, 100.5, 101.0, 94.0, 95.0],
            [3 * TF, 95.0, 96.0, 94.0, 95.0],
        ],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.entry_ts_ms == TF
    assert t.exit_ts_ms == 2 * TF, "the quiet entry bar must not close the position"
    assert t.exit_reason == "stop", "a later-bar exit must not carry the entry-bar label"
    assert t.entry_bar_exit is False
    assert t.hold_bars == 1
    assert t.exit_price == 95.0
    assert t.realized_pnl == pytest.approx(-5.195)
    assert result.meta["summary"]["entry_bar_exits"] == 0


@pytest.mark.conformance("EXEC-014")
def test_exec_014_quiet_entry_bar_then_target(instrument, costs, margin, sizing, sim):
    """EXEC-014: the favourable half of the control, so neither side is closed early."""
    result = run(
        [
            SIGNAL_BAR,
            [TF, 100.0, 101.0, 99.0, 100.5],
            [2 * TF, 100.5, 111.0, 100.0, 110.0],
        ],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    t = result.trades[0]
    assert t.exit_ts_ms == 2 * TF
    assert t.exit_reason == "target"
    assert t.hold_bars == 1
    assert t.realized_pnl == pytest.approx(9.79)


@pytest.mark.conformance("EXEC-015")
def test_exec_015_same_bar_round_trip_is_charged_funding(
    instrument, costs, margin, sizing, sim
):
    """EXEC-015: a same-bar round trip is not a free round trip.

    A settlement lands at 60000, exactly the entry timestamp, and another at 120000,
    exactly the end of the entry bar. The holding window is [60000, 120000), so the
    first is charged and the second is not.

        mark at 60000 = bar 1's open = 100.00
        cashflow = -side * qty * mark * rate = -1 * 1 * 100 * 0.001 = -0.10
        realized = -5.00 - 0.195 - 0.10 = -5.295
    """
    result = run(
        [SIGNAL_BAR, [TF, 100.0, 101.0, 94.0, 99.0], [2 * TF, 99.0, 100.0, 98.0, 99.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        funding=[(TF, 0.001), (2 * TF, 0.002)],
    )

    t = result.trades[0]
    assert t.exit_ts_ms == t.entry_ts_ms
    assert len(result.funding_charges) == 1
    assert result.funding_charges[0].ts_ms == TF
    assert t.funding == pytest.approx(-0.1)
    assert t.realized_pnl == pytest.approx(-5.295)


@pytest.mark.conformance("EXEC-016")
def test_exec_016_same_bar_exit_reports_zero_hold(
    instrument, costs, margin, sizing, sim
):
    """EXEC-016: a trade closed on its entry bar has held for zero bars, not one."""
    sim_with_hold = type(sim)(**{**sim.__dict__, "max_hold_bars": 5})
    result = run(
        [SIGNAL_BAR, [TF, 100.0, 111.0, 99.0, 110.0], [2 * TF, 110.0, 111.0, 109.0, 110.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim_with_hold,
    )

    t = result.trades[0]
    assert t.hold_bars == 0
    assert t.exit_reason == "target_entry_bar"


@pytest.mark.conformance("EXEC-016")
def test_exec_016_max_hold_arithmetic_counts_from_the_entry_bar(
    instrument, costs, margin, sizing, sim
):
    """EXEC-016: maximum hold is measured from the entry bar index.

    With max_hold_bars = 2 and the entry on bar 1, the hold expires at the boundary of
    bar 3 and the market order fills at bar 3's open of 100.50. hold_bars is 2, which is
    the same number the live runner would compute from the same entry bar.

        exit fee = 100.50 * 0.001 = 0.1005
        realized = 0.50 - 0.100 - 0.1005 = 0.2995
    """
    sim_with_hold = type(sim)(**{**sim.__dict__, "max_hold_bars": 2})
    result = run(
        [
            SIGNAL_BAR,
            QUIET_BAR_1,
            [2 * TF, 100.0, 101.0, 99.0, 100.5],
            [3 * TF, 100.5, 101.0, 99.5, 100.0],
            [4 * TF, 100.0, 101.0, 99.0, 100.0],
        ],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim_with_hold,
    )

    t = result.trades[0]
    assert t.entry_ts_ms == TF
    assert t.exit_ts_ms == 3 * TF
    assert t.hold_bars == 2
    assert t.exit_price == pytest.approx(100.5)
    assert t.exit_reason == "max_hold"
    assert t.realized_pnl == pytest.approx(0.2995)
