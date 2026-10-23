"""Explicit “knowable when” rules for every published structure bar column.

Swing confirmation alone is not enough: derived columns (especially leg retracement)
become knowable at different instants. Each rule is bound by tests in
``tests/test_structure_causality.py`` / ``tests/test_publication_rules.py``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PublicationRule:
    column: str
    knowable_when: str
    conformance: str
    notes: str = ""


# Canonical publication contract for StructureBundle.bar_features columns.
PUBLICATION_RULES: tuple[PublicationRule, ...] = (
    PublicationRule(
        "last_sh_price",
        "at_or_after_swing_high_confirm_ts",
        "CAUS-STRUCT-SWING",
    ),
    PublicationRule(
        "last_sl_price",
        "at_or_after_swing_low_confirm_ts",
        "CAUS-STRUCT-SWING",
    ),
    PublicationRule(
        "dist_last_sh_pct",
        "at_or_after_swing_high_confirm_ts",
        "CAUS-STRUCT-SWING",
    ),
    PublicationRule(
        "dist_last_sl_pct",
        "at_or_after_swing_low_confirm_ts",
        "CAUS-STRUCT-SWING",
    ),
    PublicationRule(
        "nearest_support",
        "at_or_after_cited_level_confirm_ts",
        "CAUS-STRUCT-SR",
    ),
    PublicationRule(
        "nearest_resistance",
        "at_or_after_cited_level_confirm_ts",
        "CAUS-STRUCT-SR",
    ),
    PublicationRule(
        "dist_support_pct",
        "at_or_after_cited_level_confirm_ts",
        "CAUS-STRUCT-SR",
    ),
    PublicationRule(
        "dist_resistance_pct",
        "at_or_after_cited_level_confirm_ts",
        "CAUS-STRUCT-SR",
    ),
    PublicationRule(
        "structure_bias",
        "at_or_after_last_structure_event_confirm_ts",
        "CAUS-STRUCT-LABEL",
    ),
    PublicationRule(
        "last_structure_label",
        "at_or_after_last_structure_event_confirm_ts",
        "CAUS-STRUCT-LABEL",
    ),
    PublicationRule(
        "last_leg_dir",
        "at_or_after_leg_end_confirm_ts",
        "CAUS-STRUCT-LEG",
        "Direction/kind/length of a leg are known when that leg confirms.",
    ),
    PublicationRule(
        "last_leg_kind",
        "at_or_after_leg_end_confirm_ts",
        "CAUS-STRUCT-LEG",
    ),
    PublicationRule(
        "last_leg_len_pct",
        "at_or_after_leg_end_confirm_ts",
        "CAUS-STRUCT-LEG",
    ),
    PublicationRule(
        "last_retrace_pct",
        "at_or_after_successor_leg_confirm_ts",
        "CAUS-STRUCT-001",
        "Retracement of leg i is measured to the END of leg i+1; publish only then.",
    ),
    PublicationRule(
        "last_retrace_fib",
        "at_or_after_successor_leg_confirm_ts",
        "CAUS-STRUCT-001",
    ),
    PublicationRule(
        "fib_0000",
        "at_or_after_current_leg_anchors_confirm_ts",
        "CAUS-STRUCT-FIB",
    ),
    PublicationRule(
        "fib_1000",
        "at_or_after_current_leg_anchors_confirm_ts",
        "CAUS-STRUCT-FIB",
    ),
)


def columns_for_rule(knowable_when: str) -> tuple[str, ...]:
    return tuple(r.column for r in PUBLICATION_RULES if r.knowable_when == knowable_when)


def required_columns() -> tuple[str, ...]:
    return tuple(r.column for r in PUBLICATION_RULES)
