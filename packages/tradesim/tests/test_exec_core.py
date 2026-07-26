"""EXEC-001 .. EXEC-008 and EXEC-018 .. EXEC-020 — the rest of the execution contract.

The entry-bar seven live in ``test_exec_entry_bar.py``. These cover where a fill happens,
what it costs, and which of two levels wins when a single candle contains both.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from conftest import QUIET_BAR_1, SIGNAL_BAR, TF, long_signal, run, short_signal
from tradesim.contracts import CostConfig, Liquidity, MarginConfig, MarginMode


@pytest.mark.conformance("EXEC-001")
def test_exec_001_signal_fills_at_the_next_executable_price(
    instrument, costs, margin, sizing, sim
):
    """EXEC-001: a close-based signal fills at the next bar's open, not at that close.

    Bar 0 closes at 100.00 and bar 1 opens at 102.00. The fill is 102.00: the strategy
    knew the close, but the first price it could actually transact at was the next open.
    """
    result = run(
        [
            SIGNAL_BAR,
            [TF, 102.0, 103.0, 101.0, 102.0],
            [2 * TF, 102.0, 112.0, 101.0, 111.0],
        ],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=replace(margin, leverage=2.0),
        sizing=sizing,
        sim=sim,
    )

    t = result.trades[0]
    assert t.entry_ts_ms == TF
    assert t.entry_ref_price == 102.0
    assert t.entry_price == 102.0
    assert t.exit_reason == "target"
    assert t.realized_pnl == pytest.approx(7.788)


@pytest.mark.conformance("EXEC-002")
def test_exec_002_entry_slippage_moves_the_price_not_the_rate(
    instrument, margin, sizing, sim
):
    """EXEC-002: 10 bp of entry slippage on a long buys at 100.10, and the fee follows.

        fill        = 100.00 * (1 + 0.001) = 100.10
        entry fee   = 1 * 100.10 * 0.001   = 0.10010     <- rate applied to the FILL
        slippage    = 1 * |100.10 - 100.00| = 0.10
        exit fee    = 1 * 110.00 * 0.001   = 0.110
        realized    = 9.90 - 0.1001 - 0.110 = 9.6899

    Folding slippage into the rate would charge ``1 * 100 * 0.002 = 0.20`` and fill at
    100.00, overstating the fee and understating the price impact. The two errors do not
    cancel, and only one of them is proportional to the fee schedule.
    """
    costs = CostConfig(
        taker_rate=0.001, maker_rate=0.0004, entry_slippage=0.001, market_exit_slippage=0.0
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

    t = result.trades[0]
    assert t.entry_ref_price == 100.0
    assert t.entry_price == pytest.approx(100.10)
    assert t.slippage_cost == pytest.approx(0.10)
    entry_fill = [f for f in result.fills if f.role == "entry"][0]
    assert entry_fill.fee_rate == pytest.approx(0.001), "the rate is untouched"
    assert entry_fill.fee == pytest.approx(0.10010)
    assert t.realized_pnl == pytest.approx(9.6899)


@pytest.mark.conformance("EXEC-002")
def test_exec_002_entry_slippage_is_adverse_for_a_short(
    instrument, margin, sizing, sim
):
    """EXEC-002: the short sells 10 bp lower, never higher."""
    costs = CostConfig(taker_rate=0.001, entry_slippage=0.001)
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 99.5, 100.0, 89.0, 90.0]],
        [short_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    assert result.trades[0].entry_price == pytest.approx(99.90)


@pytest.mark.conformance("EXEC-003")
def test_exec_003_fee_is_per_fill_at_the_role_rate(instrument, margin, sizing, sim):
    """EXEC-003: two fills, two fees, each at its own role's rate on its own notional.

    The take profit rests as a limit here, so it earns the maker rate; the entry crosses
    the book and pays taker. A single blended round-trip rate cannot express that.

        entry fee = 1 * 100.00 * 0.00100 = 0.1000  (taker)
        exit  fee = 1 * 110.00 * 0.00040 = 0.0440  (maker)
        realized  = 10.00 - 0.1000 - 0.0440 = 9.856
    """
    costs = CostConfig(
        taker_rate=0.001,
        maker_rate=0.0004,
        role_liquidity={"take_profit": Liquidity.MAKER},
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

    entry, exit_ = result.fills[0], result.fills[1]
    assert (entry.role, entry.liquidity, entry.fee_rate) == ("entry", "taker", 0.001)
    assert (exit_.role, exit_.liquidity, exit_.fee_rate) == ("take_profit", "maker", 0.0004)
    assert entry.fee == pytest.approx(0.1)
    assert exit_.fee == pytest.approx(0.044)
    assert result.trades[0].realized_pnl == pytest.approx(9.856)


@pytest.mark.conformance("EXEC-004")
def test_exec_004_gap_through_the_stop_fills_at_the_gap_price(
    instrument, costs, margin, sizing, sim
):
    """EXEC-004: bar 2 opens at 93.00, already through the 95.00 stop.

    With ``stop_is_stop_market=True`` the fill is the open (93.00), not the stop.

        exit fee = 1 * 93.00 * 0.001 = 0.093
        realized = -7.00 - 0.100 - 0.093 = -7.193
    """
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 93.0, 94.0, 92.0, 93.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=replace(sim, stop_is_stop_market=True),
    )

    t = result.trades[0]
    assert t.exit_price == 93.0
    assert t.exit_reason == "stop"
    assert t.realized_pnl == pytest.approx(-7.193)


@pytest.mark.conformance("EXEC-004")
def test_exec_004_stop_limit_rests_at_its_level(instrument, costs, margin, sizing, sim):
    """EXEC-004: project default is stop-LIMIT — fill at 95.00 even when the bar gaps to 93.

    Small-size policy: the resting limit is assumed to fill at its price.
    """
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 93.0, 94.0, 92.0, 93.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    assert result.trades[0].exit_price == 95.0


@pytest.mark.conformance("EXEC-005")
def test_exec_005_take_profit_limit_does_not_take_a_favourable_gap(
    instrument, costs, margin, sizing, sim
):
    """EXEC-005: bar 2 gaps to 115.00 and the resting 110.00 limit still fills at 110.00.

    A limit order at 110.00 does not become a better price because the market jumped past
    it: the order was in the book at 110.00 and that is where it traded.
    """
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 115.0, 116.0, 114.0, 115.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    t = result.trades[0]
    assert t.exit_price == 110.0
    assert t.exit_reason == "target"
    assert t.realized_pnl == pytest.approx(9.79)


@pytest.mark.conformance("EXEC-005")
def test_exec_005_market_triggered_take_profit_does_slip(
    instrument, margin, sizing, sim
):
    """EXEC-005: a take profit executed as a market order slips, and adversely.

        fill     = 110.00 * (1 - 0.001) = 109.89
        exit fee = 109.89 * 0.001 = 0.10989
        realized = 9.89 - 0.100 - 0.10989 = 9.68011
    """
    costs = CostConfig(taker_rate=0.001, market_exit_slippage=0.001)
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=replace(sim, take_profit_is_limit=False),
    )

    t = result.trades[0]
    assert t.exit_price == pytest.approx(109.89)
    assert t.realized_pnl == pytest.approx(9.68011)


@pytest.mark.conformance("EXEC-006")
def test_exec_006_both_levels_in_one_bar_resolve_adversely_and_are_labelled(
    instrument, costs, margin, sizing, sim
):
    """EXEC-006: bar 2 spans 94.00..111.00 and contains both levels.

    An OHLC candle does not say which came first. The adverse branch is taken and the
    trade is labelled, so the frequency of the assumption and its cost are both
    reportable rather than buried in the equity curve.
    """
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 94.0, 100.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    t = result.trades[0]
    assert t.exit_price == 95.0
    assert t.exit_reason == "stop"
    assert t.ambiguous_intrabar is True
    assert result.meta["summary"]["ambiguous_intrabar"] == 1
    assert any("adverse same-bar convention" in w for w in result.warnings)


@pytest.mark.conformance("EXEC-006")
def test_exec_006_favourable_policy_is_a_sensitivity_not_a_headline(
    instrument, costs, margin, sizing, sim
):
    """EXEC-006: the same bar under the favourable convention, for sensitivity only.

    The pair of numbers is the point: a strategy whose result flips with the convention
    has no evidence, it has a coin toss.
    """
    rows = [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 94.0, 100.0]]
    kw = dict(instrument=instrument, costs=costs, margin=margin, sizing=sizing)

    adverse = run(rows, [long_signal()], sim=sim, **kw)
    favourable = run(rows, [long_signal()], sim=replace(sim, same_bar_policy="favourable"), **kw)

    assert adverse.trades[0].realized_pnl == pytest.approx(-5.195)
    assert favourable.trades[0].realized_pnl == pytest.approx(9.79)
    assert favourable.trades[0].ambiguous_intrabar is True


@pytest.mark.conformance("EXEC-006")
def test_exec_006_touch_bars_resolve_the_ambiguity_with_data(
    instrument, costs, margin, sizing, sim
):
    """EXEC-006: 15-second bars settle the ordering, and the trade stops being ambiguous."""
    touch = (
        [[TF + k * 15_000, 100.0, 100.5, 99.5, 100.0] for k in range(4)]
        + [
            [2 * TF + 0, 100.5, 111.0, 100.0, 110.5],
            [2 * TF + 15_000, 110.5, 111.0, 94.0, 95.0],
            [2 * TF + 30_000, 95.0, 96.0, 94.0, 95.0],
            [2 * TF + 45_000, 95.0, 100.5, 94.5, 100.0],
        ]
    )
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 94.0, 100.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        touch_rows=touch,
    )

    t = result.trades[0]
    assert t.exit_reason == "target"
    assert t.ambiguous_intrabar is False
    assert t.resolved_by_touch is True


@pytest.mark.conformance("EXEC-007")
def test_exec_007_continuous_path_reaches_the_stop_before_liquidation(
    instrument, costs, sizing, sim
):
    """EXEC-007: at leverage 10 the liquidation sits at 90.55, below the 95.00 stop.

        P_liq = (1*100 - 10) / (1 * (1 - 0.005 - 0.001)) = 90.5433... -> 90.55 (ceil)

    Bar 2 travels from 100.00 down to 89.00. On a continuous path 95.00 is reached first,
    so the stop fires and the position is never liquidated. An engine that checks
    liquidation by "was the low beyond it" reports a liquidation here and overstates the
    loss by more than four times.
    """
    margin = MarginConfig(mode=MarginMode.ISOLATED, leverage=10.0)
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.0, 100.5, 89.0, 90.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    t = result.trades[0]
    assert t.liquidation_price == pytest.approx(90.55)
    assert t.exit_price == 95.0
    assert t.exit_reason == "stop"
    assert result.meta["summary"]["n_liquidations"] == 0


@pytest.mark.conformance("EXEC-007")
def test_exec_007_a_gap_past_both_levels_is_a_liquidation(
    instrument, costs, sizing, sim
):
    """EXEC-007: bar 2 opens at 90.00, beyond the stop AND beyond the 90.55 liquidation.

    There was no continuous path in between, so the venue's liquidation engine and the
    stop trigger at the same instant, and the venue wins. The fill is the gap price.

        exit fee = 90.00 * 0.001 = 0.09
        realized = -10.00 - 0.100 - 0.090 = -10.19
    """
    margin = MarginConfig(mode=MarginMode.ISOLATED, leverage=10.0)
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 90.0, 91.0, 88.0, 90.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    t = result.trades[0]
    assert t.exit_reason == "liquidation"
    assert t.exit_price == 90.0
    assert t.realized_pnl == pytest.approx(-10.19)
    assert result.meta["summary"]["n_liquidations"] == 1


@pytest.mark.conformance("EXEC-008")
def test_exec_008_max_hold_exits_at_the_expiring_bars_open(
    instrument, costs, margin, sizing, sim
):
    """EXEC-008: with max_hold_bars = 2 and an entry on bar 1, the exit is bar 3's open.

    The hold is counted from the ENTRY bar index, which is the same arithmetic the live
    runner does from the same entry timestamp, and the order is a market order at the
    bar boundary so it fills at the open.

        exit fee = 100.50 * 0.001 = 0.1005
        realized = 0.50 - 0.100 - 0.1005 = 0.2995
    """
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
        sim=replace(sim, max_hold_bars=2),
    )

    t = result.trades[0]
    assert (t.entry_ts_ms, t.exit_ts_ms, t.hold_bars) == (TF, 3 * TF, 2)
    assert t.exit_price == pytest.approx(100.5)
    assert t.exit_reason == "max_hold"
    assert t.realized_pnl == pytest.approx(0.2995)


@pytest.mark.conformance("EXEC-008")
def test_exec_008_per_signal_max_hold_overrides_the_run_default(
    instrument, costs, margin, sizing, sim
):
    """EXEC-008: a signal carrying its own hold budget is honoured over the run default."""
    result = run(
        [
            SIGNAL_BAR,
            QUIET_BAR_1,
            [2 * TF, 100.0, 101.0, 99.0, 100.5],
            [3 * TF, 100.5, 101.0, 99.5, 100.0],
        ],
        [long_signal(max_hold_bars=1)],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=replace(sim, max_hold_bars=10),
    )

    t = result.trades[0]
    assert t.exit_ts_ms == 2 * TF
    assert t.hold_bars == 1
    assert t.exit_reason == "max_hold"


@pytest.mark.conformance("EXEC-018")
def test_exec_018_multi_leg_take_profit_fills_each_leg_at_its_own_price(
    instrument, costs, margin, sizing, sim
):
    """EXEC-018: 50% at 105.00 on bar 2, the residual 50% at 110.00 on bar 3.

        entry fee = 1.0 * 100.00 * 0.001 = 0.1000
        leg 1 fee = 0.5 * 105.00 * 0.001 = 0.0525
        leg 2 fee = 0.5 * 110.00 * 0.001 = 0.0550
        gross     = 0.5*5.00 + 0.5*10.00 = 7.50
        realized  = 7.50 - 0.2075 = 7.2925
        weighted exit = (0.5*105 + 0.5*110) / 1.0 = 107.50
    """
    result = run(
        [
            SIGNAL_BAR,
            QUIET_BAR_1,
            [2 * TF, 100.0, 106.0, 99.0, 105.0],
            [3 * TF, 105.0, 111.0, 104.0, 110.0],
        ],
        [
            long_signal(
                target=None,
                tp_legs=[
                    {"qty_fraction": 0.5, "price": 105.0, "label": "tp1"},
                    {"qty_fraction": 0.5, "price": 110.0, "label": "tp2"},
                ],
            )
        ],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    assert result.n_trades == 1
    t = result.trades[0]
    assert t.qty == 1.0
    assert t.exit_ts_ms == 3 * TF
    assert t.exit_reason == "target"
    assert t.exit_price == pytest.approx(107.5)
    assert t.fees == pytest.approx(0.2075)
    assert t.realized_pnl == pytest.approx(7.2925)
    assert [(label, qty, price) for label, _ts, qty, price in t.legs] == [
        ("tp1", 0.5, 105.0),
        ("tp2", 0.5, 110.0),
    ]


@pytest.mark.conformance("EXEC-018")
def test_exec_018_a_leg_that_cannot_be_executed_is_refused_not_rounded_away(
    costs, margin, sim
):
    """EXEC-018: a leg below the quantity step is a non-deployable plan, not a rounding.

    With a 0.1 step and a position of 0.1, a 20% leg is 0.02 and cannot be sent. Quietly
    collapsing the plan into a single exit would backtest a strategy nobody can run.
    """
    from tradesim import InstrumentSpec, SizingConfig, SizingMode

    spec = InstrumentSpec(
        symbol="TESTUSDT", tick_size=0.01, qty_step=0.1, min_qty=0.1, min_notional=1.0
    )
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.0, 111.0, 99.0, 110.0]],
        [
            long_signal(
                target=None,
                tp_legs=[
                    {"qty_fraction": 0.2, "price": 105.0, "label": "tp1"},
                    {"qty_fraction": 0.8, "price": 110.0, "label": "tp2"},
                ],
            )
        ],
        instrument=spec,
        costs=costs,
        margin=margin,
        sizing=SizingConfig(mode=SizingMode.FIXED_QTY, fixed_qty=0.1),
        sim=sim,
    )

    assert result.n_trades == 0
    assert result.skip_counts == {"NON_DEPLOYABLE_ORDER_GRANULARITY": 1}


@pytest.mark.conformance("EXEC-019")
def test_exec_019_trailing_stop_only_ratchets_favourably(
    instrument, costs, margin, sizing, sim
):
    """EXEC-019: the trail follows the running high up and never gives ground back.

        after bar 1 (high 105.00): stop = max(95.00, 102.90) = 102.90
        after bar 2 (high 101.00): 98.98 is WORSE than 102.90, so the stop stays
        bar 3 low 102.00 takes the 102.90 trail

        exit fee = 102.90 * 0.001 = 0.1029
        realized = 2.90 - 0.100 - 0.1029 = 2.6971
    """
    result = run(
        [
            SIGNAL_BAR,
            [TF, 100.0, 105.0, 100.0, 104.0],
            [2 * TF, 104.0, 105.0, 103.0, 104.0],
            [3 * TF, 104.0, 104.0, 102.0, 102.5],
        ],
        [long_signal(target=200.0, trail={"distance": 0.02})],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    t = result.trades[0]
    assert t.exit_ts_ms == 3 * TF
    assert t.exit_price == pytest.approx(102.90)
    assert t.exit_reason == "trailing_stop"
    assert t.realized_pnl == pytest.approx(2.6971)


@pytest.mark.conformance("EXEC-019")
def test_exec_019_trailing_activation_offset_is_respected(
    instrument, costs, margin, sizing, sim
):
    """EXEC-019: below the activation threshold the original stop is still the stop."""
    result = run(
        [
            SIGNAL_BAR,
            [TF, 100.0, 101.0, 100.0, 100.5],
            [2 * TF, 100.5, 101.0, 94.0, 95.0],
        ],
        [
            long_signal(
                target=200.0,
                trail={"distance": 0.02, "activation_offset": 0.05},
            )
        ],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    t = result.trades[0]
    assert t.exit_price == 95.0
    assert t.exit_reason == "stop", "an unarmed trail must not replace the hard stop"


@pytest.mark.conformance("EXEC-020")
def test_exec_020_break_even_arms_after_the_bar_that_triggers_it(
    instrument, costs, margin, sizing, sim
):
    """EXEC-020: break-even arms on bar 1's high and protects from bar 2 onward.

    Bar 1 reaches 104.00, arming the +3% trigger and moving the stop to the 100.00 entry.
    Bar 2 falls to 99.00 and is stopped at 100.00, not at the original 95.00.

        exit fee = 100.00 * 0.001 = 0.10
        realized = 0.00 - 0.100 - 0.100 = -0.20
    """
    result = run(
        [
            SIGNAL_BAR,
            [TF, 100.0, 104.0, 100.0, 103.0],
            [2 * TF, 103.0, 103.0, 99.0, 99.5],
        ],
        [
            long_signal(
                target=200.0,
                break_even={"trigger_offset": 0.03, "stop_offset": 0.0},
            )
        ],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    t = result.trades[0]
    assert t.exit_ts_ms == 2 * TF
    assert t.exit_price == 100.0
    assert t.exit_reason == "break_even_stop"
    assert t.realized_pnl == pytest.approx(-0.20)


@pytest.mark.conformance("EXEC-020")
def test_exec_020_break_even_does_not_rescue_the_activating_bar(
    instrument, costs, margin, sizing, sim
):
    """EXEC-020: arming and stopping on the same bar resolves adversely, and is labelled.

    Bar 1 spans 94.00..104.00. The favourable reading arms break-even at 103.00 first and
    survives at 100.00; the adverse reading takes the 95.00 stop. Without sub-bar
    evidence the adverse reading stands and the trade is marked ambiguous.
    """
    result = run(
        [SIGNAL_BAR, [TF, 100.0, 104.0, 94.0, 95.0], [2 * TF, 95.0, 96.0, 94.0, 95.0]],
        [
            long_signal(
                target=200.0,
                break_even={"trigger_offset": 0.03, "stop_offset": 0.0},
            )
        ],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    t = result.trades[0]
    assert t.exit_price == 95.0
    assert t.exit_reason == "stop_entry_bar"
    assert t.ambiguous_intrabar is True
    assert t.realized_pnl == pytest.approx(-5.195)
