"""Name scan and train/test geometry checks."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from leakage import run_leakage_audit
from leakage.checks import check_name_scan, check_train_test_split
from leakage.registry import assert_no_leakage_potential, leakage_potential_columns
from leakage.types import CheckId, Severity


def test_name_scan_hard_on_label_columns():
    df = pd.DataFrame(
        {
            "sma_20": [1.0, 2.0],
            "net_return": [0.1, -0.1],
            "is_win": [1, 0],
            "fwd_ret_6h": [0.01, 0.02],
        }
    )
    findings = check_name_scan(df)
    hard_cols = {f.column for f in findings if f.severity is Severity.HARD}
    assert "net_return" in hard_cols
    assert "is_win" in hard_cols
    adv_cols = {f.column for f in findings if f.severity is Severity.ADVISORY}
    assert "fwd_ret_6h" in adv_cols


def _write_ind_db(path: Path, ts: np.ndarray) -> None:
    conn = sqlite3.connect(path)
    try:
        df = pd.DataFrame({"ts_ms": ts, "sma_20": np.arange(len(ts), dtype=float)})
        df.to_sql("btcusdt_1h_indicators", conn, index=False, if_exists="replace")
    finally:
        conn.close()


def test_train_test_split_ok_and_overlap(tmp_path):
    train = tmp_path / "train.db"
    test = tmp_path / "test.db"
    _write_ind_db(train, np.arange(1_000_000, 1_000_100))
    _write_ind_db(test, np.arange(1_000_200, 1_000_300))
    findings = check_train_test_split(train, test, min_gap_ms=50)
    # only the geometry-OK advisory
    assert all(f.severity is Severity.ADVISORY for f in findings)
    assert findings[0].check is CheckId.TRAIN_TEST_SPLIT

    bad_test = tmp_path / "bad_test.db"
    _write_ind_db(bad_test, np.arange(1_000_050, 1_000_150))
    bad = check_train_test_split(train, bad_test)
    assert any(f.severity is Severity.HARD for f in bad)


def test_assert_no_leakage_potential(tmp_path):
    from leakage.registry import update_registry_from_findings
    from leakage.types import Finding

    reg = tmp_path / "reg.json"
    update_registry_from_findings(
        reg,
        [
            Finding(
                check=CheckId.PREFIX_INVARIANCE,
                severity=Severity.HARD,
                column="dpo_20",
                message="leaky",
            )
        ],
    )
    assert leakage_potential_columns(reg) == ["dpo_20"]
    try:
        assert_no_leakage_potential(reg, ["sma_20", "dpo_20"])
        raised = False
    except RuntimeError:
        raised = True
    assert raised
    assert_no_leakage_potential(reg, ["sma_20"])


def test_audit_name_only():
    feat = pd.DataFrame({"net_return": [0.1, 0.2, 0.3]})
    report = run_leakage_audit(features=feat, run_forward_corr=False)
    assert not report.ok
    assert "net_return" in report.leakage_potential
