"""PORT-001 .. PORT-004 — one wallet, one clock, one event stream.

Adding up per-symbol equity curves produces a portfolio that could never have existed: it
has as much margin as it needs, it never turns a signal down because another position was
already using the money, and its drawdowns are the average of the parts rather than what
happens when they all go wrong on the same afternoon.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from conftest import QUIET_BAR_1, SIGNAL_BAR, TF, bars, long_signal
from tradesim import InstrumentSpec, MarginConfig, MarginMode, SkipReason, simulate
from tradesim.engine import SymbolStream

WINNER = [SIGNAL_BAR, [TF, 100.0, 111.0, 99.0, 110.0], [2 * TF, 110.0, 111.0, 109.0, 110.0]]
LOSER = [SIGNAL_BAR, [TF, 100.0, 101.0, 94.0, 99.0], [2 * TF, 99.0, 100.0, 98.0, 99.0]]
QUIET = [SIGNAL_BAR, [TF, 100.0, 101.0, 99.0, 100.0], [2 * TF, 100.0, 101.0, 99.0, 100.0]]


def _spec(symbol: str) -> InstrumentSpec:
    return InstrumentSpec(
        symbol=symbol,
        tick_size=0.01,
        qty_step=0.001,
        min_qty=0.001,
        min_notional=1.0,
        maintenance_rate=0.005,
    )


def _stream(symbol: str, rows, signals=None) -> SymbolStream:
    signals = signals if signals is not None else [long_signal()]
    return SymbolStream(
        symbol=symbol,
        instrument=_spec(symbol),
        bars=bars(rows, symbol=symbol),
        signals=tuple(replace(s, symbol=symbol) for s in signals),
    )


def _portfolio(streams, *, costs, margin, sizing, sim):
    from tradesim import simulate_portfolio

    return simulate_portfolio(
        streams=streams,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        run_id="portfolio-test",
        attach_stamp=False,
    )


@pytest.mark.conformance("PORT-001")
def test_port_001_one_chronological_wallet_across_symbols(costs, margin, sizing, sim):
    """PORT-001: two symbols, one wallet, one equity curve with one row per timestamp.

    AAAUSDT loses 5.195 and BBBUSDT makes 9.79. The shared wallet ends at 10004.595, and
    every intermediate row of the curve is the sum of both positions marked at the same
    instant — which is the only way a correlated drawdown can appear at all.
    """
    result = _portfolio(
        [
            _stream("AAAUSDT", LOSER),
            _stream("BBBUSDT", WINNER),
        ],
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    assert result.n_trades == 2
    assert [t.symbol for t in result.trades] == ["AAAUSDT", "BBBUSDT"]
    assert result.ending_equity == pytest.approx(10_004.595)
    assert list(result.equity["ts_ms"]) == [0, TF, 2 * TF]
    assert result.meta["symbols"] == ["AAAUSDT", "BBBUSDT"]


@pytest.mark.conformance("PORT-001")
def test_port_001_shared_wallet_is_not_the_sum_of_standalone_runs(
    costs, sizing, sim
):
    """PORT-001: with margin actually scarce, the two answers differ, and must.

    Run standalone, each symbol has the full 30.00 wallet and both trades happen. Run as
    a portfolio, the first position takes the margin and the second is refused: the
    portfolio makes less money than the sum of its parts, and that difference IS the
    thing a portfolio backtest exists to measure.
    """
    margin = MarginConfig(
        mode=MarginMode.ISOLATED, leverage=10.0, max_margin_utilisation=1.0
    )
    kw = dict(costs=costs, margin=margin, sizing=sizing, sim=replace(sim, starting_equity=15.0))

    standalone = [
        simulate(
            bars=bars(rows, symbol=symbol),
            signals=[replace(long_signal(), symbol=symbol)],
            instrument=_spec(symbol),
            run_id="standalone",
            attach_stamp=False,
            **kw,
        )
        for symbol, rows in (("AAAUSDT", QUIET), ("BBBUSDT", WINNER))
    ]
    together = _portfolio(
        [_stream("AAAUSDT", QUIET), _stream("BBBUSDT", WINNER)], **kw
    )

    assert [r.n_trades for r in standalone] == [1, 1]
    summed = sum(r.ending_equity - r.starting_equity for r in standalone)
    assert together.n_trades == 1
    assert together.ending_equity - together.starting_equity < summed
    assert SkipReason.INSUFFICIENT_MARGIN.value in together.skip_counts


@pytest.mark.conformance("PORT-002")
def test_port_002_simultaneous_signals_use_a_declared_priority(
    costs, sizing, sim
):
    """PORT-002: when the wallet funds only one of two same-bar signals, which one?

    The answer must be declared and deterministic rather than an accident of dictionary
    order. Under 'symbol' priority the alphabetically first symbol is served; under
    'insertion' priority the order the caller supplied them in is honoured. Either is
    defensible; an undeclared one is not reproducible.
    """
    margin = MarginConfig(
        mode=MarginMode.ISOLATED, leverage=10.0, max_margin_utilisation=1.0
    )
    streams = [_stream("BBBUSDT", QUIET), _stream("AAAUSDT", QUIET)]
    kw = dict(costs=costs, margin=margin, sizing=sizing)

    by_symbol = _portfolio(
        streams, sim=replace(sim, starting_equity=15.0, portfolio_priority="symbol"), **kw
    )
    by_insertion = _portfolio(
        streams, sim=replace(sim, starting_equity=15.0, portfolio_priority="insertion"), **kw
    )

    assert [t.symbol for t in by_symbol.trades] == ["AAAUSDT"]
    assert [t.symbol for t in by_insertion.trades] == ["BBBUSDT"]
    assert by_symbol.skips[0].symbol == "BBBUSDT"
    assert by_insertion.skips[0].symbol == "AAAUSDT"


@pytest.mark.conformance("PORT-002")
def test_port_002_priority_is_repeatable(costs, sizing, sim):
    """PORT-002: the same inputs give the same order every time, run after run."""
    margin = MarginConfig(
        mode=MarginMode.ISOLATED, leverage=10.0, max_margin_utilisation=1.0
    )
    kw = dict(
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=replace(sim, starting_equity=15.0),
    )
    runs = [
        _portfolio([_stream("AAAUSDT", QUIET), _stream("BBBUSDT", QUIET)], **kw)
        for _ in range(3)
    ]

    assert {tuple(t.symbol for t in r.trades) for r in runs} == {("AAAUSDT",)}
    assert len({r.config_digest for r in runs}) == 1


@pytest.mark.conformance("PORT-003")
def test_port_003_shared_margin_rejects_the_second_signal_and_records_it(
    costs, sizing, sim
):
    """PORT-003: the rejection is a first-class event with a reason, not a missing trade.

    A 12.00 wallet funds one 100.00 position at leverage 10 and has 2.00 left. The second
    symbol's signal is refused for insufficient margin. Recording it is what lets a
    report say "this strategy needs more capital" instead of quietly showing half the
    trades it thought it took.
    """
    margin = MarginConfig(
        mode=MarginMode.ISOLATED, leverage=10.0, max_margin_utilisation=1.0
    )
    result = _portfolio(
        [_stream("AAAUSDT", QUIET), _stream("BBBUSDT", WINNER)],
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=replace(sim, starting_equity=12.0),
    )

    assert [t.symbol for t in result.trades] == ["AAAUSDT"]
    assert result.skip_counts == {SkipReason.INSUFFICIENT_MARGIN.value: 1}
    skip = result.skips[0]
    assert skip.symbol == "BBBUSDT"
    assert "initial margin" in skip.detail


@pytest.mark.conformance("PORT-004")
def test_port_004_the_portfolio_ledger_reconciles_to_its_components(
    costs, margin, sizing, sim
):
    """PORT-004: fills, funding and trades add up to the wallet, symbol by symbol.

    Every fill fee and every funding cashflow in the portfolio result belongs to exactly
    one trade, and the per-symbol totals sum to the portfolio's.
    """
    result = _portfolio(
        [
            _stream("AAAUSDT", LOSER),
            _stream("BBBUSDT", WINNER),
        ],
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    fees_from_fills = sum(f.fee for f in result.fills)
    fees_from_trades = sum(t.fees for t in result.trades)
    assert fees_from_fills == pytest.approx(fees_from_trades)

    for trade in result.trades:
        own = [f for f in result.fills if f.trade_id == trade.trade_id]
        assert len(own) == 2, "one entry fill and one exit fill"
        assert sum(f.fee for f in own) == pytest.approx(trade.fees)
        assert {f.symbol for f in own} == {trade.symbol}

    gross = sum(t.gross_pnl for t in result.trades)
    funding = sum(t.funding for t in result.trades)
    assert result.starting_equity + gross - fees_from_trades + funding == pytest.approx(
        result.ending_equity
    )


@pytest.mark.conformance("PORT-004")
def test_port_004_equity_rows_track_used_margin_and_open_positions(
    costs, margin, sizing, sim
):
    """PORT-004: the curve carries the exposure that produced it, not just the number.

    Cash, unrealised profit and loss, used margin and the open-position count are all on
    the same row, so a drawdown can be attributed rather than merely observed.
    """
    result = _portfolio(
        [_stream("AAAUSDT", QUIET), _stream("BBBUSDT", QUIET)],
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )

    frame = result.equity
    assert list(frame["open_positions"]) == [0, 2, 2]
    assert list(frame["used_margin"]) == [0.0, 20.0, 20.0]
    assert frame["equity"].iloc[-1] == pytest.approx(
        frame["cash"].iloc[-1] + frame["unrealized"].iloc[-1]
    )
