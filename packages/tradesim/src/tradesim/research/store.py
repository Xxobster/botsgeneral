"""SQLite store for backtest runs — metrics, trades, equity, optional embedded bars.

A saved run can be re-opened for metrics + Finplot without re-simulating.
Use ``run_fingerprint`` / ``bars_fingerprint`` to prove two artifacts are the same.

Default research persistence writes a **per-run** SQLite under
``{tradesim_runs_dir()}/{strategy_id}/{run_id}.sqlite`` and upserts a summary
row into the catalog ``tradesim_runs.sqlite``.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from ..contracts import BarSeries, SimResult, Trade
from ..metrics import MetricsReport
from .fingerprint import bars_fingerprint, run_fingerprint, short_id
from .provenance import PROVENANCE_COLUMNS, provenance_column_values


SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT,
    symbol TEXT,
    decision_timeframe TEXT,
    created_at_ms INTEGER NOT NULL,
    starting_equity REAL,
    ending_equity REAL,
    wallet_blown INTEGER NOT NULL DEFAULT 0,
    ruined_at_ts_ms INTEGER,
    metrics_json TEXT NOT NULL,
    stamp_json TEXT,
    config_digest TEXT,
    notes TEXT,
    bars_fingerprint TEXT,
    run_fingerprint TEXT,
    timeframe_ms INTEGER,
    strategy_meta_json TEXT,
    engine_name TEXT,
    engine_version TEXT,
    engine_git_commit TEXT,
    strategy_git_commit TEXT,
    config_hash TEXT,
    data_snapshot_id TEXT,
    dependency_lock_hash TEXT,
    random_seed INTEGER,
    created_at_utc TEXT,
    artifact_path TEXT
);

CREATE TABLE IF NOT EXISTS backtest_trades (
    run_id TEXT NOT NULL,
    trade_id INTEGER NOT NULL,
    symbol TEXT,
    side INTEGER,
    entry_ts_ms INTEGER,
    exit_ts_ms INTEGER,
    entry_price REAL,
    exit_price REAL,
    qty REAL,
    stop_price REAL,
    target_price REAL,
    exit_reason TEXT,
    fees REAL,
    funding REAL,
    gross_pnl REAL,
    realized_pnl REAL,
    return_units REAL,
    hold_bars INTEGER,
    entry_bar_exit INTEGER,
    tp_levels_json TEXT,
    PRIMARY KEY (run_id, trade_id),
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id)
);

CREATE TABLE IF NOT EXISTS backtest_equity (
    run_id TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    equity REAL NOT NULL,
    cash_equity REAL,
    open_positions INTEGER,
    PRIMARY KEY (run_id, ts_ms),
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id)
);

CREATE TABLE IF NOT EXISTS backtest_bars (
    run_id TEXT PRIMARY KEY,
    symbol TEXT,
    timeframe_ms INTEGER NOT NULL,
    n_bars INTEGER NOT NULL,
    bars_fingerprint TEXT NOT NULL,
    ts_ms BLOB NOT NULL,
    open BLOB NOT NULL,
    high BLOB NOT NULL,
    low BLOB NOT NULL,
    close BLOB NOT NULL,
    volume BLOB,
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_runs_strategy ON backtest_runs(strategy_id, created_at_ms);
CREATE INDEX IF NOT EXISTS idx_runs_fingerprint ON backtest_runs(run_fingerprint);
"""

_PROVENANCE_DECLS: tuple[tuple[str, str], ...] = (
    ("engine_name", "TEXT"),
    ("engine_version", "TEXT"),
    ("engine_git_commit", "TEXT"),
    ("strategy_git_commit", "TEXT"),
    ("config_hash", "TEXT"),
    ("data_snapshot_id", "TEXT"),
    ("dependency_lock_hash", "TEXT"),
    ("random_seed", "INTEGER"),
    ("created_at_utc", "TEXT"),
    ("artifact_path", "TEXT"),
)


def _add_column(conn: sqlite3.Connection, table: str, name: str, decl: str) -> None:
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    except sqlite3.OperationalError:
        # Column already present on older DBs that were migrated previously.
        pass


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the first schema without dropping data."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(backtest_runs)").fetchall()}
    legacy = (
        ("bars_fingerprint", "TEXT"),
        ("run_fingerprint", "TEXT"),
        ("timeframe_ms", "INTEGER"),
        ("strategy_meta_json", "TEXT"),
    )
    for name, decl in legacy + _PROVENANCE_DECLS:
        if name not in cols:
            _add_column(conn, "backtest_runs", name, decl)

    tcols = {r[1] for r in conn.execute("PRAGMA table_info(backtest_trades)").fetchall()}
    for name, decl in (
        ("stop_price", "REAL"),
        ("target_price", "REAL"),
        ("return_units", "REAL"),
        ("tp_levels_json", "TEXT"),
    ):
        if name not in tcols:
            _add_column(conn, "backtest_trades", name, decl)


def _meta_json(strategy_meta: Any) -> str | None:
    if strategy_meta is None:
        return None
    if hasattr(strategy_meta, "to_dict"):
        return json.dumps(strategy_meta.to_dict(), default=str)
    if isinstance(strategy_meta, dict):
        return json.dumps(strategy_meta, default=str)
    return json.dumps(strategy_meta, default=str)


def _metrics_payload(metrics: MetricsReport | Mapping[str, Any]) -> dict[str, Any]:
    if hasattr(metrics, "as_dict"):
        return metrics.as_dict()  # type: ignore[no-any-return]
    return dict(metrics)


@dataclass(frozen=True)
class SavedRun:
    """Everything needed to print metrics and re-open the Finplot chart."""

    run_id: str
    strategy_id: str
    strategy_version: str
    result: SimResult
    metrics: dict[str, Any]
    bars: BarSeries | None
    bars_fingerprint: str | None
    run_fingerprint: str | None
    notes: str = ""
    strategy_meta: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    artifact_path: str | None = None

    def verify_bars(self, bars: BarSeries) -> bool:
        if not self.bars_fingerprint:
            return False
        return bars_fingerprint(bars) == self.bars_fingerprint


class BacktestStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            _migrate(conn)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def save(
        self,
        *,
        run_id: str,
        strategy_id: str,
        result: SimResult,
        metrics: MetricsReport | Mapping[str, Any],
        strategy_version: str = "",
        symbol: str = "",
        decision_timeframe: str = "",
        notes: str = "",
        bars: BarSeries | None = None,
        embed_bars: bool = True,
        strategy_meta: Any = None,
        provenance: Mapping[str, Any] | None = None,
        artifact_path: str | None = None,
        summary_only: bool = False,
    ) -> dict[str, str]:
        """Persist a run. Returns ``{bars_fingerprint, run_fingerprint}`` (may be empty).

        When ``summary_only=True``, only the ``backtest_runs`` row is upserted
        (catalog aggregation path — no trades / equity / bars rewrite).
        """
        bars_fp = bars_fingerprint(bars) if bars is not None else None
        run_fp = (
            run_fingerprint(bars=bars, result=result, extra={"strategy_id": strategy_id})
            if bars is not None
            else None
        )
        meta_json = _meta_json(strategy_meta)
        mdict = _metrics_payload(metrics)
        prov_vals = provenance_column_values(provenance)
        created_ms = int(time.time() * 1000)
        if provenance and provenance.get("created_at_utc"):
            # Keep ms aligned when ISO was pre-collected for the dual-write pair.
            pass
        art = artifact_path
        if art is None and provenance is not None:
            art = provenance.get("artifact_path")  # type: ignore[assignment]

        prov_cols_sql = ", ".join(PROVENANCE_COLUMNS)
        prov_placeholders = ", ".join("?" for _ in PROVENANCE_COLUMNS)
        with self._conn() as conn:
            conn.execute(
                f"""
                INSERT OR REPLACE INTO backtest_runs (
                    run_id, strategy_id, strategy_version, symbol, decision_timeframe,
                    created_at_ms, starting_equity, ending_equity, wallet_blown,
                    ruined_at_ts_ms, metrics_json, stamp_json, config_digest, notes,
                    bars_fingerprint, run_fingerprint, timeframe_ms, strategy_meta_json,
                    {prov_cols_sql}, artifact_path
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,{prov_placeholders},?)
                """,
                (
                    run_id,
                    strategy_id,
                    strategy_version,
                    symbol or (result.trades[0].symbol if result.trades else ""),
                    decision_timeframe,
                    created_ms,
                    result.starting_equity,
                    result.ending_equity,
                    1 if bool(mdict.get("wallet_blown")) else 0,
                    mdict.get("ruined_at_ts_ms"),
                    json.dumps(mdict, default=str),
                    json.dumps(result.stamp, default=str) if result.stamp else None,
                    result.config_digest,
                    notes,
                    bars_fp,
                    run_fp,
                    int(bars.timeframe_ms) if bars is not None else None,
                    meta_json,
                    *prov_vals,
                    art,
                ),
            )
            if summary_only:
                return {
                    "bars_fingerprint": bars_fp or "",
                    "run_fingerprint": run_fp or "",
                    "run_fingerprint_short": short_id(run_fp) if run_fp else "",
                }

            conn.execute("DELETE FROM backtest_trades WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM backtest_equity WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM backtest_bars WHERE run_id = ?", (run_id,))
            conn.executemany(
                """
                INSERT INTO backtest_trades (
                    run_id, trade_id, symbol, side, entry_ts_ms, exit_ts_ms,
                    entry_price, exit_price, qty, stop_price, target_price, exit_reason,
                    fees, funding, gross_pnl, realized_pnl, return_units,
                    hold_bars, entry_bar_exit, tp_levels_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        run_id,
                        t.trade_id,
                        t.symbol,
                        int(t.side),
                        t.entry_ts_ms,
                        t.exit_ts_ms,
                        t.entry_price,
                        t.exit_price,
                        t.qty,
                        t.stop_price,
                        t.target_price,
                        t.exit_reason,
                        t.fees,
                        t.funding,
                        t.gross_pnl,
                        t.realized_pnl,
                        t.return_units,
                        t.hold_bars,
                        1 if t.entry_bar_exit else 0,
                        json.dumps(list(getattr(t, "tp_levels", ()) or ()), default=str),
                    )
                    for t in result.trades
                ],
            )
            eq = result.equity
            if eq is not None and len(eq):
                ts = eq["ts_ms"].to_numpy(dtype=np.int64, copy=False)
                equity = eq["equity"].to_numpy(dtype=np.float64, copy=False)
                if "cash" in eq.columns:
                    cash = eq["cash"].to_numpy(dtype=np.float64, copy=False)
                elif "cash_equity" in eq.columns:
                    cash = eq["cash_equity"].to_numpy(dtype=np.float64, copy=False)
                else:
                    cash = equity
                if "open_positions" in eq.columns:
                    open_pos = eq["open_positions"].to_numpy(dtype=np.int64, copy=False)
                else:
                    open_pos = np.zeros(len(eq), dtype=np.int64)
                rows = list(
                    zip(
                        np.full(len(eq), run_id, dtype=object),
                        ts.tolist(),
                        equity.tolist(),
                        cash.tolist(),
                        open_pos.tolist(),
                    )
                )
                conn.executemany(
                    """
                    INSERT INTO backtest_equity (
                        run_id, ts_ms, equity, cash_equity, open_positions
                    ) VALUES (?,?,?,?,?)
                    """,
                    rows,
                )
            if bars is not None and embed_bars:
                vol = (
                    np.asarray(bars.volume, dtype=np.float64).tobytes()
                    if bars.volume is not None
                    else None
                )
                conn.execute(
                    """
                    INSERT INTO backtest_bars (
                        run_id, symbol, timeframe_ms, n_bars, bars_fingerprint,
                        ts_ms, open, high, low, close, volume
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        run_id,
                        getattr(bars, "symbol", symbol) or "",
                        int(bars.timeframe_ms),
                        len(bars),
                        bars_fp,
                        np.asarray(bars.ts_ms, dtype=np.int64).tobytes(),
                        np.asarray(bars.open, dtype=np.float64).tobytes(),
                        np.asarray(bars.high, dtype=np.float64).tobytes(),
                        np.asarray(bars.low, dtype=np.float64).tobytes(),
                        np.asarray(bars.close, dtype=np.float64).tobytes(),
                        vol,
                    ),
                )
        return {
            "bars_fingerprint": bars_fp or "",
            "run_fingerprint": run_fp or "",
            "run_fingerprint_short": short_id(run_fp) if run_fp else "",
        }

    def list_runs(self, strategy_id: str | None = None) -> pd.DataFrame:
        with self._conn() as conn:
            if strategy_id:
                rows = conn.execute(
                    """
                    SELECT run_id, strategy_id, strategy_version, symbol, decision_timeframe,
                           created_at_ms, starting_equity, ending_equity, wallet_blown,
                           ruined_at_ts_ms, notes, bars_fingerprint, run_fingerprint,
                           engine_name, engine_version, config_hash, created_at_utc,
                           artifact_path
                    FROM backtest_runs WHERE strategy_id = ?
                    ORDER BY created_at_ms DESC
                    """,
                    (strategy_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT run_id, strategy_id, strategy_version, symbol, decision_timeframe,
                           created_at_ms, starting_equity, ending_equity, wallet_blown,
                           ruined_at_ts_ms, notes, bars_fingerprint, run_fingerprint,
                           engine_name, engine_version, config_hash, created_at_utc,
                           artifact_path
                    FROM backtest_runs ORDER BY created_at_ms DESC
                    """
                ).fetchall()
        return pd.DataFrame([dict(r) for r in rows])

    def load_metrics(self, run_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT metrics_json FROM backtest_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown run_id {run_id!r}")
        return json.loads(row["metrics_json"])

    def load_trades(self, run_id: str) -> pd.DataFrame:
        with self._conn() as conn:
            return pd.read_sql_query(
                "SELECT * FROM backtest_trades WHERE run_id = ? ORDER BY entry_ts_ms",
                conn,
                params=(run_id,),
            )

    def load_equity(self, run_id: str) -> pd.DataFrame:
        with self._conn() as conn:
            return pd.read_sql_query(
                "SELECT * FROM backtest_equity WHERE run_id = ? ORDER BY ts_ms",
                conn,
                params=(run_id,),
            )

    def load_bars(self, run_id: str) -> BarSeries | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM backtest_bars WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        n = int(row["n_bars"])
        vol_blob = row["volume"]
        volume = (
            np.frombuffer(vol_blob, dtype=np.float64).copy()
            if vol_blob is not None
            else None
        )
        return BarSeries(
            ts_ms=np.frombuffer(row["ts_ms"], dtype=np.int64).copy(),
            open=np.frombuffer(row["open"], dtype=np.float64).copy(),
            high=np.frombuffer(row["high"], dtype=np.float64).copy(),
            low=np.frombuffer(row["low"], dtype=np.float64).copy(),
            close=np.frombuffer(row["close"], dtype=np.float64).copy(),
            volume=volume,
            timeframe_ms=int(row["timeframe_ms"]),
            symbol=str(row["symbol"] or ""),
        )

    def load_provenance(self, run_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            cols = ", ".join(PROVENANCE_COLUMNS)
            row = conn.execute(
                f"SELECT {cols}, artifact_path FROM backtest_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown run_id {run_id!r}")
        return {k: row[k] for k in (*PROVENANCE_COLUMNS, "artifact_path")}

    def load_run(self, run_id: str) -> SavedRun:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM backtest_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown run_id {run_id!r}")
        trades_df = self.load_trades(run_id)
        equity = self.load_equity(run_id)
        trades = tuple(_trade_from_row(r) for r in trades_df.itertuples(index=False))
        metrics = json.loads(row["metrics_json"])
        stamp = json.loads(row["stamp_json"]) if row["stamp_json"] else None
        result = SimResult(
            run_id=run_id,
            trades=trades,
            fills=(),
            funding_charges=(),
            skips=(),
            skip_counts={},
            equity=equity,
            daily_equity=pd.DataFrame(),
            liquidation_status=str(metrics.get("liquidation_status") or "UNKNOWN"),
            starting_equity=float(row["starting_equity"] or 0.0),
            ending_equity=float(row["ending_equity"] or 0.0),
            config_digest=str(row["config_digest"] or ""),
            stamp=stamp,
        )
        meta_raw = None
        try:
            meta_raw = row["strategy_meta_json"]
        except (IndexError, KeyError):
            meta_raw = None
        strategy_meta = json.loads(meta_raw) if meta_raw else None
        provenance = {}
        for k in PROVENANCE_COLUMNS:
            try:
                provenance[k] = row[k]
            except (IndexError, KeyError):
                provenance[k] = None
        artifact = None
        try:
            artifact = row["artifact_path"]
        except (IndexError, KeyError):
            artifact = None
        return SavedRun(
            run_id=run_id,
            strategy_id=str(row["strategy_id"]),
            strategy_version=str(row["strategy_version"] or ""),
            result=result,
            metrics=metrics,
            bars=self.load_bars(run_id),
            bars_fingerprint=row["bars_fingerprint"],
            run_fingerprint=row["run_fingerprint"],
            notes=str(row["notes"] or ""),
            strategy_meta=strategy_meta,
            provenance=provenance,
            artifact_path=str(artifact) if artifact else None,
        )


def per_run_db_path(
    runs_dir: str | Path,
    strategy_id: str,
    run_id: str,
) -> Path:
    """``{runs_dir}/{strategy_id|adhoc}/{run_id}.sqlite``."""
    strat = (strategy_id or "adhoc").strip() or "adhoc"
    # Keep path segment filesystem-safe without destroying readability.
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in strat)
    return Path(runs_dir) / safe / f"{run_id}.sqlite"


def persist_research_run(
    *,
    run_id: str,
    strategy_id: str,
    result: SimResult,
    metrics: MetricsReport | Mapping[str, Any],
    store_path: str | Path,
    runs_dir: str | Path | None = None,
    strategy_version: str = "",
    symbol: str = "",
    decision_timeframe: str = "",
    notes: str = "",
    bars: BarSeries | None = None,
    embed_bars: bool = True,
    strategy_meta: Any = None,
    provenance: Mapping[str, Any] | None = None,
) -> tuple[dict[str, str], str, str | None]:
    """Persist a run (single-file or per-run + catalog).

    Returns ``(fingerprints, primary_db_path, catalog_path_or_none)``.
    """
    catalog = Path(store_path)
    if runs_dir is not None:
        run_db = per_run_db_path(runs_dir, strategy_id, run_id)
        run_store = BacktestStore(run_db)
        fps = run_store.save(
            run_id=run_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            result=result,
            metrics=metrics,
            symbol=symbol,
            decision_timeframe=decision_timeframe,
            notes=notes,
            bars=bars,
            embed_bars=embed_bars,
            strategy_meta=strategy_meta,
            provenance=provenance,
            artifact_path=str(run_db.resolve()),
        )
        catalog_store = BacktestStore(catalog)
        catalog_store.save(
            run_id=run_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            result=result,
            metrics=metrics,
            symbol=symbol,
            decision_timeframe=decision_timeframe,
            notes=notes,
            bars=bars,
            embed_bars=False,
            strategy_meta=strategy_meta,
            provenance=provenance,
            artifact_path=str(run_db.resolve()),
            summary_only=True,
        )
        return fps, str(run_db.resolve()), str(catalog.resolve())

    store = BacktestStore(catalog)
    fps = store.save(
        run_id=run_id,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        result=result,
        metrics=metrics,
        symbol=symbol,
        decision_timeframe=decision_timeframe,
        notes=notes,
        bars=bars,
        embed_bars=embed_bars,
        strategy_meta=strategy_meta,
        provenance=provenance,
        artifact_path=str(catalog.resolve()),
    )
    return fps, str(catalog.resolve()), None


def aggregate_run_catalog(
    runs_dir: str | Path,
    catalog_path: str | Path,
) -> int:
    """Scan completed per-run SQLite files and upsert summary rows into the catalog.

    Idempotent: re-running refreshes catalog rows from per-run DBs. Returns the
    number of run rows upserted.
    """
    root = Path(runs_dir)
    catalog = BacktestStore(catalog_path)
    if not root.is_dir():
        return 0
    n = 0
    for db_path in sorted(root.rglob("*.sqlite")):
        if db_path.resolve() == Path(catalog_path).resolve():
            continue
        try:
            src = BacktestStore(db_path)
        except Exception:
            continue
        with src._conn() as conn:
            rows = conn.execute("SELECT * FROM backtest_runs").fetchall()
        if not rows:
            continue
        for row in rows:
            run_id = str(row["run_id"])
            try:
                saved = src.load_run(run_id)
            except Exception:
                continue
            prov = {k: row[k] if k in row.keys() else None for k in PROVENANCE_COLUMNS}
            catalog.save(
                run_id=run_id,
                strategy_id=saved.strategy_id,
                strategy_version=saved.strategy_version,
                result=saved.result,
                metrics=saved.metrics,
                symbol=saved.result.trades[0].symbol if saved.result.trades else "",
                notes=saved.notes,
                bars=saved.bars,
                embed_bars=False,
                strategy_meta=saved.strategy_meta,
                provenance=prov,
                artifact_path=str(db_path.resolve()),
                summary_only=True,
            )
            n += 1
    return n


def _trade_from_row(r: Any) -> Trade:
    target = getattr(r, "target_price", None)
    if target is not None and (isinstance(target, float) and np.isnan(target)):
        target = None
    raw_tp = getattr(r, "tp_levels_json", None)
    tp_levels: tuple[tuple[str, float, float], ...] = ()
    if raw_tp:
        try:
            parsed = json.loads(raw_tp)
            tp_levels = tuple(
                (str(x[0]), float(x[1]), float(x[2])) for x in parsed if len(x) >= 3
            )
        except Exception:
            tp_levels = ()
    return Trade(
        trade_id=int(r.trade_id),
        symbol=str(r.symbol or ""),
        side=int(r.side),
        entry_ts_ms=int(r.entry_ts_ms),
        entry_price=float(r.entry_price),
        entry_ref_price=float(r.entry_price),
        qty=float(r.qty),
        stop_price=float(r.stop_price if r.stop_price is not None else r.entry_price),
        target_price=float(target) if target is not None else None,
        liquidation_price=None,
        leverage=1.0,
        initial_margin=0.0,
        exit_ts_ms=int(r.exit_ts_ms),
        exit_price=float(r.exit_price),
        exit_reason=str(r.exit_reason or ""),
        hold_bars=int(r.hold_bars or 0),
        fees=float(r.fees or 0.0),
        funding=float(r.funding or 0.0),
        slippage_cost=0.0,
        gross_pnl=float(r.gross_pnl or 0.0),
        realized_pnl=float(r.realized_pnl or 0.0),
        return_units=float(getattr(r, "return_units", 0.0) or 0.0),
        mae=0.0,
        mfe=0.0,
        ambiguous_intrabar=False,
        resolved_by_touch=False,
        entry_bar_exit=bool(int(getattr(r, "entry_bar_exit", 0) or 0)),
        tp_levels=tp_levels,
    )
