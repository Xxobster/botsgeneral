"""Persistence + fingerprint: reload chart without re-simulating."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tradesim import (
    RESEARCH_STARTING_EQUITY_USDT,
    BarSeries,
    Signal,
    compute_metrics,
    run_backtest,
)
from tradesim.research.fingerprint import bars_fingerprint, run_fingerprint
from tradesim.research.plot import _bar_i, _ensure_span_i, _clip_window, _bars_frame
from tradesim.research.store import BacktestStore


def _tiny_bars(symbol: str = "TESTUSDT") -> BarSeries:
    tf = 60_000
    rows = np.array(
        [
            [0, 100.0, 101.0, 99.0, 100.0, 1.0],
            [tf, 100.0, 101.0, 99.0, 100.5, 1.0],
            [2 * tf, 100.5, 111.0, 100.0, 110.0, 1.0],
        ],
        dtype=float,
    )
    return BarSeries.from_rows(rows, timeframe_ms=tf, symbol=symbol)


def test_research_starting_equity_is_10k():
    assert RESEARCH_STARTING_EQUITY_USDT == 10_000.0


def test_bar_index_span_nonzero():
    import pandas as pd

    idx = pd.date_range("2026-01-01", periods=10, freq="h", tz="UTC")
    i0 = _bar_i(int(idx[3].value // 10**6), idx)
    i1 = _bar_i(int(idx[3].value // 10**6), idx)  # same bar
    a, b = _ensure_span_i(i0, i1, len(idx))
    assert b > a
    assert b - a >= 1


def test_store_roundtrip_embeds_bars_and_fingerprint(tmp_path: Path, instrument, costs, margin):
    bars = _tiny_bars(instrument.symbol)
    sig = Signal(
        ts_ms=0, side=1, symbol=instrument.symbol, stop_price=95.0, target_price=110.0
    )
    db = tmp_path / "runs.sqlite"
    reports = tmp_path / "reports"
    meta = {
        "name": "demo-pack",
        "batch": "unit-test",
        "model_name": "demo.joblib",
        "model_path": r"C:\models\demo.joblib",
        "tp_pct": 10.0,
        "sl_pct": 5.0,
    }
    bundle = run_backtest(
        strategy_id="fp-demo",
        bars=bars,
        signals=[sig],
        instrument=instrument,
        costs=costs,
        margin=margin,
        store_path=db,
        reports_dir=reports,
        report=True,
        strategy_meta=meta,
        print_headline=False,
        plot=False,
    )
    assert bundle.metrics.starting_equity == 10_000.0
    assert bundle.report_dir is not None
    report_folder = Path(bundle.report_dir)
    assert (report_folder / "REPORT.md").exists()
    assert (report_folder / "strategy.json").exists()
    assert (report_folder / "metrics.json").exists()
    assert (report_folder / "trades.csv").exists()
    assert (report_folder / "meta.json").exists()
    strat = json.loads((report_folder / "strategy.json").read_text(encoding="utf-8"))
    assert strat["model_path"] == meta["model_path"]
    assert strat["tp_pct"] == 10.0

    store = BacktestStore(db)
    listed = store.list_runs("fp-demo")
    assert len(listed) == 1
    assert listed.iloc[0]["run_fingerprint"]
    assert listed.iloc[0]["bars_fingerprint"]

    saved = store.load_run(bundle.run_id)
    assert saved.bars is not None
    assert len(saved.bars) == len(bars)
    assert saved.verify_bars(bars)
    assert saved.bars_fingerprint == bars_fingerprint(bars)
    assert saved.run_fingerprint == run_fingerprint(
        bars=bars, result=bundle.result, extra={"strategy_id": "fp-demo"}
    )
    assert saved.strategy_meta is not None
    assert saved.strategy_meta["batch"] == "unit-test"
    assert len(saved.result.trades) == 1
    assert saved.result.trades[0].stop_price == pytest.approx(95.0)
    assert saved.result.trades[0].target_price == pytest.approx(110.0)

    # metrics reload without re-sim
    m2 = compute_metrics(saved.result, bars=saved.bars)
    assert m2.n_trades == bundle.metrics.n_trades
    assert m2.net_pnl == pytest.approx(bundle.metrics.net_pnl)


def test_clip_window_max_bars_zero_keeps_full_period():
    import pandas as pd

    bars = _tiny_bars()
    df = _bars_frame(bars)
    eq = pd.DataFrame({"equity": [100.0] * len(df)}, index=df.index)
    out_df, out_eq = _clip_window(df, eq, trades=(), timeframe_ms=60_000, max_bars=0)
    assert len(out_df) == len(df)
    assert len(out_eq) == len(eq)
