"""Smoke: run_backtest dual-write + provenance columns."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import numpy as np

from tradesim import InstrumentSpec, Signal
from tradesim.contracts import BarSeries
from tradesim.research import run_backtest


def main() -> int:
    tf = 60_000
    rows = [
        [0, 100.0, 101.0, 99.0, 100.5],
        [tf, 100.5, 101.0, 99.0, 100.0],
        [2 * tf, 100.0, 111.0, 99.0, 110.0],
    ]
    arr = np.asarray(rows, dtype=float)
    bars = BarSeries(
        ts_ms=arr[:, 0].astype(np.int64),
        open=arr[:, 1],
        high=arr[:, 2],
        low=arr[:, 3],
        close=arr[:, 4],
        timeframe_ms=tf,
        symbol="BTCUSDT",
    )
    inst = InstrumentSpec(
        symbol="BTCUSDT",
        tick_size=0.1,
        qty_step=0.001,
        min_qty=0.001,
        min_notional=5,
        max_qty=100,
        max_leverage=50,
        maintenance_rate=0.005,
    )
    sig = Signal(
        ts_ms=0,
        side=1,
        symbol="BTCUSDT",
        stop_price=95.0,
        target_price=110.0,
    )
    with tempfile.TemporaryDirectory() as td:
        catalog = Path(td) / "catalog.sqlite"
        runs = Path(td) / "runs"
        bundle = run_backtest(
            strategy_id="platform_smoke",
            strategy_version="1",
            bars=bars,
            signals=[sig],
            instrument=inst,
            store_path=catalog,
            runs_dir=runs,
            run_id="parity-smoke-001",
            random_seed=0,
            print_headline=False,
            plot=False,
        )
        run_file = runs / "platform_smoke" / "parity-smoke-001.sqlite"
        print("trades", len(bundle.result.trades))
        print("catalog_exists", catalog.exists(), "run_exists", run_file.exists())
        with sqlite3.connect(catalog) as c:
            cols = [r[1] for r in c.execute("PRAGMA table_info(backtest_runs)")]
            row = c.execute(
                "SELECT engine_version, config_hash, random_seed, artifact_path "
                "FROM backtest_runs LIMIT 1"
            ).fetchone()
        needed = ["engine_version", "config_hash", "random_seed", "artifact_path"]
        print("cols_ok", all(x in cols for x in needed))
        print("row", row)
        assert catalog.exists() and run_file.exists()
        assert all(x in cols for x in needed)
    print("e2e ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
