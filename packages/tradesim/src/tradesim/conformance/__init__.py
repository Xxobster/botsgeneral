"""Conformance pack: identifier registry, golden fixtures, adapter, checker, stamping.

The pack grades any engine through a thin adapter, so it protects the family before any
migration happens. Grading a foreign engine and writing down what it fails is a complete,
useful action on its own.
"""

from __future__ import annotations

from .adapter import (
    EngineAdapter,
    FixtureOutcome,
    NormalisedResult,
    NormalisedTrade,
    TradesimAdapter,
    grade,
)
from .fixture_loader import (
    Fixture,
    covered_identifiers,
    fixture_pack_hash,
    fixture_pack_summary,
    fixtures_for,
    load_fixtures,
)
from .registry import (
    CONTRACT_BRACKET_BACKTEST,
    CONTRACT_BRACKET_PORTFOLIO,
    CONTRACT_LIVE_RUNNER,
    CONTRACTS,
    NON_NEGOTIABLE_ENTRY_BAR,
    REGISTRY,
    ConformanceItem,
    all_items,
    extract_identifiers,
    fixture_computable_for,
    get,
    registry_digest,
    required_for,
)
from .stamp import (
    ConformanceStamp,
    NotQuotableError,
    assert_quotable,
    build_stamp,
    last_stamp,
    ungraded_stamp,
)

__all__ = [
    "CONTRACTS",
    "CONTRACT_BRACKET_BACKTEST",
    "CONTRACT_BRACKET_PORTFOLIO",
    "CONTRACT_LIVE_RUNNER",
    "ConformanceItem",
    "ConformanceStamp",
    "EngineAdapter",
    "Fixture",
    "FixtureOutcome",
    "NON_NEGOTIABLE_ENTRY_BAR",
    "NormalisedResult",
    "NormalisedTrade",
    "NotQuotableError",
    "REGISTRY",
    "TradesimAdapter",
    "all_items",
    "assert_quotable",
    "build_stamp",
    "covered_identifiers",
    "extract_identifiers",
    "fixture_computable_for",
    "fixture_pack_hash",
    "fixture_pack_summary",
    "fixtures_for",
    "get",
    "grade",
    "last_stamp",
    "load_fixtures",
    "registry_digest",
    "required_for",
    "ungraded_stamp",
]
