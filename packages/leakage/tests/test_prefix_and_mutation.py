"""Prefix-invariance and future-mutation catch centered / forward-looking features."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from leakage import run_leakage_audit
from leakage.checks import check_future_mutation, check_prefix_invariance
from leakage.types import CheckId


def _synth_ohlcv(n: int = 800, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # random walk close
    ret = rng.normal(0, 0.01, size=n)
    close = 100 * np.exp(np.cumsum(ret))
    high = close * (1 + rng.uniform(0, 0.005, size=n))
    low = close * (1 - rng.uniform(0, 0.005, size=n))
    open_ = close * (1 + rng.normal(0, 0.001, size=n))
    vol = rng.uniform(1, 10, size=n)
    idx = pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


def build_causal(ohlcv: pd.DataFrame, *, interval: str = "1h") -> pd.DataFrame:
    c = ohlcv["close"]
    out = pd.DataFrame(index=ohlcv.index)
    out["ret_1"] = c.pct_change(1)
    out["sma_20"] = c.rolling(20, min_periods=20).mean()
    out["ema_12"] = c.ewm(span=12, adjust=False).mean()
    return out


def build_leaky_centered(ohlcv: pd.DataFrame, *, interval: str = "1h") -> pd.DataFrame:
    """Mimic pandas_ta DPO centered=True: subtract centered MA then shift -t."""
    c = ohlcv["close"]
    length = 20
    t = int(0.5 * length) + 1  # 11
    # centered MA via shift(-t) after rolling mean
    ma = c.rolling(length, min_periods=length).mean().shift(-t)
    dpo = c - ma
    out = build_causal(ohlcv, interval=interval)
    out["dpo_leaky"] = dpo
    return out


def test_prefix_passes_causal():
    ohlcv = _synth_ohlcv()
    findings = check_prefix_invariance(
        ohlcv, build_causal, cuts=2, compare_rows=100
    )
    assert findings == []


def test_prefix_fails_leaky_dpo():
    ohlcv = _synth_ohlcv()
    findings = check_prefix_invariance(
        ohlcv, build_leaky_centered, cuts=2, compare_rows=100
    )
    cols = {f.column for f in findings}
    assert "dpo_leaky" in cols
    assert all(f.check is CheckId.PREFIX_INVARIANCE for f in findings)


def test_future_mutation_fails_leaky():
    ohlcv = _synth_ohlcv()
    findings = check_future_mutation(
        ohlcv, build_leaky_centered, compare_rows=100
    )
    assert any(f.column == "dpo_leaky" for f in findings)


def test_future_mutation_passes_causal():
    ohlcv = _synth_ohlcv()
    findings = check_future_mutation(ohlcv, build_causal, compare_rows=100)
    assert findings == []


def test_audit_marks_registry(tmp_path):
    ohlcv = _synth_ohlcv()
    reg = tmp_path / "leakage_registry.json"
    report = run_leakage_audit(
        ohlcv=ohlcv,
        build_features=build_leaky_centered,
        registry_path=reg,
        compare_rows=100,
        cuts=2,
        symbol="TEST",
    )
    assert not report.ok
    assert "dpo_leaky" in report.leakage_potential
    text = reg.read_text(encoding="utf-8")
    assert "LEAKAGE_POTENTIAL" in text
    assert "dpo_leaky" in text


def test_audit_pass_causal(tmp_path):
    ohlcv = _synth_ohlcv()
    reg = tmp_path / "leakage_registry.json"
    report = run_leakage_audit(
        ohlcv=ohlcv,
        build_features=build_causal,
        registry_path=reg,
        compare_rows=100,
        cuts=2,
        run_forward_corr=False,
    )
    assert report.ok, report.summary()
