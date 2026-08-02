"""Advisory forward-return correlation scan (mechanical-leak signature)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..types import CheckId, Finding, Severity


def check_forward_corr(
    ohlcv: pd.DataFrame,
    features: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (1, 6, 12, 24),
    warn_abs: float = 0.20,
    hard_abs: float = 0.50,
) -> list[Finding]:
    """Flag columns with anomalously high |corr| to future close returns.

    ``hard_abs`` (default 0.50) is a HARD fail — near the centered-DPO signature
    (~0.64). Between ``warn_abs`` and ``hard_abs`` is ADVISORY (still marks
    LEAKAGE_POTENTIAL).
    """
    if "close" not in ohlcv.columns:
        raise ValueError("ohlcv must contain 'close'")
    close = pd.to_numeric(ohlcv["close"], errors="coerce")
    # Align features to ohlcv index intersection
    idx = features.index.intersection(ohlcv.index)
    if len(idx) < 100:
        return [
            Finding(
                check=CheckId.FORWARD_CORR,
                severity=Severity.ADVISORY,
                column=None,
                message=f"insufficient aligned rows for forward corr ({len(idx)})",
            )
        ]

    feats = features.loc[idx]
    close = close.loc[idx]
    findings: list[Finding] = []

    for h in horizons:
        fwd = close.shift(-h) / close - 1.0
        y = fwd.to_numpy(dtype=float)
        for col in feats.columns:
            x = pd.to_numeric(feats[col], errors="coerce").to_numpy(dtype=float)
            mask = np.isfinite(x) & np.isfinite(y)
            if mask.sum() < 50:
                continue
            # vectorized Pearson
            xv = x[mask]
            yv = y[mask]
            xv = xv - xv.mean()
            yv = yv - yv.mean()
            denom = float(np.sqrt((xv * xv).sum() * (yv * yv).sum()))
            if denom <= 0:
                continue
            corr = float((xv * yv).sum() / denom)
            ac = abs(corr)
            if ac < warn_abs:
                continue
            sev = Severity.HARD if ac >= hard_abs else Severity.ADVISORY
            findings.append(
                Finding(
                    check=CheckId.FORWARD_CORR,
                    severity=sev,
                    column=str(col),
                    message=f"|corr|={ac:.4f} vs forward return h={h}",
                    detail={"corr": corr, "horizon": h, "n": int(mask.sum())},
                )
            )

    # Keep worst finding per column
    best: dict[str, Finding] = {}
    for f in findings:
        if f.column is None:
            continue
        prev = best.get(f.column)
        if prev is None or abs(float(f.detail.get("corr", 0))) > abs(
            float(prev.detail.get("corr", 0))
        ):
            best[f.column] = f
    return list(best.values())
