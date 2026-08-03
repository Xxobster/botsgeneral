"""Fibonacci ratios and price levels between two swing anchors.

All ratios are fractions of the leg length (price B − price A). Retracement levels
sit between A and B; extension levels project beyond B in the leg direction.
"""

from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

# Classic retracement ratios used to separate impulse vs correction depth.
FIB_RETRACEMENT: tuple[float, ...] = (0.236, 0.382, 0.5, 0.618, 0.786)

# Extension / projection ratios (measured from A through B, past B).
FIB_EXTENSION: tuple[float, ...] = (1.0, 1.272, 1.618, 2.0, 2.618)

# Full set persisted in the warehouse for maximum information.
FIB_ALL: tuple[float, ...] = tuple(
    sorted(set(FIB_RETRACEMENT) | set(FIB_EXTENSION) | {0.0})
)

_FIB_LABELS: dict[float, str] = {
    0.0: "0.000",
    0.236: "0.236",
    0.382: "0.382",
    0.5: "0.500",
    0.618: "0.618",
    0.786: "0.786",
    1.0: "1.000",
    1.272: "1.272",
    1.618: "1.618",
    2.0: "2.000",
    2.618: "2.618",
}


def fib_label(ratio: float) -> str:
    key = round(float(ratio), 6)
    if key in _FIB_LABELS:
        return _FIB_LABELS[key]
    return f"{float(ratio):.3f}"


def fib_levels(
    price_a: float,
    price_b: float,
    ratios: Sequence[float] = FIB_ALL,
) -> dict[str, float]:
    """Map fib labels → absolute prices for the leg A → B.

    Retracement ratio ``r`` is the price that has given back ``r`` of the move
    from B back toward A: ``price = B - r * (B - A)``.
    Extension ``r > 1`` continues past B: ``price = A + r * (B - A)``.
    """
    a = float(price_a)
    b = float(price_b)
    span = b - a
    out: dict[str, float] = {}
    for r in ratios:
        rr = float(r)
        # Unified: level at fraction r of the A→B span measured from A.
        # Retracement of depth r from B equals A + (1-r)*span.
        if rr <= 1.0:
            price = b - rr * span
        else:
            price = a + rr * span
        out[fib_label(rr)] = float(price)
    return out


def retracement_ratio(
    price_a: float,
    price_b: float,
    price_c: float,
) -> float:
    """How deep C retraces the A→B leg, as a fraction of |B−A|.

    0 = no retrace (still at B). 1 = full retrace back to A. >1 = beyond A.
    """
    span = float(price_b) - float(price_a)
    if abs(span) < 1e-15:
        return float("nan")
    return float((float(price_b) - float(price_c)) / span)


def nearest_fib(
    ratio: float,
    candidates: Sequence[float] = FIB_RETRACEMENT,
) -> tuple[float, str, float]:
    """Return ``(fib_ratio, label, abs_error)`` for the nearest candidate."""
    if not np.isfinite(ratio):
        return float("nan"), "", float("nan")
    arr = np.asarray(list(candidates), dtype=float)
    err = np.abs(arr - float(ratio))
    i = int(np.argmin(err))
    r = float(arr[i])
    return r, fib_label(r), float(err[i])


def fib_column_names(ratios: Sequence[float] = FIB_ALL) -> tuple[str, ...]:
    return tuple(f"fib_{fib_label(r).replace('.', '')}" for r in ratios)


def levels_to_columns(levels: Mapping[str, float]) -> dict[str, float]:
    """``{'0.618': price}`` → ``{'fib_0618': price}``."""
    out: dict[str, float] = {}
    for label, price in levels.items():
        key = "fib_" + str(label).replace(".", "")
        out[key] = float(price)
    return out
