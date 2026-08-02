"""Prefix-invariance: values at cutoff must not depend on future bars."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..types import CheckId, FeatureBuilder, Finding, Severity


def _numeric_compare(
    full: pd.DataFrame,
    prefix: pd.DataFrame,
    *,
    compare_rows: int,
    tol: float,
) -> list[Finding]:
    idx = prefix.index[-compare_rows:]
    findings: list[Finding] = []
    for col in prefix.columns:
        if col not in full.columns:
            continue
        a = pd.to_numeric(prefix.loc[idx, col], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(full.loc[idx, col], errors="coerce").to_numpy(dtype=float)
        nan_a = np.isnan(a)
        nan_b = np.isnan(b)
        nan_only_in_prefix = int((nan_a & ~nan_b).sum())
        both = ~nan_a & ~nan_b
        max_diff = float(np.max(np.abs(a[both] - b[both]))) if both.any() else 0.0
        if nan_only_in_prefix or max_diff > tol:
            findings.append(
                Finding(
                    check=CheckId.PREFIX_INVARIANCE,
                    severity=Severity.HARD,
                    column=str(col),
                    message=(
                        f"depends on future bars "
                        f"(max_diff={max_diff:.3e}, nan_only_in_prefix={nan_only_in_prefix})"
                    ),
                    detail={
                        "max_diff": max_diff,
                        "nan_only_in_prefix": nan_only_in_prefix,
                        "n_compared": int(both.sum()),
                    },
                )
            )
    return findings


def check_prefix_invariance(
    ohlcv: pd.DataFrame,
    build_features: FeatureBuilder,
    *,
    interval: str = "1h",
    cuts: int = 3,
    compare_rows: int = 300,
    tol: float = 1e-8,
    cut_frac_lo: float = 0.70,
    cut_frac_hi: float = 0.92,
) -> list[Finding]:
    """Recompute features on truncated prefixes; hard-fail columns that change."""
    if ohlcv.empty:
        raise ValueError("ohlcv is empty")
    n = len(ohlcv)
    if n < compare_rows + 50:
        raise ValueError(
            f"need at least {compare_rows + 50} bars for prefix check; got {n}"
        )

    full = build_features(ohlcv, interval=interval)
    if not isinstance(full, pd.DataFrame) or full.empty:
        raise ValueError("build_features returned empty / non-DataFrame")

    positions = [int(n * f) for f in np.linspace(cut_frac_lo, cut_frac_hi, cuts)]
    # de-dupe while preserving order
    seen: set[int] = set()
    uniq_pos: list[int] = []
    for p in positions:
        p = min(max(p, compare_rows), n - 1)
        if p not in seen:
            seen.add(p)
            uniq_pos.append(p)

    by_col: dict[str, Finding] = {}
    for pos in uniq_pos:
        prefix_ohlcv = ohlcv.iloc[: pos + 1]
        prefix = build_features(prefix_ohlcv, interval=interval)
        for f in _numeric_compare(full, prefix, compare_rows=compare_rows, tol=tol):
            prev = by_col.get(f.column or "")
            if prev is None or float(f.detail.get("max_diff", 0)) > float(
                prev.detail.get("max_diff", 0)
            ):
                by_col[f.column or ""] = f
    return list(by_col.values())
