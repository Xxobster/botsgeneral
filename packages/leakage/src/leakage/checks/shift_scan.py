"""Detect features that track future price moves more than past ones.

Catches explicit ``shift(-k)`` / centered-window style leaks that survive a weak
prefix cut when the compare window is too short, and label-like columns that are
nearly equal to a forward return.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..types import CheckId, Finding, Severity


def check_forward_shift_scan(
    ohlcv: pd.DataFrame,
    features: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (1, 3, 6, 12),
    hard_abs_corr: float = 0.95,
    warn_abs_corr: float = 0.80,
) -> list[Finding]:
    """Hard-fail columns whose tip correlation with future return is near-perfect."""
    if ohlcv.empty or features.empty:
        return []
    close = pd.to_numeric(ohlcv["close"], errors="coerce")
    # Align features onto ohlcv index.
    feat = features.reindex(ohlcv.index)
    findings: list[Finding] = []
    for h in horizons:
        fwd = close.pct_change(h).shift(-h)
        for col in feat.columns:
            x = pd.to_numeric(feat[col], errors="coerce")
            both = x.notna() & fwd.notna()
            if int(both.sum()) < 80:
                continue
            a = x[both].to_numpy(dtype=float)
            b = fwd[both].to_numpy(dtype=float)
            if np.std(a) < 1e-15 or np.std(b) < 1e-15:
                continue
            corr = float(np.corrcoef(a, b)[0, 1])
            if not np.isfinite(corr):
                continue
            abs_c = abs(corr)
            if abs_c >= hard_abs_corr:
                findings.append(
                    Finding(
                        check=CheckId.FORWARD_SHIFT_SCAN,
                        severity=Severity.HARD,
                        column=str(col),
                        message=(
                            f"near-identity with forward return h={h} "
                            f"(abs_corr={abs_c:.4f}) — likely shift/label leak"
                        ),
                        detail={"horizon": h, "abs_corr": abs_c},
                    )
                )
            elif abs_c >= warn_abs_corr:
                findings.append(
                    Finding(
                        check=CheckId.FORWARD_SHIFT_SCAN,
                        severity=Severity.ADVISORY,
                        column=str(col),
                        message=(
                            f"elevated correlation with forward return h={h} "
                            f"(abs_corr={abs_c:.4f})"
                        ),
                        detail={"horizon": h, "abs_corr": abs_c},
                    )
                )
    # De-dupe: keep hardest finding per column.
    by_col: dict[str, Finding] = {}
    for f in findings:
        key = f.column or "*"
        prev = by_col.get(key)
        if prev is None:
            by_col[key] = f
            continue
        rank = {Severity.HARD: 2, Severity.ADVISORY: 1}
        if rank[f.severity] > rank[prev.severity]:
            by_col[key] = f
        elif (
            rank[f.severity] == rank[prev.severity]
            and float(f.detail.get("abs_corr", 0))
            > float(prev.detail.get("abs_corr", 0))
        ):
            by_col[key] = f
    return list(by_col.values())
