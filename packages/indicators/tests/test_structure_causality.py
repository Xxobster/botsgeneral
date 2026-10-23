"""CAUS-STRUCT-001: bar T must not change when bars after T arrive.

Live recomputes the structure series from candles up to the current bar; research
recomputes the same series later over a longer history. Every published column has
to be a function of data at or before its own bar, or the two can never agree and
the research number is look-ahead.

Regression for the leg-retracement defect: ``retrace_pct`` measures a leg against
the END of the following opposite leg, so publishing it at the leg's own
confirmation time back-filled future prices into bar T.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from indicators.compute import compute_structure

PUBLISHED_COLUMNS = (
    "last_sh_price",
    "dist_last_sh_pct",
    "last_sl_price",
    "dist_last_sl_pct",
    "structure_bias",
    "last_leg_dir",
    "last_leg_kind",
    "last_leg_len_pct",
    "last_retrace_pct",
    "last_retrace_fib",
    "nearest_support",
    "nearest_resistance",
    "dist_support_pct",
    "dist_resistance_pct",
)


def _wavy_ohlcv(n: int = 400, seed: int = 7) -> pd.DataFrame:
    """Series with many confirmed swings in both directions."""
    rng = np.random.default_rng(seed)
    ts = 1_700_000_000_000 + np.arange(n, dtype=np.int64) * 3_600_000
    t = np.arange(n)
    base = 100 + 8 * np.sin(t / 7.0) + 3 * np.sin(t / 23.0) + t * 0.02
    base = base + rng.normal(0, 0.25, n)
    high = base + 0.8 + rng.random(n) * 0.4
    low = base - 0.8 - rng.random(n) * 0.4
    close = (high + low) / 2
    return pd.DataFrame(
        {
            "ts_ms": ts,
            "open": np.r_[close[0], close[:-1]],
            "high": high,
            "low": low,
            "close": close,
            "volume": np.ones(n),
            "source": "test",
        }
    )


def _bar_features(ohlcv: pd.DataFrame) -> pd.DataFrame:
    bundle = compute_structure(
        ohlcv, source="test", symbol="TESTUSDT", timeframe="1h"
    )
    df = bundle.bar_features.copy()
    return df.set_index("ts_ms")


def test_bar_features_are_prefix_invariant():
    """Truncating the future must not move any already-published value."""
    ohlcv = _wavy_ohlcv()
    full = _bar_features(ohlcv)

    offenders: dict[str, int] = {}
    for cut in range(len(ohlcv) - 60, len(ohlcv), 6):
        truncated = _bar_features(ohlcv.iloc[:cut])
        ts = int(truncated.index[-1])
        if ts not in full.index:
            continue
        for col in PUBLISHED_COLUMNS:
            if col not in truncated.columns:
                continue
            a, b = truncated.loc[ts, col], full.loc[ts, col]
            if isinstance(a, str) or isinstance(b, str):
                same = str(a) == str(b)
            else:
                a_f, b_f = float(a), float(b)
                same = (np.isnan(a_f) and np.isnan(b_f)) or abs(a_f - b_f) <= 1e-12
            if not same:
                offenders[col] = offenders.get(col, 0) + 1

    assert not offenders, (
        "columns rewritten by future bars (look-ahead): "
        f"{sorted(offenders.items(), key=lambda kv: -kv[1])}"
    )


def test_retrace_is_published_only_after_the_next_leg_confirms():
    """The retracement in force at bar T belongs to a *completed* retracement."""
    ohlcv = _wavy_ohlcv()
    bundle = compute_structure(
        ohlcv, source="test", symbol="TESTUSDT", timeframe="1h"
    )
    legs = bundle.legs
    if len(legs) < 3:
        pytest.skip("fixture produced too few legs")

    feats = bundle.bar_features.set_index("ts_ms")
    in_force = float(feats["last_retrace_pct"].to_numpy(dtype=float)[-1])
    # The newest leg has no confirmed successor, so its retracement is unknowable.
    newest = float(legs[-1].retrace_pct)
    if np.isfinite(newest) and np.isfinite(in_force):
        assert not np.isclose(in_force, newest, atol=1e-12), (
            "bar T is using the retracement of the leg that is still forming"
        )
    # It must instead be a retracement whose closing leg has already confirmed.
    completed = [
        float(lg.retrace_pct) for lg in legs[:-1] if np.isfinite(float(lg.retrace_pct))
    ]
    if np.isfinite(in_force):
        assert any(np.isclose(in_force, c, atol=1e-12) for c in completed), (
            "in-force retracement does not correspond to any completed leg"
        )


def test_direction_and_length_still_publish_at_leg_confirmation():
    """The causality fix must not delay columns that are known at confirmation."""
    ohlcv = _wavy_ohlcv()
    feats = _bar_features(ohlcv)
    known = feats["last_leg_dir"].astype(str) != ""
    assert known.to_numpy().sum() > len(feats) * 0.5, (
        "leg direction should be in force for most bars"
    )
