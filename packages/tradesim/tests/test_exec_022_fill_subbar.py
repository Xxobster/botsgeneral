"""EXEC-022 — the sub-bar that contains a resting-limit fill is only partly after the fill.

Live evidence 2026-10-17 (ETH long, limit 2380.17, TP +0.5 % = 2392.07): the fill minute
opened at 2394.42 (above the TP), made its high first, then fell to 2378.88 where the limit
filled. The engine used the whole fill minute and booked ``target_entry_bar``; live was stopped.
Conservative rule: in the fill sub-bar only the part that cannot be earlier than the fill counts
(favourable side clipped to the fill price; adverse side kept).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from tradesim import EntryOrder
from tradesim.research.defaults import research_sim_limit_entry

from conftest import TF, long_signal, run, short_signal
from test_exec_021_limit_fill_clock import TOUCH, _cover


def _run(instrument, costs, margin, sizing, rows, touch, signal, conservative=True):
    sim = research_sim_limit_entry(starting_equity=10_000.0, decision_timeframe="1m")
    sim = replace(sim, fill_subbar_conservative=conservative)
    return run(rows, [signal], instrument=instrument, costs=costs, margin=margin,
               sizing=sizing, sim=sim, touch_rows=touch, touch_tf=TOUCH)


def _long_case():
    # limit 98, TP 103, stop 95. Fill sub-bar opens at 103 (TP level) and falls to 98.
    touch = (
        _cover(TF, [[103.0, 103.0, 98.0, 98.5], [98.5, 99.0, 98.0, 98.5],
                    [98.5, 99.0, 98.0, 98.5], [98.5, 99.0, 98.0, 98.5]])
        + _cover(2 * TF, [[98.5, 99.0, 98.0, 98.5], [98.5, 98.5, 96.0, 96.5],
                          [96.5, 96.5, 94.0, 95.0], [95.0, 95.0, 94.5, 94.8]])
    )
    rows = [[0, 100.0, 100.0, 100.0, 100.0], [TF, 103.0, 103.0, 98.0, 98.5],
            [2 * TF, 98.5, 99.0, 94.0, 94.8]]
    sig = long_signal(stop=95.0, target=103.0, qty=1.0, entry_order=EntryOrder.LIMIT, limit_price=98.0)
    return rows, touch, sig


@pytest.mark.conformance("EXEC-022")
def test_exec_022_target_hit_before_fill_in_same_subbar_is_not_a_win(instrument, costs, margin, sizing):
    rows, touch, sig = _long_case()
    r = _run(instrument, costs, margin, sizing, rows, touch, sig, conservative=True)
    assert r.n_trades == 1
    t = r.trades[0]
    assert t.entry_price == pytest.approx(98.0)
    assert t.exit_reason == "stop"


@pytest.mark.conformance("EXEC-022")
def test_exec_022_legacy_flag_reproduces_optimistic_target(instrument, costs, margin, sizing):
    rows, touch, sig = _long_case()
    r = _run(instrument, costs, margin, sizing, rows, touch, sig, conservative=False)
    assert r.trades[0].exit_reason.startswith("target")


@pytest.mark.conformance("EXEC-022")
def test_exec_022_short_mirror(instrument, costs, margin, sizing):
    # short limit 102, TP 97, stop 105. Fill sub-bar opens at 97 (TP) and rises to 102.
    touch = (
        _cover(TF, [[97.0, 102.0, 97.0, 101.5], [101.5, 102.0, 101.0, 101.5],
                    [101.5, 102.0, 101.0, 101.5], [101.5, 102.0, 101.0, 101.5]])
        + _cover(2 * TF, [[101.5, 102.0, 101.0, 101.5], [101.5, 104.0, 101.5, 103.5],
                          [103.5, 106.0, 103.5, 105.5], [105.5, 106.0, 105.0, 105.5]])
    )
    rows = [[0, 100.0, 100.0, 100.0, 100.0], [TF, 97.0, 102.0, 97.0, 101.5],
            [2 * TF, 101.5, 106.0, 101.0, 105.5]]
    sig = short_signal(stop=105.0, target=97.0, qty=1.0, entry_order=EntryOrder.LIMIT, limit_price=102.0)
    r = _run(instrument, costs, margin, sizing, rows, touch, sig, conservative=True)
    assert r.trades[0].exit_reason == "stop"
    r2 = _run(instrument, costs, margin, sizing, rows, touch, sig, conservative=False)
    assert r2.trades[0].exit_reason.startswith("target")


def _case(first_bar, stop, target, limit, after_ok=True):
    """Decision minute 1 whose first 15 s sub-bar is ``first_bar`` (o,h,l,c); later minutes quiet near limit."""
    q = [limit + 0.5, limit + 1.0, limit - 0.5, limit + 0.5]
    touch = (_cover(TF, [first_bar, q, q, q]) + _cover(2 * TF, [q, q, q, q]))
    rows = [[0, limit + 2, limit + 2, limit + 2, limit + 2],
            [TF, first_bar[0], max(first_bar[1], q[1]), min(first_bar[2], q[2]), q[3]],
            [2 * TF, q[0], q[1], q[2], q[3]]]
    sig = long_signal(stop=stop, target=target, qty=1.0, entry_order=EntryOrder.LIMIT, limit_price=limit)
    return rows, touch, sig


@pytest.mark.conformance("EXEC-022")
def test_exec_022_eth_2026_10_17_regression(instrument, costs, margin, sizing):
    # ETH 2026-10-17 21:32: limit 2380.17, TP 2392.07, minute opened 2394.42 (> TP), high 2394.45,
    # low 2378.88 (fill), closed back near the limit. The TP must NOT be booked.
    rows, touch, sig = _case([2394.42, 2394.45, 2378.88, 2380.5], stop=2368.27, target=2392.07, limit=2380.17)
    r = _run(instrument, costs, margin, sizing, rows, touch, sig, conservative=True)
    assert r.n_trades == 1
    assert not r.trades[0].exit_reason.startswith("target")
    legacy = _run(instrument, costs, margin, sizing, rows, touch, sig, conservative=False)
    assert legacy.trades[0].exit_reason.startswith("target")


@pytest.mark.conformance("EXEC-022")
def test_exec_022_fill_minute_close_beyond_target_still_counts(instrument, costs, margin, sizing):
    # The fill minute CLOSES above the TP: price provably went limit -> TP after the fill.
    rows, touch, sig = _case([98.4, 104.0, 98.0, 103.5], stop=95.0, target=103.0, limit=98.0)
    r = _run(instrument, costs, margin, sizing, rows, touch, sig, conservative=True)
    assert r.trades[0].exit_reason.startswith("target")


@pytest.mark.conformance("EXEC-022")
def test_exec_022_stop_before_target_when_both_in_fill_minute(instrument, costs, margin, sizing):
    # Fill minute spans stop 95 and closes beyond TP 103: order unknown -> stop first.
    rows, touch, sig = _case([98.4, 104.0, 94.0, 103.5], stop=95.0, target=103.0, limit=98.0)
    r = _run(instrument, costs, margin, sizing, rows, touch, sig, conservative=True)
    assert r.trades[0].exit_reason.startswith("stop")
