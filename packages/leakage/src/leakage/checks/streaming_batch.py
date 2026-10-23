"""Streaming vs batch tip identity.

Recomputing features on the full history and on the prefix ending at the tip must
agree on the tip row. This is prefix-invariance at a single cut, kept as its own
check so a missing binding fails the build like any other conformance id.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..types import CheckId, FeatureBuilder, Finding, Severity


def check_streaming_batch_tip(
    ohlcv: pd.DataFrame,
    build_features: FeatureBuilder,
    *,
    interval: str = "1h",
    tip_rows: int = 5,
    tol: float = 1e-8,
) -> list[Finding]:
    """Hard-fail columns whose tip values rewrite when earlier history is extended."""
    n = len(ohlcv)
    if n < tip_rows + 100:
        raise ValueError(
            f"need at least {tip_rows + 100} bars for streaming/batch tip; got {n}"
        )
    # Tip of a short prefix vs the same tip inside the full series.
    # Keep enough post-tip bars in the full frame that a shift(-1)/centered
    # window at the prefix tip is defined there but not on the truncated tip.
    cut = n - max(int(tip_rows), 20)
    cut = max(cut, 100)
    prefix = ohlcv.iloc[:cut]
    full_feat = build_features(ohlcv, interval=interval)
    pref_feat = build_features(prefix, interval=interval)
    if not isinstance(full_feat, pd.DataFrame) or not isinstance(pref_feat, pd.DataFrame):
        return [
            Finding(
                check=CheckId.STREAMING_BATCH,
                severity=Severity.HARD,
                column=None,
                message="build_features did not return a DataFrame",
            )
        ]
    tip_ts = pref_feat.index[-1]
    if tip_ts not in full_feat.index:
        return [
            Finding(
                check=CheckId.STREAMING_BATCH,
                severity=Severity.HARD,
                column=None,
                message=f"tip index {tip_ts} missing from full feature frame",
            )
        ]
    findings: list[Finding] = []
    for col in pref_feat.columns:
        if col not in full_feat.columns:
            continue
        a = pref_feat.loc[tip_ts, col]
        b = full_feat.loc[tip_ts, col]
        if isinstance(a, str) or isinstance(b, str):
            same = str(a) == str(b)
            max_diff = 0.0 if same else 1.0
        else:
            a_f = float(pd.to_numeric(a, errors="coerce"))
            b_f = float(pd.to_numeric(b, errors="coerce"))
            if np.isnan(a_f) and np.isnan(b_f):
                same = True
                max_diff = 0.0
            elif np.isnan(a_f) or np.isnan(b_f):
                same = False
                max_diff = float("nan")
            else:
                max_diff = abs(a_f - b_f)
                same = max_diff <= tol
        if not same:
            findings.append(
                Finding(
                    check=CheckId.STREAMING_BATCH,
                    severity=Severity.HARD,
                    column=str(col),
                    message=(
                        f"tip rewritten when history extended past the tip "
                        f"(diff={max_diff})"
                    ),
                    detail={"tip": str(tip_ts), "diff": max_diff},
                )
            )
    return findings
