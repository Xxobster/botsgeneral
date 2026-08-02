"""Provenance stamping + per-run SQLite / catalog aggregation."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from tradesim import Signal, run_backtest
from tradesim.contracts import BarSeries
from tradesim.research.provenance import PROVENANCE_COLUMNS, collect_provenance
from tradesim.research.store import (
    BacktestStore,
    aggregate_run_catalog,
    per_run_db_path,
)
from tradesim.version import ENGINE_NAME, ENGINE_VERSION


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


def test_collect_provenance_core_fields(tmp_path: Path):
    lock = tmp_path / "requirements.txt"
    lock.write_text("numpy==1.26.0\n", encoding="utf-8")
    ohlcv = tmp_path / "ohlcv.sqlite"
    ohlcv.write_bytes(b"fake-db")
    prov = collect_provenance(
        config={"a": 1, "b": [2, 3]},
        strategy_git_commit="abc123",
        data_path=ohlcv,
        random_seed=42,
        engine_repo=tmp_path,
    )
    assert prov["engine_name"] == ENGINE_NAME
    assert prov["engine_version"] == ENGINE_VERSION
    assert prov["strategy_git_commit"] == "abc123"
    assert prov["random_seed"] == 42
    assert prov["config_hash"]
    assert prov["data_snapshot_id"]
    assert prov["dependency_lock_hash"]
    assert prov["created_at_utc"].endswith("Z")
    for key in PROVENANCE_COLUMNS:
        assert key in prov


def test_provenance_fields_persisted_after_run(tmp_path: Path, instrument, costs, margin):
    bars = _tiny_bars(instrument.symbol)
    sig = Signal(
        ts_ms=0, side=1, symbol=instrument.symbol, stop_price=95.0, target_price=110.0
    )
    db = tmp_path / "single.sqlite"
    bundle = run_backtest(
        strategy_id="prov-demo",
        bars=bars,
        signals=[sig],
        instrument=instrument,
        costs=costs,
        margin=margin,
        store_path=db,
        reports_dir=None,
        report=False,
        print_headline=False,
        plot=False,
        random_seed=7,
        strategy_git_commit="strat-deadbeef",
    )
    assert bundle.provenance["engine_name"] == ENGINE_NAME
    assert bundle.provenance["engine_version"] == ENGINE_VERSION
    assert bundle.provenance["random_seed"] == 7
    assert bundle.provenance["strategy_git_commit"] == "strat-deadbeef"
    assert bundle.provenance["config_hash"] == bundle.result.config_digest
    assert bundle.provenance["created_at_utc"]

    store = BacktestStore(db)
    loaded = store.load_provenance(bundle.run_id)
    assert loaded["engine_name"] == ENGINE_NAME
    assert loaded["engine_version"] == ENGINE_VERSION
    assert loaded["random_seed"] == 7
    assert loaded["strategy_git_commit"] == "strat-deadbeef"
    assert loaded["config_hash"] == bundle.result.config_digest
    assert loaded["created_at_utc"]

    saved = store.load_run(bundle.run_id)
    assert saved.provenance is not None
    assert saved.provenance["engine_name"] == ENGINE_NAME


def test_per_run_store_and_catalog_aggregate(
    tmp_path: Path, instrument, costs, margin
):
    bars = _tiny_bars(instrument.symbol)
    sig = Signal(
        ts_ms=0, side=1, symbol=instrument.symbol, stop_price=95.0, target_price=110.0
    )
    catalog = tmp_path / "catalog.sqlite"
    runs_dir = tmp_path / "runs"
    bundle = run_backtest(
        strategy_id="dual-demo",
        bars=bars,
        signals=[sig],
        instrument=instrument,
        costs=costs,
        margin=margin,
        store_path=catalog,
        runs_dir=runs_dir,
        reports_dir=None,
        report=False,
        print_headline=False,
        plot=False,
        random_seed=99,
    )
    run_db = Path(bundle.store_path)
    assert run_db.exists()
    assert run_db == per_run_db_path(runs_dir, "dual-demo", bundle.run_id)
    assert bundle.catalog_path == str(catalog.resolve())

    run_store = BacktestStore(run_db)
    assert run_store.load_provenance(bundle.run_id)["random_seed"] == 99
    assert len(run_store.load_trades(bundle.run_id)) == 1
    assert run_store.load_bars(bundle.run_id) is not None

    cat = BacktestStore(catalog)
    listed = cat.list_runs("dual-demo")
    assert len(listed) == 1
    assert listed.iloc[0]["run_id"] == bundle.run_id
    assert listed.iloc[0]["config_hash"]
    assert Path(listed.iloc[0]["artifact_path"]) == run_db
    # catalog summary has no embedded bars
    assert cat.load_bars(bundle.run_id) is None

    # rebuild into a fresh catalog via aggregate (idempotent)
    catalog2 = tmp_path / "catalog_rebuilt.sqlite"
    n = aggregate_run_catalog(runs_dir, catalog2)
    assert n == 1
    rebuilt = BacktestStore(catalog2)
    assert len(rebuilt.list_runs("dual-demo")) == 1
    assert rebuilt.load_provenance(bundle.run_id)["random_seed"] == 99
    assert aggregate_run_catalog(runs_dir, catalog2) == 1
