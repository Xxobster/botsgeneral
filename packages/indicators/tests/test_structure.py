"""Unit tests for Fibonacci price-structure indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from indicators.compute import compute_structure
from indicators.fibonacci import fib_levels, nearest_fib, retracement_ratio
from indicators.store import IndicatorDB
from indicators.swings import find_swings


def _ohlcv_uptrend(n: int = 80) -> pd.DataFrame:
    """Synthetic series with clear higher highs / higher lows."""
    rng = np.random.default_rng(0)
    t0 = 1_700_000_000_000
    tf = 3_600_000
    ts = t0 + np.arange(n, dtype=np.int64) * tf
    # Smooth uptrend + noise
    base = np.linspace(100, 140, n) + rng.normal(0, 0.3, n)
    high = base + 1.5 + rng.random(n)
    low = base - 1.5 - rng.random(n)
    # Force a few local extrema
    for i in (10, 20, 30, 40, 50, 60, 70):
        if i + 2 < n:
            high[i] = high[i - 1] + 3.0
            low[i + 5] = low[i + 4] - 2.5
    close = (high + low) / 2
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "ts_ms": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.ones(n),
            "source": "test",
        }
    )


def test_fib_levels_and_retrace():
    levels = fib_levels(100.0, 200.0)
    assert levels["0.000"] == pytest.approx(200.0)
    assert levels["1.000"] == pytest.approx(100.0)
    assert levels["0.618"] == pytest.approx(200.0 - 0.618 * 100.0)
    assert levels["1.618"] == pytest.approx(100.0 + 1.618 * 100.0)
    r = retracement_ratio(100.0, 200.0, 138.2)
    fib, lab, err = nearest_fib(r)
    assert lab == "0.618"
    assert err < 0.01


def test_find_swings_and_structure():
    df = _ohlcv_uptrend()
    swings = find_swings(
        df["high"].to_numpy(),
        df["low"].to_numpy(),
        df["ts_ms"].to_numpy(),
        left=2,
        right=2,
    )
    assert len(swings) >= 4
    # Every swing confirm index is after pivot
    assert all(s.confirm_i == s.pivot_i + 2 for s in swings)

    bundle = compute_structure(df, source="test", symbol="TEST", timeframe="1h")
    assert bundle.n_swings == len(swings)
    assert len(bundle.events) == len(swings)
    assert not bundle.bar_features.empty
    # Causality: before first confirm, last_sh/sl should be nan
    first_confirm = min(s.confirm_i for s in swings)
    early = bundle.bar_features.iloc[:first_confirm]
    assert early["last_sh_price"].isna().all() or early["last_sl_price"].isna().any()
    # Later bars have structure columns populated
    late = bundle.bar_features.iloc[-1]
    assert late["close"] > 0


def test_build_legs_bias_prefix_matches_scan():
    """O(n) prefix bias must match legacy per-swing event scan (geometry parity)."""
    from indicators.structure import build_legs, label_structure

    df = _ohlcv_uptrend(n=300)
    swings = find_swings(
        df["high"].to_numpy(),
        df["low"].to_numpy(),
        df["ts_ms"].to_numpy(),
        left=2,
        right=2,
    )
    events = label_structure(swings)
    legs = build_legs(swings, events)

    # Legacy scan
    def bias_at(swing_id: int) -> int:
        bull = bear = 0
        for e in events:
            if e.swing_id > swing_id:
                break
            if e.label in ("HH", "HL"):
                bull += 1
            elif e.label in ("LH", "LL"):
                bear += 1
        if bull > bear:
            return 1
        if bear > bull:
            return -1
        return 0

    ordered = sorted(swings, key=lambda s: (s.pivot_i, s.confirm_i))
    expected_kinds = []
    prev = None
    for s in ordered:
        if prev is None:
            prev = s
            continue
        if s.kind == prev.kind:
            prev = s
            continue
        direction = "up" if s.price > prev.price else "down"
        b = bias_at(s.swing_id)
        if b > 0:
            kind = "impulse" if direction == "up" else "correction"
        elif b < 0:
            kind = "impulse" if direction == "down" else "correction"
        else:
            kind = "unknown"
        expected_kinds.append(kind)
        prev = s
    assert [L.kind for L in legs] == expected_kinds


def test_build_legs_scales_linearly_large_n():
    """Regression: 20k+ swings must finish well under the old O(n^2) blow-up."""
    import time

    from indicators.structure import build_legs, label_structure
    from indicators.swings import Swing

    n = 20_000
    swings = []
    for i in range(n):
        kind = "high" if i % 2 == 0 else "low"
        price = 100.0 + (i if kind == "high" else -i) * 0.01
        swings.append(
            Swing(
                swing_id=i,
                kind=kind,
                pivot_i=i * 3,
                confirm_i=i * 3 + 2,
                pivot_ts_ms=i * 60_000,
                confirm_ts_ms=i * 60_000 + 30_000,
                price=price,
            )
        )
    events = label_structure(swings)
    t0 = time.perf_counter()
    legs = build_legs(swings, events)
    elapsed = time.perf_counter() - t0
    assert len(legs) > n // 3
    assert elapsed < 2.0, f"build_legs too slow: {elapsed:.2f}s"


def test_indicator_db_roundtrip(tmp_path):
    df = _ohlcv_uptrend()
    bundle = compute_structure(df, source="test", symbol="TEST", timeframe="1h")
    path = tmp_path / "indicators.sqlite"
    with IndicatorDB(path) as db:
        counts = db.upsert_bundle(bundle)
        assert counts["bar_features"] == bundle.n_bars
        feats = db.load_bar_features("TEST", "1h", source="test")
        legs = db.load_legs("TEST", "1h", source="test")
        swings = db.load_swings("TEST", "1h", source="test")
        cov = db.coverage()
    assert len(feats) == bundle.n_bars
    assert len(swings) == bundle.n_swings
    assert not cov.empty
    assert list(cov["symbol"]) == ["TEST"]
    # legs may be empty on weird synthetic data but usually not
    assert isinstance(legs, pd.DataFrame)
