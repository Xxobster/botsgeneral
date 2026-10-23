"""CAUS-WAREHOUSE-001: builders that ignore OHLCV must hard-fail."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from leakage import run_leakage_audit
from leakage.checks import check_builder_responsiveness
from leakage.types import CheckId, Severity


def _synth_ohlcv(n: int = 800, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
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
    return out


def build_cached_warehouse(ohlcv: pd.DataFrame, *, interval: str = "1h") -> pd.DataFrame:
    """Ignores ohlcv — serves a frozen frame keyed only by the passed index."""
    _ = interval
    # Deterministic fake warehouse: values depend on calendar position, not prices.
    n = len(ohlcv)
    pos = np.arange(n, dtype=float)
    out = pd.DataFrame(index=ohlcv.index)
    out["last_retrace_pct"] = np.sin(pos / 17.0)
    out["struct_dir"] = np.sign(np.sin(pos / 31.0))
    return out


@pytest.mark.conformance("CAUS-WAREHOUSE-001")
def test_responsiveness_passes_causal_builder():
    ohlcv = _synth_ohlcv()
    findings = check_builder_responsiveness(ohlcv, build_causal, compare_rows=40)
    assert findings == [], findings


@pytest.mark.conformance("CAUS-WAREHOUSE-001")
def test_responsiveness_fails_cached_warehouse_builder():
    ohlcv = _synth_ohlcv()
    findings = check_builder_responsiveness(ohlcv, build_cached_warehouse, compare_rows=40)
    assert findings, "cached builder must hard-fail"
    assert any(f.detail.get("code") == "EXTERNAL_CACHE_SUSPECTED" for f in findings)
    assert all(f.check is CheckId.BUILDER_RESPONSIVENESS for f in findings)
    assert all(f.severity is Severity.HARD for f in findings)


@pytest.mark.conformance("CAUS-WAREHOUSE-001")
def test_audit_runs_responsiveness_before_prefix_false_pass(tmp_path):
    """A warehouse builder false-PASSes prefix; the audit must still FAIL overall."""
    ohlcv = _synth_ohlcv()
    report = run_leakage_audit(
        ohlcv=ohlcv,
        build_features=build_cached_warehouse,
        registry_path=tmp_path / "reg.json",
        compare_rows=40,
        cuts=2,
        run_forward_corr=False,
    )
    assert not report.ok, report.summary()
    assert any(
        f.check is CheckId.BUILDER_RESPONSIVENESS for f in report.findings
    ), report.summary()
