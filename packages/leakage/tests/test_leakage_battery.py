"""Battery covering each leakage class the engine must catch."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from leakage import run_leakage_audit
from leakage.checks import (
    check_builder_responsiveness,
    check_forward_shift_scan,
    check_future_mutation,
    check_prefix_invariance,
    check_streaming_batch_tip,
)
from leakage.types import CheckId, Severity


def _synth(n: int = 900, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ret = rng.normal(0, 0.01, size=n)
    close = 100 * np.exp(np.cumsum(ret))
    idx = pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 1.0,
        },
        index=idx,
    )


def build_causal(ohlcv: pd.DataFrame, *, interval: str = "1h") -> pd.DataFrame:
    c = ohlcv["close"]
    out = pd.DataFrame(index=ohlcv.index)
    out["ret_1"] = c.pct_change(1)
    out["sma_20"] = c.rolling(20, min_periods=20).mean()
    return out


def build_shift_neg1(ohlcv: pd.DataFrame, *, interval: str = "1h") -> pd.DataFrame:
    out = build_causal(ohlcv, interval=interval)
    out["future_close"] = ohlcv["close"].shift(-1)
    return out


def build_centered_ma(ohlcv: pd.DataFrame, *, interval: str = "1h") -> pd.DataFrame:
    c = ohlcv["close"]
    out = build_causal(ohlcv, interval=interval)
    out["centered"] = c.rolling(21, min_periods=21).mean().shift(-10)
    return out


def build_fwd_return_feature(ohlcv: pd.DataFrame, *, interval: str = "1h") -> pd.DataFrame:
    out = build_causal(ohlcv, interval=interval)
    out["y_fwd6"] = ohlcv["close"].pct_change(6).shift(-6)
    return out


def build_warehouse(ohlcv: pd.DataFrame, *, interval: str = "1h") -> pd.DataFrame:
    _ = interval
    pos = np.arange(len(ohlcv), dtype=float)
    return pd.DataFrame({"cached": np.sin(pos / 11.0)}, index=ohlcv.index)


@pytest.mark.conformance("CAUS-PREFIX-001")
def test_prefix_catches_centered_ma():
    ohlcv = _synth()
    findings = check_prefix_invariance(ohlcv, build_centered_ma, cuts=2, compare_rows=100)
    assert any(f.column == "centered" for f in findings)


@pytest.mark.conformance("CAUS-MUTATION-001")
def test_future_mutation_catches_shift_neg1():
    ohlcv = _synth()
    findings = check_future_mutation(ohlcv, build_shift_neg1, compare_rows=100)
    assert any(f.column == "future_close" for f in findings)


@pytest.mark.conformance("CAUS-WAREHOUSE-001")
def test_responsiveness_catches_warehouse():
    ohlcv = _synth()
    findings = check_builder_responsiveness(ohlcv, build_warehouse, compare_rows=40)
    assert findings and any(f.detail.get("code") == "EXTERNAL_CACHE_SUSPECTED" for f in findings)


@pytest.mark.conformance("CAUS-STREAM-001")
def test_streaming_batch_catches_shift_neg1():
    """Tip of a short prefix must rewrite once real future bars exist after it."""
    ohlcv = _synth()
    findings = check_streaming_batch_tip(ohlcv, build_shift_neg1, tip_rows=20)
    assert any(f.column == "future_close" for f in findings), findings


@pytest.mark.conformance("CAUS-SHIFT-001")
def test_forward_shift_scan_catches_label_column():
    ohlcv = _synth()
    feat = build_fwd_return_feature(ohlcv)
    findings = check_forward_shift_scan(ohlcv, feat, horizons=(6,))
    assert any(
        f.column == "y_fwd6" and f.severity is Severity.HARD for f in findings
    )


@pytest.mark.conformance("CAUS-DECISIVE-001")
def test_skipping_decisive_check_is_hard_fail(tmp_path):
    ohlcv = _synth()
    report = run_leakage_audit(
        ohlcv=ohlcv,
        build_features=build_causal,
        registry_path=tmp_path / "r.json",
        compare_rows=80,
        cuts=2,
        run_forward_corr=False,
        run_builder_responsiveness=False,  # agent tries to skip
        require_decisive=True,
    )
    assert not report.ok
    assert any(f.check is CheckId.DECISIVE_CHECKS_REQUIRED for f in report.findings)


@pytest.mark.conformance("CAUS-BATTERY-001")
def test_full_battery_passes_causal(tmp_path):
    ohlcv = _synth()
    report = run_leakage_audit(
        ohlcv=ohlcv,
        build_features=build_causal,
        registry_path=tmp_path / "r.json",
        compare_rows=80,
        cuts=2,
        run_forward_corr=False,
    )
    assert report.ok, report.summary()


@pytest.mark.conformance("CAUS-BATTERY-001")
def test_full_battery_fails_warehouse(tmp_path):
    ohlcv = _synth()
    report = run_leakage_audit(
        ohlcv=ohlcv,
        build_features=build_warehouse,
        registry_path=tmp_path / "r.json",
        compare_rows=80,
        cuts=2,
        run_forward_corr=False,
    )
    assert not report.ok
    assert any(f.check is CheckId.BUILDER_RESPONSIVENESS for f in report.findings)
