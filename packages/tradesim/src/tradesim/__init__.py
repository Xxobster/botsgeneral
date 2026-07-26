"""tradesim — the shared, conformance-tested trade-execution engine.

Use this instead of writing another simulator. Across repositories, every hand-written
trade simulator is an independent chance to omit one of roughly forty subtle behaviours,
and a green project test suite is not evidence that the omission is absent.

    from tradesim import simulate, BarSeries, Signal, InstrumentSpec

    result = simulate(bars=bars, signals=signals, instrument=spec, run_id="exp-001")
    print(result.stamp)          # every result knows how trustworthy it is
    assert_quotable(result.stamp)  # and refuses to be quoted when it is not

The package is deterministic and offline: no network, no clock, no globals, and no
dependency on any data-collection or live-trading runtime. Research is reproducible from
stored inputs alone.
"""

from __future__ import annotations

from .contracts import (
    BASE_EXIT_REASONS,
    ENTRY_BAR_SUFFIX,
    REASON_BREAK_EVEN,
    REASON_END_OF_DATA,
    REASON_LIQUIDATION,
    REASON_MAX_HOLD,
    REASON_SIGNAL_EXIT,
    REASON_STOP,
    REASON_TARGET,
    REASON_TRAILING,
    Bar,
    BarSeries,
    BreakEvenConfig,
    CostConfig,
    EntryRef,
    FeeRole,
    Fill,
    FundingCharge,
    InstrumentSpec,
    LiquidationStatus,
    Liquidity,
    MaintenanceTier,
    MarginConfig,
    MarginMode,
    SameBarPolicy,
    Side,
    Signal,
    SimConfig,
    SimResult,
    SizingConfig,
    SizingMode,
    Skip,
    SkipReason,
    TakeProfitLeg,
    Trade,
    TrailConfig,
    base_reason,
    is_entry_bar_reason,
    round_to_step,
    round_to_tick,
)
from .conformance.stamp import ConformanceStamp, NotQuotableError, assert_quotable
from .engine import (
    DataValidationError,
    InfeasibleOrderError,
    SymbolStream,
    simulate,
    simulate_portfolio,
    validate_bars,
)
from .exits import (
    ExitEvent,
    ExitPolicy,
    ProtectiveLevels,
    TargetLevel,
    resolve_bar,
    resolve_bar_exit,
    update_protective_levels,
)
from .metrics import MetricsReport, SharpeReport, compute_metrics, headline_table
from .parity import ParityDiff, Tolerance, diff_trades, run_parity
from .version import ENGINE_NAME, ENGINE_VERSION, RESULT_SCHEMA_VERSION

__version__ = ENGINE_VERSION

__all__ = [
    "BASE_EXIT_REASONS",
    "Bar",
    "BarSeries",
    "BreakEvenConfig",
    "ConformanceStamp",
    "CostConfig",
    "DataValidationError",
    "ENGINE_NAME",
    "ENGINE_VERSION",
    "ENTRY_BAR_SUFFIX",
    "EntryRef",
    "ExitEvent",
    "ExitPolicy",
    "FeeRole",
    "Fill",
    "FundingCharge",
    "InfeasibleOrderError",
    "InstrumentSpec",
    "LiquidationStatus",
    "Liquidity",
    "MaintenanceTier",
    "MarginConfig",
    "MarginMode",
    "MetricsReport",
    "NotQuotableError",
    "ParityDiff",
    "ProtectiveLevels",
    "REASON_BREAK_EVEN",
    "REASON_END_OF_DATA",
    "REASON_LIQUIDATION",
    "REASON_MAX_HOLD",
    "REASON_SIGNAL_EXIT",
    "REASON_STOP",
    "REASON_TARGET",
    "REASON_TRAILING",
    "RESULT_SCHEMA_VERSION",
    "SameBarPolicy",
    "SharpeReport",
    "Side",
    "Signal",
    "SimConfig",
    "SimResult",
    "SizingConfig",
    "SizingMode",
    "Skip",
    "SkipReason",
    "SymbolStream",
    "TakeProfitLeg",
    "TargetLevel",
    "Tolerance",
    "Trade",
    "TrailConfig",
    "assert_quotable",
    "base_reason",
    "compute_metrics",
    "diff_trades",
    "headline_table",
    "is_entry_bar_reason",
    "resolve_bar",
    "resolve_bar_exit",
    "round_to_step",
    "round_to_tick",
    "run_parity",
    "simulate",
    "simulate_portfolio",
    "update_protective_levels",
    "validate_bars",
    "__version__",
]
