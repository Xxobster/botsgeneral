"""Detect builders that ignore their OHLCV argument (external cache / warehouse).

Prefix-invariance and future-mutation both call ``build_features(ohlcv)``. If that
callable joins a pre-computed warehouse keyed by calendar time and never reads the
passed frame, truncating or mutating the frame changes nothing and both checks pass
trivially. That is exactly how ``structure_v1``'s look-ahead in ``last_retrace_pct``
survived the shared leakage engine (CAUS-STRUCT-001 / CAUS-WAREHOUSE-001).

This probe shape-shocks the tip of the candle frame. A builder that actually derives
features from those bars must move at least one tip value. A silent no-op is a hard
fail: ``EXTERNAL_CACHE_SUSPECTED``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..types import CheckId, FeatureBuilder, Finding, Severity


def _shape_shock_tip(ohlcv: pd.DataFrame, *, n_bars: int) -> pd.DataFrame:
    """Mutate the tip path so scale-free structure features must change if recomputed.

    Scaling the whole series leaves ratios unchanged; inverting the tip's return path
    changes swing geometry and any feature that truly reads those bars.
    """
    out = ohlcv.copy()
    n = len(out)
    m = min(max(int(n_bars), 20), max(n // 4, 20), n)
    if m < 20:
        raise ValueError(f"need at least 20 tip bars to shock; got m={m}, n={n}")
    idx = out.index[-m:]
    close = pd.to_numeric(out.loc[idx, "close"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(close).all() or np.any(close <= 0):
        # Fall back: absolute spike on the tip high/low.
        tip = idx[-1]
        for col in ("high", "close"):
            if col in out.columns:
                out.loc[tip, col] = float(out.loc[tip, col]) * 1.5 + 1000.0
        if "low" in out.columns:
            out.loc[tip, "low"] = float(out.loc[tip, "low"]) * 0.5
        return out

    # Rebuild tip as an inverted random-walk of the same length, anchored at the
    # first tip close so earlier history is untouched and only the tip path flips.
    rets = np.diff(np.log(close))
    inv = -rets[::-1]
    new_close = np.empty_like(close)
    new_close[0] = close[0]
    new_close[1:] = close[0] * np.exp(np.cumsum(inv))
    # Reconstruct a plausible OHLC around the new close path.
    span = np.maximum(np.abs(np.diff(new_close, prepend=new_close[0])), close * 1e-4)
    out.loc[idx, "close"] = new_close
    if "open" in out.columns:
        opened = np.empty_like(new_close)
        opened[0] = float(out.loc[idx[0], "open"]) if np.isfinite(out.loc[idx[0], "open"]) else new_close[0]
        opened[1:] = new_close[:-1]
        out.loc[idx, "open"] = opened
    if "high" in out.columns:
        base_o = out.loc[idx, "open"].to_numpy(dtype=float) if "open" in out.columns else new_close
        out.loc[idx, "high"] = np.maximum(base_o, new_close) + span
    if "low" in out.columns:
        base_o = out.loc[idx, "open"].to_numpy(dtype=float) if "open" in out.columns else new_close
        out.loc[idx, "low"] = np.minimum(base_o, new_close) - span
    return out


def check_builder_responsiveness(
    ohlcv: pd.DataFrame,
    build_features: FeatureBuilder,
    *,
    interval: str = "1h",
    compare_rows: int = 50,
    tip_shock_bars: int = 120,
    tol: float = 1e-8,
    min_moved_frac: float = 0.0,
) -> list[Finding]:
    """Hard-fail when tip features are unchanged after a tip shape-shock.

    ``min_moved_frac=0`` means: at least one numeric tip cell must move. Raising it
    requires a larger share of columns to respond (stricter).
    """
    if ohlcv.empty:
        raise ValueError("ohlcv is empty")
    if len(ohlcv) < tip_shock_bars + compare_rows:
        raise ValueError(
            f"need at least {tip_shock_bars + compare_rows} bars for responsiveness; "
            f"got {len(ohlcv)}"
        )

    base = build_features(ohlcv, interval=interval)
    if not isinstance(base, pd.DataFrame) or base.empty:
        raise ValueError("build_features returned empty / non-DataFrame")

    shocked_ohlcv = _shape_shock_tip(ohlcv, n_bars=tip_shock_bars)
    shocked = build_features(shocked_ohlcv, interval=interval)
    if not isinstance(shocked, pd.DataFrame) or shocked.empty:
        return [
            Finding(
                check=CheckId.BUILDER_RESPONSIVENESS,
                severity=Severity.HARD,
                column=None,
                message="build_features returned empty frame after tip shape-shock",
                detail={"code": "EXTERNAL_CACHE_SUSPECTED"},
            )
        ]

    # Align on common columns / index tip.
    cols = [c for c in base.columns if c in shocked.columns]
    if not cols:
        return [
            Finding(
                check=CheckId.BUILDER_RESPONSIVENESS,
                severity=Severity.HARD,
                column=None,
                message="no common columns between base and shocked feature frames",
                detail={"code": "EXTERNAL_CACHE_SUSPECTED"},
            )
        ]

    idx = base.index.intersection(shocked.index)[-compare_rows:]
    if len(idx) == 0:
        return [
            Finding(
                check=CheckId.BUILDER_RESPONSIVENESS,
                severity=Severity.HARD,
                column=None,
                message="no overlapping index rows to compare after tip shape-shock",
                detail={"code": "EXTERNAL_CACHE_SUSPECTED"},
            )
        ]

    moved: list[str] = []
    stuck: list[str] = []
    for col in cols:
        a = pd.to_numeric(base.loc[idx, col], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(shocked.loc[idx, col], errors="coerce").to_numpy(dtype=float)
        both = np.isfinite(a) & np.isfinite(b)
        if not both.any():
            # All-NaN on both sides — treat as unresponsive (warehouse join of missing).
            stuck.append(str(col))
            continue
        max_diff = float(np.max(np.abs(a[both] - b[both])))
        if max_diff > tol:
            moved.append(str(col))
        else:
            stuck.append(str(col))

    n = len(cols)
    moved_frac = len(moved) / n if n else 0.0
    findings: list[Finding] = []

    if moved_frac <= float(min_moved_frac):
        findings.append(
            Finding(
                check=CheckId.BUILDER_RESPONSIVENESS,
                severity=Severity.HARD,
                column=None,
                message=(
                    "tip shape-shock did not move feature outputs — builder is ignoring "
                    f"its OHLCV argument (moved={len(moved)}/{n}, "
                    f"stuck_sample={stuck[:8]})"
                ),
                detail={
                    "code": "EXTERNAL_CACHE_SUSPECTED",
                    "n_columns": n,
                    "n_moved": len(moved),
                    "n_stuck": len(stuck),
                    "moved_frac": moved_frac,
                    "stuck_columns": stuck[:40],
                    "conformance": "CAUS-WAREHOUSE-001",
                },
            )
        )
    # Also surface stuck columns as HARD when *most* of the frame is frozen but a
    # few vol-normalised overlays moved (classic warehouse + local transform pattern).
    elif len(stuck) >= max(3, int(0.5 * n)):
        for col in stuck[:20]:
            findings.append(
                Finding(
                    check=CheckId.BUILDER_RESPONSIVENESS,
                    severity=Severity.HARD,
                    column=col,
                    message=(
                        "column unchanged after tip shape-shock while sibling columns "
                        "moved — likely read from an external warehouse/cache"
                    ),
                    detail={
                        "code": "EXTERNAL_CACHE_SUSPECTED",
                        "conformance": "CAUS-WAREHOUSE-001",
                    },
                )
            )
    return findings
