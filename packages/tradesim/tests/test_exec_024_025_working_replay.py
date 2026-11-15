"""EXEC-024 (posted vs partially filled vs protected) and EXEC-025 (event chronology, ties, stress).

Synthetic clocks only: a decision at t=1000 ms, an order active from 1006 ms to 1100 ms, 1-minute envelope bars.
"""

from dataclasses import replace

import pytest

from tradesim import CostConfig, Side, SimConfig
from tradesim.contracts import Liquidity
from tradesim.engine import SymbolStream
from tradesim.working_replay import WorkingOrderReplay

from conftest import TF, bars
from test_working_orders import admit, intent, slot
from test_working_replay import new_replay


def replay_with(instrument, costs, *, hold=16):
    book = slot(instrument)
    envelope = bars([[i * TF, 100, 100, 100, 100] for i in range(3)])
    stream = SymbolStream(book.spec.symbol, book.spec, envelope, mark_bars=envelope)
    config = SimConfig(stop_trigger="mark", stop_is_stop_market=True, close_at_end_of_data=False)
    return WorkingOrderReplay(stream, costs=costs, margin=book.margin, sim=config, risk_fraction=0.01, hold_bars=hold)


def filled(sim, qty=20, ts=1020):
    sim.submit(intent(), target=97, mark=100)
    sim.fill("one", ts, fill_id="a", qty=qty, mark=100, last=101, executable_exit=102)


@pytest.mark.conformance("EXEC-024")
@pytest.mark.parametrize(("side", "limit"), [(Side.SHORT, 99.98), (Side.LONG, 100.02)])
def test_post_only_strictly_crossing_limit_is_rejected_and_reserves_nothing(instrument, side, limit):
    book = slot(instrument)
    outcome = admit(book, replace(intent(side=side), limit_price=limit))
    assert outcome.status == "LIMIT_WOULD_CROSS" and book.order is None and outcome.order is None


@pytest.mark.conformance("EXEC-024")
def test_price_and_quantity_are_aligned_on_the_instrument_grid(instrument):
    reserved = admit(slot(instrument), intent()).order
    assert reserved.qty / instrument.qty_step == pytest.approx(round(reserved.qty / instrument.qty_step))
    assert reserved.limit_price / instrument.tick_size == pytest.approx(round(reserved.limit_price / instrument.tick_size))
    assert admit(slot(instrument), replace(intent("off", 1000), stop_price=106.005)).status == "STOP_OFF_TICK_GRID"


@pytest.mark.conformance("EXEC-024")
def test_favourable_print_before_the_first_fill_cannot_close_anything(instrument):
    sim = new_replay(instrument)
    order = sim.submit(intent(), target=97, mark=100).order
    sim.point(1010, mark=96, last=96.5, executable_exit=96.5, target_qty=order.qty)
    sim.point(1015, mark=96, last=95, executable_exit=95, target_qty=order.qty)
    assert not sim.fills and not sim.trades
    assert sim.wallet[-1].position_qty == 0 and sim.wallet[-1].reserved_margin == order.initial_margin
    sim.fill("one", 1020, fill_id="p1", qty=order.qty, mark=100, last=97, executable_exit=97.01)
    assert not sim.trades and sim.fills[0].price == 101
    sim.point(1030, mark=98, last=97, executable_exit=97.01, target_qty=order.qty)
    trade, = sim.trades
    assert (trade.exit_ts_ms, trade.exit_price) == (1030, 97)
    assert trade.exit_ts_ms > trade.entry_ts_ms


@pytest.mark.conformance("EXEC-024")
def test_partial_then_cancel_has_one_accounting_effect_per_slice(instrument):
    book = slot(instrument)
    reservation = admit(book, intent()).order
    first = book.book_fill("one", 1020, fill_id="a", qty=7)
    assert book.book_fill("one", 1020, fill_id="a", qty=7).status == "DUPLICATE_FILL"
    cancelled = book.cancel(1030, order_id="one")
    with pytest.raises(ValueError):
        book.cancel(1030, order_id="one")
    assert first.margin_to_position + cancelled.margin_released == pytest.approx(reservation.initial_margin)
    assert first.risk_to_position + cancelled.risk_released == pytest.approx(reservation.risk)
    assert first.fee_reserve_released + cancelled.fee_reserve_released == pytest.approx(reservation.entry_fee)


@pytest.mark.conformance("EXEC-024")
def test_protection_clocks_distinguish_theoretical_from_attested_arming(instrument):
    sim = new_replay(instrument)
    sim.submit(intent(), target=97, mark=100)
    one = sim.fill("one", 1020, fill_id="a", qty=7, mark=101, last=101, executable_exit=102, protection_attested_ms=1050)
    assert (one.protection_theoretical_ms, one.protection_attested_ms) == (1020, 1050)
    two = sim.fill("one", 1030, fill_id="b", qty=5, mark=101, last=101, executable_exit=102)
    assert (two.protection_theoretical_ms, two.protection_attested_ms) == (1030, None)
    with pytest.raises(ValueError, match="Attested protection"):
        sim.fill("one", 1040, fill_id="c", qty=1, mark=101, last=101, executable_exit=102, protection_attested_ms=1039)


@pytest.mark.conformance("EXEC-024")
def test_gap_with_exposure_is_indeterminate_with_a_reason_and_no_exit(instrument):
    sim = new_replay(instrument)
    filled(sim)
    sim.censor(1040, reason="PRIVATE_STREAM_GAP")
    assert sim.censored and not sim.trades
    assert sim.transitions[-1].status == "CAPTURE_GAP" and sim.transitions[-1].reason == "PRIVATE_STREAM_GAP"
    assert sim.exposure_state()["position_qty"] == 20
    with pytest.raises(ValueError, match="censored"):
        sim.point(1050, mark=90, last=90, executable_exit=90, target_qty=20)


@pytest.mark.conformance("EXEC-025")
def test_funding_tie_with_a_fill_is_unorderable_in_both_orders_and_resolves_to_indeterminate(instrument):
    first = new_replay(instrument)
    first.submit(intent(), target=97, mark=100)
    first.settle(1025, rate=0.001, mark=101)
    with pytest.raises(ValueError, match="tie"):
        first.fill("one", 1025, fill_id="a", qty=7, mark=101, last=101, executable_exit=102)
    first.censor(1025, reason="UNORDERABLE_FUNDING_FILL_TIE")
    assert first.censored and first.transitions[-1].reason == "UNORDERABLE_FUNDING_FILL_TIE" and not first.fills

    second = new_replay(instrument)
    second.submit(intent(), target=97, mark=100)
    second.fill("one", 1025, fill_id="a", qty=7, mark=101, last=101, executable_exit=102)
    with pytest.raises(ValueError, match="tie"):
        second.settle(1025, rate=0.001, mark=101)
    assert not second.funding


@pytest.mark.conformance("EXEC-025")
def test_funding_tie_with_an_exit_is_unorderable_in_both_orders(instrument):
    before = new_replay(instrument)
    filled(before)
    before.settle(1050, rate=0.001, mark=100)
    with pytest.raises(ValueError, match="tie"):
        before.point(1050, mark=100, last=96, executable_exit=97, target_qty=20)
    assert not before.trades and before.funding[0].qty == 20

    after = new_replay(instrument)
    filled(after)
    after.point(1050, mark=100, last=96, executable_exit=97, target_qty=20)
    assert after.trades
    with pytest.raises(ValueError, match="tie"):
        after.settle(1050, rate=0.001, mark=100)
    assert not after.funding


@pytest.mark.conformance("EXEC-025")
def test_funding_is_charged_on_the_quantity_open_at_settlement_only(instrument):
    sim = new_replay(instrument)
    sim.submit(intent(), target=97, mark=100)
    sim.settle(1010, rate=0.001, mark=100)
    sim.fill("one", 1020, fill_id="a", qty=7, mark=100, last=101, executable_exit=102)
    sim.settle(1030, rate=0.001, mark=100)
    sim.fill("one", 1040, fill_id="b", qty=13, mark=100, last=101, executable_exit=102)
    sim.settle(1050, rate=0.001, mark=100)
    assert [f.qty for f in sim.funding] == [7, 20]
    assert [f.cashflow for f in sim.funding] == pytest.approx([0.7, 2.0])


@pytest.mark.conformance("EXEC-025")
def test_expiry_wins_a_clock_tie_with_a_fill_and_with_a_price_event(instrument):
    sim = new_replay(instrument)
    order = sim.submit(intent(), target=97, mark=100).order
    with pytest.raises(ValueError, match="expiration"):
        sim.fill("one", 1100, fill_id="late", qty=1, mark=100, last=101, executable_exit=102)
    with pytest.raises(ValueError, match="expiration"):
        sim.point(1100, mark=100, last=95, executable_exit=95, target_qty=order.qty)
    expired = sim.expire(1100, mark=100)
    assert expired.status == "EXPIRED" and expired.margin_released == order.initial_margin
    with pytest.raises(ValueError, match="observable order"):
        sim.fill("one", 1100, fill_id="late", qty=1, mark=100, last=101, executable_exit=102)
    sim.point(1100, mark=100, last=95, executable_exit=95, target_qty=0)
    assert not sim.fills


@pytest.mark.conformance("EXEC-025")
def test_hold_deadline_ties_with_funding_and_must_be_processed_exactly(instrument):
    sim = new_replay(instrument, hold=1)
    filled(sim)
    with pytest.raises(ValueError, match="deadline"):
        sim.settle(TF, rate=0.001, mark=100)
    sim.point(TF, mark=100, last=101, executable_exit=101.5, target_qty=0)
    trade, = sim.trades
    assert (trade.exit_ts_ms, trade.exit_reason) == (TF, "max_hold")
    with pytest.raises(ValueError, match="tie"):
        sim.settle(TF, rate=0.001, mark=100)


@pytest.mark.conformance("EXEC-025")
def test_all_taker_stress_changes_billing_but_keeps_passive_chronology(instrument):
    maker = slot(instrument).costs.with_role_liquidity(take_profit=Liquidity.MAKER)
    taker = CostConfig(taker_rate=maker.taker_rate, maker_rate=maker.maker_rate)
    runs = []
    for costs in (maker, taker):
        sim = replay_with(instrument, costs)
        order = sim.submit(intent(), target=97, mark=100).order
        sim.fill("one", 1020, fill_id="a", qty=order.qty, mark=100, last=101, executable_exit=102)
        sim.point(1040, mark=98, last=97, executable_exit=97.01, target_qty=order.qty)
        runs.append(sim)
    base, stress = runs

    def chronology(sim):
        return [(f.ts_ms, f.price, f.qty, f.role) for f in sim.fills]

    assert chronology(base) == chronology(stress)
    assert [f.liquidity for f in base.fills] == ["maker", "maker"]
    assert [f.liquidity for f in stress.fills] == ["taker", "taker"]
    assert stress.trades[0].fees > base.trades[0].fees
    assert stress.trades[0].gross_pnl == pytest.approx(base.trades[0].gross_pnl)
