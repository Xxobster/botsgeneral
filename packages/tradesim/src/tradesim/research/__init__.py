"""Research helpers: defaults, persistence, Finplot, one-call runner, reports."""

from __future__ import annotations

from .candles import ensure_candles
from .defaults import (
    RESEARCH_ENTRY_SLIPPAGE,
    RESEARCH_MAKER_RATE,
    RESEARCH_REPORTS_DIR,
    RESEARCH_STARTING_EQUITY_USDT,
    RESEARCH_STORE_PATH,
    RESEARCH_TAKER_RATE,
    research_costs,
    research_instrument,
    research_limit_entry_costs,
    research_margin,
    research_sim,
    research_sim_limit_entry,
    research_sizing,
    research_starting_equity,
)
from .fingerprint import bars_fingerprint, run_fingerprint, short_id, trades_fingerprint
from .plot import PlotView, plot_backtest
from .provenance import collect_provenance
from .report import StrategyDetails, open_report, write_report
from .run import BacktestBundle, run_backtest
from .store import BacktestStore, SavedRun, aggregate_run_catalog, persist_research_run

__all__ = [
    "RESEARCH_ENTRY_SLIPPAGE",
    "RESEARCH_MAKER_RATE",
    "RESEARCH_REPORTS_DIR",
    "RESEARCH_STARTING_EQUITY_USDT",
    "RESEARCH_STORE_PATH",
    "RESEARCH_TAKER_RATE",
    "BacktestBundle",
    "BacktestStore",
    "PlotView",
    "SavedRun",
    "StrategyDetails",
    "aggregate_run_catalog",
    "bars_fingerprint",
    "collect_provenance",
    "ensure_candles",
    "open_report",
    "persist_research_run",
    "plot_backtest",
    "research_costs",
    "research_instrument",
    "research_limit_entry_costs",
    "research_margin",
    "research_sim",
    "research_sim_limit_entry",
    "research_sizing",
    "research_starting_equity",
    "run_backtest",
    "run_fingerprint",
    "short_id",
    "trades_fingerprint",
    "write_report",
]
