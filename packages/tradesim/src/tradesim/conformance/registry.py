"""The conformance identifier registry (standard section 24.0).

Every mandatory behaviour carries a stable identifier ``AREA-NNN``. Identifiers are
permanent: never renumbered, never reused. A retired identifier keeps its number and is
marked ``retired`` so historical stamps stay interpretable.

An identifier is satisfied only when a discoverable automated test declares it AND that
test runs and passes. A *missing* binding is a hard failure, exactly like a failing test:
that is the mechanism that would have caught the entry-bar defect, where the repository
had a green suite but nothing declared ``EXEC-010`` and nothing objected to its absence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping

IDENTIFIER_RE = re.compile(r"\b(DATA|CAUS|EXEC|FUND|QTY|METR|VALD|PORT|LIVE)-(\d{3})\b")

AREAS = ("DATA", "CAUS", "EXEC", "FUND", "QTY", "METR", "VALD", "PORT", "LIVE")


@dataclass(frozen=True)
class ConformanceItem:
    identifier: str
    area: str
    behaviour: str
    section: str
    contracts: frozenset[str]
    fixture_computable: bool = False
    retired: bool = False
    note: str = ""

    def is_mandatory_for(self, contract: str) -> bool:
        return (not self.retired) and contract in self.contracts


# --------------------------------------------------------------------------------------
# Contracts
# --------------------------------------------------------------------------------------
# A contract names the kind of thing being graded. An engine declares one, and the
# checker demands exactly the identifiers that contract makes mandatory.

CONTRACT_BRACKET_BACKTEST = "perp_bracket_backtest"
CONTRACT_BRACKET_PORTFOLIO = "perp_bracket_portfolio"
CONTRACT_LIVE_RUNNER = "perp_live_runner"

CONTRACTS: tuple[str, ...] = (
    CONTRACT_BRACKET_BACKTEST,
    CONTRACT_BRACKET_PORTFOLIO,
    CONTRACT_LIVE_RUNNER,
)

_BT = CONTRACT_BRACKET_BACKTEST
_PF = CONTRACT_BRACKET_PORTFOLIO
_LR = CONTRACT_LIVE_RUNNER

# The portfolio contract is a superset of the single-symbol backtest contract, and the
# live-runner contract is a superset of both. Expressed by listing every contract an
# item belongs to, so a reader never has to compute a closure in their head.
_ALL = (_BT, _PF, _LR)
_PF_UP = (_PF, _LR)


def _item(
    identifier: str,
    behaviour: str,
    section: str,
    contracts: Iterable[str],
    *,
    fixture: bool = False,
    retired: bool = False,
    note: str = "",
) -> ConformanceItem:
    area = identifier.split("-", 1)[0]
    if area not in AREAS:
        raise ValueError(f"unknown area in {identifier}")
    return ConformanceItem(
        identifier=identifier,
        area=area,
        behaviour=behaviour,
        section=section,
        contracts=frozenset(contracts),
        fixture_computable=fixture,
        retired=retired,
        note=note,
    )


REGISTRY: tuple[ConformanceItem, ...] = (
    # ---------------------------------------------------------------- DATA -----------
    _item(
        "DATA-001",
        "Duplicate, missing and out-of-order bars are detected and rejected, never silently reordered or de-duplicated.",
        "6.4",
        _ALL,
        fixture=True,
    ),
    _item(
        "DATA-002",
        "OHLC invariants are enforced: high >= max(open, close), low <= min(open, close), and non-positive prices are rejected.",
        "6.4",
        _ALL,
        fixture=True,
    ),
    _item(
        "DATA-003",
        "Bars before the instrument's launch timestamp are skipped with an explicit reason, never traded.",
        "6.1",
        _ALL,
    ),
    _item(
        "DATA-004",
        "Bar timestamps are UTC epoch milliseconds naming the bar's OPEN, and the timeframe is consistent with the spacing.",
        "6.5",
        _ALL,
    ),
    _item(
        "DATA-005",
        "A gap in the touch (lower) timeframe invalidates lower-timeframe resolution for that decision bar instead of silently falling back to a favourable answer.",
        "6.4",
        _ALL,
    ),
    # ---------------------------------------------------------------- CAUS -----------
    _item(
        "CAUS-001",
        "A signal computed from a bar's close cannot fill at that close retroactively with that bar's range treated as post-entry.",
        "7.1",
        _ALL,
        fixture=True,
    ),
    _item(
        "CAUS-002",
        "Mutating future bars cannot change any earlier trade: entry, exit, price or reason.",
        "7.4",
        _ALL,
    ),
    _item(
        "CAUS-003",
        "Truncating the series after bar k reproduces byte-identical trades for everything resolved at or before k.",
        "7.4",
        _ALL,
    ),
    _item(
        "CAUS-004",
        "Touch-timeframe replay for a decision bar reads only sub-bars inside that decision bar's own window.",
        "10",
        _ALL,
    ),
    _item(
        "CAUS-005",
        "Trailing and break-even updates derived from a bar cannot take effect on that same bar's exit resolution without lower-timeframe evidence.",
        "10",
        _ALL,
        fixture=True,
    ),
    # ---------------------------------------------------------------- EXEC -----------
    _item(
        "EXEC-001",
        "A signal computed from a bar's close fills at the next executable price, not at that close.",
        "9.1 / 24.0",
        _ALL,
        fixture=True,
    ),
    _item(
        "EXEC-002",
        "Entry fill price includes directional slippage; slippage moves the price and is never folded into the fee rate.",
        "11.2 / 24.0",
        _ALL,
        fixture=True,
    ),
    _item(
        "EXEC-003",
        "Fee is charged per fill, on that fill's executed notional, at the correct maker/taker rate for its order type.",
        "11.0 / 24.0",
        _ALL,
        fixture=True,
    ),
    _item(
        "EXEC-004",
        "A gap through the stop fills worse than the stop, not at the stop.",
        "9.3 / 24.0",
        _ALL,
        fixture=True,
    ),
    _item(
        "EXEC-005",
        "A take-profit limit touch fills at the limit price with no favourable exit slippage; a market-triggered take profit does slip.",
        "11.0 / 24.0",
        _ALL,
        fixture=True,
    ),
    _item(
        "EXEC-006",
        "Both stop and target inside one bar resolves adversely, or by lower-timeframe replay, and is labelled ambiguous.",
        "10 / 24.0",
        _ALL,
        fixture=True,
    ),
    _item(
        "EXEC-007",
        "Stop and liquidation inside one bar resolve in the correct order for the actual margin model.",
        "13.4 / 24.0",
        _ALL,
        fixture=True,
    ),
    _item(
        "EXEC-008",
        "Maximum hold exits at the correct bar and price, counted from the entry bar index.",
        "9.6 / 24.0",
        _ALL,
        fixture=True,
    ),
    _item(
        "EXEC-009",
        "Reduce-only and position-mode semantics match the live venue; a reduce-only order never opens or flips a position.",
        "9.3 / 24.0",
        (_LR,),
        note="Order-routing behaviour. Not mandatory for a pure bar-replay backtest contract.",
    ),
    _item(
        "EXEC-010",
        "ENTRY BAR STOP: entry fills at a bar and that same bar's range takes out the stop; the trade closes on its entry bar with exit_ts == entry_ts and both fills' fees charged.",
        "9.6 / 24.0",
        _ALL,
        fixture=True,
    ),
    _item(
        "EXEC-011",
        "ENTRY BAR TARGET: the same, for the take profit.",
        "9.6 / 24.0",
        _ALL,
        fixture=True,
    ),
    _item(
        "EXEC-012",
        "ENTRY BAR BOTH: the entry bar contains stop and target; the adverse one is taken (or lower-timeframe resolved) and the trade is labelled ambiguous.",
        "9.6 / 24.0",
        _ALL,
        fixture=True,
    ),
    _item(
        "EXEC-013",
        "ENTRY BAR LIQUIDATION: the entry bar reaches the liquidation price; liquidation resolves on the entry bar, in the correct order relative to the stop.",
        "9.6 / 24.0",
        _ALL,
        fixture=True,
    ),
    _item(
        "EXEC-014",
        "QUIET ENTRY BAR (negative control): an entry bar that touches nothing does NOT close the position, and a later bar still resolves it correctly.",
        "9.6 / 24.0",
        _ALL,
        fixture=True,
        note="Paired control for EXEC-010. Without it an engine passes EXEC-010 by closing everything immediately.",
    ),
    _item(
        "EXEC-015",
        "ENTRY BAR FUNDING: a position opened and closed on the same bar is still charged the funding settlements inside its holding window.",
        "9.6 / 24.0",
        _ALL,
        fixture=True,
    ),
    _item(
        "EXEC-016",
        "SAME-BAR HOLD COUNT: a trade closed on its entry bar reports a hold of zero, and maximum-hold arithmetic is identical to the live runner's.",
        "9.6 / 24.0",
        _ALL,
        fixture=True,
    ),
    _item(
        "EXEC-017",
        "Retry is idempotent; a retried order never becomes two positions.",
        "9.3 / 24.0",
        (_LR,),
        note="Order-routing behaviour. Not mandatory for a pure bar-replay backtest contract.",
    ),
    _item(
        "EXEC-018",
        "Multi-leg take profit fills each leg at its own price and quantity, the residual closes, and no leg rounds to zero.",
        "12.3",
        _ALL,
        fixture=True,
    ),
    _item(
        "EXEC-019",
        "A trailing stop ratchets only in the favourable direction and never uses a future extreme from the bar it is resolving.",
        "10",
        _ALL,
        fixture=True,
    ),
    _item(
        "EXEC-020",
        "Break-even activation happens after the fill that triggers it and never rescues a stop hit on the activating bar without lower-timeframe evidence.",
        "10",
        _ALL,
        fixture=True,
    ),
    # ---------------------------------------------------------------- FUND -----------
    _item(
        "FUND-001",
        "With a positive funding rate the long pays and the short receives, under the product's convention.",
        "11.3",
        _ALL,
        fixture=True,
    ),
    _item(
        "FUND-002",
        "A negative funding rate reverses the cashflow.",
        "11.3",
        _ALL,
        fixture=True,
    ),
    _item(
        "FUND-003",
        "No funding is charged while flat.",
        "11.3",
        _ALL,
        fixture=True,
    ),
    _item(
        "FUND-004",
        "Each settlement is charged exactly once, on the mark/position value at that settlement.",
        "11.3",
        _ALL,
        fixture=True,
    ),
    _item(
        "FUND-005",
        "Holding-window boundaries are explicit and documented: entry-inclusive, exit-exclusive at the resolved exit interval's end.",
        "11.3",
        _ALL,
        fixture=True,
    ),
    _item(
        "FUND-006",
        "Funding moves wallet, equity and available margin chronologically, so it can change a later liquidation.",
        "11.3",
        _ALL,
    ),
    # ---------------------------------------------------------------- QTY ------------
    _item(
        "QTY-001",
        "Prices round to the tick grid and quantities to the quantity step, in the live rounding direction.",
        "12.2",
        _ALL,
        fixture=True,
    ),
    _item(
        "QTY-002",
        "An order below minimum quantity or minimum notional is skipped with an explicit reason, never silently resized and never rounded to zero.",
        "12.2",
        _ALL,
        fixture=True,
    ),
    _item(
        "QTY-003",
        "A minimum executable order that breaches the frozen risk cap is skipped with SKIP_MIN_QTY_RISK_CAP, not rounded up into over-risk.",
        "12.2",
        _ALL,
        fixture=True,
    ),
    _item(
        "QTY-004",
        "Insufficient margin rejects the order instead of silently funding it.",
        "13.4",
        _ALL,
        fixture=True,
    ),
    _item(
        "QTY-005",
        "Lowering leverage changes margin and liquidation distance but not fixed-quantity price PnL.",
        "13.4",
        _ALL,
    ),
    _item(
        "QTY-006",
        "Liquidation uses the maintenance tier for the position's notional and the Mark trigger; the status is MODELLED, SIMPLIFIED or UNKNOWN, never a silent pass.",
        "13.3",
        _ALL,
    ),
    _item(
        "QTY-007",
        "On a continuous path a valid stop is reached before a deeper liquidation threshold; a gap can reverse that order and the engine says which happened.",
        "13.4",
        _ALL,
        fixture=True,
    ),
    _item(
        "QTY-008",
        "The wallet reconciles: starting equity + gross PnL - fees +/- funding == ending equity, within tolerance.",
        "14.1",
        _ALL,
        fixture=True,
    ),
    _item(
        "QTY-009",
        "A ruined wallet stops trading unless a deposit policy is declared.",
        "14.1",
        _ALL,
    ),
    _item(
        "QTY-010",
        "A stop that sits beyond the liquidation price is rejected rather than simulated as a working protective order.",
        "13.4",
        _ALL,
    ),
    # ---------------------------------------------------------------- METR -----------
    _item(
        "METR-001",
        "Profit factor is pooled gross profit over absolute pooled gross loss, never capped and never a mean of fold values.",
        "17.3",
        _ALL,
        fixture=True,
    ),
    _item(
        "METR-002",
        "Zero gross loss yields infinity/undefined with a sample warning, not an automatic pass.",
        "17.3",
        _ALL,
        fixture=True,
    ),
    _item(
        "METR-003",
        "Drawdown is computed on mark-to-market equity including unrealised PnL, not realised-only.",
        "17.4",
        _ALL,
        fixture=True,
    ),
    _item(
        "METR-004",
        "Raw periodic and annualised Sharpe are reported separately with the calendar factor stated.",
        "17.2",
        _ALL,
        fixture=True,
    ),
    _item(
        "METR-005",
        "A serial-dependence-aware Sharpe diagnostic (HAC / Newey-West) is reported alongside the IID value.",
        "17.2",
        _ALL,
        fixture=True,
    ),
    _item(
        "METR-006",
        "Exposure, turnover, and fee/slippage/funding totals are reported.",
        "17.8",
        _ALL,
    ),
    _item(
        "METR-007",
        "The entry-bar-exit count and the ambiguous-intrabar count are reported, and an entry-bar-exit frequency above 25% raises a prominent warning.",
        "9.6",
        _ALL,
        fixture=True,
    ),
    _item(
        "METR-008",
        "Win rate is reported with an uncertainty interval and is never presented alone as proof of edge.",
        "17.3",
        _ALL,
    ),
    # ---------------------------------------------------------------- VALD -----------
    _item(
        "VALD-001",
        "Every SimResult carries a conformance stamp, and assert_quotable refuses a result whose stamp is absent or not green.",
        "24.0",
        _ALL,
    ),
    _item(
        "VALD-002",
        "The checker exits non-zero when a required identifier has no binding, exactly as if a bound test had failed.",
        "24.0",
        _ALL,
    ),
    _item(
        "VALD-003",
        "The fixture pack is content-hashed and the hash changes when any fixture changes.",
        "24.0",
        _ALL,
    ),
    _item(
        "VALD-004",
        "A dirty working tree stamps the commit as UNKNOWN_DIRTY rather than a clean hash.",
        "24.0",
        _ALL,
    ),
    _item(
        "VALD-005",
        "A bound test that is skipped counts as a failure, not as a pass.",
        "24.0",
        _ALL,
    ),
    _item(
        "VALD-006",
        "Every public entry point accepts and propagates a run identifier into the result.",
        "5.2",
        _ALL,
    ),
    # ---------------------------------------------------------------- PORT -----------
    _item(
        "PORT-001",
        "Shared-wallet results come from one chronological event simulation across symbols, not from summed standalone equity curves.",
        "14.3",
        _PF_UP,
        fixture=True,
    ),
    _item(
        "PORT-002",
        "Simultaneous signals on the same bar are ordered by a deterministic, declared priority.",
        "14.3",
        _PF_UP,
        fixture=True,
    ),
    _item(
        "PORT-003",
        "Shared available margin can reject a later signal on the same bar, and the rejection is recorded.",
        "14.3",
        _PF_UP,
        fixture=True,
    ),
    _item(
        "PORT-004",
        "Portfolio ledger reconciles to component trades and cashflows.",
        "14.3",
        _PF_UP,
    ),
    # ---------------------------------------------------------------- LIVE -----------
    _item(
        "LIVE-001",
        "Startup fails closed on a missing instrument specification rather than substituting a default.",
        "22",
        (_LR,),
    ),
    _item(
        "LIVE-002",
        "Exactly one decision per closed bar, with a persisted last_processed_bar_ts and restart catch-up that neither skips nor repeats a bar.",
        "22.1",
        (_LR,),
    ),
    _item(
        "LIVE-003",
        "A late or absent bar produces a stale-data event and no action.",
        "22.1",
        (_LR,),
    ),
    _item(
        "LIVE-004",
        "No credentials appear in any artifact.",
        "2",
        (_LR,),
    ),
)


_BY_ID: Mapping[str, ConformanceItem] = {item.identifier: item for item in REGISTRY}


def all_items() -> tuple[ConformanceItem, ...]:
    return REGISTRY


def get(identifier: str) -> ConformanceItem:
    try:
        return _BY_ID[identifier]
    except KeyError as exc:  # pragma: no cover - defensive
        raise KeyError(f"unknown conformance identifier {identifier!r}") from exc


def known_identifier(identifier: str) -> bool:
    return identifier in _BY_ID


def required_for(contract: str) -> tuple[str, ...]:
    """Identifiers a given contract must have bound, run and passing."""
    if contract not in CONTRACTS:
        raise ValueError(f"unknown contract {contract!r}; expected one of {CONTRACTS}")
    return tuple(
        item.identifier for item in REGISTRY if item.is_mandatory_for(contract)
    )


def fixture_computable_for(contract: str) -> tuple[str, ...]:
    return tuple(
        item.identifier
        for item in REGISTRY
        if item.is_mandatory_for(contract) and item.fixture_computable
    )


# The seven entry-bar identifiers are jointly non-negotiable: no repository may declare
# execution parity without all of them bound, run and passing.
NON_NEGOTIABLE_ENTRY_BAR: tuple[str, ...] = (
    "EXEC-010",
    "EXEC-011",
    "EXEC-012",
    "EXEC-013",
    "EXEC-014",
    "EXEC-015",
    "EXEC-016",
)


def extract_identifiers(text: str) -> tuple[str, ...]:
    """Pull every well-formed identifier out of arbitrary text, preserving order."""
    seen: list[str] = []
    for match in IDENTIFIER_RE.finditer(text or ""):
        ident = f"{match.group(1)}-{match.group(2)}"
        if ident not in seen:
            seen.append(ident)
    return tuple(seen)


def registry_digest() -> str:
    """Stable hash of the registry so a stamp records which registry it was graded against."""
    import hashlib

    h = hashlib.sha256()
    for item in REGISTRY:
        h.update(item.identifier.encode())
        h.update(item.behaviour.encode())
        h.update(",".join(sorted(item.contracts)).encode())
        h.update(b"1" if item.retired else b"0")
    return h.hexdigest()
