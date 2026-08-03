"""Frozen value types shared by every tradesim module.

Nothing in this module computes a fill. It defines the vocabulary: the instrument, the
cost schedule, the margin model, the sizing policy, the simulation policy, and the
result records. Keeping it free of logic means a fixture, an adapter and the engine all
agree on field names without importing the engine.

Time is integer milliseconds since the Unix epoch, UTC, always referring to a bar's OPEN
timestamp. Prices and quantities are floats in the instrument's own units.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Sequence

import numpy as np

# --------------------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------------------


class Side(int, Enum):
    """Position direction. The integer value is the sign used in every PnL formula."""

    LONG = 1
    SHORT = -1

    @classmethod
    def coerce(cls, value: "Side | int | str") -> "Side":
        if isinstance(value, Side):
            return value
        if isinstance(value, str):
            key = value.strip().lower()
            if key in ("long", "buy", "+1", "1"):
                return cls.LONG
            if key in ("short", "sell", "-1"):
                return cls.SHORT
            raise ValueError(f"unrecognised side {value!r}")
        if value > 0:
            return cls.LONG
        if value < 0:
            return cls.SHORT
        raise ValueError("side 0 is flat, not a position")


class EntryRef(str, Enum):
    """Where a signal known at a decision bar's close becomes an executable fill.

    ``NEXT_OPEN``   fill at the next bar's open; the whole of that bar is post-entry.
    ``CLOSE``       market order fired immediately after the decision bar closes, filled
                    at that close price plus slippage, but exposure is booked from the
                    next bar's open so no part of the decision bar is used retroactively.
    ``NEXT_CLOSE``  fill at the next bar's close; only that close is post-entry, so the
                    entry bar's post-entry path is a single point.

    There is deliberately no mode that fills at the decision bar's own close and then
    uses that bar's range: that is the retroactive fill forbidden by standard section 7.1.
    """

    NEXT_OPEN = "next_open"
    CLOSE = "close"
    NEXT_CLOSE = "next_close"


class EntryOrder(str, Enum):
    """How the entry fill is worked on the entry reference bar.

    ``MARKET``  cross the book: directional entry slippage + taker fee (default).
    ``LIMIT``   rest as Post-Only style: fill at the limit when touched, **maker** fee,
                **no** entry slippage. A marketable (crossing) limit is skipped, not
                silently converted to a taker fill — that would hide live Post-Only cancels.
    """

    MARKET = "market"
    LIMIT = "limit"

    @classmethod
    def coerce(cls, value: "EntryOrder | str | None") -> "EntryOrder":
        if value is None:
            return cls.MARKET
        if isinstance(value, cls):
            return value
        key = str(value).strip().lower()
        if key in ("market", "taker", "mkt"):
            return cls.MARKET
        if key in ("limit", "maker", "post_only", "post-only", "lmt"):
            return cls.LIMIT
        raise ValueError(f"unrecognised entry_order {value!r}")


class SameBarPolicy(str, Enum):
    """What to do when one bar contains both a favourable and an adverse trigger."""

    ADVERSE = "adverse"
    FAVOURABLE = "favourable"  # diagnostic sensitivity only, never a headline
    RAISE = "raise"


class MarginMode(str, Enum):
    ISOLATED = "isolated"
    CROSS = "cross"


class SizingMode(str, Enum):
    FIXED_QTY = "fixed_qty"
    FIXED_NOTIONAL = "fixed_notional"
    RISK_FRACTION = "risk_fraction"
    FIXED_RISK_CASH = "fixed_risk_cash"
    # Smallest venue-legal order: max(min_qty, min_notional / price), rounded up to step.
    # Preferred for research when absolute dollar PnL is secondary to path metrics.
    MIN_EXCHANGE = "min_exchange"


class LiquidationStatus(str, Enum):
    """How much of the venue's real liquidation machinery was actually modelled.

    Never absent from a result. ``UNKNOWN`` is a legitimate answer; a silent pass is not.
    """

    MODELLED = "MODELLED"  # tier table + Mark price series + fees + funding
    SIMPLIFIED = "SIMPLIFIED"  # single maintenance rate and/or Last-price proxy
    UNKNOWN = "UNKNOWN"  # no margin model supplied


class FeeRole(str, Enum):
    ENTRY = "entry"
    TAKE_PROFIT = "take_profit"
    STOP = "stop"
    LIQUIDATION = "liquidation"
    TIMEOUT = "timeout"
    TRAILING = "trailing"
    BREAK_EVEN = "break_even"
    END_OF_DATA = "end_of_data"


class Liquidity(str, Enum):
    MAKER = "maker"
    TAKER = "taker"


class SkipReason(str, Enum):
    """Every order that does not become a position leaves one of these behind.

    An infeasible order is never silently resized, never silently dropped and never
    rounded to zero (standard section 12.2).
    """

    QTY_ROUNDS_TO_ZERO = "SKIP_QTY_ROUNDS_TO_ZERO"
    BELOW_MIN_QTY = "SKIP_BELOW_MIN_QTY"
    BELOW_MIN_NOTIONAL = "SKIP_BELOW_MIN_NOTIONAL"
    ABOVE_MAX_QTY = "SKIP_ABOVE_MAX_QTY"
    MIN_QTY_EXCEEDS_RISK_CAP = "SKIP_MIN_QTY_RISK_CAP"
    INSUFFICIENT_MARGIN = "SKIP_INSUFFICIENT_MARGIN"
    MARGIN_UTILISATION_CAP = "SKIP_MARGIN_UTILISATION_CAP"
    LEVERAGE_INFEASIBLE = "SKIP_LEVERAGE_INFEASIBLE"
    STOP_INSIDE_LIQUIDATION = "SKIP_STOP_INSIDE_LIQUIDATION"
    INVALID_STOP_GEOMETRY = "SKIP_INVALID_STOP_GEOMETRY"
    PRE_LAUNCH_BAR = "SKIP_PRE_LAUNCH_BAR"
    NO_EXECUTABLE_BAR = "SKIP_NO_EXECUTABLE_BAR"
    POSITION_LIMIT = "SKIP_POSITION_LIMIT"
    WALLET_RUINED = "SKIP_WALLET_RUINED"
    NON_DEPLOYABLE_ORDER_GRANULARITY = "NON_DEPLOYABLE_ORDER_GRANULARITY"
    LIMIT_NOT_FILLED = "SKIP_LIMIT_NOT_FILLED"
    LIMIT_WOULD_CROSS = "SKIP_LIMIT_WOULD_CROSS"


# Exit reason vocabulary. Entry-bar exits carry the ``_entry_bar`` suffix so their
# frequency is reportable (standard section 9.6 point 4).
ENTRY_BAR_SUFFIX = "_entry_bar"

REASON_STOP = "stop"
REASON_TARGET = "target"
REASON_LIQUIDATION = "liquidation"
REASON_MAX_HOLD = "max_hold"
REASON_TRAILING = "trailing_stop"
REASON_BREAK_EVEN = "break_even_stop"
REASON_END_OF_DATA = "end_of_data"
REASON_SIGNAL_EXIT = "signal_exit"

BASE_EXIT_REASONS = (
    REASON_STOP,
    REASON_TARGET,
    REASON_LIQUIDATION,
    REASON_MAX_HOLD,
    REASON_TRAILING,
    REASON_BREAK_EVEN,
    REASON_END_OF_DATA,
    REASON_SIGNAL_EXIT,
)


def is_entry_bar_reason(reason: str) -> bool:
    return reason.endswith(ENTRY_BAR_SUFFIX)


def base_reason(reason: str) -> str:
    return reason[: -len(ENTRY_BAR_SUFFIX)] if is_entry_bar_reason(reason) else reason


# --------------------------------------------------------------------------------------
# Instrument specification
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MaintenanceTier:
    """One row of a venue risk-limit ladder.

    ``mm_rate`` applies to position notional above ``notional_floor``; ``deduction`` is
    the venue's cumulative maintenance-amount offset that keeps the ladder continuous.
    """

    notional_floor: float
    mm_rate: float
    max_leverage: float
    deduction: float = 0.0


@dataclass(frozen=True)
class InstrumentSpec:
    """Timestamped exchange rules for one symbol (standard section 6.2)."""

    symbol: str
    tick_size: float
    qty_step: float
    min_qty: float
    min_notional: float
    max_qty: float = float("inf")
    max_leverage: float = 100.0
    maintenance_rate: float = 0.005
    maintenance_tiers: tuple[MaintenanceTier, ...] = ()
    funding_interval_ms: int = 8 * 60 * 60 * 1000
    launch_ts_ms: int | None = None
    contract_size: float = 1.0
    quote_currency: str = "USDT"
    snapshot_ts_ms: int | None = None
    source: str = "UNSPECIFIED"

    def __post_init__(self) -> None:
        if self.tick_size <= 0:
            raise ValueError("tick_size must be positive")
        if self.qty_step <= 0:
            raise ValueError("qty_step must be positive")
        if self.min_qty < 0 or self.min_notional < 0:
            raise ValueError("minimums cannot be negative")

    @property
    def tiers_available(self) -> bool:
        return len(self.maintenance_tiers) > 0

    def tier_for_notional(self, notional: float) -> MaintenanceTier:
        if not self.maintenance_tiers:
            return MaintenanceTier(0.0, self.maintenance_rate, self.max_leverage, 0.0)
        chosen = self.maintenance_tiers[0]
        for tier in self.maintenance_tiers:
            if abs(notional) >= tier.notional_floor:
                chosen = tier
            else:
                break
        return chosen


# --------------------------------------------------------------------------------------
# Costs
# --------------------------------------------------------------------------------------


def default_role_liquidity(
    *,
    entry: Liquidity = Liquidity.TAKER,
    take_profit: Liquidity = Liquidity.TAKER,
    stop: Liquidity = Liquidity.TAKER,
    liquidation: Liquidity = Liquidity.TAKER,
    timeout: Liquidity = Liquidity.TAKER,
    trailing: Liquidity = Liquidity.TAKER,
    break_even: Liquidity = Liquidity.TAKER,
    end_of_data: Liquidity = Liquidity.TAKER,
) -> dict[str, Liquidity]:
    """Per-fill maker/taker map. Conservative research default is taker on every role."""
    return {
        FeeRole.ENTRY.value: entry,
        FeeRole.TAKE_PROFIT.value: take_profit,
        FeeRole.STOP.value: stop,
        FeeRole.LIQUIDATION.value: liquidation,
        FeeRole.TIMEOUT.value: timeout,
        FeeRole.TRAILING.value: trailing,
        FeeRole.BREAK_EVEN.value: break_even,
        FeeRole.END_OF_DATA.value: end_of_data,
    }


@dataclass(frozen=True)
class CostConfig:
    """Fee and slippage schedule.

    Fees are ``qty * executed_price * rate`` per fill (standard section 11.0). Slippage
    moves the fill price and is never folded into a rate. Rates are fractions, not basis
    points and not percent: Bybit non-VIP taker is ``0.00055``, maker ``0.0002``.
    """

    taker_rate: float = 0.00055
    maker_rate: float = 0.0002
    entry_slippage: float = 0.0
    market_exit_slippage: float = 0.0
    spread: float = 0.0
    # Which side of the book each fill role is assumed to hit. The conservative default
    # is taker everywhere: a resting take-profit limit only earns the maker rate when
    # maker execution has been evidenced (standard section 11.0 rule 4).
    role_liquidity: Mapping[str, Liquidity] = field(
        default_factory=default_role_liquidity
    )
    # Extra fee charged by the venue's liquidation engine, on top of the taker fee.
    liquidation_penalty_rate: float = 0.0
    # Multiplies every slippage term. Frozen stress scenarios move this, not the base.
    slippage_stress_multiplier: float = 1.0

    def rate_for(self, role: FeeRole | str, liquidity: Liquidity | None = None) -> float:
        key = role.value if isinstance(role, FeeRole) else str(role)
        liq = self.liquidity_for(role) if liquidity is None else liquidity
        rate = self.maker_rate if liq == Liquidity.MAKER else self.taker_rate
        if key == FeeRole.LIQUIDATION.value:
            rate += self.liquidation_penalty_rate
        return rate

    def liquidity_for(self, role: FeeRole | str) -> Liquidity:
        key = role.value if isinstance(role, FeeRole) else str(role)
        return self.role_liquidity.get(key, Liquidity.TAKER)

    def with_role_liquidity(self, **roles: Liquidity | str) -> "CostConfig":
        """Return a copy with selected roles remapped (e.g. ``entry=Liquidity.MAKER``)."""
        merged = dict(self.role_liquidity)
        for key, value in roles.items():
            merged[key] = value if isinstance(value, Liquidity) else Liquidity(str(value))
        return replace(self, role_liquidity=merged)

    @property
    def effective_entry_slippage(self) -> float:
        return (self.entry_slippage + self.spread / 2.0) * self.slippage_stress_multiplier

    @property
    def effective_market_exit_slippage(self) -> float:
        return (
            self.market_exit_slippage + self.spread / 2.0
        ) * self.slippage_stress_multiplier


# --------------------------------------------------------------------------------------
# Margin
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MarginConfig:
    mode: MarginMode = MarginMode.ISOLATED
    leverage: float | None = None  # None => derive from stop distance
    # Buffers used when deriving leverage from the stop distance:
    # leverage = floor(1 / (sl_pct + maintenance_buffer + mark_buffer)).
    maintenance_buffer: float = 0.005
    mark_buffer: float = 0.002
    max_margin_utilisation: float = 0.60
    # Include the estimated fee to close in the liquidation solve.
    include_close_fee_in_liquidation: bool = True
    # A stop that sits beyond the liquidation price is not a stop. Reject the order
    # rather than pretending the protective level exists.
    require_stop_inside_liquidation: bool = True
    # Liquidation triggers on Mark price at the venue. When no mark series is supplied
    # the engine falls back to Last and downgrades the liquidation status.
    liquidation_trigger: str = "mark"


# --------------------------------------------------------------------------------------
# Sizing
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SizingConfig:
    mode: SizingMode = SizingMode.FIXED_QTY
    fixed_qty: float = 1.0
    fixed_notional: float = 1000.0
    risk_fraction: float = 0.005
    fixed_risk_cash: float = 50.0
    # Multiplies the minimum executable quantity when checking feasibility, so a trade
    # that is only just executable is skipped rather than left with no headroom.
    min_qty_safety_buffer: float = 1.0
    # Hard ceiling on risk per trade as a fraction of equity. The minimum executable
    # order is skipped rather than rounded up through this cap.
    max_risk_fraction: float | None = None
    compound: bool = True


@dataclass(frozen=True)
class TakeProfitLeg:
    """One leg of a multi-leg take profit.

    ``price`` is absolute; ``price_offset`` is a signed fraction of the entry fill in the
    favourable direction. Exactly one of them must be supplied per leg.
    ``qty_fraction`` is the fraction of the ORIGINAL filled quantity closed by this leg.
    """

    qty_fraction: float
    price: float | None = None
    price_offset: float | None = None
    label: str = "tp"

    def resolve_price(self, side: Side, entry_price: float) -> float:
        if self.price is not None:
            return float(self.price)
        if self.price_offset is None:
            raise ValueError("take-profit leg needs price or price_offset")
        return entry_price * (1.0 + int(side) * float(self.price_offset))


@dataclass(frozen=True)
class BreakEvenConfig:
    """Move the stop to entry (plus an offset) once price advances far enough."""

    trigger_offset: float | None = None  # favourable fraction of entry that arms it
    trigger_price: float | None = None
    trigger_on_leg: int | None = None  # arm when this take-profit leg index fills
    stop_offset: float = 0.0  # where the stop goes, as a fraction of entry


@dataclass(frozen=True)
class TrailConfig:
    """Ratchet the stop behind the best price seen so far."""

    distance: float  # fraction of the extreme price
    activation_offset: float | None = None  # arm only after this much favourable move
    step: float = 0.0  # minimum improvement before the stop is moved


# --------------------------------------------------------------------------------------
# Simulation policy
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SimConfig:
    """Everything about how the simulation runs that is not instrument or cost."""

    entry_ref: EntryRef = EntryRef.NEXT_OPEN
    # Default entry order type. Per-signal ``Signal.entry_order`` overrides this.
    entry_order: EntryOrder = EntryOrder.MARKET
    latency_bars: int = 0
    same_bar_policy: SameBarPolicy = SameBarPolicy.ADVERSE
    max_hold_bars: int | None = None
    # Take-profit exits are limit orders resting at the level: no favourable slippage.
    # Set False to model a market-triggered take profit, which does slip.
    take_profit_is_limit: bool = True
    # Project default (2026-07-26): stop-loss is a limit at the level, no exit slip, assumed
    # to fill at small size. Set True to model a stop-market that gaps through and slips.
    stop_is_stop_market: bool = False
    allow_concurrent_positions: bool = False
    max_positions_per_symbol: int = 1
    close_at_end_of_data: bool = True
    # Charge funding settlements that fall inside the exit bar when sub-bar timing is
    # unknown. "bar_end" is the adverse-cost resolution; "bar_start" is the exact
    # half-open [entry, exit) window and undercharges same-bar round trips.
    funding_exit_boundary: str = "bar_end"
    # Deterministic tie-break when several symbols signal on the same bar.
    portfolio_priority: str = "symbol"
    starting_equity: float = 10_000.0
    allow_trading_after_ruin: bool = False
    # Fail loudly on an infeasible order instead of recording a skip.
    raise_on_infeasible: bool = False
    decision_timeframe: str = "UNSPECIFIED"
    touch_timeframe: str | None = None
    annualisation_days: float = 365.0


# --------------------------------------------------------------------------------------
# Market data
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BarSeries:
    """Validated OHLC bars. ``ts_ms`` is each bar's OPEN time, strictly increasing."""

    ts_ms: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    timeframe_ms: int
    volume: np.ndarray | None = None
    symbol: str = "UNSPECIFIED"

    def __post_init__(self) -> None:
        object.__setattr__(self, "ts_ms", np.asarray(self.ts_ms, dtype=np.int64))
        for name in ("open", "high", "low", "close"):
            object.__setattr__(self, name, np.asarray(getattr(self, name), dtype=float))
        if self.volume is not None:
            object.__setattr__(self, "volume", np.asarray(self.volume, dtype=float))
        n = len(self.ts_ms)
        for name in ("open", "high", "low", "close"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"{name} length {len(getattr(self, name))} != ts length {n}")
        if self.timeframe_ms <= 0:
            raise ValueError("timeframe_ms must be positive")

    def __len__(self) -> int:
        return int(len(self.ts_ms))

    @property
    def end_ts_ms(self) -> np.ndarray:
        return self.ts_ms + self.timeframe_ms

    def bar(self, i: int) -> "Bar":
        return Bar(
            ts_ms=int(self.ts_ms[i]),
            open=float(self.open[i]),
            high=float(self.high[i]),
            low=float(self.low[i]),
            close=float(self.close[i]),
            timeframe_ms=int(self.timeframe_ms),
        )

    @classmethod
    def from_rows(
        cls,
        rows: Sequence[Sequence[float]],
        timeframe_ms: int,
        symbol: str = "UNSPECIFIED",
    ) -> "BarSeries":
        """Build from ``[ts_ms, open, high, low, close, volume?]`` rows."""
        arr = np.asarray(rows, dtype=float)
        if arr.ndim != 2 or arr.shape[1] < 5:
            raise ValueError("rows must be [ts_ms, open, high, low, close, volume?]")
        return cls(
            ts_ms=arr[:, 0].astype(np.int64),
            open=arr[:, 1],
            high=arr[:, 2],
            low=arr[:, 3],
            close=arr[:, 4],
            volume=arr[:, 5] if arr.shape[1] > 5 else None,
            timeframe_ms=int(timeframe_ms),
            symbol=symbol,
        )


@dataclass(frozen=True)
class Bar:
    """A single bar, or a synthetic sub-path handed to the exit resolver."""

    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    timeframe_ms: int

    @property
    def end_ts_ms(self) -> int:
        return int(self.ts_ms) + int(self.timeframe_ms)

    def as_point(self, price: float, ts_ms: int | None = None) -> "Bar":
        """Degenerate bar used when the only post-entry exposure is a single price."""
        return Bar(
            ts_ms=int(self.ts_ms if ts_ms is None else ts_ms),
            open=price,
            high=price,
            low=price,
            close=price,
            timeframe_ms=int(self.timeframe_ms),
        )


# --------------------------------------------------------------------------------------
# Signals
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Signal:
    """A causal intent produced by a strategy at ``ts_ms``'s CLOSE.

    The engine, not the strategy, decides where that becomes a fill.
    ``stop_offset`` / ``target_offset`` are fractions of the entry fill; absolute
    ``stop_price`` / ``target_price`` take precedence when supplied.
    """

    ts_ms: int
    side: Side
    symbol: str = "UNSPECIFIED"
    stop_price: float | None = None
    target_price: float | None = None
    stop_offset: float | None = None
    target_offset: float | None = None
    tp_legs: tuple[TakeProfitLeg, ...] = ()
    break_even: BreakEvenConfig | None = None
    trail: TrailConfig | None = None
    max_hold_bars: int | None = None
    qty: float | None = None
    notional: float | None = None
    risk_fraction: float | None = None
    # None → use ``SimConfig.entry_order``. ``LIMIT`` = maker fee, no entry slip.
    entry_order: EntryOrder | None = None
    # Absolute limit price, or passive offset from the entry reference (long buys at
    # ``ref * (1 - offset)``, short sells at ``ref * (1 + offset)``). Both None → limit
    # at the reference itself (fill when the entry bar touches that price).
    limit_price: float | None = None
    limit_offset: float | None = None
    tag: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", Side.coerce(self.side))
        object.__setattr__(self, "ts_ms", int(self.ts_ms))
        if self.entry_order is not None:
            object.__setattr__(self, "entry_order", EntryOrder.coerce(self.entry_order))


# --------------------------------------------------------------------------------------
# Result records
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fill:
    ts_ms: int
    symbol: str
    role: str
    side: str  # the direction of THIS fill: "buy" or "sell"
    qty: float
    price: float
    notional: float
    liquidity: str
    fee_rate: float
    fee: float
    slippage_cost: float
    trade_id: int
    reason: str = ""


@dataclass(frozen=True)
class FundingCharge:
    ts_ms: int
    symbol: str
    rate: float
    mark_price: float
    qty: float
    side: int
    notional: float
    cashflow: float  # negative = paid
    trade_id: int


@dataclass(frozen=True)
class Skip:
    ts_ms: int
    symbol: str
    reason: str
    detail: str = ""
    requested_qty: float = 0.0


@dataclass(frozen=True)
class Trade:
    trade_id: int
    symbol: str
    side: int
    entry_ts_ms: int
    entry_price: float
    entry_ref_price: float
    qty: float
    stop_price: float
    target_price: float | None
    liquidation_price: float | None
    leverage: float
    initial_margin: float
    exit_ts_ms: int
    exit_price: float
    exit_reason: str
    hold_bars: int
    fees: float
    funding: float
    slippage_cost: float
    gross_pnl: float
    realized_pnl: float
    return_units: float  # realized_pnl / entry notional
    mae: float
    mfe: float
    ambiguous_intrabar: bool
    resolved_by_touch: bool
    entry_bar_exit: bool
    tag: str = ""
    legs: tuple[tuple[str, int, float, float], ...] = ()  # (label, ts_ms, qty, price)
    # Planned take-profit ladder at open: (label, price, qty_fraction). Empty when single TP
    # is only in ``target_price``.
    tp_levels: tuple[tuple[str, float, float], ...] = ()

    @property
    def entry_notional(self) -> float:
        return abs(self.qty * self.entry_price)


@dataclass(frozen=True)
class SimResult:
    """Everything a report writer is allowed to see, including how trustworthy it is."""

    run_id: str
    trades: tuple[Trade, ...]
    fills: tuple[Fill, ...]
    funding_charges: tuple[FundingCharge, ...]
    skips: tuple[Skip, ...]
    skip_counts: Mapping[str, int]
    equity: "PandasFrameLike"
    daily_equity: "PandasFrameLike"
    liquidation_status: str
    starting_equity: float
    ending_equity: float
    config_digest: str
    stamp: Mapping[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def n_trades(self) -> int:
        return len(self.trades)


# ``pandas.DataFrame`` is only referenced for typing; avoid importing pandas here so the
# contract module stays importable in the narrowest environments.
PandasFrameLike = Any


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _grid_epsilon(n: float) -> float:
    """Relative tolerance for grid rounding.

    ``95.0 / 0.01`` is 9500.000000000002 and ``102.9 / 0.01`` is 10289.999999999998 in
    binary floating point. A fixed absolute epsilon gets one of those wrong; the error
    scales with the magnitude, so the tolerance has to as well.
    """
    return 1e-9 * max(1.0, abs(n))


def round_to_tick(price: float, tick: float, mode: str = "nearest") -> float:
    """Round a price onto the instrument grid without floating-point drift."""
    if tick <= 0:
        return float(price)
    n = float(price) / float(tick)
    eps = _grid_epsilon(n)
    if mode == "floor":
        k = math.floor(n + eps)
    elif mode == "ceil":
        k = math.ceil(n - eps)
    else:
        k = math.floor(n + 0.5) if n >= 0 else math.ceil(n - 0.5)
    return _clean(k * float(tick))


def round_to_step(qty: float, step: float, mode: str = "floor") -> float:
    if step <= 0:
        return float(qty)
    n = float(qty) / float(step)
    eps = _grid_epsilon(n)
    if mode == "ceil":
        k = math.ceil(n - eps)
    elif mode == "nearest":
        k = math.floor(n + 0.5)
    else:
        k = math.floor(n + eps)
    return _clean(k * float(step))


def _clean(value: float) -> float:
    """Strip binary-representation dust so 0.30000000000000004 stores as 0.3."""
    return float(f"{value:.12g}")


def replace_config(cfg: Any, **changes: Any) -> Any:
    return replace(cfg, **changes)
