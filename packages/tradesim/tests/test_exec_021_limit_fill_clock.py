"""EXEC-021 — resting-limit fill clock is the first lower-timeframe touch.

Decision-bar high/low may include both the take-profit and the limit. That does not put
the position in at the decision-bar open. Walk the 1-minute (here 15-second) path: fill
at the limit when it is first touched, then arm take-profit/stop.
"""

from __future__ import annotations

import numpy as np
import pytest

from tradesim import EntryOrder, Side, Signal
from tradesim.fees import first_limit_touch_ts_ms
from tradesim.research.defaults import research_sim_limit_entry

from conftest import TF, long_signal, run, short_signal

TOUCH = 15_000


def _cover(start: int, rows: list[list[float]]) -> list[list[float]]:
    """Four 15-second bars covering one 1-minute decision bar starting at ``start``."""
    out: list[list[float]] = []
    for k, row in enumerate(rows):
        o, h, l, c = row
        out.append([start + k * TOUCH, o, h, l, c])
    if len(out) != 4:
        raise ValueError("need exactly four touch bars per decision minute")
    return out


def test_first_limit_touch_ts_ms_is_vectorized_first_hit():
    ts = np.asarray([0, 15_000, 30_000, 45_000], dtype=np.int64)
    high = np.asarray([101.0, 103.0, 102.0, 99.0], dtype=float)
    low = np.asarray([100.0, 102.0, 98.0, 97.5], dtype=float)
    assert first_limit_touch_ts_ms(
        side=Side.LONG,
        limit_price=98.0,
        ts_ms=ts,
        high=high,
        low=low,
        window_start_ms=0,
        window_end_ms=60_000,
    ) == 30_000
    assert first_limit_touch_ts_ms(
        side=Side.SHORT,
        limit_price=102.5,
        ts_ms=ts,
        high=high,
        low=low,
        window_start_ms=0,
        window_end_ms=60_000,
    ) == 15_000


@pytest.mark.conformance("EXEC-021")
def test_exec_021_take_profit_before_limit_is_not_a_fill(
    instrument, costs, margin, sizing
):
    """EXEC-021: 100 → 103 → 98. The 103 print is not a win. Fill is 98; then stop 95.

    Decision bar 1 (open 100, high 103, low 98) would look like a same-bar target if the
    engine pretended the buy limit 98 filled at the open. 15-second path:

        0–15s: high 103, low 100  (take-profit would fire if already in)
        15–30s: 103..102
        30–45s: low 98            (actual fill at 98)
        45–60s: quiet after fill
    Next minute's low 94 takes the 95 stop.
    """
    touch = (
        _cover(TF, [[100.0, 103.0, 100.0, 103.0], [103.0, 103.0, 102.0, 102.0],
                     [102.0, 102.0, 98.0, 98.0], [98.0, 99.0, 97.5, 98.0]])
        + _cover(2 * TF, [[98.0, 99.0, 97.0, 98.0], [98.0, 98.5, 96.0, 97.0],
                           [97.0, 97.0, 94.0, 95.0], [95.0, 95.5, 94.5, 95.0]])
    )
    result = run(
        [
            [0, 100.0, 100.0, 100.0, 100.0],
            [TF, 100.0, 103.0, 98.0, 99.0],
            [2 * TF, 98.0, 99.0, 94.0, 95.0],
        ],
        [
            long_signal(
                stop=95.0,
                target=103.0,
                qty=1.0,
                entry_order=EntryOrder.LIMIT,
                limit_price=98.0,
            )
        ],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=research_sim_limit_entry(starting_equity=10_000.0, decision_timeframe="1m"),
        touch_rows=touch,
        touch_tf=TOUCH,
    )
    assert result.n_trades == 1
    t = result.trades[0]
    assert t.entry_price == pytest.approx(98.0)
    assert t.exit_reason == "stop"
    assert t.exit_price == pytest.approx(95.0)
    assert t.exit_reason != "target"


@pytest.mark.conformance("EXEC-021")
def test_exec_021_take_profit_after_limit_on_same_decision_bar_still_counts(
    instrument, costs, margin, sizing
):
    """EXEC-021 control: fill first, then take-profit later in the same decision bar."""
    touch = _cover(
        TF,
        [
            [100.0, 100.5, 99.8, 100.2],
            [100.2, 100.2, 98.0, 98.0],
            [98.0, 103.0, 98.0, 103.0],
            [103.0, 103.0, 102.0, 102.5],
        ],
    )
    result = run(
        [
            [0, 100.0, 100.0, 100.0, 100.0],
            [TF, 100.0, 103.0, 98.0, 102.5],
            [2 * TF, 102.5, 103.0, 102.0, 102.5],
        ],
        [
            Signal(
                ts_ms=0,
                side=Side.LONG,
                symbol="TESTUSDT",
                stop_price=95.0,
                target_price=103.0,
                qty=1.0,
                entry_order=EntryOrder.LIMIT,
                limit_price=98.0,
            )
        ],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=research_sim_limit_entry(starting_equity=10_000.0, decision_timeframe="1m"),
        touch_rows=touch,
        touch_tf=TOUCH,
    )
    t = result.trades[0]
    assert t.entry_price == pytest.approx(98.0)
    assert t.exit_reason in ("target", "target_entry_bar")
    assert t.exit_price == pytest.approx(103.0)
    assert t.entry_bar_exit is True


@pytest.mark.conformance("EXEC-021")
def test_exec_021_short_take_profit_before_limit_is_not_a_fill(
    instrument, costs, margin, sizing
):
    """EXEC-021 short: 100 → 97 → 102. The 97 print is not a win. Fill is sell limit 102."""
    touch = (
        _cover(TF, [[100.0, 100.0, 97.0, 97.0], [97.0, 98.0, 97.0, 98.0],
                     [98.0, 102.0, 98.0, 102.0], [102.0, 102.5, 101.5, 102.0]])
        + _cover(2 * TF, [[102.0, 103.0, 101.5, 102.0], [102.0, 104.0, 102.0, 103.0],
                           [103.0, 105.0, 103.0, 105.0], [105.0, 105.5, 104.5, 105.0]])
    )
    result = run(
        [
            [0, 100.0, 100.0, 100.0, 100.0],
            [TF, 100.0, 102.0, 97.0, 102.0],
            [2 * TF, 102.0, 105.0, 101.5, 105.0],
        ],
        [
            short_signal(
                stop=105.0,
                target=97.0,
                qty=1.0,
                entry_order=EntryOrder.LIMIT,
                limit_price=102.0,
            )
        ],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=research_sim_limit_entry(starting_equity=10_000.0, decision_timeframe="1m"),
        touch_rows=touch,
        touch_tf=TOUCH,
    )
    t = result.trades[0]
    assert t.entry_price == pytest.approx(102.0)
    assert t.exit_reason == "stop"
    assert t.exit_price == pytest.approx(105.0)
