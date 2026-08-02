"""The chronological simulation loop.

Path-dependent state genuinely needs a loop: an order's fate depends on what the wallet,
the margin and the other positions were doing at that instant. Feature and indicator work
is vectorised outside this module; what happens here is sequential because reality is.

Order of operations inside one bar, for one symbol:

1. charge the funding settlements due inside this bar for positions already open;
2. fill any entry scheduled for this bar and charge its funding from the fill onward;
3. **resolve every open position against this bar** — including one filled in step 2;
4. update trailing and break-even levels from this bar's extremes, for the NEXT bar;
5. mark to market.

Step 3 is the only place in this file that resolves an exit, and it runs after step 2.
There is no second call site to forget, and no branch that can skip the entry bar. That
is a structural answer to a defect that prose rules and a green test suite both failed to
prevent: opening a position at a bar and starting exit checks on the following bar granted
one free bar of immunity to every trade, and on a daily strategy it hid that 47.6% of 1278
trades were stopped out on their entry day.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .contracts import (
    BASE_EXIT_REASONS,
    ENTRY_BAR_SUFFIX,
    REASON_BREAK_EVEN,
    REASON_END_OF_DATA,
    REASON_LIQUIDATION,
    REASON_MAX_HOLD,
    REASON_STOP,
    REASON_TARGET,
    REASON_TRAILING,
    Bar,
    BarSeries,
    CostConfig,
    EntryRef,
    FeeRole,
    Fill,
    FundingCharge,
    InstrumentSpec,
    LiquidationStatus,
    MarginConfig,
    MarginMode,
    SameBarPolicy,
    Side,
    Signal,
    SimConfig,
    SimResult,
    SizingConfig,
    Skip,
    SkipReason,
    TakeProfitLeg,
    Trade,
    round_to_tick,
)
from .exits import (
    ExitPolicy,
    ProtectiveLevels,
    TargetLevel,
    resolve_bar,
    update_protective_levels,
)
from .fees import apply_entry_slippage, price_fill
from .funding import (
    FundingSchedule,
    funding_cashflow,
    holding_window_end,
    mark_at_settlement,
)
from .margin import MarginError, build_margin_state, stop_is_inside_liquidation, worst_status
from .sizing import desired_qty, normalise_order, split_legs
from .version import ENGINE_NAME, ENGINE_VERSION


class InfeasibleOrderError(RuntimeError):
    """Raised instead of recording a skip when SimConfig.raise_on_infeasible is set."""


class DataValidationError(ValueError):
    """Raised when a bar series violates a data-integrity invariant."""


# --------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolStream:
    """Everything the engine needs about one symbol."""

    symbol: str
    instrument: InstrumentSpec
    bars: BarSeries
    signals: tuple[Signal, ...] = ()
    touch_bars: BarSeries | None = None
    mark_bars: BarSeries | None = None
    funding_ts_ms: np.ndarray | None = None
    funding_rate: np.ndarray | None = None


def validate_bars(bars: BarSeries, *, what: str = "bars") -> None:
    """Reject duplicates, gaps in ordering, broken OHLC and non-positive prices.

    Never silently reorder, de-duplicate or fill. A data defect that repairs itself is a
    data defect you find out about from a live account.
    """
    n = len(bars)
    if n == 0:
        raise DataValidationError(f"{what}: empty series")
    ts = bars.ts_ms
    if n > 1 and not np.all(np.diff(ts) > 0):
        bad = int(np.argmin(np.diff(ts)))
        raise DataValidationError(
            f"{what}: timestamps must be strictly increasing; "
            f"bar {bad} at {ts[bad]} is followed by {ts[bad + 1]}"
        )
    if n > 1:
        # A timestamp is a bar OPEN on a fixed grid, so every spacing is a whole number
        # of timeframes. A spacing that is not says the series and its declared timeframe
        # disagree, and every hold count, funding window and annualisation downstream is
        # computed from the wrong period.
        gaps = np.diff(ts)
        misaligned = np.where(gaps % int(bars.timeframe_ms) != 0)[0]
        if len(misaligned):
            i = int(misaligned[0])
            raise DataValidationError(
                f"{what}: spacing {int(gaps[i])} ms between bar {i} ({ts[i]}) and bar "
                f"{i + 1} ({ts[i + 1]}) is not a multiple of the declared timeframe "
                f"{bars.timeframe_ms} ms"
            )

    o, h, l, c = bars.open, bars.high, bars.low, bars.close
    for name, arr in (("open", o), ("high", h), ("low", l), ("close", c)):
        if not np.all(np.isfinite(arr)):
            raise DataValidationError(f"{what}: {name} contains non-finite values")
        if not np.all(arr > 0):
            idx = int(np.argmin(arr))
            raise DataValidationError(
                f"{what}: {name} must be positive; bar {idx} at {ts[idx]} has {arr[idx]}"
            )
    bad_high = np.where(h < np.maximum(o, c) - 1e-12)[0]
    bad_low = np.where(l > np.minimum(o, c) + 1e-12)[0]
    if len(bad_high):
        i = int(bad_high[0])
        raise DataValidationError(
            f"{what}: OHLC invariant violated at bar {i} (ts {ts[i]}): high {h[i]} is "
            f"below max(open {o[i]}, close {c[i]})"
        )
    if len(bad_low):
        i = int(bad_low[0])
        raise DataValidationError(
            f"{what}: OHLC invariant violated at bar {i} (ts {ts[i]}): low {l[i]} is "
            f"above min(open {o[i]}, close {c[i]})"
        )
    if not np.all(h >= l - 1e-12):
        raise DataValidationError(f"{what}: OHLC invariant violated, high below low")


# --------------------------------------------------------------------------------------
# Internal state
# --------------------------------------------------------------------------------------


@dataclass
class _Position:
    trade_id: int
    symbol: str
    side: Side
    qty: float
    original_qty: float
    entry_price: float
    entry_ref_price: float
    entry_ts_ms: int
    entry_bar_index: int
    funding_from_ms: int
    levels: ProtectiveLevels
    stop_price: float
    target_price: float | None
    liquidation_price: float | None
    leverage: float
    initial_margin: float
    maintenance_rate: float
    maintenance_deduction: float
    liq_status: LiquidationStatus
    max_hold_bars: int | None
    trail: Any = None
    break_even: Any = None
    break_even_armed: bool = False
    legs_filled: int = 0
    fees: float = 0.0
    funding: float = 0.0
    slippage_cost: float = 0.0
    gross_pnl: float = 0.0
    ambiguous: bool = False
    resolved_by_touch: bool = False
    mae: float = 0.0
    mfe: float = 0.0
    legs: list[tuple[str, int, float, float]] = field(default_factory=list)
    exit_notional: float = 0.0
    funding_charged_this_bar: float = 0.0
    tag: str = ""
    # Frozen copy of the take-profit ladder at open (labels survive as legs fill).
    planned_tp: tuple[tuple[str, float, float], ...] = ()

    @property
    def entry_notional(self) -> float:
        return abs(self.original_qty * self.entry_price)


@dataclass
class _SymbolRuntime:
    stream: SymbolStream
    funding: FundingSchedule
    exec_index: dict[int, list[Signal]]
    touch_starts: np.ndarray
    positions: list[_Position] = field(default_factory=list)
    bar_cursor: int = 0
    approximated_funding_marks: int = 0
    touch_gaps: int = 0


# --------------------------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------------------------


def simulate(
    *,
    bars: BarSeries,
    signals: Sequence[Signal],
    instrument: InstrumentSpec,
    costs: CostConfig | None = None,
    margin: MarginConfig | None = None,
    sizing: SizingConfig | None = None,
    sim: SimConfig | None = None,
    touch_bars: BarSeries | None = None,
    mark_bars: BarSeries | None = None,
    funding_ts_ms: np.ndarray | None = None,
    funding_rate: np.ndarray | None = None,
    run_id: str = "",
    attach_stamp: bool = True,
) -> SimResult:
    """Simulate one symbol. A run identifier is accepted and propagated into the result."""
    stream = SymbolStream(
        symbol=instrument.symbol,
        instrument=instrument,
        bars=bars,
        signals=tuple(signals),
        touch_bars=touch_bars,
        mark_bars=mark_bars,
        funding_ts_ms=funding_ts_ms,
        funding_rate=funding_rate,
    )
    return simulate_portfolio(
        streams=[stream],
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        run_id=run_id,
        attach_stamp=attach_stamp,
    )


def simulate_portfolio(
    *,
    streams: Sequence[SymbolStream],
    costs: CostConfig | None = None,
    margin: MarginConfig | None = None,
    sizing: SizingConfig | None = None,
    sim: SimConfig | None = None,
    run_id: str = "",
    attach_stamp: bool = True,
) -> SimResult:
    """Simulate several symbols against ONE shared wallet, from one event stream.

    Standalone equity curves added together are not a portfolio result: they cannot see
    shared margin, correlated drawdown or a rejection caused by another position
    (standard section 14.3).
    """
    return _Engine(
        streams=list(streams),
        costs=costs or CostConfig(),
        margin=margin or MarginConfig(),
        sizing=sizing or SizingConfig(),
        sim=sim or SimConfig(),
        run_id=run_id,
        attach_stamp=attach_stamp,
    ).run()


# --------------------------------------------------------------------------------------
# The engine
# --------------------------------------------------------------------------------------


class _Engine:
    def __init__(
        self,
        *,
        streams: list[SymbolStream],
        costs: CostConfig,
        margin: MarginConfig,
        sizing: SizingConfig,
        sim: SimConfig,
        run_id: str,
        attach_stamp: bool,
    ) -> None:
        if not streams:
            raise ValueError("no symbol streams supplied")
        self.costs = costs
        self.margin = margin
        self.sizing = sizing
        self.sim = sim
        self.run_id = run_id
        self.attach_stamp = attach_stamp

        self.policy = ExitPolicy(
            same_bar=sim.same_bar_policy,
            take_profit_is_limit=sim.take_profit_is_limit,
            stop_is_stop_market=sim.stop_is_stop_market,
            market_exit_slippage=costs.effective_market_exit_slippage,
            tick_size=0.0,  # set per symbol
        )

        self.cash = float(sim.starting_equity)
        self.trades: list[Trade] = []
        self.fills: list[Fill] = []
        self.funding_charges: list[FundingCharge] = []
        self.skips: list[Skip] = []
        self.warnings: list[str] = []
        self.liq_statuses: list[LiquidationStatus] = []
        self._next_trade_id = 1
        self._equity_rows: list[tuple[int, float, float, float, float, int]] = []
        self._ruined = False
        self._ruined_at_ts_ms: int | None = None

        # Scheduling records skips, so the ledgers above have to exist first.
        self.runtimes: dict[str, _SymbolRuntime] = {}
        for stream in streams:
            validate_bars(stream.bars, what=f"{stream.symbol} bars")
            if stream.touch_bars is not None:
                validate_bars(stream.touch_bars, what=f"{stream.symbol} touch bars")
            self.runtimes[stream.symbol] = _SymbolRuntime(
                stream=stream,
                funding=FundingSchedule.build(stream.funding_ts_ms, stream.funding_rate),
                exec_index=self._schedule_signals(stream),
                touch_starts=(
                    stream.touch_bars.ts_ms
                    if stream.touch_bars is not None
                    else np.empty(0, dtype=np.int64)
                ),
            )

    # -- scheduling ------------------------------------------------------------------

    def _schedule_signals(self, stream: SymbolStream) -> dict[int, list[Signal]]:
        """Map each signal onto the bar index at which it becomes an executable fill.

        A signal is known at its decision bar's CLOSE. It can never fill at that close
        with that bar's range treated as post-entry, whichever entry reference is chosen.
        """
        ts = stream.bars.ts_ms
        out: dict[int, list[Signal]] = {}
        n = len(ts)
        for signal in sorted(stream.signals, key=lambda s: s.ts_ms):
            # A signal routed to the wrong symbol's bars would be filled against another
            # instrument's prices and booked under its own name. Fail closed rather than
            # let the two disagree quietly.
            if signal.symbol not in ("UNSPECIFIED", stream.symbol):
                raise ValueError(
                    f"signal at {signal.ts_ms} is labelled {signal.symbol!r} but was "
                    f"supplied on the {stream.symbol!r} stream"
                )
            signal = replace(signal, symbol=stream.symbol)
            idx = int(np.searchsorted(ts, signal.ts_ms, side="left"))
            if idx >= n or int(ts[idx]) != int(signal.ts_ms):
                self.skips.append(
                    Skip(
                        signal.ts_ms,
                        stream.symbol,
                        SkipReason.NO_EXECUTABLE_BAR.value,
                        "signal timestamp does not match any decision bar open",
                    )
                )
                continue
            exec_idx = idx + 1 + int(self.sim.latency_bars)
            if exec_idx >= n:
                self.skips.append(
                    Skip(
                        signal.ts_ms,
                        stream.symbol,
                        SkipReason.NO_EXECUTABLE_BAR.value,
                        "no bar after the decision bar to execute against",
                    )
                )
                continue
            launch = stream.instrument.launch_ts_ms
            if launch is not None and int(ts[exec_idx]) < int(launch):
                self.skips.append(
                    Skip(
                        signal.ts_ms,
                        stream.symbol,
                        SkipReason.PRE_LAUNCH_BAR.value,
                        f"execution bar {ts[exec_idx]} precedes the instrument launch {launch}",
                    )
                )
                continue
            out.setdefault(exec_idx, []).append((signal, idx))  # type: ignore[arg-type]
        return out

    # -- main loop -------------------------------------------------------------------

    def run(self) -> SimResult:
        timeline = self._timeline()
        priority = self._priority_order()

        for ts in timeline:
            for symbol in priority:
                rt = self.runtimes[symbol]
                i = self._bar_index(rt, ts)
                if i is None:
                    continue
                self._process_bar(rt, i)
            self._record_equity(int(ts))

        if self.sim.close_at_end_of_data:
            self._flatten_all()

        return self._build_result()

    def _timeline(self) -> np.ndarray:
        stamps = [rt.stream.bars.ts_ms for rt in self.runtimes.values()]
        return np.unique(np.concatenate(stamps)) if stamps else np.empty(0, dtype=np.int64)

    def _priority_order(self) -> list[str]:
        if self.sim.portfolio_priority == "symbol":
            return sorted(self.runtimes)
        if self.sim.portfolio_priority == "insertion":
            return list(self.runtimes)
        raise ValueError(
            f"unknown portfolio_priority {self.sim.portfolio_priority!r}; "
            "use 'symbol' or 'insertion'"
        )

    @staticmethod
    def _bar_index(rt: _SymbolRuntime, ts: int) -> int | None:
        arr = rt.stream.bars.ts_ms
        idx = int(np.searchsorted(arr, ts, side="left"))
        if idx < len(arr) and int(arr[idx]) == int(ts):
            return idx
        return None

    def _process_bar(self, rt: _SymbolRuntime, i: int) -> None:
        bars = rt.stream.bars
        bar = bars.bar(i)
        spec = rt.stream.instrument
        policy = replace(self.policy, tick_size=spec.tick_size)

        # 1. funding for positions already open at this bar's start
        for pos in rt.positions:
            pos.funding_charged_this_bar = 0.0
            self._charge_funding(rt, pos, bar.ts_ms, bar.end_ts_ms, i)

        # 1b. cross margin re-prices the liquidation as the wallet moves
        if self.margin.mode == MarginMode.CROSS:
            for pos in rt.positions:
                self._reprice_cross_liquidation(rt, pos)

        # 2. entries scheduled for this bar
        opened = self._fill_entries(rt, i, bar)
        for pos in opened:
            self._charge_funding(rt, pos, pos.funding_from_ms, bar.end_ts_ms, i)

        # 3. THE exit resolution. One call site, after the entries exist, applied
        #    identically to a position opened on this bar and one opened last month.
        for pos in list(rt.positions):
            self._resolve_position(rt, pos, bar, i, policy, just_opened=pos in opened)

        # 4. trailing and break-even from this bar's extremes, for the NEXT bar
        for pos in rt.positions:
            self._update_levels(pos, bar, spec)

    # -- entries ---------------------------------------------------------------------

    def _fill_entries(self, rt: _SymbolRuntime, i: int, bar: Bar) -> list[_Position]:
        scheduled = rt.exec_index.get(i, [])
        opened: list[_Position] = []
        for signal, decision_idx in scheduled:
            if self._ruined and not self.sim.allow_trading_after_ruin:
                self._skip(signal, SkipReason.WALLET_RUINED, "wallet is ruined")
                continue
            if len(rt.positions) >= max(1, self.sim.max_positions_per_symbol):
                self._skip(
                    signal,
                    SkipReason.POSITION_LIMIT,
                    f"{len(rt.positions)} position(s) already open on {signal.symbol}",
                )
                continue
            pos = self._open_position(rt, signal, decision_idx, i, bar)
            if pos is not None:
                rt.positions.append(pos)
                opened.append(pos)
        return opened

    def _open_position(
        self, rt: _SymbolRuntime, signal: Signal, decision_idx: int, i: int, bar: Bar
    ) -> _Position | None:
        spec = rt.stream.instrument
        bars = rt.stream.bars

        # Entry reference price. None of these read the decision bar's own range.
        if self.sim.entry_ref == EntryRef.NEXT_OPEN:
            ref = float(bars.open[i])
            funding_from = bar.ts_ms
        elif self.sim.entry_ref == EntryRef.CLOSE:
            ref = float(bars.close[i - 1])
            funding_from = bar.ts_ms
        elif self.sim.entry_ref == EntryRef.NEXT_CLOSE:
            ref = float(bars.close[i])
            funding_from = bar.end_ts_ms
        else:  # pragma: no cover - enum is exhaustive
            raise ValueError(f"unhandled entry reference {self.sim.entry_ref}")

        fill_price = apply_entry_slippage(ref, signal.side, self.costs, spec.tick_size)
        if fill_price <= 0:
            self._skip(signal, SkipReason.QTY_ROUNDS_TO_ZERO, "non-positive entry price")
            return None

        stop_price = self._resolve_level(
            signal.stop_price, signal.stop_offset, fill_price, -int(signal.side), spec
        )
        target_price = self._resolve_level(
            signal.target_price, signal.target_offset, fill_price, int(signal.side), spec
        )
        legs = self._resolve_legs(signal, fill_price, target_price, spec)

        if stop_price is not None and int(signal.side) * (fill_price - stop_price) <= 0:
            self._skip(
                signal,
                SkipReason.INVALID_STOP_GEOMETRY,
                f"stop {stop_price} is not on the losing side of the fill {fill_price}",
            )
            return None

        equity = self._equity()
        try:
            raw_qty, _unit = desired_qty(
                cfg=self.sizing,
                price=fill_price,
                stop_price=stop_price,
                equity=equity if self.sizing.compound else self.sim.starting_equity,
                signal_qty=signal.qty,
                signal_notional=signal.notional,
                signal_risk_fraction=signal.risk_fraction,
                spec=spec,
            )
        except ValueError as exc:
            self._skip(signal, SkipReason.INVALID_STOP_GEOMETRY, str(exc))
            return None

        outcome = normalise_order(
            raw_qty=raw_qty,
            price=fill_price,
            stop_price=stop_price,
            equity=equity if self.sizing.compound else self.sim.starting_equity,
            spec=spec,
            cfg=self.sizing,
        )
        if not outcome.ok:
            self._skip(signal, outcome.skip_reason, outcome.detail, outcome.requested_qty)
            return None
        qty = outcome.qty

        try:
            state = build_margin_state(
                side=signal.side,
                entry_price=fill_price,
                qty=qty,
                stop_price=stop_price,
                spec=spec,
                cfg=self.margin,
                close_fee_rate=self.costs.rate_for(FeeRole.LIQUIDATION),
                wallet_available=self._available_margin(),
                has_mark_series=rt.stream.mark_bars is not None,
            )
        except MarginError as exc:
            self._skip(signal, SkipReason.LEVERAGE_INFEASIBLE, str(exc))
            return None

        available = self._available_margin()
        if state.initial_margin > available + 1e-12:
            self._skip(
                signal,
                SkipReason.INSUFFICIENT_MARGIN,
                f"initial margin {state.initial_margin:.6g} exceeds available "
                f"{available:.6g}",
            )
            return None
        util_cap = self._equity() * self.margin.max_margin_utilisation
        if self._used_margin() + state.initial_margin > util_cap + 1e-12:
            self._skip(
                signal,
                SkipReason.MARGIN_UTILISATION_CAP,
                f"margin utilisation would exceed {self.margin.max_margin_utilisation:.0%}",
            )
            return None

        if self.margin.require_stop_inside_liquidation and not stop_is_inside_liquidation(
            signal.side, stop_price, state.liquidation_price
        ):
            self._skip(
                signal,
                SkipReason.STOP_INSIDE_LIQUIDATION,
                f"stop {stop_price} sits beyond the liquidation price "
                f"{state.liquidation_price} at leverage {state.leverage:g}; it could "
                "never protect the position",
            )
            return None

        if legs is None:
            self._skip(
                signal,
                SkipReason.NON_DEPLOYABLE_ORDER_GRANULARITY,
                "a take-profit leg is not independently executable at this quantity",
            )
            return None
        if len(legs) > 1:
            # Every leg has to be a sendable order at the quantity actually filled.
            # Collapsing an unsendable plan into one exit would backtest a strategy that
            # cannot be run, which is the most expensive kind of passing test.
            _, problem = split_legs(qty, [leg.qty_fraction for leg in legs], spec)
            if problem:
                self._skip(
                    signal,
                    SkipReason.NON_DEPLOYABLE_ORDER_GRANULARITY,
                    f"take-profit plan is not executable at quantity {qty:g}: {problem}",
                )
                return None

        trade_id = self._next_trade_id
        self._next_trade_id += 1

        priced = price_fill(
            role=FeeRole.ENTRY,
            qty=qty,
            price=fill_price,
            ref_price=ref,
            costs=self.costs,
        )
        self.cash -= priced.fee
        self.fills.append(
            Fill(
                ts_ms=bar.ts_ms,
                symbol=signal.symbol,
                role=FeeRole.ENTRY.value,
                side="buy" if int(signal.side) > 0 else "sell",
                qty=qty,
                price=fill_price,
                notional=priced.notional,
                liquidity=priced.liquidity,
                fee_rate=priced.fee_rate,
                fee=priced.fee,
                slippage_cost=priced.slippage_cost,
                trade_id=trade_id,
            )
        )
        self.liq_statuses.append(state.status)

        levels = ProtectiveLevels(
            side=signal.side,
            entry_price=fill_price,
            stop=stop_price,
            stop_reason=REASON_STOP,
            liquidation=state.liquidation_price,
            targets=tuple(legs),
        )
        return _Position(
            trade_id=trade_id,
            symbol=signal.symbol,
            side=signal.side,
            qty=qty,
            original_qty=qty,
            entry_price=fill_price,
            entry_ref_price=ref,
            entry_ts_ms=bar.ts_ms,
            entry_bar_index=i,
            funding_from_ms=funding_from,
            levels=levels,
            stop_price=stop_price if stop_price is not None else float("nan"),
            target_price=target_price,
            liquidation_price=state.liquidation_price,
            leverage=state.leverage,
            initial_margin=state.initial_margin,
            maintenance_rate=state.maintenance_rate,
            maintenance_deduction=state.maintenance_deduction,
            liq_status=state.status,
            max_hold_bars=(
                signal.max_hold_bars
                if signal.max_hold_bars is not None
                else self.sim.max_hold_bars
            ),
            trail=signal.trail,
            break_even=signal.break_even,
            slippage_cost=priced.slippage_cost,
            fees=priced.fee,
            tag=signal.tag,
            planned_tp=tuple(
                (str(t.label), float(t.price), float(t.qty_fraction)) for t in (legs or ())
            ),
        )

    def _resolve_level(
        self,
        absolute: float | None,
        offset: float | None,
        fill_price: float,
        direction: int,
        spec: InstrumentSpec,
    ) -> float | None:
        """Protective levels are entry-relative and derived from the ACTUAL fill."""
        if absolute is not None:
            return round_to_tick(float(absolute), spec.tick_size, "nearest")
        if offset is None:
            return None
        return round_to_tick(
            fill_price * (1.0 + direction * float(offset)), spec.tick_size, "nearest"
        )

    def _resolve_legs(
        self,
        signal: Signal,
        fill_price: float,
        target_price: float | None,
        spec: InstrumentSpec,
    ) -> list[TargetLevel] | None:
        if signal.tp_legs:
            fractions = [leg.qty_fraction for leg in signal.tp_legs]
            total = sum(fractions)
            if abs(total - 1.0) > 1e-9:
                raise ValueError(
                    f"take-profit leg fractions sum to {total}, not 1.0; a partial exit "
                    "plan that does not close the position leaves undefined residual"
                )
            out: list[TargetLevel] = []
            for leg in signal.tp_legs:
                price = round_to_tick(
                    leg.resolve_price(signal.side, fill_price), spec.tick_size, "nearest"
                )
                out.append(TargetLevel(leg.label, price, float(leg.qty_fraction)))
            return sorted(out, key=lambda t: int(signal.side) * t.price)
        if target_price is not None:
            return [TargetLevel("tp", target_price, 1.0)]
        return []

    # -- resolution ------------------------------------------------------------------

    def _resolve_position(
        self,
        rt: _SymbolRuntime,
        pos: _Position,
        bar: Bar,
        i: int,
        policy: ExitPolicy,
        *,
        just_opened: bool,
    ) -> None:
        hold = i - pos.entry_bar_index
        self._track_excursion(pos, bar)

        # A maximum-hold market order fires at the bar boundary, before any intrabar
        # move, so it takes precedence on the bar where the hold expires.
        if pos.max_hold_bars is not None and hold >= int(pos.max_hold_bars):
            price = self._market_exit_price(pos, bar.open, rt.stream.instrument)
            self._close(rt, pos, price, REASON_MAX_HOLD, bar, i, FeeRole.TIMEOUT)
            return

        path_bar = self._post_entry_path(pos, bar, just_opened)
        touch = self._touch_slice(rt, bar, since_ms=(pos.funding_from_ms if just_opened else bar.ts_ms))
        resolution = resolve_bar(pos.levels, path_bar, policy=policy, touch_bars=touch)

        pos.ambiguous = pos.ambiguous or resolution.ambiguous
        # Not sticky: the question this answers is "was the exit decided by data or by
        # convention", so it describes the bar that closes the trade, not any earlier bar
        # that happened to have complete coverage.
        pos.resolved_by_touch = resolution.resolved_by_touch

        for event in resolution.events:
            if not event.terminal:
                self._partial_exit(rt, pos, event, bar, i)
                continue
            if event.reason in _ADVERSE_REASONS and not resolution.resolved_by_touch:
                # A bar that both takes the stop and would have armed break-even or
                # tightened the trailing stop is ambiguous in exactly the way section 10
                # names. The adverse sequence is used and the trade is labelled, so the
                # convention's cost is reportable instead of invisible.
                if self._levels_would_change(pos, bar, rt.stream.instrument):
                    pos.ambiguous = True
            role = _ROLE_FOR_REASON[event.reason]
            self._close(rt, pos, event.price, event.reason, bar, i, role, label=event.label)
            return

    def _post_entry_path(self, pos: _Position, bar: Bar, just_opened: bool) -> Bar:
        """The portion of this bar the position was actually exposed to.

        For an open fill or a close-then-next-bar fill that is the whole bar. For a fill
        at this bar's close it is a single point, because no part of the bar's range
        happened after the fill. This is a restriction on the PATH, expressed as data;
        the resolver still runs, and still runs the same way.
        """
        if just_opened and self.sim.entry_ref == EntryRef.NEXT_CLOSE:
            return bar.as_point(bar.close)
        return bar

    def _touch_slice(self, rt: _SymbolRuntime, bar: Bar, *, since_ms: int) -> list[Bar]:
        """Lower-timeframe sub-bars covering this decision bar, or nothing.

        Partial coverage is refused. A touch series with a hole in it answers the
        ordering question from whichever part of the bar happens to be present, and the
        missing part is exactly where the adverse move usually is: a gap that silently
        produces the favourable answer is worse than having no touch data at all
        (standard section 10.4). The decision bar then falls back to the declared
        same-bar convention and the gap is counted and reported.
        """
        tb = rt.stream.touch_bars
        if tb is None:
            return []
        start = max(int(bar.ts_ms), int(since_ms))
        if start >= int(bar.end_ts_ms):
            return []
        lo = int(np.searchsorted(rt.touch_starts, start, side="left"))
        hi = int(np.searchsorted(rt.touch_starts, bar.end_ts_ms, side="left"))
        subs = [tb.bar(k) for k in range(lo, hi)]
        if not subs:
            rt.touch_gaps += 1
            return []
        step = int(tb.timeframe_ms)
        complete = (
            subs[0].ts_ms == start
            and subs[-1].ts_ms + step == int(bar.end_ts_ms)
            and all(b.ts_ms + step == subs[k + 1].ts_ms for k, b in enumerate(subs[:-1]))
        )
        if not complete:
            rt.touch_gaps += 1
            return []
        return subs

    def _track_excursion(self, pos: _Position, bar: Bar) -> None:
        sign = int(pos.side)
        adverse = (bar.low - pos.entry_price) if sign > 0 else (pos.entry_price - bar.high)
        favourable = (bar.high - pos.entry_price) if sign > 0 else (pos.entry_price - bar.low)
        pos.mae = min(pos.mae, adverse * pos.qty)
        pos.mfe = max(pos.mfe, favourable * pos.qty)

    def _market_exit_price(self, pos: _Position, raw: float, spec: InstrumentSpec) -> float:
        sign = int(pos.side)
        slip = self.costs.effective_market_exit_slippage
        price = raw * (1.0 - sign * slip) if slip else raw
        return round_to_tick(price, spec.tick_size, "floor" if sign > 0 else "ceil")

    def _levels_would_change(self, pos: _Position, bar: Bar, spec: InstrumentSpec) -> bool:
        """Would this bar's extremes have armed break-even or tightened the trail?"""
        if pos.trail is None and pos.break_even is None:
            return False
        updated, _ = update_protective_levels(
            pos.levels,
            high=bar.high,
            low=bar.low,
            trail=pos.trail,
            break_even=pos.break_even,
            break_even_armed=pos.break_even_armed,
            legs_filled=pos.legs_filled,
            tick_size=spec.tick_size,
        )
        return updated.stop != pos.levels.stop or updated.stop_reason != pos.levels.stop_reason

    def _update_levels(self, pos: _Position, bar: Bar, spec: InstrumentSpec) -> None:
        if pos.trail is None and pos.break_even is None:
            return
        pos.levels, pos.break_even_armed = update_protective_levels(
            pos.levels,
            high=bar.high,
            low=bar.low,
            trail=pos.trail,
            break_even=pos.break_even,
            break_even_armed=pos.break_even_armed,
            legs_filled=pos.legs_filled,
            tick_size=spec.tick_size,
        )

    # -- exits -----------------------------------------------------------------------

    def _partial_exit(
        self, rt: _SymbolRuntime, pos: _Position, event, bar: Bar, i: int
    ) -> None:
        spec = rt.stream.instrument
        legs, problem = split_legs(
            pos.original_qty, [event.qty_fraction, 1.0 - event.qty_fraction], spec
        )
        leg_qty = legs[0]
        if problem or leg_qty <= 0:
            self.warnings.append(
                f"{pos.symbol} trade {pos.trade_id}: take-profit leg {event.label} is not "
                f"independently executable ({problem}); the leg was not filled"
            )
            return
        leg_qty = min(leg_qty, pos.qty)
        priced = price_fill(
            role=FeeRole.TAKE_PROFIT,
            qty=leg_qty,
            price=event.price,
            ref_price=event.price,
            costs=self.costs,
        )
        gross = int(pos.side) * (event.price - pos.entry_price) * leg_qty
        self.cash += gross - priced.fee
        pos.gross_pnl += gross
        pos.fees += priced.fee
        pos.qty -= leg_qty
        pos.legs_filled += 1
        pos.exit_notional += leg_qty * event.price
        pos.legs.append((event.label, bar.ts_ms, leg_qty, event.price))
        self.fills.append(
            Fill(
                ts_ms=bar.ts_ms,
                symbol=pos.symbol,
                role=FeeRole.TAKE_PROFIT.value,
                side="sell" if int(pos.side) > 0 else "buy",
                qty=leg_qty,
                price=event.price,
                notional=priced.notional,
                liquidity=priced.liquidity,
                fee_rate=priced.fee_rate,
                fee=priced.fee,
                slippage_cost=0.0,
                trade_id=pos.trade_id,
                reason=event.label,
            )
        )
        pos.levels = replace(
            pos.levels,
            targets=tuple(t for t in pos.levels.targets if t.label != event.label),
        )

    def _close(
        self,
        rt: _SymbolRuntime,
        pos: _Position,
        price: float,
        reason: str,
        bar: Bar,
        i: int,
        role: FeeRole,
        *,
        label: str = "",
    ) -> None:
        if self.sim.funding_exit_boundary == "bar_start" and pos.funding_charged_this_bar:
            # Reverse this bar's settlements: the caller asked for the exact half-open
            # [entry, exit) window rather than the adverse bar-end reading.
            self.cash -= pos.funding_charged_this_bar
            pos.funding -= pos.funding_charged_this_bar
            self.funding_charges = [
                fc
                for fc in self.funding_charges
                if not (fc.trade_id == pos.trade_id and fc.ts_ms >= bar.ts_ms)
            ]
            pos.funding_charged_this_bar = 0.0

        qty = pos.qty
        priced = price_fill(
            role=role, qty=qty, price=price, ref_price=price, costs=self.costs
        )
        gross = int(pos.side) * (price - pos.entry_price) * qty
        self.cash += gross - priced.fee
        pos.gross_pnl += gross
        pos.fees += priced.fee
        pos.exit_notional += qty * price

        entry_bar_exit = i == pos.entry_bar_index
        full_reason = reason + ENTRY_BAR_SUFFIX if entry_bar_exit else reason

        self.fills.append(
            Fill(
                ts_ms=bar.ts_ms,
                symbol=pos.symbol,
                role=role.value,
                side="sell" if int(pos.side) > 0 else "buy",
                qty=qty,
                price=price,
                notional=priced.notional,
                liquidity=priced.liquidity,
                fee_rate=priced.fee_rate,
                fee=priced.fee,
                slippage_cost=0.0,
                trade_id=pos.trade_id,
                reason=full_reason,
            )
        )
        pos.legs.append((label or reason, bar.ts_ms, qty, price))

        realized = pos.gross_pnl - pos.fees + pos.funding
        if (
            reason == REASON_LIQUIDATION
            and self.margin.mode == MarginMode.ISOLATED
            and -realized > pos.initial_margin + 1e-9
        ):
            self.warnings.append(
                f"{pos.symbol} trade {pos.trade_id}: modelled liquidation loss "
                f"{-realized:.6g} exceeds isolated margin {pos.initial_margin:.6g}. The "
                "venue would have stopped at the bankruptcy price and the insurance fund "
                "would have absorbed the rest; the modelled loss is the conservative one."
            )

        weighted_exit = pos.exit_notional / pos.original_qty if pos.original_qty else price
        self.trades.append(
            Trade(
                trade_id=pos.trade_id,
                symbol=pos.symbol,
                side=int(pos.side),
                entry_ts_ms=pos.entry_ts_ms,
                entry_price=pos.entry_price,
                entry_ref_price=pos.entry_ref_price,
                qty=pos.original_qty,
                stop_price=pos.stop_price,
                target_price=pos.target_price,
                liquidation_price=pos.liquidation_price,
                leverage=pos.leverage,
                initial_margin=pos.initial_margin,
                exit_ts_ms=bar.ts_ms,
                exit_price=round(weighted_exit, 12),
                exit_reason=full_reason,
                hold_bars=i - pos.entry_bar_index,
                fees=pos.fees,
                funding=pos.funding,
                slippage_cost=pos.slippage_cost,
                gross_pnl=pos.gross_pnl,
                realized_pnl=realized,
                return_units=realized / pos.entry_notional if pos.entry_notional else 0.0,
                mae=pos.mae,
                mfe=pos.mfe,
                ambiguous_intrabar=pos.ambiguous,
                resolved_by_touch=pos.resolved_by_touch,
                entry_bar_exit=entry_bar_exit,
                tag=pos.tag,
                legs=tuple(pos.legs),
                tp_levels=tuple(pos.planned_tp),
            )
        )
        rt.positions.remove(pos)

        if self._equity() <= 0:
            self._ruined = True
            self._ruined_at_ts_ms = int(bar.ts_ms)
            self.warnings.append(
                f"WALLET BLOWN at ts_ms={bar.ts_ms}: equity reached zero after "
                f"trade {pos.trade_id}; trading stops unless a deposit policy is declared "
                "(standard section 14.1)"
            )

    def _flatten_all(self) -> None:
        for rt in self.runtimes.values():
            if not rt.positions:
                continue
            i = len(rt.stream.bars) - 1
            bar = rt.stream.bars.bar(i)
            for pos in list(rt.positions):
                price = self._market_exit_price(pos, bar.close, rt.stream.instrument)
                pos.resolved_by_touch = False
                self._close(
                    rt, pos, price, REASON_END_OF_DATA, bar, i, FeeRole.END_OF_DATA
                )

    # -- funding ---------------------------------------------------------------------

    def _charge_funding(
        self, rt: _SymbolRuntime, pos: _Position, start_ms: int, end_ms: int, i: int
    ) -> None:
        if rt.funding.empty:
            return
        window_end = holding_window_end(
            end_ms - rt.stream.bars.timeframe_ms,
            rt.stream.bars.timeframe_ms,
            "bar_end",
        )
        stamps, rates = rt.funding.settlements_in(
            max(int(start_ms), int(pos.funding_from_ms)), int(window_end)
        )
        if len(stamps) == 0:
            return
        bars = rt.stream.bars
        marks = rt.stream.mark_bars or bars
        for ts, rate in zip(stamps.tolist(), rates.tolist()):
            mark, exact = mark_at_settlement(
                int(ts), marks.ts_ms, marks.open, marks.close, marks.timeframe_ms
            )
            if not exact:
                rt.approximated_funding_marks += 1
            flow = funding_cashflow(
                side=int(pos.side), qty=pos.qty, mark_price=mark, rate=float(rate)
            )
            self.cash += flow
            pos.funding += flow
            pos.funding_charged_this_bar += flow
            self.funding_charges.append(
                FundingCharge(
                    ts_ms=int(ts),
                    symbol=pos.symbol,
                    rate=float(rate),
                    mark_price=mark,
                    qty=pos.qty,
                    side=int(pos.side),
                    notional=abs(pos.qty * mark),
                    cashflow=flow,
                    trade_id=pos.trade_id,
                )
            )

    def _reprice_cross_liquidation(self, rt: _SymbolRuntime, pos: _Position) -> None:
        from .margin import liquidation_price

        posted = max(pos.initial_margin, self._available_margin() + pos.initial_margin)
        liq = liquidation_price(
            side=pos.side,
            entry_price=pos.entry_price,
            qty=pos.qty,
            posted_margin=posted,
            mm_rate=pos.maintenance_rate,
            deduction=pos.maintenance_deduction,
            close_fee_rate=(
                self.costs.rate_for(FeeRole.LIQUIDATION)
                if self.margin.include_close_fee_in_liquidation
                else 0.0
            ),
            tick_size=rt.stream.instrument.tick_size,
        )
        pos.liquidation_price = liq
        pos.levels = replace(pos.levels, liquidation=liq)

    # -- wallet ----------------------------------------------------------------------

    def _open_positions(self) -> list[_Position]:
        return [p for rt in self.runtimes.values() for p in rt.positions]

    def _unrealized(self, marks: Mapping[str, float] | None = None) -> float:
        total = 0.0
        for rt in self.runtimes.values():
            if not rt.positions:
                continue
            i = min(rt.bar_cursor, len(rt.stream.bars) - 1)
            price = float(rt.stream.bars.close[i])
            if marks and rt.stream.symbol in marks:
                price = marks[rt.stream.symbol]
            for pos in rt.positions:
                total += int(pos.side) * (price - pos.entry_price) * pos.qty
        return total

    def _equity(self) -> float:
        return self.cash + self._unrealized()

    def _used_margin(self) -> float:
        return sum(p.initial_margin for p in self._open_positions())

    def _available_margin(self) -> float:
        return self._equity() - self._used_margin()

    def _record_equity(self, ts: int) -> None:
        for rt in self.runtimes.values():
            idx = int(np.searchsorted(rt.stream.bars.ts_ms, ts, side="right")) - 1
            rt.bar_cursor = max(0, idx)
        unrealized = self._unrealized()
        equity = self.cash + unrealized
        self._equity_rows.append(
            (
                int(ts),
                equity,
                self.cash,
                unrealized,
                self._used_margin(),
                len(self._open_positions()),
            )
        )

    # -- skips -----------------------------------------------------------------------

    def _skip(
        self,
        signal: Signal,
        reason: SkipReason,
        detail: str,
        requested_qty: float = 0.0,
    ) -> None:
        if self.sim.raise_on_infeasible:
            raise InfeasibleOrderError(f"{reason.value} on {signal.symbol}: {detail}")
        self.skips.append(
            Skip(signal.ts_ms, signal.symbol, reason.value, detail, requested_qty)
        )

    # -- result ----------------------------------------------------------------------

    def _build_result(self) -> SimResult:
        equity_df = pd.DataFrame(
            self._equity_rows,
            columns=["ts_ms", "equity", "cash", "unrealized", "used_margin", "open_positions"],
        )
        if not equity_df.empty:
            equity_df["ts"] = pd.to_datetime(equity_df["ts_ms"], unit="ms", utc=True)
        daily = _daily_equity(equity_df)

        skip_counts: dict[str, int] = {}
        for s in self.skips:
            skip_counts[s.reason] = skip_counts.get(s.reason, 0) + 1

        n = len(self.trades)
        entry_bar_exits = sum(1 for t in self.trades if t.entry_bar_exit)
        ambiguous = sum(1 for t in self.trades if t.ambiguous_intrabar)
        touch_resolved = sum(1 for t in self.trades if t.resolved_by_touch)
        liquidations = sum(
            1 for t in self.trades if t.exit_reason.startswith(REASON_LIQUIDATION)
        )
        rate = entry_bar_exits / n if n else 0.0

        if n and rate > 0.25:
            self.warnings.append(
                f"{entry_bar_exits} of {n} trades ({rate:.1%}) exited on their entry bar. "
                "Above 25% the stop is inside ordinary single-bar noise: the strategy is "
                "paying entry and exit costs to be shaken out, and this must be stated "
                "prominently in any report (standard section 9.6)."
            )
        if n and ambiguous / n > 0.10:
            self.warnings.append(
                f"{ambiguous} of {n} trades ({ambiguous / n:.1%}) were resolved by the "
                "adverse same-bar convention rather than by data. Supply touch-timeframe "
                "bars, and report the PnL sensitivity of the convention."
            )
        touch_gaps = sum(rt.touch_gaps for rt in self.runtimes.values())
        if touch_gaps:
            self.warnings.append(
                f"{touch_gaps} decision bar(s) had incomplete touch-timeframe coverage; "
                "lower-timeframe resolution was refused for them and the declared "
                "same-bar convention was used instead."
            )
        approximated = sum(rt.approximated_funding_marks for rt in self.runtimes.values())
        if approximated:
            self.warnings.append(
                f"{approximated} funding settlements did not land on a bar boundary; the "
                "containing bar's close stood in for the mark at that instant."
            )

        status = worst_status(self.liq_statuses) if self.liq_statuses else (
            LiquidationStatus.UNKNOWN if n else LiquidationStatus.UNKNOWN
        )
        if status != LiquidationStatus.MODELLED and n:
            self.warnings.append(
                f"liquidation status is {status.value}: maintenance tiers and/or a Mark "
                "price series were not supplied, so liquidation evidence is bounded, not "
                "deployment-grade (standard section 13.3)."
            )

        ending = self.cash + self._unrealized()
        summary = {
            "n_trades": n,
            "entry_bar_exits": entry_bar_exits,
            "entry_bar_exit_rate": rate,
            "ambiguous_intrabar": ambiguous,
            "ambiguous_rate": (ambiguous / n) if n else 0.0,
            "touch_resolved": touch_resolved,
            "touch_gaps": touch_gaps,
            "n_liquidations": liquidations,
            "n_skips": len(self.skips),
            "total_fees": sum(t.fees for t in self.trades),
            "total_funding": sum(t.funding for t in self.trades),
            "total_slippage": sum(t.slippage_cost for t in self.trades),
            "total_gross_pnl": sum(t.gross_pnl for t in self.trades),
            "total_realized_pnl": sum(t.realized_pnl for t in self.trades),
            "wallet_blown": bool(self._ruined),
            "ruined_at_ts_ms": self._ruined_at_ts_ms,
            "n_longs": sum(1 for t in self.trades if int(t.side) > 0),
            "n_shorts": sum(1 for t in self.trades if int(t.side) < 0),
        }

        stamp = None
        if self.attach_stamp:
            from .conformance.stamp import last_stamp, ungraded_stamp

            recorded = last_stamp()
            stamp = (
                recorded.as_dict()
                if recorded is not None
                else ungraded_stamp(
                    engine_name=ENGINE_NAME,
                    engine_version=ENGINE_VERSION,
                    contract="perp_bracket_portfolio",
                ).as_dict()
            )

        return SimResult(
            run_id=self.run_id,
            trades=tuple(self.trades),
            fills=tuple(self.fills),
            funding_charges=tuple(self.funding_charges),
            skips=tuple(self.skips),
            skip_counts=skip_counts,
            equity=equity_df,
            daily_equity=daily,
            liquidation_status=status.value,
            starting_equity=float(self.sim.starting_equity),
            ending_equity=float(ending),
            config_digest=self._config_digest(),
            stamp=stamp,
            warnings=tuple(self.warnings),
            meta={
                "engine": ENGINE_NAME,
                "engine_version": ENGINE_VERSION,
                "symbols": sorted(self.runtimes),
                "summary": summary,
            },
        )

    def _config_digest(self) -> str:
        payload = {
            "costs": _digestable(self.costs),
            "margin": _digestable(self.margin),
            "sizing": _digestable(self.sizing),
            "sim": _digestable(self.sim),
            "symbols": {
                s: _digestable(rt.stream.instrument) for s, rt in sorted(self.runtimes.items())
            },
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()


_ADVERSE_REASONS = frozenset(
    {REASON_STOP, REASON_LIQUIDATION, REASON_TRAILING, REASON_BREAK_EVEN}
)

_ROLE_FOR_REASON = {
    REASON_STOP: FeeRole.STOP,
    REASON_TARGET: FeeRole.TAKE_PROFIT,
    REASON_LIQUIDATION: FeeRole.LIQUIDATION,
    REASON_MAX_HOLD: FeeRole.TIMEOUT,
    REASON_TRAILING: FeeRole.TRAILING,
    REASON_BREAK_EVEN: FeeRole.BREAK_EVEN,
    REASON_END_OF_DATA: FeeRole.END_OF_DATA,
}


def _digestable(obj: Any) -> dict[str, Any]:  # noqa: ANN401
    out: dict[str, Any] = {}
    for key, value in vars(obj).items():
        if isinstance(value, np.ndarray):
            out[key] = value.tolist()
        elif isinstance(value, Mapping):
            out[key] = {str(k): str(v) for k, v in value.items()}
        else:
            out[key] = str(value)
    return out


def _daily_equity(equity: pd.DataFrame) -> pd.DataFrame:
    """Last mark-to-market equity of each UTC day, the canonical return series."""
    if equity.empty:
        return pd.DataFrame(columns=["day", "ts_ms", "equity"])
    df = equity.copy()
    df["day"] = df["ts"].dt.floor("D")
    last = df.groupby("day", as_index=False).last()
    return last[["day", "ts_ms", "equity"]].reset_index(drop=True)
