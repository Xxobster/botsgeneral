"""Scan feature column names for label / future / outcome leakage."""

from __future__ import annotations

import re

import pandas as pd

from ..types import CheckId, Finding, Severity

# Substrings that almost always mean the column is a label or post-outcome field.
_HARD_SUBSTR = (
    "net_return",
    "gross_return",
    "is_win",
    "outcome",
    "tp_touch",
    "sl_touch",
    "holding_ms",
    "trade_id",
    "label_",
    "_label",
    "target_",
    "y_true",
    "y_hat",
)

_ADVISORY_RE = re.compile(
    r"(future|fwd_|forward_|lookahead|look_ahead|next_ret|ret_fwd)",
    re.IGNORECASE,
)


def check_name_scan(
    features: pd.DataFrame,
    *,
    extra_hard: tuple[str, ...] = (),
) -> list[Finding]:
    """Hard-fail known label/outcome names; advisory on future-ish names."""
    findings: list[Finding] = []
    hard_needles = tuple(s.lower() for s in (_HARD_SUBSTR + extra_hard))
    for col in features.columns:
        name = str(col)
        low = name.lower()
        hit = next((n for n in hard_needles if n in low), None)
        if hit is not None:
            findings.append(
                Finding(
                    check=CheckId.NAME_SCAN,
                    severity=Severity.HARD,
                    column=name,
                    message=f"feature name contains label/outcome token '{hit}'",
                    detail={"token": hit},
                )
            )
            continue
        if _ADVISORY_RE.search(name):
            findings.append(
                Finding(
                    check=CheckId.NAME_SCAN,
                    severity=Severity.ADVISORY,
                    column=name,
                    message="feature name looks future-looking; verify causality",
                )
            )
    return findings
