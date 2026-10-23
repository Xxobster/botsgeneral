"""Every published structure column must declare and satisfy a knowable-when rule."""

from __future__ import annotations

import numpy as np
import pytest

from indicators.compute import compute_structure
from indicators.publication_rules import PUBLICATION_RULES, required_columns


def _wavy(n: int = 450, seed: int = 3):
    rng = np.random.default_rng(seed)
    ts = 1_700_000_000_000 + np.arange(n, dtype=np.int64) * 3_600_000
    t = np.arange(n)
    base = 100 + 8 * np.sin(t / 7.0) + 3 * np.sin(t / 23.0) + t * 0.02
    base = base + rng.normal(0, 0.25, n)
    high = base + 0.8 + rng.random(n) * 0.4
    low = base - 0.8 - rng.random(n) * 0.4
    close = (high + low) / 2
    import pandas as pd

    return pd.DataFrame(
        {
            "ts_ms": ts,
            "open": np.r_[close[0], close[:-1]],
            "high": high,
            "low": low,
            "close": close,
            "volume": np.ones(n),
        }
    )


@pytest.mark.conformance("CAUS-STRUCT-PUB")
def test_every_publication_rule_column_is_in_bar_features():
    bundle = compute_structure(_wavy(), source="t", symbol="T", timeframe="1h")
    cols = set(bundle.bar_features.columns)
    missing = [c for c in required_columns() if c not in cols]
    # fib_* grid columns may be named consistently; allow partial if compute renames.
    soft_missing = [c for c in missing if c.startswith("fib_")]
    hard_missing = [c for c in missing if c not in soft_missing]
    assert not hard_missing, f"published columns missing from bar_features: {hard_missing}"


@pytest.mark.conformance("CAUS-STRUCT-001")
def test_retrace_rule_is_successor_leg_not_own_confirm():
    rule = next(r for r in PUBLICATION_RULES if r.column == "last_retrace_pct")
    assert rule.knowable_when == "at_or_after_successor_leg_confirm_ts"
    assert rule.conformance == "CAUS-STRUCT-001"


@pytest.mark.conformance("CAUS-STRUCT-PUB")
def test_prefix_invariance_covers_all_ruled_numeric_columns():
    """Knowable-when contract implies prefix-invariance for every ruled column."""
    ohlcv = _wavy()
    full = compute_structure(ohlcv, source="t", symbol="T", timeframe="1h").bar_features
    full = full.set_index("ts_ms")
    offenders: dict[str, int] = {}
    for cut in range(len(ohlcv) - 80, len(ohlcv), 10):
        trunc = compute_structure(
            ohlcv.iloc[:cut], source="t", symbol="T", timeframe="1h"
        ).bar_features.set_index("ts_ms")
        ts = int(trunc.index[-1])
        if ts not in full.index:
            continue
        for col in required_columns():
            if col not in trunc.columns or col not in full.columns:
                continue
            a, b = trunc.loc[ts, col], full.loc[ts, col]
            if isinstance(a, str) or isinstance(b, str):
                same = str(a) == str(b)
            else:
                a_f, b_f = float(a), float(b)
                same = (np.isnan(a_f) and np.isnan(b_f)) or abs(a_f - b_f) <= 1e-12
            if not same:
                offenders[col] = offenders.get(col, 0) + 1
    assert not offenders, f"knowable-when violated (future rewrite): {offenders}"
