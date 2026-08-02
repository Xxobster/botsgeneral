"""Shared types for the leakage audit engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol

import pandas as pd


class Severity(str, Enum):
    HARD = "HARD"  # fail closed — block train/test
    ADVISORY = "ADVISORY"  # mark LEAKAGE_POTENTIAL; investigate before use


class CheckId(str, Enum):
    PREFIX_INVARIANCE = "PREFIX_INVARIANCE"
    FUTURE_MUTATION = "FUTURE_MUTATION"
    FORWARD_CORR = "FORWARD_CORR"
    NAME_SCAN = "NAME_SCAN"
    TRAIN_TEST_SPLIT = "TRAIN_TEST_SPLIT"


class ColumnStatus(str, Enum):
    LEAKAGE_POTENTIAL = "LEAKAGE_POTENTIAL"
    CLEAN = "CLEAN"
    CLEARED = "CLEARED"  # was potential; later audit passed with same engine note


FeatureBuilder = Callable[..., pd.DataFrame]


class FeatureBuilderProtocol(Protocol):
    def __call__(self, ohlcv: pd.DataFrame, *, interval: str = "1h") -> pd.DataFrame: ...


@dataclass
class Finding:
    check: CheckId
    severity: Severity
    column: str | None
    message: str
    detail: dict = field(default_factory=dict)

    def key(self) -> str:
        return f"{self.check.value}:{self.column or '*'}"


@dataclass
class LeakageReport:
    ok: bool
    n_columns: int
    findings: list[Finding] = field(default_factory=list)
    leakage_potential: list[str] = field(default_factory=list)
    registry_path: str | None = None
    notes: list[str] = field(default_factory=list)

    def hard_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.HARD]

    def summary(self) -> str:
        if self.ok:
            return (
                f"PASS — {self.n_columns} columns; "
                f"no hard-fail leakage; "
                f"LEAKAGE_POTENTIAL={len(self.leakage_potential)}"
            )
        hard = self.hard_findings()
        cols = sorted({f.column for f in hard if f.column})
        return (
            f"FAIL — {len(hard)} hard finding(s); "
            f"columns={cols}; "
            f"LEAKAGE_POTENTIAL={sorted(self.leakage_potential)}"
        )
