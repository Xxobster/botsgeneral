"""DATA-001 .. DATA-005 — the series is trusted only after it has been checked.

Every one of these defects is silent when it is tolerated. A duplicated bar double-counts
a decision, an out-of-order bar reorders causality, a broken candle invents a touch that
never happened, and a hole in the touch series answers an intrabar ordering question from
whichever half of the bar survived. The engine refuses all of them.
"""

from __future__ import annotations

import pytest

from conftest import QUIET_BAR_1, SIGNAL_BAR, TF, bars, long_signal, run
from tradesim.contracts import InstrumentSpec, SkipReason
from tradesim.engine import DataValidationError, validate_bars


@pytest.mark.conformance("DATA-001")
def test_data_001_duplicate_timestamp_is_rejected():
    """DATA-001: a repeated bar open is refused, never de-duplicated in silence."""
    with pytest.raises(DataValidationError, match="strictly increasing"):
        validate_bars(bars([SIGNAL_BAR, QUIET_BAR_1, QUIET_BAR_1]))


@pytest.mark.conformance("DATA-001")
def test_data_001_out_of_order_bars_are_rejected_not_sorted(
    instrument, costs, margin, sizing, sim
):
    """DATA-001: an out-of-order series is refused, never quietly sorted.

    Sorting would produce a plausible-looking result from a series whose provenance is
    unknown, which is the worst of both outcomes.
    """
    with pytest.raises(DataValidationError, match="strictly increasing"):
        run(
            [SIGNAL_BAR, [2 * TF, 100.0, 101.0, 99.0, 100.0], QUIET_BAR_1],
            [long_signal()],
            instrument=instrument,
            costs=costs,
            margin=margin,
            sizing=sizing,
            sim=sim,
        )


@pytest.mark.conformance("DATA-002")
def test_data_002_ohlc_invariants_are_enforced():
    """DATA-002: high below max(open, close), or low above min(open, close), is refused."""
    with pytest.raises(DataValidationError, match="OHLC invariant"):
        validate_bars(bars([SIGNAL_BAR, [TF, 100.0, 99.0, 98.0, 98.5]]))
    with pytest.raises(DataValidationError, match="OHLC invariant"):
        validate_bars(bars([SIGNAL_BAR, [TF, 100.0, 101.0, 100.5, 100.2]]))


@pytest.mark.conformance("DATA-002")
def test_data_002_non_positive_prices_are_rejected():
    """DATA-002: a zero or negative price is data corruption, not a cheap fill."""
    with pytest.raises(DataValidationError, match="positive"):
        validate_bars(bars([SIGNAL_BAR, [TF, 100.0, 101.0, 0.0, 100.0]]))
    with pytest.raises(DataValidationError, match="positive"):
        validate_bars(bars([SIGNAL_BAR, [TF, 100.0, 101.0, -5.0, 100.0]]))


@pytest.mark.conformance("DATA-003")
def test_data_003_pre_launch_bars_are_skipped_with_a_reason(
    costs, margin, sizing, sim
):
    """DATA-003: a signal whose execution bar precedes the listing is skipped explicitly.

    Backfilled or synthetic pre-listing candles are not tradeable history. The order is
    refused with SKIP_PRE_LAUNCH_BAR rather than filled against a price that no venue
    was quoting.
    """
    spec = InstrumentSpec(
        symbol="TESTUSDT",
        tick_size=0.01,
        qty_step=0.001,
        min_qty=0.001,
        min_notional=1.0,
        launch_ts_ms=10 * TF,
    )
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.0, 101.0, 99.0, 100.0]],
        [long_signal()],
        instrument=spec,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    assert result.n_trades == 0
    assert result.skip_counts == {SkipReason.PRE_LAUNCH_BAR.value: 1}
    assert "launch" in result.skips[0].detail


@pytest.mark.conformance("DATA-004")
def test_data_004_spacing_must_match_the_declared_timeframe():
    """DATA-004: bar spacing that is not a whole number of timeframes is refused.

    Hold counts, funding windows and annualisation are all computed from the declared
    timeframe, so a series that is actually 45-second data labelled as one-minute data
    corrupts every one of them.
    """
    with pytest.raises(DataValidationError, match="not a multiple of the declared timeframe"):
        validate_bars(bars([[0, 100.0, 100.0, 100.0, 100.0], [45_000, 100.0, 101.0, 99.0, 100.0]]))

    # A whole missing bar is a multiple of the timeframe and stays legal: real venues
    # have outages, and the engine must not pretend the gap did not happen either.
    validate_bars(bars([[0, 100.0, 100.0, 100.0, 100.0], [2 * TF, 100.0, 101.0, 99.0, 100.0]]))


@pytest.mark.conformance("DATA-004")
def test_data_004_timestamps_name_the_bar_open(instrument, costs, margin, sizing, sim):
    """DATA-004: ts_ms is a bar's OPEN, so a next-open fill happens AT that timestamp.

    If the timestamps were bar closes, the entry recorded at TF would actually have
    happened at TF + 60000 and every funding window would be one bar late.
    """
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.0, 111.0, 100.0, 110.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    t = result.trades[0]
    assert t.entry_ts_ms == TF
    assert t.entry_price == pytest.approx(QUIET_BAR_1[1]), "fill is the bar's OPEN price"
    assert list(result.equity["ts_ms"]) == [0, TF, 2 * TF]


@pytest.mark.conformance("DATA-005")
def test_data_005_touch_gap_refuses_lower_timeframe_resolution(
    instrument, costs, margin, sizing, sim
):
    """DATA-005: an incomplete touch series does not get to answer the ordering question.

    Bar 2 contains both the 95 stop and the 110 target. The 15-second series covers only
    the first half of that bar, and that half reaches the target. Accepting it would give
    the favourable answer from data that is missing precisely the window where the stop
    was hit. The engine refuses the partial evidence, applies the adverse convention,
    marks the trade ambiguous and reports the gap.
    """
    touch = [
        [TF + 0, 100.0, 100.5, 99.5, 100.0],
        [TF + 15_000, 100.0, 100.5, 99.5, 100.0],
        [TF + 30_000, 100.0, 100.5, 99.5, 100.0],
        [TF + 45_000, 100.0, 100.5, 99.5, 100.0],
        [2 * TF + 0, 100.0, 111.0, 100.0, 110.5],
        [2 * TF + 15_000, 110.5, 111.0, 110.0, 110.5],
        # 2*TF + 30000 and 2*TF + 45000 are missing: the hole is where 94.00 printed.
    ]
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.0, 111.0, 94.0, 100.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        touch_rows=touch,
    )

    t = result.trades[0]
    assert t.resolved_by_touch is False, "partial touch data must not resolve the bar"
    assert t.exit_price == 95.0
    assert t.exit_reason == "stop"
    assert t.ambiguous_intrabar is True
    assert result.meta["summary"]["touch_gaps"] >= 1
    assert any("incomplete touch-timeframe coverage" in w for w in result.warnings)


@pytest.mark.conformance("DATA-005")
def test_data_005_complete_touch_coverage_is_still_used(
    instrument, costs, margin, sizing, sim
):
    """DATA-005: the control. Complete coverage of the same bar does resolve it.

    Without this, refusing every touch series would pass the test above.
    """
    touch = [
        [TF + k * 15_000, 100.0, 100.5, 99.5, 100.0] for k in range(4)
    ] + [
        [2 * TF + 0, 100.0, 111.0, 100.0, 110.5],
        [2 * TF + 15_000, 110.5, 111.0, 110.0, 110.5],
        [2 * TF + 30_000, 110.5, 111.0, 94.0, 95.0],
        [2 * TF + 45_000, 95.0, 100.5, 94.5, 100.0],
    ]
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.0, 111.0, 94.0, 100.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        touch_rows=touch,
    )

    t = result.trades[0]
    assert t.resolved_by_touch is True
    assert t.exit_reason == "target"
    assert t.ambiguous_intrabar is False
    assert result.meta["summary"]["touch_gaps"] == 0
