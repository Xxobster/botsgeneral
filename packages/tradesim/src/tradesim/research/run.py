"""One-call research backtest: simulate → metrics → store → report folder → optional Finplot."""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..contracts import (
    BarSeries,
    CostConfig,
    InstrumentSpec,
    MarginConfig,
    Signal,
    SimConfig,
    SimResult,
    SizingConfig,
)
from ..engine import simulate
from ..metrics import MetricsReport, compute_metrics, headline_table
from .defaults import (
    RESEARCH_REPORTS_DIR,
    RESEARCH_STARTING_EQUITY_USDT,
    RESEARCH_STORE_PATH,
    research_costs,
    research_instrument,
    research_margin,
    research_sim,
    research_sizing,
)
from .report import StrategyDetails, write_report
from .store import BacktestStore


def _default_plot() -> bool:
    """Open chart+metrics on interactive terminals; stay quiet in pytest/CI."""
    if os.environ.get("TRADESIM_NO_PLOT", "").strip() in ("1", "true", "yes"):
        return False
    if os.environ.get("TRADESIM_PLOT", "").strip() in ("1", "true", "yes"):
        return True
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


@dataclass(frozen=True)
class BacktestBundle:
    """Everything recorded for one research backtest."""

    run_id: str
    strategy_id: str
    strategy_version: str
    result: SimResult
    metrics: MetricsReport
    headline: str
    store_path: str | None = None
    report_dir: str | None = None
    fingerprints: dict[str, str] = field(default_factory=dict)

    @property
    def wallet_blown(self) -> bool:
        return self.metrics.wallet_blown


def run_backtest(
    *,
    strategy_id: str,
    bars: BarSeries,
    signals: Sequence[Signal],
    instrument: InstrumentSpec | None = None,
    symbol: str | None = None,
    strategy_version: str = "",
    run_id: str | None = None,
    touch_bars: BarSeries | None = None,
    funding_ts_ms: np.ndarray | None = None,
    funding_rate: np.ndarray | None = None,
    costs: CostConfig | None = None,
    margin: MarginConfig | None = None,
    sizing: SizingConfig | None = None,
    sim: SimConfig | None = None,
    starting_equity: float = RESEARCH_STARTING_EQUITY_USDT,
    store_path: str | Path | None = RESEARCH_STORE_PATH,
    reports_dir: str | Path | None = RESEARCH_REPORTS_DIR,
    report: bool = True,
    strategy_meta: Mapping[str, Any] | StrategyDetails | None = None,
    notes: str = "",
    plot: bool | None = None,
    print_headline: bool = True,
    max_bars: int = 0,
    max_zone_trades: int = 200,
) -> BacktestBundle:
    """Run a strategy backtest with research defaults and full artifact capture.

    Defaults (override only when you mean to):
    - starting equity **10_000 USDT** (large enough that 1× + venue min size never
      fails margin on BTC/ETH; headline % is return on invested notional, not wallet %)
    - sizing = smallest exchange-legal quantity (omit ``Signal.qty``)
    - instrument limits from Bybit (``symbol=`` or pass ``instrument=``)
    - leverage 1×
    - limit TP/SL, no exit slip; entry next-open + entry slip; taker fees
    - trading stops if the wallet is blown
    - persist to ``D:/projectsdata/backtests/tradesim_runs.sqlite``
    - write a report folder under ``D:/projectsdata/backtests/reports/{run_id}/``
    - open Finplot (full period) + metrics on interactive terminals
      (``plot=False`` / ``TRADESIM_NO_PLOT=1`` to disable; no re-sim on reopen)

    Pass ``strategy_meta`` with name / batch / model_path / tp_pct / sl_pct / …
    so the report and metrics window show pack identity.
    """
    rid = run_id or f"{strategy_id}-{uuid.uuid4().hex[:10]}"
    if instrument is None:
        sym = symbol or (bars.symbol if hasattr(bars, "symbol") else None)
        if not sym:
            raise ValueError("pass instrument= or symbol= (Bybit USDT perp, e.g. BTCUSDT)")
        instrument = research_instrument(str(sym))
    costs = costs or research_costs()
    margin = margin or research_margin()
    sizing = sizing or research_sizing()
    if sim is None:
        sim = research_sim(starting_equity=starting_equity)
    elif starting_equity != sim.starting_equity:
        from dataclasses import replace

        sim = replace(sim, starting_equity=float(starting_equity))

    result = simulate(
        bars=bars,
        signals=list(signals),
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        touch_bars=touch_bars,
        funding_ts_ms=funding_ts_ms,
        funding_rate=funding_rate,
        run_id=rid,
        attach_stamp=True,
    )
    metrics = compute_metrics(
        result, annualisation_days=sim.annualisation_days, bars=bars
    )
    headline = headline_table(metrics)
    if print_headline:
        print(headline)
        if metrics.wallet_blown:
            print(
                f"*** WALLET BLOWN for strategy={strategy_id!r} run={rid} "
                f"at ts_ms={metrics.ruined_at_ts_ms} ***\n"
            )

    path_str = None
    fingerprints: dict[str, str] = {}
    if store_path is not None:
        store = BacktestStore(store_path)
        fingerprints = store.save(
            run_id=rid,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            result=result,
            metrics=metrics,
            symbol=instrument.symbol,
            decision_timeframe=sim.decision_timeframe,
            notes=notes,
            bars=bars,
            embed_bars=True,
            strategy_meta=strategy_meta,
        )
        path_str = str(Path(store_path).resolve())
        if print_headline and fingerprints.get("run_fingerprint_short"):
            print(
                f"saved run_id={rid}  fingerprint={fingerprints['run_fingerprint_short']}  "
                f"db={path_str}"
            )

    report_path_str = None
    if report and reports_dir is not None:
        paths = write_report(
            run_id=rid,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            result=result,
            metrics=metrics,
            strategy_meta=strategy_meta,
            notes=notes,
            reports_dir=reports_dir,
            store_path=path_str or store_path,
            fingerprints=fingerprints,
            symbol=instrument.symbol,
            decision_timeframe=sim.decision_timeframe or "",
        )
        report_path_str = str(paths.folder.resolve())
        if print_headline:
            print(f"report folder={report_path_str}")
            print(f"reopen later: tradesim-research open --run-id {rid}")

    do_plot = _default_plot() if plot is None else bool(plot)
    if do_plot:
        from .plot import plot_backtest

        meta_dict: dict[str, Any] | None
        if isinstance(strategy_meta, StrategyDetails):
            meta_dict = strategy_meta.to_dict()
        elif strategy_meta:
            meta_dict = dict(strategy_meta)
        else:
            meta_dict = None
        plot_backtest(
            bars,
            result,
            title=f"{strategy_id} [{rid}]",
            metrics=metrics,
            strategy_meta=meta_dict,
            max_bars=int(max_bars),
            max_zone_trades=int(max_zone_trades),
            show=True,
            show_metrics_window=True,
        )

    return BacktestBundle(
        run_id=rid,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        result=result,
        metrics=metrics,
        headline=headline,
        store_path=path_str,
        report_dir=report_path_str,
        fingerprints=fingerprints,
    )
