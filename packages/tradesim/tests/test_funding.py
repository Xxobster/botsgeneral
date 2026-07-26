"""FUND-001 .. FUND-006 — funding is a signed cashflow, not a cost overlay.

On a perpetual held across settlements, funding is frequently larger than the fee bill and
occasionally larger than the edge. It is charged chronologically because it moves the
wallet, and a wallet that moves changes what the next order can afford and where the next
liquidation sits.

Convention: ``cashflow = -side * qty * mark * rate``. A positive rate is paid by the long.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from conftest import QUIET_BAR_1, SIGNAL_BAR, TF, long_signal, run, short_signal


@pytest.mark.conformance("FUND-001")
def test_fund_001_positive_rate_is_paid_by_the_long(
    instrument, costs, margin, sizing, sim
):
    """FUND-001: a +0.01% settlement at 2*TF costs the long 0.01 on a 100 notional.

        cashflow = -(+1) * 1.0 * 100.00 * 0.0001 = -0.01
    """
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.0, 111.0, 99.0, 110.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        funding=[(2 * TF, 0.0001)],
    )

    charge = result.funding_charges[0]
    assert charge.ts_ms == 2 * TF
    assert charge.mark_price == 100.0
    assert charge.cashflow == pytest.approx(-0.01)
    assert result.trades[0].funding == pytest.approx(-0.01)
    assert result.trades[0].realized_pnl == pytest.approx(9.79 - 0.01)


@pytest.mark.conformance("FUND-001")
def test_fund_001_positive_rate_is_received_by_the_short(
    instrument, costs, margin, sizing, sim
):
    """FUND-001: the same settlement pays the short. Never ``abs(rate)``."""
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.0, 101.0, 89.0, 90.0]],
        [short_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        funding=[(2 * TF, 0.0001)],
    )

    assert result.funding_charges[0].cashflow == pytest.approx(+0.01)
    assert result.trades[0].funding == pytest.approx(+0.01)


@pytest.mark.conformance("FUND-002")
def test_fund_002_negative_rate_reverses_the_cashflow(
    instrument, costs, margin, sizing, sim
):
    """FUND-002: a negative rate pays the long and charges the short."""
    kw = dict(
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        funding=[(2 * TF, -0.0001)],
    )
    long_result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.0, 111.0, 99.0, 110.0]],
        [long_signal()],
        **kw,
    )
    short_result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.0, 101.0, 89.0, 90.0]],
        [short_signal()],
        **kw,
    )

    assert long_result.trades[0].funding == pytest.approx(+0.01)
    assert short_result.trades[0].funding == pytest.approx(-0.01)


@pytest.mark.conformance("FUND-003")
def test_fund_003_no_funding_while_flat(instrument, costs, margin, sizing, sim):
    """FUND-003: settlements before the entry and after the exit are not charged.

    The position exists over bar 2 only. The settlements at 0 and at 4*TF fall outside
    the holding window and must leave no trace in the wallet.
    """
    result = run(
        [
            SIGNAL_BAR,
            QUIET_BAR_1,
            [2 * TF, 100.0, 111.0, 99.0, 110.0],
            [3 * TF, 110.0, 111.0, 109.0, 110.0],
            [4 * TF, 110.0, 111.0, 109.0, 110.0],
        ],
        [long_signal(ts_ms=TF)],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        funding=[(0, 0.001), (4 * TF, 0.001)],
    )

    t = result.trades[0]
    assert (t.entry_ts_ms, t.exit_ts_ms) == (2 * TF, 2 * TF)
    assert result.funding_charges == ()
    assert t.funding == 0.0
    assert result.ending_equity == pytest.approx(10_009.79)


@pytest.mark.conformance("FUND-004")
def test_fund_004_each_settlement_is_charged_once_at_its_own_mark(
    instrument, costs, margin, sizing, sim
):
    """FUND-004: three settlements, three charges, each at that instant's mark.

        at 1*TF, mark = bar 1 open = 100.00 -> -1 * 1 * 100.00 * 0.001 = -0.100
        at 2*TF, mark = bar 2 open = 102.00 -> -1 * 1 * 102.00 * 0.001 = -0.102
        at 3*TF, mark = bar 3 open = 104.00 -> -1 * 1 * 104.00 * 0.001 = -0.104
        total = -0.306
    """
    result = run(
        [
            SIGNAL_BAR,
            [TF, 100.0, 102.0, 99.0, 102.0],
            [2 * TF, 102.0, 104.0, 101.0, 104.0],
            [3 * TF, 104.0, 111.0, 103.0, 110.0],
        ],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        funding=[(TF, 0.001), (2 * TF, 0.001), (3 * TF, 0.001)],
    )

    charges = result.funding_charges
    assert [c.ts_ms for c in charges] == [TF, 2 * TF, 3 * TF]
    assert [c.mark_price for c in charges] == [100.0, 102.0, 104.0]
    assert [c.cashflow for c in charges] == pytest.approx([-0.100, -0.102, -0.104])
    assert result.trades[0].funding == pytest.approx(-0.306)


@pytest.mark.conformance("FUND-005")
def test_fund_005_holding_window_is_entry_inclusive_and_exit_exclusive(
    instrument, costs, margin, sizing, sim
):
    """FUND-005: the window is [entry, end of the exit interval).

    A settlement at the entry timestamp is inside it; one at the exit bar's end is not.
    The exit boundary defaults to the END of the closing bar because the instant inside
    that bar at which the exit happened is unknown, and that reading is the adverse one.
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
    assert t.entry_ts_ms == t.exit_ts_ms == TF
    assert [c.ts_ms for c in result.funding_charges] == [TF]
    assert t.funding == pytest.approx(-0.10)


@pytest.mark.conformance("FUND-005")
def test_fund_005_bar_start_boundary_is_available_and_undercharges(
    instrument, costs, margin, sizing, sim
):
    """FUND-005: the exact [entry, exit) reading is selectable, and it is documented.

    On a same-bar round trip it charges nothing at all, because entry and exit carry the
    same timestamp. That is why it is not the default: the position existed, and on a
    real venue it would have paid.
    """
    result = run(
        [SIGNAL_BAR, [TF, 100.0, 101.0, 94.0, 99.0], [2 * TF, 99.0, 100.0, 98.0, 99.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=replace(sim, funding_exit_boundary="bar_start"),
        funding=[(TF, 0.001), (2 * TF, 0.002)],
    )

    assert result.funding_charges == ()
    assert result.trades[0].funding == 0.0
    assert result.trades[0].realized_pnl == pytest.approx(-5.195)


@pytest.mark.conformance("FUND-006")
def test_fund_006_funding_moves_the_wallet_chronologically(
    instrument, costs, margin, sizing, sim
):
    """FUND-006: funding is in the wallet before the next decision, not added afterwards.

    A 2% settlement drains 2.00 per bar from a 100.00 notional. By the last bar the
    equity curve has to show it, and the cash column has to move with it — a
    post-simulation overlay would leave the intermediate equity, and therefore any
    equity-dependent sizing or margin check, describing a wallet that never existed.
    """
    result = run(
        [
            SIGNAL_BAR,
            [TF, 100.0, 101.0, 99.0, 100.0],
            [2 * TF, 100.0, 101.0, 99.0, 100.0],
            [3 * TF, 100.0, 101.0, 99.0, 100.0],
        ],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        funding=[(TF, 0.02), (2 * TF, 0.02), (3 * TF, 0.02)],
    )

    cash = list(result.equity["cash"])
    assert cash[0] == pytest.approx(10_000.0)
    assert cash[1] == pytest.approx(10_000.0 - 0.10 - 2.00)
    assert cash[2] == pytest.approx(10_000.0 - 0.10 - 4.00)
    assert result.trades[0].funding == pytest.approx(-6.00)


@pytest.mark.conformance("FUND-006")
def test_fund_006_funding_can_cause_the_liquidation_it_precedes(
    instrument, costs, sizing, sim
):
    """FUND-006: draining the wallet must be able to change what happens next.

    This is the reason funding cannot be a post-run subtraction: under cross margin the
    liquidation price is re-derived from what the wallet can still absorb, so paying
    funding pulls liquidation closer to the mark. The engine re-prices it every bar.
    """
    from tradesim import MarginConfig, MarginMode

    kw = dict(
        instrument=instrument,
        costs=costs,
        margin=MarginConfig(
            mode=MarginMode.CROSS, leverage=10.0, require_stop_inside_liquidation=False
        ),
        sizing=sizing,
        sim=replace(sim, starting_equity=40.0),
    )
    rows = [
        SIGNAL_BAR,
        [TF, 100.0, 101.0, 99.0, 100.0],
        [2 * TF, 100.0, 101.0, 99.0, 100.0],
        [3 * TF, 100.0, 101.0, 99.0, 100.0],
    ]

    unfunded = run(rows, [long_signal(stop=1.0)], **kw)
    funded = run(rows, [long_signal(stop=1.0)], funding=[(2 * TF, 0.10)], **kw)

    assert funded.trades[0].funding == pytest.approx(-10.0)
    assert funded.trades[0].liquidation_price > unfunded.trades[0].liquidation_price
