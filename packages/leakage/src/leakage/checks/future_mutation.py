"""Future-mutation: extreme future bars must not change earlier feature values."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..types import CheckId, FeatureBuilder, Finding, Severity


def check_future_mutation(
    ohlcv: pd.DataFrame,
    build_features: FeatureBuilder,
    *,
    interval: str = "1h",
    cutoff_frac: float = 0.80,
    compare_rows: int = 300,
    tol: float = 1e-8,
    shock_mult: float = 10.0,
) -> list[Finding]:
    """Append shocked future OHLCV after a cutoff; earlier rows must stay identical."""
    n = len(ohlcv)
    if n < compare_rows + 50:
        raise ValueError(
            f"need at least {compare_rows + 50} bars for future-mutation; got {n}"
        )
    cut = int(n * cutoff_frac)
    cut = min(max(cut, compare_rows), n - 2)

    base = ohlcv.iloc[: cut + 1].copy()
    base_feat = build_features(base, interval=interval)

    mutated = ohlcv.copy()
    # Shock only bars strictly after the cutoff.
    after = mutated.iloc[cut + 1 :].copy()
    if after.empty:
        return []
    close = after["close"].to_numpy(dtype=float)
    shock = close * shock_mult
    for col in ("open", "high", "low", "close"):
        if col in after.columns:
            after[col] = shock
    if "volume" in after.columns:
        after["volume"] = after["volume"].to_numpy(dtype=float) * shock_mult
    mutated.iloc[cut + 1 :] = after

    mut_feat = build_features(mutated, interval=interval)
    idx = base_feat.index[-compare_rows:]
    findings: list[Finding] = []
    for col in base_feat.columns:
        if col not in mut_feat.columns:
            continue
        a = pd.to_numeric(base_feat.loc[idx, col], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(mut_feat.loc[idx, col], errors="coerce").to_numpy(dtype=float)
        nan_a = np.isnan(a)
        nan_b = np.isnan(b)
        # Future mutation should not invent values where base was NaN nor vice versa
        # on the shared past window, except both NaN.
        nan_mismatch = int((nan_a != nan_b).sum())
        both = ~nan_a & ~nan_b
        max_diff = float(np.max(np.abs(a[both] - b[both]))) if both.any() else 0.0
        if nan_mismatch or max_diff > tol:
            findings.append(
                Finding(
                    check=CheckId.FUTURE_MUTATION,
                    severity=Severity.HARD,
                    column=str(col),
                    message=(
                        f"past values changed when future was shocked "
                        f"(max_diff={max_diff:.3e}, nan_mismatch={nan_mismatch})"
                    ),
                    detail={
                        "max_diff": max_diff,
                        "nan_mismatch": nan_mismatch,
                        "cutoff_iloc": cut,
                    },
                )
            )
    return findings
