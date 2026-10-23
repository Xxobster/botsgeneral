"""Orchestrate leakage checks and persist LEAKAGE_POTENTIAL marks."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from .checks import (
    check_builder_responsiveness,
    check_forward_corr,
    check_forward_shift_scan,
    check_future_mutation,
    check_name_scan,
    check_prefix_invariance,
    check_streaming_batch_tip,
    check_train_test_split,
)
from .registry import update_registry_from_findings
from .types import CheckId, FeatureBuilder, Finding, LeakageReport, Severity

# Decisive checks that must all run when ohlcv+build_features are supplied.
# Skipping any of them is itself a HARD failure (agents cannot "partial-audit").
DECISIVE_CHECK_IDS: tuple[CheckId, ...] = (
    CheckId.BUILDER_RESPONSIVENESS,
    CheckId.PREFIX_INVARIANCE,
    CheckId.FUTURE_MUTATION,
    CheckId.STREAMING_BATCH,
)


def run_leakage_audit(
    ohlcv: pd.DataFrame | None = None,
    build_features: FeatureBuilder | None = None,
    *,
    interval: str = "1h",
    features: pd.DataFrame | None = None,
    registry_path: str | Path | None = None,
    symbol: str | None = None,
    timeframe: str | None = None,
    cuts: int = 3,
    compare_rows: int = 300,
    tol: float = 1e-8,
    forward_horizons: tuple[int, ...] = (1, 6, 12, 24),
    forward_warn_abs: float = 0.20,
    forward_hard_abs: float = 0.50,
    train_path: str | Path | None = None,
    test_path: str | Path | None = None,
    min_gap_ms: int = 0,
    ts_col: str = "ts_ms",
    run_prefix: bool = True,
    run_future_mutation: bool = True,
    run_builder_responsiveness: bool = True,
    run_streaming_batch: bool = True,
    run_forward_shift_scan: bool = True,
    run_forward_corr: bool = True,
    run_name_scan: bool = True,
    require_decisive: bool = True,
    extra_hard_name_tokens: tuple[str, ...] = (),
) -> LeakageReport:
    """Run the shared leakage battery.

    Hard-fail (blocks train/test):
      - builder-responsiveness / EXTERNAL_CACHE_SUSPECTED
      - prefix-invariance
      - future-mutation
      - streaming/batch tip identity
      - forward-shift / near-label scan (near-identity with future return)
      - label/outcome name scan
      - train/test geometry when both paths are supplied
      - decisive-checks-required (cannot skip the battery when a builder is given)

    Advisory: elevated forward-return correlation below the hard threshold.

    Separate train/test databases alone never prove causality.
    """
    findings: list[Finding] = []
    notes: list[str] = []
    feat: pd.DataFrame | None = features
    ran_decisive: set[CheckId] = set()

    runnable = False

    if ohlcv is not None and build_features is not None:
        runnable = True
        if run_builder_responsiveness:
            findings.extend(
                check_builder_responsiveness(
                    ohlcv,
                    build_features,
                    interval=interval,
                    compare_rows=min(compare_rows, 50),
                    tol=tol,
                )
            )
            ran_decisive.add(CheckId.BUILDER_RESPONSIVENESS)
        if run_prefix:
            findings.extend(
                check_prefix_invariance(
                    ohlcv,
                    build_features,
                    interval=interval,
                    cuts=cuts,
                    compare_rows=compare_rows,
                    tol=tol,
                )
            )
            ran_decisive.add(CheckId.PREFIX_INVARIANCE)
        if run_future_mutation:
            findings.extend(
                check_future_mutation(
                    ohlcv,
                    build_features,
                    interval=interval,
                    compare_rows=compare_rows,
                    tol=tol,
                )
            )
            ran_decisive.add(CheckId.FUTURE_MUTATION)
        if run_streaming_batch:
            findings.extend(
                check_streaming_batch_tip(
                    ohlcv,
                    build_features,
                    interval=interval,
                    tol=tol,
                )
            )
            ran_decisive.add(CheckId.STREAMING_BATCH)
        if feat is None:
            feat = build_features(ohlcv, interval=interval)
        if require_decisive:
            missing = [c for c in DECISIVE_CHECK_IDS if c not in ran_decisive]
            if missing:
                findings.append(
                    Finding(
                        check=CheckId.DECISIVE_CHECKS_REQUIRED,
                        severity=Severity.HARD,
                        column=None,
                        message=(
                            "builder supplied but decisive checks were skipped: "
                            + ",".join(c.value for c in missing)
                        ),
                        detail={"missing": [c.value for c in missing]},
                    )
                )
    elif build_features is not None and ohlcv is None:
        notes.append("ohlcv missing — skipped decisive builder checks")
    elif ohlcv is not None and build_features is None:
        notes.append("build_features missing — skipped decisive builder checks")

    if feat is not None:
        runnable = True
        if run_name_scan:
            findings.extend(
                check_name_scan(feat, extra_hard=extra_hard_name_tokens)
            )
        if run_forward_shift_scan and ohlcv is not None:
            findings.extend(
                check_forward_shift_scan(
                    ohlcv,
                    feat,
                    horizons=tuple(h for h in forward_horizons if h > 0) or (1, 6, 12),
                )
            )
        if run_forward_corr and ohlcv is not None:
            findings.extend(
                check_forward_corr(
                    ohlcv,
                    feat,
                    horizons=forward_horizons,
                    warn_abs=forward_warn_abs,
                    hard_abs=forward_hard_abs,
                )
            )
    else:
        notes.append("no feature frame — skipped name scan / forward corr / shift scan")

    if train_path is not None and test_path is not None:
        runnable = True
        findings.extend(
            check_train_test_split(
                train_path,
                test_path,
                ts_col=ts_col,
                min_gap_ms=min_gap_ms,
            )
        )
    elif train_path or test_path:
        findings.append(
            Finding(
                check=CheckId.TRAIN_TEST_SPLIT,
                severity=Severity.HARD,
                column=None,
                message="both train_path and test_path are required for split check",
            )
        )
        runnable = True

    if not runnable:
        findings.append(
            Finding(
                check=CheckId.PREFIX_INVARIANCE,
                severity=Severity.HARD,
                column=None,
                message=(
                    "no checks runnable — provide ohlcv+build_features "
                    "and/or features and/or train_path+test_path"
                ),
            )
        )

    markable = [f for f in findings if f.column is not None]
    if registry_path is not None and markable:
        update_registry_from_findings(
            registry_path,
            markable,
            symbol=symbol,
            timeframe=timeframe or interval,
        )

    hard = [f for f in findings if f.severity is Severity.HARD]
    potential = sorted({f.column for f in markable if f.column})
    n_cols = 0 if feat is None else int(len(feat.columns))

    return LeakageReport(
        ok=len(hard) == 0,
        n_columns=n_cols,
        findings=findings,
        leakage_potential=potential,
        registry_path=str(registry_path) if registry_path else None,
        notes=notes,
    )


def require_clean_audit(report: LeakageReport) -> None:
    """Raise RuntimeError unless the audit hard-passed."""
    if not report.ok:
        raise RuntimeError(report.summary())


def format_report(report: LeakageReport) -> str:
    lines = [
        "=" * 84,
        "LEAKAGE AUDIT",
        "=" * 84,
        report.summary(),
    ]
    if report.notes:
        lines.append("notes: " + "; ".join(report.notes))
    if report.registry_path:
        lines.append(f"registry: {report.registry_path}")
    if report.findings:
        lines.append("")
        lines.append(f"{'sev':<10}{'check':<22}{'column':<28}{'message'}")
        lines.append("-" * 84)
        for f in sorted(
            report.findings,
            key=lambda x: (x.severity.value, x.check.value, x.column or ""),
        ):
            lines.append(
                f"{f.severity.value:<10}{f.check.value:<22}"
                f"{(f.column or '-'):<28}{f.message}"
            )
    lines.append("=" * 84)
    return "\n".join(lines)


def merge_findings(groups: Iterable[list[Finding]]) -> list[Finding]:
    out: list[Finding] = []
    for g in groups:
        out.extend(g)
    return out
