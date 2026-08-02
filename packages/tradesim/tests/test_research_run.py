"""Research runner: 10k wallet, min size, wallet-blown flag, SQLite persistence."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from conftest import SIGNAL_BAR, TF, bars, long_signal
from tradesim import (
    RESEARCH_STARTING_EQUITY_USDT,
    InstrumentSpec,
    MarginConfig,
    MarginMode,
    Signal,
    SimConfig,
    SizingConfig,
    SizingMode,
    SkipReason,
    research_sizing,
    run_backtest,
)
from tradesim.research.store import BacktestStore


def test_research_defaults_are_10k_and_min_exchange():
    assert RESEARCH_STARTING_EQUITY_USDT == 10_000.0
    assert research_sizing().mode == SizingMode.MIN_EXCHANGE


def test_run_backtest_records_metrics_and_strategy(tmp_path: Path, instrument, costs, margin, sim):
    db = tmp_path / "runs.sqlite"
    sig = Signal(
        ts_ms=0, side=1, symbol=instrument.symbol, stop_price=95.0, target_price=110.0
    )
    series = bars(
        [
            SIGNAL_BAR,
            [TF, 100.0, 101.0, 99.0, 100.5],
            [2 * TF, 100.5, 111.0, 100.0, 110.0],
        ],
        symbol=instrument.symbol,
    )
    bundle = run_backtest(
        strategy_id="demo-strategy",
        strategy_version="1",
        bars=series,
        signals=[sig],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sim=sim,
        store_path=db,
        print_headline=False,
        plot=False,
    )
    assert bundle.metrics.n_trades == 1
    assert bundle.metrics.n_longs == 1
    assert bundle.metrics.n_shorts == 0
    assert bundle.metrics.starting_equity == 10_000.0
    assert bundle.metrics.invested_notional > 0
    assert math.isfinite(bundle.metrics.return_on_invested)
    assert bundle.result.trades[0].qty == pytest.approx(0.01)  # max(min_qty, min_notional/price)
    assert not bundle.wallet_blown

    store = BacktestStore(db)
    listed = store.list_runs("demo-strategy")
    assert len(listed) == 1
    assert listed.iloc[0]["run_id"] == bundle.run_id
    metrics = store.load_metrics(bundle.run_id)
    assert "sharpe" in metrics
    assert "sortino_annualised" in metrics
    assert "win_rate" in metrics
    assert "trades_per_month" in metrics
    assert len(store.load_trades(bundle.run_id)) == 1


def test_wallet_blown_is_flagged(tmp_path: Path, costs):
    """A wiped wallet surfaces as wallet_blown with a timestamp and stop on later signals."""
    instrument = InstrumentSpec(
        symbol="TESTUSDT",
        tick_size=0.01,
        qty_step=0.001,
        min_qty=0.001,
        min_notional=1.0,
        maintenance_rate=0.005,
    )
    series = bars(
        [
            SIGNAL_BAR,
            [TF, 100.0, 101.0, 99.0, 100.0],
            [2 * TF, 85.0, 86.0, 84.0, 85.0],
            [3 * TF, 85.0, 86.0, 84.0, 85.0],
            [4 * TF, 85.0, 96.0, 84.0, 95.0],
        ],
        symbol=instrument.symbol,
    )
    bundle = run_backtest(
        strategy_id="blow-up",
        bars=series,
        signals=[
            long_signal(qty=1.0),
            long_signal(ts_ms=3 * TF, stop=80.0, target=95.0, qty=1.0),
        ],
        instrument=instrument,
        costs=costs,
        margin=MarginConfig(
            mode=MarginMode.ISOLATED, leverage=10.0, max_margin_utilisation=1.0
        ),
        sizing=SizingConfig(mode=SizingMode.FIXED_QTY, fixed_qty=1.0),
        sim=SimConfig(starting_equity=10.0),
        starting_equity=10.0,
        store_path=tmp_path / "blow.sqlite",
        print_headline=False,
    )
    assert bundle.wallet_blown
    assert bundle.metrics.ruined_at_ts_ms == 2 * TF
    assert bundle.result.skip_counts.get(SkipReason.WALLET_RUINED.value) == 1
    listed = BacktestStore(tmp_path / "blow.sqlite").list_runs("blow-up")
    assert int(listed.iloc[0]["wallet_blown"]) == 1
