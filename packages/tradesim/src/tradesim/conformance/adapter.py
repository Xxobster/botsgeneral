"""The contract an engine must satisfy to be graded, plus the tradesim implementation.

The point of this module is that a foreign engine should need roughly thirty lines to be
gradable. An adapter translates one fixture payload into whatever the engine wants, runs
it, and returns a ``NormalisedResult``. Everything else — comparison, tolerance,
reporting — is done here, identically for every engine.

An adapter is allowed to say "I cannot express this fixture" via :meth:`supports`. That
is recorded as ``UNSUPPORTED``, which is not a pass: it tells the truth about a
capability gap instead of hiding it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .fixture_loader import Fixture

# --------------------------------------------------------------------------------------
# Normalised result shape
# --------------------------------------------------------------------------------------


@dataclass
class NormalisedTrade:
    symbol: str = "UNSPECIFIED"
    side: int = 1
    entry_ts_ms: int = 0
    exit_ts_ms: int = 0
    entry_ref_price: float = math.nan
    entry_price: float = math.nan
    exit_price: float = math.nan
    qty: float = math.nan
    exit_reason: str = ""
    entry_fee: float = math.nan
    exit_fee: float = math.nan
    fees: float = math.nan
    funding: float = 0.0
    slippage_cost: float = 0.0
    gross_pnl: float = math.nan
    realized_pnl: float = math.nan
    hold_bars: int = -1
    ambiguous: bool = False
    resolved_by_touch: bool = False
    entry_bar_exit: bool = False
    liquidation_price: float | None = None
    n_legs: int = 1


@dataclass
class NormalisedResult:
    trades: list[NormalisedTrade] = field(default_factory=list)
    skip_counts: dict[str, int] = field(default_factory=dict)
    ending_equity: float = math.nan
    starting_equity: float = math.nan
    liquidation_status: str = "UNKNOWN"
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    fill_rates: list[float] = field(default_factory=list)
    # Metric values for a ``metrics`` fixture, flattened as e.g. "sharpe.raw_periodic".
    # An engine that reports none of them fails the metric identifiers, which is the
    # honest outcome: the standard requires these numbers to exist.
    metrics: dict[str, Any] = field(default_factory=dict)
    n_funding_charges: int = 0
    total_fees: float = 0.0
    total_funding: float = 0.0
    total_gross_pnl: float = 0.0
    error: str | None = None


@runtime_checkable
class EngineAdapter(Protocol):
    """Minimal surface an engine must expose to be graded by the conformance pack."""

    name: str
    version: str
    contract: str

    def supports(self, fixture: Fixture) -> tuple[bool, str]:
        """Return ``(True, "")`` or ``(False, reason)``."""
        ...

    def run_fixture(self, fixture: Fixture) -> NormalisedResult:
        """Run the fixture. Raise to signal that the engine rejected the inputs."""
        ...


# --------------------------------------------------------------------------------------
# Grading
# --------------------------------------------------------------------------------------


@dataclass
class FixtureOutcome:
    fixture: str
    ids: tuple[str, ...]
    status: str  # PASS | FAIL | UNSUPPORTED | ERROR
    failures: tuple[str, ...] = ()
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "PASS"


def _as_float(value: Any) -> float:
    """JSON has no infinity, so a fixture writes it as a sentinel string."""
    if isinstance(value, str):
        key = value.strip().lower()
        if key in ("inf", "infinity", "+inf"):
            return math.inf
        if key == "-inf":
            return -math.inf
        if key == "nan":
            return math.nan
    return value


def _close(a: float, b: float, tol: float) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return a == b
    if math.isnan(fa) and math.isnan(fb):
        return True
    if math.isinf(fa) or math.isinf(fb):
        return fa == fb
    return abs(fa - fb) <= tol + tol * abs(fb)


def grade(adapter: EngineAdapter, fixture: Fixture) -> FixtureOutcome:
    supported, why = adapter.supports(fixture)
    if not supported:
        return FixtureOutcome(fixture.name, fixture.ids, "UNSUPPORTED", detail=why)

    expect = dict(fixture.expect)
    tol = fixture.tolerance

    try:
        result = adapter.run_fixture(fixture)
    except Exception as exc:  # noqa: BLE001 - an engine raising IS an observable outcome
        result = NormalisedResult(error=f"{type(exc).__name__}: {exc}")

    failures: list[str] = []

    # A fixture that expects a rejection is graded on the rejection, nothing else.
    if "error" in expect:
        needle = str(expect["error"]).lower()
        if result.error is None:
            failures.append(
                f"expected the engine to reject these inputs with a message containing "
                f"{expect['error']!r}, but it returned {len(result.trades)} trades"
            )
        elif needle not in result.error.lower():
            failures.append(
                f"expected rejection mentioning {expect['error']!r}, got {result.error!r}"
            )
        return _outcome(fixture, failures)

    if result.error is not None:
        return FixtureOutcome(
            fixture.name, fixture.ids, "ERROR", (result.error,), detail=result.error
        )

    if "n_trades" in expect and len(result.trades) != int(expect["n_trades"]):
        failures.append(
            f"n_trades: expected {expect['n_trades']}, got {len(result.trades)}"
        )

    for key in ("ending_equity", "starting_equity"):
        if key in expect and not _close(getattr(result, key), expect[key], tol):
            failures.append(f"{key}: expected {expect[key]}, got {getattr(result, key)}")

    if "liquidation_status" in expect and result.liquidation_status != expect["liquidation_status"]:
        failures.append(
            f"liquidation_status: expected {expect['liquidation_status']}, "
            f"got {result.liquidation_status}"
        )

    if "n_funding_charges" in expect and result.n_funding_charges != int(
        expect["n_funding_charges"]
    ):
        failures.append(
            f"n_funding_charges: expected {expect['n_funding_charges']}, "
            f"got {result.n_funding_charges}"
        )

    for reason, count in dict(expect.get("skip_counts", {})).items():
        got = int(result.skip_counts.get(reason, 0))
        if got != int(count):
            failures.append(
                f"skip_counts[{reason}]: expected {count}, got {got} "
                f"(all skips: {result.skip_counts or 'none'})"
            )

    for key, value in dict(expect.get("metrics", {})).items():
        if key not in result.metrics:
            failures.append(f"metrics[{key}] is not reported by this engine")
            continue
        got = result.metrics[key]
        if isinstance(value, str):
            # Notes are graded on substance, not on wording.
            if value.lower() not in str(got).lower():
                failures.append(f"metrics[{key}]: expected {value!r} within {got!r}")
        elif not _close(got, _as_float(value), tol):
            failures.append(f"metrics[{key}]: expected {value}, got {got}")

    for key, value in dict(expect.get("summary", {})).items():
        if key not in result.summary:
            failures.append(f"summary[{key}] missing from the result")
        elif not _close(result.summary[key], value, tol):
            failures.append(
                f"summary[{key}]: expected {value}, got {result.summary[key]}"
            )

    if "warns_contains" in expect:
        needle = str(expect["warns_contains"]).lower()
        if not any(needle in w.lower() for w in result.warnings):
            failures.append(
                f"expected a warning containing {expect['warns_contains']!r}; "
                f"warnings were {result.warnings or 'none'}"
            )

    if "fill_rates" in expect:
        want = [float(x) for x in expect["fill_rates"]]
        got = list(result.fill_rates)
        if len(want) != len(got) or not all(_close(g, w, tol) for g, w in zip(got, want)):
            failures.append(f"fill_rates: expected {want}, got {got}")

    if "trade_symbols" in expect:
        want_syms = list(expect["trade_symbols"])
        got_syms = [t.symbol for t in result.trades]
        if got_syms != want_syms:
            failures.append(f"trade_symbols: expected {want_syms}, got {got_syms}")

    if expect.get("reconciles"):
        lhs = result.starting_equity + result.total_gross_pnl - result.total_fees + result.total_funding
        if not _close(lhs, result.ending_equity, max(tol, 1e-6)):
            failures.append(
                "wallet does not reconcile: start "
                f"{result.starting_equity} + gross {result.total_gross_pnl} "
                f"- fees {result.total_fees} + funding {result.total_funding} "
                f"= {lhs}, but ending equity is {result.ending_equity}"
            )

    for i, want_trade in enumerate(expect.get("trades", [])):
        if i >= len(result.trades):
            failures.append(f"trade[{i}] missing")
            continue
        got_trade = result.trades[i]
        for key, value in dict(want_trade).items():
            if not hasattr(got_trade, key):
                failures.append(f"trade[{i}].{key} is not reported by this engine")
                continue
            actual = getattr(got_trade, key)
            if isinstance(value, bool) or isinstance(actual, bool):
                if bool(actual) != bool(value):
                    failures.append(f"trade[{i}].{key}: expected {value}, got {actual}")
            elif isinstance(value, str):
                if actual != value:
                    failures.append(f"trade[{i}].{key}: expected {value!r}, got {actual!r}")
            elif not _close(actual, value, tol):
                failures.append(f"trade[{i}].{key}: expected {value}, got {actual}")

    return _outcome(fixture, failures)


def _outcome(fixture: Fixture, failures: list[str]) -> FixtureOutcome:
    if failures:
        return FixtureOutcome(fixture.name, fixture.ids, "FAIL", tuple(failures))
    return FixtureOutcome(fixture.name, fixture.ids, "PASS")


# --------------------------------------------------------------------------------------
# The tradesim adapter
# --------------------------------------------------------------------------------------


def _build_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a fixture payload into tradesim call arguments."""
    import numpy as np

    from ..contracts import (
        BarSeries,
        BreakEvenConfig,
        CostConfig,
        EntryRef,
        InstrumentSpec,
        Liquidity,
        MaintenanceTier,
        MarginConfig,
        MarginMode,
        SameBarPolicy,
        Side,
        Signal,
        SimConfig,
        SizingConfig,
        SizingMode,
        TakeProfitLeg,
        TrailConfig,
    )

    inst_raw = dict(payload["instrument"])
    tiers = tuple(
        MaintenanceTier(**t) for t in inst_raw.pop("maintenance_tiers", []) or ()
    )
    instrument = InstrumentSpec(maintenance_tiers=tiers, **inst_raw)

    cost_raw = dict(payload["costs"])
    roles = cost_raw.pop("role_liquidity", None)
    costs = CostConfig(**cost_raw)
    if roles:
        merged = dict(costs.role_liquidity)
        merged.update({k: Liquidity(v) for k, v in roles.items()})
        costs = CostConfig(**{**cost_raw, "role_liquidity": merged})

    margin_raw = dict(payload["margin"])
    margin_raw["mode"] = MarginMode(margin_raw.get("mode", "isolated"))
    margin = MarginConfig(**margin_raw)

    sizing_raw = dict(payload["sizing"])
    sizing_raw["mode"] = SizingMode(sizing_raw.get("mode", "fixed_qty"))
    sizing = SizingConfig(**sizing_raw)

    sim_raw = dict(payload["sim"])
    sim_raw["entry_ref"] = EntryRef(sim_raw.get("entry_ref", "next_open"))
    sim_raw["same_bar_policy"] = SameBarPolicy(sim_raw.get("same_bar_policy", "adverse"))
    sim = SimConfig(**sim_raw)

    def make_bars(spec: Mapping[str, Any] | None, symbol: str) -> BarSeries | None:
        if not spec or not spec.get("rows"):
            return None
        return BarSeries.from_rows(spec["rows"], int(spec["timeframe_ms"]), symbol=symbol)

    def make_signals(raw: Sequence[Mapping[str, Any]], symbol: str) -> list[Signal]:
        out: list[Signal] = []
        for s in raw:
            s = dict(s)
            legs = tuple(TakeProfitLeg(**leg) for leg in s.pop("tp_legs", []) or ())
            be = s.pop("break_even", None)
            tr = s.pop("trail", None)
            out.append(
                Signal(
                    side=Side.coerce(s.pop("side")),
                    symbol=symbol,
                    tp_legs=legs,
                    break_even=BreakEvenConfig(**be) if be else None,
                    trail=TrailConfig(**tr) if tr else None,
                    **s,
                )
            )
        return out

    funding = payload.get("funding") or []
    funding_ts = np.asarray([int(row[0]) for row in funding], dtype=np.int64)
    funding_rate = np.asarray([float(row[1]) for row in funding], dtype=float)

    return {
        "instrument": instrument,
        "costs": costs,
        "margin": margin,
        "sizing": sizing,
        "sim": sim,
        "bars": make_bars(payload.get("bars"), instrument.symbol),
        "touch_bars": make_bars(payload.get("touch_bars"), instrument.symbol),
        "signals": make_signals(payload.get("signals") or [], instrument.symbol),
        "funding_ts_ms": funding_ts,
        "funding_rate": funding_rate,
        "_make_bars": make_bars,
        "_make_signals": make_signals,
    }


def normalise_sim_result(result: Any) -> NormalisedResult:
    """Turn a tradesim ``SimResult`` into the shape the grader compares against."""
    from ..contracts import is_entry_bar_reason

    trades = [
        NormalisedTrade(
            symbol=t.symbol,
            side=int(t.side),
            entry_ts_ms=int(t.entry_ts_ms),
            exit_ts_ms=int(t.exit_ts_ms),
            entry_ref_price=float(t.entry_ref_price),
            entry_price=float(t.entry_price),
            exit_price=float(t.exit_price),
            qty=float(t.qty),
            exit_reason=str(t.exit_reason),
            entry_fee=_entry_fee(result, t.trade_id),
            exit_fee=_exit_fee(result, t.trade_id),
            fees=float(t.fees),
            funding=float(t.funding),
            slippage_cost=float(t.slippage_cost),
            gross_pnl=float(t.gross_pnl),
            realized_pnl=float(t.realized_pnl),
            hold_bars=int(t.hold_bars),
            ambiguous=bool(t.ambiguous_intrabar),
            resolved_by_touch=bool(t.resolved_by_touch),
            entry_bar_exit=bool(t.entry_bar_exit) or is_entry_bar_reason(t.exit_reason),
            liquidation_price=t.liquidation_price,
            n_legs=max(1, len(t.legs)),
        )
        for t in result.trades
    ]
    return NormalisedResult(
        trades=trades,
        skip_counts=dict(result.skip_counts),
        ending_equity=float(result.ending_equity),
        starting_equity=float(result.starting_equity),
        liquidation_status=str(result.liquidation_status),
        warnings=list(result.warnings),
        summary=dict(result.meta.get("summary", {})),
        fill_rates=[float(f.fee_rate) for f in result.fills],
        n_funding_charges=len(result.funding_charges),
        total_fees=sum(t.fees for t in result.trades),
        total_funding=sum(t.funding for t in result.trades),
        total_gross_pnl=sum(t.gross_pnl for t in result.trades),
    )


def _entry_fee(result: Any, trade_id: int) -> float:
    return sum(f.fee for f in result.fills if f.trade_id == trade_id and f.role == "entry")


def _exit_fee(result: Any, trade_id: int) -> float:
    return sum(f.fee for f in result.fills if f.trade_id == trade_id and f.role != "entry")


def _tradesim_metrics(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Answer a metrics fixture from the one authoritative implementation.

    The inputs are a trade profit-and-loss list, a periodic return series and an equity
    curve, so the metric is graded on its own arithmetic rather than on whether some
    simulation happened to produce the right trades.
    """
    from ..metrics import max_drawdown, profit_factor, sharpe, sortino, wilson_interval

    out: dict[str, Any] = {}

    if payload.get("pnls") is not None:
        pnls = [float(x) for x in payload["pnls"]]
        value, note = profit_factor(pnls)
        out["profit_factor"] = value
        out["profit_factor_note"] = note
        wins = sum(1 for p in pnls if p > 0)
        low, high = wilson_interval(wins, len(pnls))
        out["win_rate"] = (wins / len(pnls)) if pnls else math.nan
        out["win_rate_ci_low"] = low
        out["win_rate_ci_high"] = high

    if payload.get("returns") is not None:
        report = sharpe(
            [float(x) for x in payload["returns"]],
            annualisation_days=float(payload.get("annualisation_days", 365.0)),
        )
        for name in (
            "raw_periodic",
            "annualised",
            "annualisation_factor",
            "n_periods",
            "hac_raw",
            "hac_annualised",
            "hac_lag",
            "available",
        ):
            out[f"sharpe.{name}"] = getattr(report, name)
        out["sharpe.reason"] = report.reason
        out["sortino_annualised"] = sortino(
            [float(x) for x in payload["returns"]],
            annualisation_days=float(payload.get("annualisation_days", 365.0)),
        )

    if payload.get("equity") is not None:
        magnitude, fraction, periods = max_drawdown([float(x) for x in payload["equity"]])
        out["max_drawdown"] = magnitude
        out["max_drawdown_pct"] = fraction
        out["max_drawdown_periods"] = periods

    return out


class TradesimAdapter:
    """Grades the engine that ships with this package."""

    def __init__(self, contract: str = "perp_bracket_portfolio") -> None:
        from ..version import ENGINE_NAME, ENGINE_VERSION

        self.name = ENGINE_NAME
        self.version = ENGINE_VERSION
        self.contract = contract

    def supports(self, fixture: Fixture) -> tuple[bool, str]:
        if fixture.kind not in ("simulation", "portfolio", "metrics"):
            return False, f"unknown fixture kind {fixture.kind!r}"
        return True, ""

    def run_fixture(self, fixture: Fixture) -> NormalisedResult:
        from ..engine import SymbolStream, simulate, simulate_portfolio

        payload = fixture.payload

        if fixture.kind == "metrics":
            return NormalisedResult(metrics=_tradesim_metrics(payload))

        built = _build_from_payload(payload)

        if fixture.kind == "portfolio":
            make_bars = built["_make_bars"]
            make_signals = built["_make_signals"]
            streams = []
            from ..contracts import InstrumentSpec, MaintenanceTier

            for symbol, spec in sorted(payload["symbols"].items()):
                inst_raw = dict(spec["instrument"])
                tiers = tuple(
                    MaintenanceTier(**t) for t in inst_raw.pop("maintenance_tiers", []) or ()
                )
                instrument = InstrumentSpec(maintenance_tiers=tiers, **inst_raw)
                streams.append(
                    SymbolStream(
                        symbol=symbol,
                        instrument=instrument,
                        bars=make_bars(spec["bars"], symbol),
                        signals=tuple(make_signals(spec.get("signals", []), symbol)),
                        touch_bars=make_bars(spec.get("touch_bars"), symbol),
                    )
                )
            result = simulate_portfolio(
                streams=streams,
                costs=built["costs"],
                margin=built["margin"],
                sizing=built["sizing"],
                sim=built["sim"],
                run_id=f"fixture:{fixture.name}",
            )
        else:
            result = simulate(
                bars=built["bars"],
                signals=built["signals"],
                instrument=built["instrument"],
                costs=built["costs"],
                margin=built["margin"],
                sizing=built["sizing"],
                sim=built["sim"],
                touch_bars=built["touch_bars"],
                funding_ts_ms=built["funding_ts_ms"],
                funding_rate=built["funding_rate"],
                run_id=f"fixture:{fixture.name}",
                attach_stamp=False,
            )
        return normalise_sim_result(result)
