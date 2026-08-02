"""Train/test database geometry checks (hardening, not causality proof)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..types import CheckId, Finding, Severity


def _load_ts(path: str | Path, ts_col: str = "ts_ms") -> np.ndarray:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    if p.suffix.lower() in {".pkl", ".pickle"}:
        df = pd.read_pickle(p)
    else:
        import sqlite3

        conn = sqlite3.connect(p)
        try:
            tables = pd.read_sql(
                "SELECT name FROM sqlite_master WHERE type='table'", conn
            )["name"].tolist()
            if not tables:
                raise ValueError(f"no tables in {p}")
            table = next((t for t in tables if "indicator" in t.lower()), tables[0])
            df = pd.read_sql(f'SELECT * FROM "{table}"', conn)
        finally:
            conn.close()
    if ts_col not in df.columns:
        # common aliases
        for alt in ("timestamp", "ts", "entry_ts_ms", "t"):
            if alt in df.columns:
                ts_col = alt
                break
        else:
            raise ValueError(f"no timestamp column in {p}; columns={list(df.columns)[:20]}")
    s = pd.to_numeric(df[ts_col], errors="coerce")
    if s.isna().all():
        # datetime strings
        s = pd.to_datetime(df[ts_col], utc=True, errors="coerce").astype("int64") // 10**6
    return s.dropna().to_numpy(dtype=np.int64)


def check_train_test_split(
    train_path: str | Path,
    test_path: str | Path,
    *,
    ts_col: str = "ts_ms",
    min_gap_ms: int = 0,
) -> list[Finding]:
    """Require distinct files, no timestamp overlap, train max < test min (+ gap)."""
    findings: list[Finding] = []
    tp = Path(train_path).resolve()
    xp = Path(test_path).resolve()
    if tp == xp:
        findings.append(
            Finding(
                check=CheckId.TRAIN_TEST_SPLIT,
                severity=Severity.HARD,
                column=None,
                message="train and test resolve to the same file path",
                detail={"path": str(tp)},
            )
        )
        return findings

    train_ts = np.sort(np.unique(_load_ts(tp, ts_col=ts_col)))
    test_ts = np.sort(np.unique(_load_ts(xp, ts_col=ts_col)))
    if train_ts.size == 0 or test_ts.size == 0:
        findings.append(
            Finding(
                check=CheckId.TRAIN_TEST_SPLIT,
                severity=Severity.HARD,
                column=None,
                message="train or test has zero usable timestamps",
                detail={"n_train": int(train_ts.size), "n_test": int(test_ts.size)},
            )
        )
        return findings

    overlap = np.intersect1d(train_ts, test_ts)
    if overlap.size:
        findings.append(
            Finding(
                check=CheckId.TRAIN_TEST_SPLIT,
                severity=Severity.HARD,
                column=None,
                message=f"train/test timestamp overlap: {overlap.size} shared keys",
                detail={"n_overlap": int(overlap.size)},
            )
        )

    train_max = int(train_ts.max())
    test_min = int(test_ts.min())
    if train_max >= test_min:
        findings.append(
            Finding(
                check=CheckId.TRAIN_TEST_SPLIT,
                severity=Severity.HARD,
                column=None,
                message=(
                    f"train max ts ({train_max}) is not strictly before "
                    f"test min ts ({test_min})"
                ),
                detail={"train_max": train_max, "test_min": test_min},
            )
        )
    elif min_gap_ms and (test_min - train_max) < min_gap_ms:
        findings.append(
            Finding(
                check=CheckId.TRAIN_TEST_SPLIT,
                severity=Severity.HARD,
                column=None,
                message=(
                    f"train/test gap {test_min - train_max} ms < required "
                    f"min_gap_ms={min_gap_ms}"
                ),
                detail={
                    "gap_ms": int(test_min - train_max),
                    "min_gap_ms": min_gap_ms,
                },
            )
        )

    if not findings:
        findings.append(
            Finding(
                check=CheckId.TRAIN_TEST_SPLIT,
                severity=Severity.ADVISORY,
                column=None,
                message=(
                    "train/test file geometry OK — still not causality proof; "
                    "prefix-invariance remains mandatory"
                ),
                detail={
                    "train_max": train_max,
                    "test_min": test_min,
                    "gap_ms": int(test_min - train_max),
                },
            )
        )
    return findings
