"""leakage — shared dataset / indicator look-ahead test engine.

Every coding agent must run this before training or testing models that consume
project-built indicators. Separate train/test databases are hardening only.

    from leakage.ensure_source import prefer_botsgeneral_leakage
    prefer_botsgeneral_leakage()

    from leakage import run_leakage_audit, require_clean_audit

    report = run_leakage_audit(ohlcv=df, build_features=build_fn, registry_path=...)
    require_clean_audit(report)
"""

from __future__ import annotations

from .engine import format_report, merge_findings, require_clean_audit, run_leakage_audit
from .ensure_source import assert_botsgeneral_leakage, prefer_botsgeneral_leakage
from .registry import (
    assert_no_leakage_potential,
    leakage_potential_columns,
    load_registry,
    save_registry,
    update_registry_from_findings,
)
from .types import (
    CheckId,
    ColumnStatus,
    FeatureBuilder,
    Finding,
    LeakageReport,
    Severity,
)

__version__ = "1.0.0"

__all__ = [
    "CheckId",
    "ColumnStatus",
    "FeatureBuilder",
    "Finding",
    "LeakageReport",
    "Severity",
    "assert_botsgeneral_leakage",
    "assert_no_leakage_potential",
    "format_report",
    "leakage_potential_columns",
    "load_registry",
    "merge_findings",
    "prefer_botsgeneral_leakage",
    "require_clean_audit",
    "run_leakage_audit",
    "save_registry",
    "update_registry_from_findings",
    "__version__",
]
