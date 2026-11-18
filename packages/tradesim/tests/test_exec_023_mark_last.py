"""EXEC-023: independent Mark triggers and Last fills on aligned execution bars."""

from dataclasses import replace

import numpy as np
import pytest

from tradesim import (
    DataValidationError,
    EntryOrder,
    MaintenanceTier,
    MarginConfig,
    MarginMode,
    SameBarPolicy,
    Side,
    Signal,
    SimConfig,
    run_backtest,
    simulate,
)
from tradesim.exits import AmbiguousBarError

from conftest import TF, bars


HOUR = 60 * TF
MINUTE = 60_000


def last_rows(*, high=100, low=100, close=100):
    return [[0, 100, 100, 100, 100], [TF, 100, 100, 100, 100],
            [2 * TF, 100, high, low, close], [3 * TF, 100, 100, 100, 100]]


def mark_rows(*, open_=100, high=100):
    rows = last_rows()
    rows[2] = [2 * TF, open_, high, 100, 100]
    return rows


def short(*, stop=105, target=95):
    return Signal(0, Side.SHORT, "TESTUSDT", stop_price=stop, target_price=target, qty=1, max_hold_bars=2)


def mark_stop(**kwargs):
    return SimConfig(stop_is_stop_market=True, stop_trigger="mark", **kwargs)


@pytest.mark.conformance("EXEC-023")
def test_exec_023_stop_triggers_on_mark_and_fills_on_last(instrument, costs, margin):
    result = simulate(
        bars=bars(last_rows(high=101)), mark_bars=bars(mark_rows(high=106)),
        signals=[short()], instrument=instrument, costs=costs, margin=margin, sim=mark_stop(),
    )
    t = result.trades[0]
    assert (t.exit_reason, t.exit_ts_ms, t.exit_price) == ("stop", 2 * TF, 101)
    assert t.ambiguous_intrabar
    at_open = simulate(
        bars=bars(last_rows(high=101)), mark_bars=bars(mark_rows(open_=106, high=107)),
        signals=[short()], instrument=instrument, costs=replace(costs, market_exit_slippage=0.001),
        margin=margin, sim=mark_stop(),
    )
    assert at_open.trades[0].exit_price == pytest.approx(100.10)
    assert not at_open.trades[0].ambiguous_intrabar


@pytest.mark.conformance("EXEC-023")
def test_exec_023_liquidation_triggers_on_mark(instrument, costs):
    spec = replace(instrument, maintenance_tiers=(MaintenanceTier(0, 0.005, 100),))
    common = dict(signals=[short(stop=None)], instrument=spec, costs=costs, margin=MarginConfig(leverage=5))
    mark = simulate(bars=bars(last_rows()), mark_bars=bars(mark_rows(high=140)), **common)
    assert mark.liquidation_status == "MODELLED"
    trade = mark.trades[0]
    assert 100 < trade.liquidation_price < 140
    assert (trade.exit_reason, trade.exit_ts_ms, trade.exit_price) == ("liquidation", 2 * TF, 100)
    last = simulate(bars=bars(last_rows(high=140)), mark_bars=bars(last_rows()), **common)
    assert last.trades[0].exit_reason == "max_hold"
    legacy = simulate(bars=bars(last_rows(high=140)), **common)
    assert legacy.trades[0].exit_reason == "liquidation"
    assert legacy.liquidation_status != "MODELLED"


@pytest.mark.conformance("EXEC-023")
def test_exec_023_last_stop_and_take_profit_do_not_use_mark(instrument, costs, margin):
    result = simulate(
        bars=bars(last_rows(high=107)), mark_bars=bars(last_rows()),
        signals=[short()], instrument=instrument, costs=costs, margin=margin,
        sim=SimConfig(stop_is_stop_market=True),
    )
    assert result.trades[0].exit_reason == "stop"
    mark_only_target = simulate(
        bars=bars(last_rows()), mark_bars=bars(last_rows(low=94)),
        signals=[short()], instrument=instrument, costs=costs, margin=margin, sim=mark_stop(),
    )
    assert mark_only_target.trades[0].exit_reason == "max_hold"
    last_target = simulate(
        bars=bars(last_rows(low=94)), mark_bars=bars(last_rows()),
        signals=[short()], instrument=instrument, costs=costs, margin=margin, sim=mark_stop(),
    )
    assert last_target.trades[0].exit_reason == "target"


@pytest.mark.conformance("EXEC-023")
def test_exec_023_same_subbar_dual_feed_ambiguity(instrument, costs, margin):
    args = dict(
        bars=bars(last_rows(high=101, low=94)), mark_bars=bars(mark_rows(high=106)),
        signals=[short()], instrument=instrument, costs=costs, margin=margin,
    )
    adverse = simulate(**args, sim=mark_stop()).trades[0]
    assert adverse.exit_reason == "stop"
    assert adverse.ambiguous_intrabar
    favourable = simulate(**args, sim=mark_stop(same_bar_policy=SameBarPolicy.FAVOURABLE)).trades[0]
    assert favourable.exit_reason == "target"
    assert favourable.ambiguous_intrabar
    with pytest.raises(AmbiguousBarError):
        simulate(**args, sim=mark_stop(same_bar_policy=SameBarPolicy.RAISE))


@pytest.mark.conformance("EXEC-023")
def test_exec_023_simultaneous_last_stop_and_mark_liquidation_at_open(instrument, costs):
    last = last_rows()
    last[2] = [2 * TF, 106, 106, 106, 106]
    result = simulate(
        bars=bars(last), mark_bars=bars(mark_rows(open_=140, high=140)),
        signals=[short()], instrument=instrument, costs=costs,
        margin=MarginConfig(leverage=5), sim=SimConfig(stop_is_stop_market=True),
        funding_ts_ms=np.array([2 * TF]), funding_rate=np.array([0.01]),
    )
    assert result.trades[0].exit_reason == "liquidation"
    assert result.trades[0].exit_price == 106  # market execution on Last, never Mark
    assert not result.funding_charges  # certain boundary uses [entry, exit)


@pytest.mark.conformance("EXEC-023")
def test_exec_023_no_pre_fill_mark_trigger_and_no_funding_after_exit(instrument, costs, margin):
    last = [[HOUR + i * MINUTE, 100, 100, 100, 100] for i in range(60)]
    mark = [row.copy() for row in last]
    last[8] = [HOUR + 8 * MINUTE, 100, 101, 100, 100]
    last[20] = [HOUR + 20 * MINUTE, 100, 101, 100, 100]
    mark[3][2] = 106  # prior to the Last limit fill, so the stop is unarmed
    mark[20][2] = 106
    decision = bars([[0, 100, 100, 100, 100], [HOUR, 100, 101, 100, 100]], HOUR)
    fund_times = np.array([HOUR + i * MINUTE for i in (2, 12, 20, 28)], dtype=np.int64)
    result = run_backtest(
        strategy_id="mark_last_fixture", bars=decision, touch_bars=bars(last, MINUTE), mark_bars=bars(mark, MINUTE),
        signals=[replace(short(), entry_order=EntryOrder.LIMIT, limit_price=101)],
        instrument=instrument, costs=costs, margin=margin, sim=mark_stop(),
        funding_ts_ms=fund_times, funding_rate=np.full(len(fund_times), 0.01),
        store_path=None, report=False, plot=False, print_headline=False,
    ).result
    trade = result.trades[0]
    assert trade.entry_ts_ms == HOUR + 8 * MINUTE
    assert trade.exit_ts_ms == HOUR + 20 * MINUTE
    assert (trade.entry_price, trade.exit_price, trade.exit_reason) == (101, 101, "stop_entry_bar")
    assert [fill.ts_ms for fill in result.fills] == [trade.entry_ts_ms, trade.exit_ts_ms]
    assert [settlement.ts_ms for settlement in result.funding_charges] == list(fund_times[[1, 2]])
    assert trade.funding == pytest.approx(2.0)


@pytest.mark.conformance("EXEC-023")
def test_exec_023_rejects_missing_mark_and_gaps(instrument, costs, margin):
    args = dict(bars=bars(last_rows()), signals=[short()], instrument=instrument, costs=costs, margin=margin,
                sim=mark_stop())
    with pytest.raises(DataValidationError, match="Mark stop requires Mark bars"):
        simulate(**args)
    with pytest.raises(DataValidationError, match="missing aligned Mark bar"):
        simulate(**args, mark_bars=bars(last_rows()[:2] + last_rows()[3:]))
    with pytest.raises(DataValidationError, match="resolution timeframes differ"):
        simulate(**args, mark_bars=bars(last_rows(), TF // 2))
    with pytest.raises(ValueError, match="requires isolated margin"):
        simulate(**dict(args, margin=MarginConfig(mode=MarginMode.CROSS)), mark_bars=bars(last_rows()))
