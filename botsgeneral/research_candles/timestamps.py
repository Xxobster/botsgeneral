"""Shared timestamp helpers (handles datetime64[s] and datetime64[ns])."""

from __future__ import annotations

import numpy as np
import pandas as pd


def to_ts_ms(values) -> np.ndarray:
    """Convert datetime-like values to UTC epoch milliseconds (int64)."""
    ts = pd.to_datetime(values, utc=True)
    # Normalize to ns precision so int64 is always nanoseconds since epoch
    ns = ts.astype("datetime64[ns, UTC]")
    return (ns.astype("int64") // 1_000_000).to_numpy(dtype="int64")
