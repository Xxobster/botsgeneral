"""CAUS-001 .. CAUS-005 — nothing may know a price before it printed.

Look-ahead is the failure mode that produces the most convincing wrong answer, because it
makes an equity curve smoother rather than noisier. These tests attack it from both ends:
a signal cannot reach backwards into the bar that produced it, and no later bar can reach
backwards into a trade that already resolved.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from conftest import QUIET_BAR_1, SIGNAL_BAR, TF, long_signal, run
from tradesim.contracts import EntryRef


def _trade_tuple(t):
    """The fields a re-run must reproduce byte for byte."""
    return (
        t.trade_id,
        t.entry_ts_ms,
        t.entry_price,
        t.qty,
        t.exit_ts_ms,
        t.exit_price,
        t.exit_reason,
        t.realized_pnl,
    )


@pytest.mark.conformance("CAUS-001")
def test_caus_001_signal_bar_range_is_not_post_entry(
    instrument, costs, margin, sizing, sim
):
    """CAUS-001: bar 0 spans 80..120 and must not resolve the trade it produced.

    An engine that fills at bar 0's close and then scans bar 0's own range reports a
    stop-out at 95.00 on bar 0. The causal answer is an entry at bar 1's open of 102.00
    and a target at 110.00 on bar 2.
    """
    result = run(
        [
            [0, 100.0, 120.0, 80.0, 100.0],
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
    assert t.entry_price == 102.0
    assert t.exit_ts_ms == 2 * TF
    assert t.exit_reason == "target"
    assert t.realized_pnl == pytest.approx(7.788)


@pytest.mark.conformance("CAUS-001")
def test_caus_001_close_entry_ref_still_excludes_the_decision_bar(
    instrument, costs, margin, sizing, sim
):
    """CAUS-001: even a fill AT the decision close does not make that bar post-entry.

    ``EntryRef.CLOSE`` models a market order fired the instant the bar closed. The fill
    price is that close, but exposure starts at the next bar, so bar 0's 80.00 low
    cannot stop the trade out.
    """
    result = run(
        [
            [0, 100.0, 120.0, 80.0, 100.0],
            [TF, 102.0, 103.0, 101.0, 102.0],
            [2 * TF, 102.0, 112.0, 101.0, 111.0],
        ],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=replace(margin, leverage=2.0),
        sizing=sizing,
        sim=replace(sim, entry_ref=EntryRef.CLOSE),
    )

    t = result.trades[0]
    assert t.entry_price == 100.0, "fill is the decision bar's close"
    assert t.entry_ts_ms == TF, "but exposure is booked from the next bar"
    assert t.exit_reason == "target"


@pytest.mark.conformance("CAUS-002")
def test_caus_002_future_bars_cannot_change_a_resolved_trade(
    instrument, costs, margin, sizing, sim
):
    """CAUS-002: rewriting bars 3 and 4 leaves the trade that resolved on bar 2 identical."""
    head = [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]]
    kw = dict(
        instrument=instrument, costs=costs, margin=margin, sizing=sizing, sim=sim
    )

    calm = run(
        head + [[3 * TF, 110.0, 111.0, 109.0, 110.0], [4 * TF, 110.0, 111.0, 109.0, 110.0]],
        [long_signal()],
        **kw,
    )
    violent = run(
        head + [[3 * TF, 110.0, 400.0, 1.0, 5.0], [4 * TF, 5.0, 900.0, 1.0, 900.0]],
        [long_signal()],
        **kw,
    )

    assert _trade_tuple(calm.trades[0]) == _trade_tuple(violent.trades[0])


@pytest.mark.conformance("CAUS-003")
def test_caus_003_truncation_reproduces_identical_trades(
    instrument, costs, margin, sizing, sim
):
    """CAUS-003: truncating after bar 2 reproduces everything resolved at or before it.

    This is the property that makes a walk-forward split meaningful: a fold boundary
    must not change what happened before it.
    """
    rows = [
        SIGNAL_BAR,
        QUIET_BAR_1,
        [2 * TF, 100.5, 111.0, 100.0, 110.0],
        [3 * TF, 110.0, 111.0, 94.0, 95.0],
        [4 * TF, 95.0, 96.0, 94.0, 95.0],
    ]
    kw = dict(
        instrument=instrument, costs=costs, margin=margin, sizing=sizing, sim=sim
    )

    full = run(rows, [long_signal()], **kw)
    truncated = run(rows[:3], [long_signal()], **kw)

    assert len(truncated.trades) == 1
    assert _trade_tuple(full.trades[0]) == _trade_tuple(truncated.trades[0])
    assert full.trades[0].exit_ts_ms == 2 * TF


@pytest.mark.conformance("CAUS-004")
def test_caus_004_touch_replay_reads_only_this_decision_bar(
    instrument, costs, margin, sizing, sim
):
    """CAUS-004: the sub-bars of the NEXT decision bar are invisible to this one.

    Bar 2 contains both levels and its own sub-bars reach the target first. Bar 3's
    sub-bars open at 94.00. If the replay were allowed to run past the decision bar's
    window it would find the stop and report an adverse exit at a price that had not
    printed yet.
    """
    touch = (
        [[TF + k * 15_000, 100.0, 100.5, 99.5, 100.0] for k in range(4)]
        + [
            [2 * TF + 0, 100.0, 111.0, 100.0, 110.5],
            [2 * TF + 15_000, 110.5, 111.0, 110.0, 110.5],
            [2 * TF + 30_000, 110.5, 111.0, 110.0, 110.5],
            [2 * TF + 45_000, 110.5, 111.0, 110.0, 110.5],
        ]
        + [[3 * TF + k * 15_000, 94.0, 94.5, 93.0, 94.0] for k in range(4)]
    )
    result = run(
        [
            SIGNAL_BAR,
            QUIET_BAR_1,
            [2 * TF, 100.0, 111.0, 94.0, 110.5],
            [3 * TF, 94.0, 94.5, 93.0, 94.0],
        ],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        touch_rows=touch,
    )

    t = result.trades[0]
    assert t.exit_ts_ms == 2 * TF
    assert t.exit_reason == "target"
    assert t.exit_price == 110.0
    assert t.resolved_by_touch is True


@pytest.mark.conformance("CAUS-005")
def test_caus_005_trailing_update_cannot_use_the_bar_it_resolves(
    instrument, costs, margin, sizing, sim
):
    """CAUS-005: a 2% trail may not use bar 2's own high to stop out on bar 2.

        after bar 1 (high 100.00): stop = max(95.00, 98.00) = 98.00
        bar 2 spans 99.00..105.00. Trailing from bar 2's OWN high would put the stop at
        102.90 and exit at 102.90 on bar 2. The live runner cannot do that: it sees the
        high only once the bar has closed.
        after bar 2: stop = 102.90, and bar 3's low of 102.00 takes it.
    """
    result = run(
        [
            SIGNAL_BAR,
            [TF, 100.0, 100.0, 100.0, 100.0],
            [2 * TF, 100.0, 105.0, 99.0, 104.0],
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


@pytest.mark.conformance("CAUS-005")
def test_caus_005_break_even_cannot_arm_and_rescue_on_one_bar(
    instrument, costs, margin, sizing, sim
):
    """CAUS-005: break-even arming at 103.00 does not save a 95.00 stop on the same bar.

    Bar 2 spans 94.00..104.00, so it both arms the break-even and takes the original
    stop. Without lower-timeframe evidence the adverse sequence stands, and the trade is
    labelled ambiguous so the convention's cost is visible.
    """
    result = run(
        [
            SIGNAL_BAR,
            [TF, 100.0, 100.0, 100.0, 100.0],
            [2 * TF, 100.0, 104.0, 94.0, 95.0],
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
    assert t.exit_price == 95.0
    assert t.exit_reason == "stop"
    assert t.ambiguous_intrabar is True
    assert t.realized_pnl == pytest.approx(-5.195)
