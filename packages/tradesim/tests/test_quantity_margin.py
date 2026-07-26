"""QTY-001 .. QTY-010 — quantity, margin, liquidation and the wallet identity.

Two themes. First, an order the venue would reject is refused here with a reason, never
silently resized into something the venue would accept — because the resized order is a
different strategy. Second, liquidation is solved rather than approximated, and the run
says how much of the venue's machinery it actually modelled.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from conftest import QUIET_BAR_1, SIGNAL_BAR, TF, bars, long_signal, run
from tradesim import (
    InstrumentSpec,
    MaintenanceTier,
    MarginConfig,
    MarginMode,
    SizingConfig,
    SizingMode,
    SkipReason,
    round_to_step,
    round_to_tick,
)
from tradesim.margin import liquidation_price
from tradesim.sizing import minimum_executable_qty, normalise_order

TINY = InstrumentSpec(
    symbol="TESTUSDT", tick_size=0.01, qty_step=0.001, min_qty=0.001, min_notional=1.0
)


@pytest.mark.conformance("QTY-001")
def test_qty_001_prices_and_quantities_land_on_the_venue_grid():
    """QTY-001: rounding is explicit, directional, and free of binary-float drift.

    ``102.9 / 0.01`` is 10289.999999999998 in binary floating point. A fixed epsilon gets
    that wrong in one direction or 95.00 wrong in the other, so the tolerance scales with
    the magnitude.
    """
    assert round_to_tick(102.9, 0.01) == 102.9
    assert round_to_tick(102.904, 0.01) == 102.90
    assert round_to_tick(102.906, 0.01) == 102.91
    assert round_to_tick(102.904, 0.01, "ceil") == 102.91
    assert round_to_tick(102.906, 0.01, "floor") == 102.90
    assert round_to_step(1.2349, 0.001) == 1.234, "quantities floor: never buy more"
    assert round_to_step(1.2349, 0.001, "ceil") == 1.235


@pytest.mark.conformance("QTY-001")
def test_qty_001_entry_rounding_never_manufactures_a_better_fill(
    margin, sizing, sim
):
    """QTY-001: a slipped long entry rounds UP to the tick, a short rounds DOWN.

    Rounding in the trader's favour is a systematic gift of half a tick per fill, which
    on a high-frequency strategy is the entire result.
    """
    from tradesim import CostConfig

    costs = CostConfig(taker_rate=0.001, entry_slippage=0.000_04)
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal()],
        instrument=TINY,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    # 100.00 * 1.00004 = 100.004, which is not on the 0.01 grid: the long pays 100.01.
    assert result.trades[0].entry_price == pytest.approx(100.01)


@pytest.mark.conformance("QTY-002")
def test_qty_002_below_minimum_notional_is_skipped_with_a_reason(
    costs, margin, sim
):
    """QTY-002: a 0.005 order at 100.00 is 0.50 of notional against a 1.00 minimum.

    It is refused, not rounded up to the minimum. Rounding up would report a strategy
    trading twice the intended size at exactly the moments its own rules said to trade
    small.
    """
    spec = InstrumentSpec(
        symbol="TESTUSDT",
        tick_size=0.01,
        qty_step=0.001,
        min_qty=0.001,
        min_notional=1.0,
    )
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal()],
        instrument=spec,
        costs=costs,
        margin=margin,
        sizing=SizingConfig(mode=SizingMode.FIXED_QTY, fixed_qty=0.005),
        sim=sim,
    )

    assert result.n_trades == 0
    assert result.skip_counts == {SkipReason.BELOW_MIN_NOTIONAL.value: 1}


@pytest.mark.conformance("QTY-002")
def test_qty_002_quantity_that_rounds_to_zero_is_skipped_not_zero_filled():
    """QTY-002: 0.0004 on a 0.001 step is not a trade, and not an error to swallow."""
    outcome = normalise_order(
        raw_qty=0.0004,
        price=100.0,
        stop_price=95.0,
        equity=10_000.0,
        spec=TINY,
        cfg=SizingConfig(),
    )
    assert not outcome.ok
    assert outcome.skip_reason == SkipReason.QTY_ROUNDS_TO_ZERO


@pytest.mark.conformance("QTY-003")
def test_qty_003_minimum_order_breaching_the_risk_cap_is_skipped(
    costs, margin, sim
):
    """QTY-003: when the smallest sendable order over-risks, the answer is no trade.

    The venue minimum here is 1.0 unit (1.00 of notional at a price of 1.00), risking
    0.05 per unit against a cap of 0.1% of a 10.00 wallet, which is 0.01. Rounding up to
    the minimum would take five times the risk the policy allows, at exactly the moments
    the policy was trying to protect.
    """
    spec = InstrumentSpec(
        symbol="TESTUSDT", tick_size=0.01, qty_step=1.0, min_qty=1.0, min_notional=1.0
    )
    result = run(
        [
            [0, 1.0, 1.0, 1.0, 1.0],
            [TF, 1.0, 1.01, 0.99, 1.0],
            [2 * TF, 1.0, 1.2, 0.99, 1.1],
        ],
        [long_signal(stop=0.95, target=1.10)],
        instrument=spec,
        costs=costs,
        margin=margin,
        sizing=SizingConfig(
            mode=SizingMode.RISK_FRACTION, risk_fraction=0.001, max_risk_fraction=0.001
        ),
        sim=replace(sim, starting_equity=10.0),
    )

    assert result.n_trades == 0
    assert result.skip_counts == {SkipReason.MIN_QTY_EXCEEDS_RISK_CAP.value: 1}
    assert "frozen cap" in result.skips[0].detail


@pytest.mark.conformance("QTY-003")
def test_qty_003_minimum_executable_quantity_respects_both_minimums():
    """QTY-003: the floor is ``ceil_to_step(max(min_qty, min_notional / price))``."""
    assert minimum_executable_qty(TINY, 100.0) == 0.01
    assert minimum_executable_qty(TINY, 10_000.0) == 0.001


@pytest.mark.conformance("QTY-004")
def test_qty_004_insufficient_margin_rejects_the_order(costs, sizing, sim):
    """QTY-004: a 12.00 wallet cannot post the 100.00 of margin a 1x position needs."""
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal()],
        instrument=TINY,
        costs=costs,
        margin=MarginConfig(
            mode=MarginMode.ISOLATED, leverage=1.0, max_margin_utilisation=1.0
        ),
        sizing=sizing,
        sim=replace(sim, starting_equity=12.0),
    )

    assert result.n_trades == 0
    assert result.skip_counts == {SkipReason.INSUFFICIENT_MARGIN.value: 1}


@pytest.mark.conformance("QTY-004")
def test_qty_004_margin_utilisation_cap_is_separate_from_running_out(
    costs, sizing, sim
):
    """QTY-004: the policy cap bites before the wallet does, and says so distinctly.

    A 260.00 wallet can easily post the 100.00 of margin this position needs, but a 30%
    utilisation cap allows only 78.00. The order is refused by policy, not by poverty,
    and the reason code has to keep those two apart: one is a parameter to reconsider,
    the other is a strategy that cannot be funded.
    """
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal()],
        instrument=TINY,
        costs=costs,
        margin=MarginConfig(
            mode=MarginMode.ISOLATED, leverage=1.0, max_margin_utilisation=0.3
        ),
        sizing=sizing,
        sim=replace(sim, starting_equity=260.0),
    )

    assert result.n_trades == 0
    assert result.skip_counts == {SkipReason.MARGIN_UTILISATION_CAP.value: 1}


@pytest.mark.conformance("QTY-005")
def test_qty_005_leverage_changes_margin_not_price_pnl(
    instrument, costs, sizing, sim
):
    """QTY-005: at a fixed quantity, leverage moves margin and liquidation only.

    The profit and loss of one unit from 100.00 to 110.00 is 10.00 whatever the leverage.
    What changes is the margin posted (10.00 versus 20.00) and therefore how far away the
    liquidation sits, which is a risk statement, not a return statement.
    """
    rows = [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]]
    kw = dict(instrument=instrument, costs=costs, sizing=sizing, sim=sim)

    ten = run(rows, [long_signal()], margin=MarginConfig(leverage=10.0), **kw)
    five = run(rows, [long_signal()], margin=MarginConfig(leverage=5.0), **kw)

    a, b = ten.trades[0], five.trades[0]
    assert a.realized_pnl == b.realized_pnl == pytest.approx(9.79)
    assert (a.initial_margin, b.initial_margin) == (10.0, 20.0)
    assert a.liquidation_price == pytest.approx(90.55)
    assert b.liquidation_price == pytest.approx(80.49)


@pytest.mark.conformance("QTY-006")
def test_qty_006_liquidation_uses_the_tier_for_the_position_notional(
    costs, sizing, sim
):
    """QTY-006: the maintenance rate comes from the ladder row the notional lands in.

    A flat 0.5% rate applied to a position sitting in a 1.0% tier understates the
    maintenance requirement and pushes the modelled liquidation further away than the
    venue's, which is the flattering direction.
    """
    spec = InstrumentSpec(
        symbol="TESTUSDT",
        tick_size=0.01,
        qty_step=0.001,
        min_qty=0.001,
        min_notional=1.0,
        maintenance_rate=0.005,
        maintenance_tiers=(
            MaintenanceTier(0.0, 0.005, 100.0, 0.0),
            MaintenanceTier(50.0, 0.01, 50.0, 0.25),
        ),
    )
    assert spec.tier_for_notional(100.0).mm_rate == 0.01

    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal()],
        instrument=spec,
        costs=costs,
        margin=MarginConfig(leverage=10.0),
        sizing=sizing,
        sim=sim,
        mark_bars=bars([SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]]),
    )

    t = result.trades[0]
    # (1*100 - 10 - 0.25) / (1 * (1 - 0.01 - 0.001)) = 90.7482... -> 90.75 (ceil, adverse)
    # On the flat 0.5% rate it would be 90.55: two ticks of flattery per unit.
    assert t.liquidation_price == pytest.approx(90.75)
    assert result.liquidation_status == "MODELLED"


@pytest.mark.conformance("QTY-006")
def test_qty_006_missing_tiers_or_mark_series_downgrade_the_status(
    instrument, costs, sizing, sim
):
    """QTY-006: without a tier table and a Mark series the status is SIMPLIFIED, loudly.

    A silent pass would let a single-rate, Last-price approximation be quoted as
    liquidation evidence.
    """
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=MarginConfig(leverage=10.0),
        sizing=sizing,
        sim=sim,
    )

    assert result.liquidation_status == "SIMPLIFIED"
    assert any("liquidation status is SIMPLIFIED" in w for w in result.warnings)


@pytest.mark.conformance("QTY-007")
def test_qty_007_the_engine_says_which_of_stop_or_liquidation_happened(
    instrument, costs, sizing, sim
):
    """QTY-007: same levels, two paths, two answers, both stated explicitly.

    Continuous descent through 95.00 to 89.00 is a stop. A gap that opens at 90.00 is a
    liquidation. An engine that answers "was the low beyond the liquidation price" calls
    both of them liquidations and overstates the loss on the first by 4.99.
    """
    margin = MarginConfig(mode=MarginMode.ISOLATED, leverage=10.0)
    kw = dict(instrument=instrument, costs=costs, margin=margin, sizing=sizing, sim=sim)

    walked = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.0, 100.5, 89.0, 90.0]], [long_signal()], **kw
    )
    gapped = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 90.0, 91.0, 88.0, 90.0]], [long_signal()], **kw
    )

    assert walked.trades[0].exit_reason == "stop"
    assert walked.trades[0].realized_pnl == pytest.approx(-5.195)
    assert gapped.trades[0].exit_reason == "liquidation"
    assert gapped.trades[0].realized_pnl == pytest.approx(-10.19)


@pytest.mark.conformance("QTY-007")
def test_qty_007_liquidation_price_is_solved_not_approximated():
    """QTY-007: the solve keeps the closing fee and the tier deduction.

    ``entry * (1 - 1/leverage)`` gives 90.00 here. The correct answer is 90.55, and the
    0.55 is the maintenance requirement and the fee to close that the shorthand drops.
    """
    solved = liquidation_price(
        side=1,
        entry_price=100.0,
        qty=1.0,
        posted_margin=10.0,
        mm_rate=0.005,
        close_fee_rate=0.001,
        tick_size=0.01,
    )
    assert solved == pytest.approx(90.55)
    assert solved > 100.0 * (1 - 1 / 10.0), "the shorthand is optimistic"


@pytest.mark.conformance("QTY-008")
def test_qty_008_the_wallet_reconciles(instrument, costs, margin, sizing, sim):
    """QTY-008: starting + gross - fees + funding == ending, to the cent and beyond.

    Three trades, two of them losers, with funding charged throughout. If this identity
    does not hold there is money in the result that came from nowhere, and no other
    number in the report can be trusted.
    """
    result = run(
        [
            SIGNAL_BAR,
            [TF, 100.0, 101.0, 94.0, 99.0],
            [2 * TF, 99.0, 100.0, 98.0, 100.0],
            [3 * TF, 100.0, 111.0, 99.0, 110.0],
            [4 * TF, 110.0, 111.0, 109.0, 110.0],
            [5 * TF, 110.0, 111.0, 104.0, 105.0],
            [6 * TF, 105.0, 106.0, 104.0, 105.0],
        ],
        [
            long_signal(),
            long_signal(ts_ms=2 * TF, stop=95.0, target=110.0),
            long_signal(ts_ms=4 * TF, stop=105.0, target=120.0),
        ],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        funding=[(k * TF, 0.0001) for k in range(7)],
    )

    assert result.n_trades == 3
    gross = sum(t.gross_pnl for t in result.trades)
    fees = sum(t.fees for t in result.trades)
    funding = sum(t.funding for t in result.trades)
    assert result.starting_equity + gross - fees + funding == pytest.approx(
        result.ending_equity, abs=1e-9
    )
    summary = result.meta["summary"]
    assert summary["total_gross_pnl"] == pytest.approx(gross)
    assert summary["total_fees"] == pytest.approx(fees)
    assert summary["total_funding"] == pytest.approx(funding)


@pytest.mark.conformance("QTY-009")
def test_qty_009_a_ruined_wallet_stops_trading(instrument, costs, sizing, sim):
    """QTY-009: once equity reaches zero, later signals are refused, not funded.

    A 10.00 wallet fully committed at leverage 10 is liquidated by a gap to 85.00 and
    ends below zero. Continuing to trade from a negative wallet is how a backtest
    produces a recovery that no account could have participated in.
    """
    result = run(
        [
            SIGNAL_BAR,
            QUIET_BAR_1,
            [2 * TF, 85.0, 86.0, 84.0, 85.0],
            [3 * TF, 85.0, 86.0, 84.0, 85.0],
            [4 * TF, 85.0, 96.0, 84.0, 95.0],
        ],
        [long_signal(), long_signal(ts_ms=3 * TF, stop=80.0, target=95.0)],
        instrument=instrument,
        costs=costs,
        margin=MarginConfig(
            mode=MarginMode.ISOLATED, leverage=10.0, max_margin_utilisation=1.0
        ),
        sizing=sizing,
        sim=replace(sim, starting_equity=10.0),
    )

    assert result.n_trades == 1
    assert result.trades[0].exit_reason == "liquidation"
    assert result.ending_equity < 0
    assert result.skip_counts == {SkipReason.WALLET_RUINED.value: 1}
    assert any("wallet equity reached zero" in w for w in result.warnings)


@pytest.mark.conformance("QTY-010")
def test_qty_010_a_stop_beyond_liquidation_is_rejected(
    instrument, costs, sizing, sim
):
    """QTY-010: at leverage 50 the liquidation is 98.60 and a 90.00 stop is fiction.

    That order would be simulated as protected at 90.00 while the venue would have closed
    it at 98.60. Refusing it is the only honest answer; the alternative is a backtest of
    a risk control that does not exist.
    """
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal(stop=90.0)],
        instrument=instrument,
        costs=costs,
        margin=MarginConfig(
            mode=MarginMode.ISOLATED, leverage=50.0, require_stop_inside_liquidation=True
        ),
        sizing=sizing,
        sim=sim,
    )

    assert result.n_trades == 0
    assert result.skip_counts == {SkipReason.STOP_INSIDE_LIQUIDATION.value: 1}
    assert "never protect" in result.skips[0].detail


@pytest.mark.conformance("QTY-010")
def test_qty_010_the_same_stop_is_accepted_at_a_leverage_that_supports_it(
    instrument, costs, sizing, sim
):
    """QTY-010: the control, so that refusing every order cannot pass the test above.

    Dropping to leverage 8 posts 12.50 of margin and moves the liquidation to 88.03,
    which is below the 90.00 stop. The stop is now a real protective order and the trade
    is taken.
    """
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal(stop=90.0)],
        instrument=instrument,
        costs=costs,
        margin=MarginConfig(mode=MarginMode.ISOLATED, leverage=8.0),
        sizing=sizing,
        sim=sim,
    )

    assert result.n_trades == 1
    assert result.trades[0].liquidation_price == pytest.approx(88.03)
    assert result.trades[0].exit_reason == "target"
