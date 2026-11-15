from dataclasses import replace
import sqlite3

import pytest

from tradesim import SimConfig
from tradesim.engine import SymbolStream
from tradesim.research.working_replay_store import save_working_replay
from tradesim.working_replay import WorkingOrderReplay

from conftest import TF, bars
from test_working_orders import intent, slot


def new_replay(instrument, *, hold=16, slippage=0):
    book = slot(instrument)
    envelope = bars([[i * TF, 100, 100, 100, 100] for i in range(3)])
    stream = SymbolStream(book.spec.symbol, book.spec, envelope, mark_bars=envelope)
    config = SimConfig(stop_trigger="mark", stop_is_stop_market=True, close_at_end_of_data=False)
    return WorkingOrderReplay(stream, costs=replace(book.costs, market_exit_slippage=slippage), margin=book.margin, sim=config,
                              risk_fraction=0.01, hold_bars=hold)


def test_replay_has_mark_equity_and_funding_for_quantity_open_at_settlement(instrument):
    sim = new_replay(instrument)
    admission = sim.submit(intent(), target=97, mark=100)
    assert sim.wallet[-1].equity == 10000
    assert sim.wallet[-1].reserved_margin == admission.order.initial_margin
    assert sim.wallet[-1].position_margin == 0
    sim.point(1010, mark=95, last=95, executable_exit=95, target_qty=20)
    assert not sim.fills
    first = sim.fill("one", 1020, fill_id="p1", qty=7, mark=102, last=95, executable_exit=102)
    assert sim.fill("one", 1020, fill_id="p1", qty=7, mark=102, last=95, executable_exit=102).status == "DUPLICATE_FILL"
    assert not sim.trades
    assert sim.wallet[-1].equity == pytest.approx(10000 - first.fill.fee - 7)
    sim.settle(1025, rate=0.001, mark=102)
    assert sim.funding[0].qty == 7
    assert sim.funding[0].cashflow == pytest.approx(0.714)
    with pytest.raises(ValueError, match="tie"):
        sim.fill("one", 1025, fill_id="tie", qty=5, mark=102, last=101, executable_exit=102)
    sim.fill("one", 1030, fill_id="p2", qty=5, mark=101, last=101, executable_exit=102)
    with pytest.raises(ValueError, match="same-millisecond"):
        sim.point(1030, mark=95, last=95, executable_exit=95, target_qty=12)
    with pytest.raises(ValueError, match="Partial take-profit"):
        sim.point(1035, mark=95, last=95, executable_exit=95, target_qty=3)
    expired = sim.expire(1100, mark=101)
    assert sim.wallet[-1].position_qty == 12
    assert sim.wallet[-1].position_margin + expired.margin_released == pytest.approx(admission.order.initial_margin)
    assert sim.wallet[-1].reserved_margin == 0
    sim.point(1120, mark=107, last=101, executable_exit=103, target_qty=0)
    trade, = sim.trades
    assert (trade.exit_price, trade.exit_reason, trade.qty) == (103, "stop_entry_bar", 12)
    assert trade.realized_pnl == pytest.approx(-24 + 0.714 - trade.fees)
    assert sim.wallet[-1].equity == pytest.approx(10000 + trade.realized_pnl)


def test_stop_after_partial_cancels_remainder_before_any_reentry(instrument):
    sim = new_replay(instrument, slippage=0.001)
    order = sim.submit(intent(), target=97, mark=100).order
    assert sim.submit(intent("busy", 1010), target=97, mark=100).status == "WORKING_ORDER"
    sim.fill("one", 1020, fill_id="p1", qty=7, mark=107, last=101, executable_exit=103)
    assert sim.trades[0].exit_ts_ms == 1020
    assert sim.trades[0].exit_price == 103.11
    assert sim.trades[0].slippage_cost == pytest.approx(0.77)
    assert sim.transitions[-1].status == "CANCELLED"
    assert sim.transitions[-1].margin_released == pytest.approx(order.initial_margin * 13 / 20)
    assert sim.wallet[-1].position_qty == sim.wallet[-1].reserved_margin == 0
    with pytest.raises(ValueError, match="observable order"):
        sim.fill("one", 1021, fill_id="late", qty=1, mark=101, last=101, executable_exit=103)


def test_censor_does_not_create_a_terminal_fill(instrument):
    sim = new_replay(instrument)
    sim.submit(intent(), target=97, mark=100)
    sim.fill("one", 1020, fill_id="p1", qty=7, mark=101, last=101, executable_exit=103)
    sim.censor(1030)
    assert sim.censored and sim.transitions[-1].status == "CAPTURE_GAP"
    assert len(sim.fills) == 1 and not sim.trades
    with pytest.raises(ValueError, match="censored"):
        sim.expire(1100, mark=101)


def test_flat_gap_does_not_invalidate_later_certified_data(instrument):
    sim = new_replay(instrument)
    sim.censor(100)
    assert not sim.censored
    assert sim.transitions[-1].status == "COVERAGE_GAP_FLAT"
    assert sim.submit(intent(), target=97, mark=100).status == "RESERVED"


def test_timeout_uses_hour_anchor_and_only_qualified_target_can_fill(instrument):
    sim = new_replay(instrument, hold=1)
    order = sim.submit(intent(), target=97, mark=100).order
    sim.fill("one", 1020, fill_id="p1", qty=order.qty, mark=101, last=101, executable_exit=103)
    sim.point(TF - 1, mark=100, last=95, executable_exit=100, target_qty=0)
    assert not sim.trades
    with pytest.raises(ValueError, match="deadline"):
        sim.point(TF + 1, mark=100, last=95, executable_exit=100, target_qty=20)
    sim.point(TF, mark=100, last=95, executable_exit=100, target_qty=20)
    assert (sim.trades[0].exit_ts_ms, sim.trades[0].exit_reason, sim.trades[0].exit_price) == (TF, "max_hold", 100)


def test_sqlite_ledger_is_idempotent_and_preserves_unresolved_positions(instrument, tmp_path):
    db = tmp_path / "ledger.sqlite"
    identity = dict(protocol_sha256="fixture", data_snapshot="synthetic", engine_sha256="fixture",
                    arm="reference", scenario="baseline")

    def replay():
        sim = new_replay(instrument)
        sim.submit(intent(), target=97, mark=100)
        sim.fill("one", 1020, fill_id="p1", qty=7, mark=101, last=101, executable_exit=103)
        sim.censor(1030)
        return sim

    run_id = save_working_replay(db, identity=identity, replay=replay())
    assert save_working_replay(db, identity=identity, replay=replay()) == run_id
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert conn.execute("SELECT count(*) FROM working_replay_run").fetchone() == (1,)
        rows = dict(conn.execute("SELECT kind,count(*) FROM working_replay_event GROUP BY kind"))
        assert rows == {"fill": 1, "order": 3, "terminal_state": 1, "wallet": 2}
        row, = conn.execute("SELECT json_extract(payload_json, '$.position_qty'), json_extract(payload_json, '$.censored') "
                            "FROM working_replay_event WHERE kind='terminal_state'")
        assert row == (7, 1)
    with pytest.raises(ValueError, match="different ledger"):
        save_working_replay(db, identity=identity, replay=new_replay(instrument))
