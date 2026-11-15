from dataclasses import replace

import pytest

from tradesim import CostConfig, MaintenanceTier, MarginConfig, Side, SimConfig, SizingConfig
from tradesim.contracts import Liquidity
from tradesim.engine import SymbolStream, _Engine
from tradesim.working_orders import WorkingIntent, WorkingOrderSlot

from conftest import TF, bars


def slot(instrument, *, entry_fee=Liquidity.MAKER):
    spec = replace(instrument, maintenance_tiers=(MaintenanceTier(0, 0.005, 100),))
    costs = CostConfig().with_role_liquidity(entry=entry_fee)
    return WorkingOrderSlot(spec, MarginConfig(leverage=5), costs, risk_fraction=0.01)


def intent(order_id="one", start=1000, *, side=Side.SHORT):
    return WorkingIntent(order_id, side, start, start + 5, start + 6, start + 100,
                         start + 2, start + 3, 99.99, 100.01, 101 if side == Side.SHORT else 99,
                         106 if side == Side.SHORT else 94)


def admit(book, order, *, equity=10000, available=10000, used=0, exposed=False):
    return book.admit(order, equity=equity, used_margin=used,
                      available_margin=available, position_open=exposed)


@pytest.mark.parametrize(("side", "limit"), [(Side.SHORT, 99.99), (Side.LONG, 100.01)])
def test_post_only_equal_quote_rejected_for_both_sides(instrument, side, limit):
    book = slot(instrument)
    outcome = admit(book, replace(intent(side=side), limit_price=limit))
    assert outcome.status == "LIMIT_WOULD_CROSS"
    assert book.order is None


def test_expiry_releases_only_once_and_can_precede_admission_at_same_timestamp(instrument):
    book = slot(instrument)
    first = admit(book, intent()).order
    assert first.qty == 20
    assert first.reserved_margin == 404
    assert first.reserved_risk == 100
    assert admit(book, intent("two", 1040)).status == "WORKING_ORDER"
    expired = book.expire(1100, coverage_confirmed=True)
    assert (expired.margin_released, expired.risk_released) == (404, 100)
    with pytest.raises(ValueError, match="observable pending"):
        book.expire(1100, coverage_confirmed=True)
    assert admit(book, intent("three", 1095)).ts_ms == expired.ts_ms
    assert book.order.intent.order_id == "three"


def test_partial_fill_uses_reserved_price_and_conserves_allocation(instrument):
    book = slot(instrument)
    order = admit(book, intent()).order
    for ts in (1006, 1100):
        with pytest.raises(ValueError, match="active order window"):
            book.book_fill("one", ts, fill_id="outside", qty=1)
    with pytest.raises(ValueError, match="off-step"):
        book.book_fill("one", 1020, fill_id="bad", qty=0.0001)
    fill = book.book_fill("one", 1020, fill_id="print", qty=7)
    assert fill.status == "PARTIAL_FILL"
    assert (fill.fill.qty, fill.fill.price, fill.order.remaining_qty) == (7, 101, 13)
    assert book.book_fill("one", 1020, fill_id="print", qty=7).status == "DUPLICATE_FILL"
    with pytest.raises(ValueError, match="Conflicting"):
        book.book_fill("one", 1020, fill_id="print", qty=8)
    expiration = book.expire(1100, coverage_confirmed=True)
    assert fill.margin_to_position + expiration.margin_released == pytest.approx(order.initial_margin)
    assert fill.risk_to_position + expiration.risk_released == pytest.approx(order.risk)
    assert fill.fee_reserve_released == pytest.approx(fill.fill.fee)
    assert fill.fee_reserve_released + expiration.fee_reserve_released == pytest.approx(order.entry_fee)
    assert admit(book, intent("three", 1100), exposed=True).status == "POSITION_OPEN"


def test_cost_stress_charges_taker_rate_without_changing_passive_fill(instrument):
    results = []
    for liquidity in (Liquidity.MAKER, Liquidity.TAKER):
        book = slot(instrument, entry_fee=liquidity)
        order = admit(book, intent()).order
        result = book.book_fill("one", 1020, fill_id="print", qty=order.qty)
        assert result.status == "FILLED" and book.order is None
        assert result.execution_liquidity == Liquidity.MAKER
        assert result.fill.liquidity == liquidity.value
        assert result.fill.slippage_cost == 0
        results.append(result)
    a, b = results
    assert (a.ts_ms, a.fill.price, a.fill.qty) == (b.ts_ms, b.fill.price, b.fill.qty)
    assert b.fill.fee > a.fill.fee


def test_gap_keeps_pending_state_unknown_and_blocks_admission(instrument):
    book = slot(instrument)
    before = admit(book, intent()).order
    censored = book.expire(1100, coverage_confirmed=False)
    assert censored.status == "CAPTURE_GAP" and censored.margin_released == 0
    assert censored.order.reserved_margin == before.reserved_margin
    assert admit(book, intent("later", 1101)).status == "CAPTURE_GAP"
    with pytest.raises(ValueError, match="observable order"):
        book.book_fill("one", 1120, fill_id="after-gap", qty=1)


def test_full_risk_and_margin_checks_run_at_admission(instrument):
    assert admit(slot(instrument), intent(), equity=0.1).status == "SKIP_MIN_QTY_RISK_CAP"
    assert admit(slot(instrument), intent(), available=404).status == "INSUFFICIENT_MARGIN"
    assert admit(slot(instrument), intent(), used=5800).status == "MARGIN_UTILISATION_CAP"
    stale = replace(intent("stale", 6000), quote_exchange_ms=10, quote_received_ms=20)
    assert admit(slot(instrument), stale).status == "QUOTE_STALE_OR_FUTURE"


def test_confirmed_cancellation_releases_only_the_pending_remainder(instrument):
    book = slot(instrument)
    reservation = admit(book, intent()).order
    fill = book.book_fill("one", 1020, fill_id="print", qty=7)
    cancellation = book.cancel(1021, order_id="one")
    assert cancellation.status == "CANCELLED"
    assert fill.margin_to_position + cancellation.margin_released == pytest.approx(reservation.initial_margin)
    assert book.order is None


def test_canonical_ledger_aggregates_partial_entries_and_reuses_mark_stop(instrument):
    book = slot(instrument)
    last = bars([[0, 101, 101, 95, 101], [TF, 103, 103, 103, 103]])
    mark = bars([[0, 101, 102, 101, 101], [TF, 107, 107, 107, 107]])
    engine = _Engine(streams=[SymbolStream(book.spec.symbol, book.spec, last, mark_bars=mark)],
                     costs=book.costs, margin=book.margin, sizing=SizingConfig(),
                     sim=SimConfig(stop_trigger="mark", stop_is_stop_market=True),
                     run_id="synthetic-partials", attach_stamp=False)
    rt = engine.runtimes[book.spec.symbol]
    order = admit(book, intent()).order
    first = book.book_fill("one", 1020, fill_id="first", qty=7)
    second = book.book_fill("one", 1030, fill_id="second", qty=5)
    opened = engine._apply_reserved_entry_fill(rt, first, target_price=97, entry_bar_index=0, max_hold_bars=16)
    assert opened.qty == 7
    same = engine._apply_reserved_entry_fill(rt, second, target_price=97, entry_bar_index=0, max_hold_bars=16)
    assert same is opened and same.qty == 12 and len(rt.positions) == 1
    assert same.entry_ts_ms == 1020
    expiry = book.expire(1100, coverage_confirmed=True)
    assert same.initial_margin + expiry.margin_released == pytest.approx(order.initial_margin)
    assert engine.cash == pytest.approx(10000 - first.fill.fee - second.fill.fee)

    policy = replace(engine.policy, tick_size=book.spec.tick_size)
    # Resolve the next fully observed minute with the existing shared exit logic.
    engine._resolve_position(rt, same, last.bar(1), 1, policy, just_opened=False)
    trade, = engine.trades
    assert not rt.positions
    assert (trade.qty, trade.exit_reason, trade.exit_price) == (12, "stop", 103)
    assert len({entry.trade_id for entry in engine.fills}) == 1
    assert [entry.qty for entry in engine.fills] == [7, 5, 12]
    assert trade.realized_pnl == pytest.approx(-24 - sum(entry.fee for entry in engine.fills))
