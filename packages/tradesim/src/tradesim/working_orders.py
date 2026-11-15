"""Admission, reservation and partial-entry accounting for a single passive order.

The caller supplies an already qualified fill quantity and causally available
wallet/quote inputs. This component does not infer fills from public trades,
resolve exits, debit wallet cash or certify exchange parity.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from math import isfinite
from typing import Callable

from .contracts import CostConfig, FeeRole, InstrumentSpec, Liquidity, MarginConfig, MarginMode, Side, SizingConfig, SizingMode
from .fees import PricedFill, price_fill, resolve_limit_entry_price
from .margin import MarginError, build_margin_state, stop_is_inside_liquidation
from .sizing import desired_qty, normalise_order


@dataclass(frozen=True)
class WorkingIntent:
    order_id: str
    side: Side
    decision_ms: int
    submitted_ms: int
    active_ms: int
    expires_ms: int
    quote_exchange_ms: int
    quote_received_ms: int
    bid: float
    ask: float
    limit_price: float
    stop_price: float


@dataclass(frozen=True)
class ReservedOrder:
    intent: WorkingIntent
    limit_price: float
    stop_price: float
    qty: float
    remaining_qty: float
    initial_margin: float
    leverage: float
    entry_fee: float
    risk: float
    censored: bool = False

    @property
    def fraction_remaining(self) -> float:
        return self.remaining_qty / self.qty

    @property
    def reserved_margin(self) -> float:
        return self.initial_margin * self.fraction_remaining

    @property
    def reserved_fee(self) -> float:
        return self.entry_fee * self.fraction_remaining

    @property
    def reserved_risk(self) -> float:
        return self.risk * self.fraction_remaining


@dataclass(frozen=True)
class WorkingTransition:
    order_id: str
    ts_ms: int
    status: str
    order: ReservedOrder | None = None
    fill: PricedFill | None = None
    fill_id: str | None = None
    margin_to_position: float = 0.0
    risk_to_position: float = 0.0
    margin_released: float = 0.0
    fee_reserve_released: float = 0.0
    risk_released: float = 0.0
    execution_liquidity: Liquidity | None = None
    # Why a result is indeterminate (CAPTURE_GAP only). Empty for every other status.
    reason: str = ""
    # Protection clocks of an entry slice. The theoretical instant is the fill itself (the engine
    # evaluates the frozen Mark stop from that event). The attested instant is when real data confirmed
    # an armed stop; None means no attestation. No protection latency is modelled.
    protection_theoretical_ms: int | None = None
    protection_attested_ms: int | None = None


@dataclass
class WorkingOrderSlot:
    """One slot for one symbol in a one-way isolated paper portfolio."""

    spec: InstrumentSpec
    margin: MarginConfig
    costs: CostConfig
    risk_fraction: float
    notional_ceiling: float | None = None
    order: ReservedOrder | None = field(default=None, init=False)
    _seen_orders: set[str] = field(default_factory=set, init=False, repr=False)
    _seen_fills: dict[str, tuple[str, int, float]] = field(default_factory=dict, init=False, repr=False)
    _last_ms: int = field(default=-1, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.margin.mode != MarginMode.ISOLATED or not self.spec.tiers_available:
            raise ValueError("A passive slot requires isolated margin and maintenance tiers")
        if not 0 < self.risk_fraction <= 1:
            raise ValueError("Risk fraction must be in (0, 1]")
        if self.notional_ceiling is not None and not (isfinite(self.notional_ceiling) and self.notional_ceiling > 0):
            raise ValueError("Invalid maintenance notional ceiling")
        for role in (FeeRole.ENTRY, FeeRole.LIQUIDATION):
            rate = self.costs.rate_for(role)
            if not isfinite(rate) or rate < 0:
                raise ValueError("Fee rates must be finite and non-negative")

    def _require_time(self, ts_ms: int) -> None:
        if type(ts_ms) is not int or ts_ms < self._last_ms:
            raise ValueError("Events must be processed in chronological order")

    def _admission_status(self, intent, equity, used_margin, available_margin, position_open):
        if self.order is not None:
            return "CAPTURE_GAP" if self.order.censored else "WORKING_ORDER"
        if position_open:
            return "POSITION_OPEN"
        stamps = (intent.decision_ms, intent.submitted_ms, intent.active_ms, intent.expires_ms,
                  intent.quote_exchange_ms, intent.quote_received_ms)
        if any(type(value) is not int or value < 0 for value in stamps):
            raise ValueError("Invalid intent timestamps")
        if not (intent.decision_ms <= intent.submitted_ms <= intent.active_ms < intent.expires_ms):
            raise ValueError("Invalid intent clock")
        if any(not isfinite(value) for value in (equity, used_margin, available_margin)) or used_margin < 0:
            raise ValueError("Invalid wallet snapshot")
        if not (intent.submitted_ms - 5000 <= intent.quote_exchange_ms <= intent.quote_received_ms <= intent.submitted_ms):
            return "QUOTE_STALE_OR_FUTURE"
        if self.spec.snapshot_ts_ms is not None and self.spec.snapshot_ts_ms > intent.submitted_ms:
            return "INSTRUMENT_SNAPSHOT_FUTURE"
        if self.spec.launch_ts_ms is not None and intent.submitted_ms < self.spec.launch_ts_ms:
            return "PRE_LAUNCH_BAR"
        return None

    def admit(self, intent: WorkingIntent, *, equity: float, used_margin: float,
              available_margin: float, position_open: bool) -> WorkingTransition:
        if not intent.order_id or intent.order_id in self._seen_orders:
            raise ValueError("Expected a new paper order identity")
        self._require_time(intent.submitted_ms)
        status = self._admission_status(intent, equity, used_margin, available_margin, position_open)
        order = None
        if status is None:
            status, order = self._prepare(intent, equity, used_margin, available_margin)
        self._last_ms = intent.submitted_ms
        self._seen_orders.add(intent.order_id)
        if order is not None:
            self.order = order
        return WorkingTransition(intent.order_id, intent.submitted_ms, status, order)

    def _prepare(self, intent, equity, used_margin, available_margin):
        side = Side.coerce(intent.side)
        if any(not isfinite(value) or value <= 0 for value in (intent.bid, intent.ask, intent.limit_price, intent.stop_price)) or intent.bid >= intent.ask:
            return "INVALID_QUOTE_OR_LEVEL", None
        limit = resolve_limit_entry_price(ref_price=intent.bid, side=side, tick=self.spec.tick_size, limit_price=intent.limit_price)
        if (side == Side.SHORT and limit <= intent.bid) or (side == Side.LONG and limit >= intent.ask):
            return "LIMIT_WOULD_CROSS", None
        if Decimal(str(intent.stop_price)) % Decimal(str(self.spec.tick_size)) != 0:
            return "STOP_OFF_TICK_GRID", None
        if limit <= 0 or int(side) * (limit - intent.stop_price) <= 0:
            return "INVALID_STOP_GEOMETRY", None
        if equity <= 0 or available_margin <= 0:
            return "INSUFFICIENT_MARGIN", None
        sizing = SizingConfig(mode=SizingMode.RISK_FRACTION, risk_fraction=self.risk_fraction,
                              max_risk_fraction=self.risk_fraction)
        raw, _ = desired_qty(cfg=sizing, price=limit, stop_price=intent.stop_price, equity=equity)
        sizing_outcome = normalise_order(raw_qty=raw, price=limit, stop_price=intent.stop_price,
                                         equity=equity, spec=self.spec, cfg=sizing)
        if not sizing_outcome.ok:
            return sizing_outcome.skip_reason.value.upper(), None
        qty = sizing_outcome.qty
        if self.notional_ceiling is not None and qty * limit > self.notional_ceiling:
            return "RISK_NOTIONAL_CEILING", None
        try:
            margin = build_margin_state(side=side, entry_price=limit, qty=qty, stop_price=intent.stop_price,
                                        spec=self.spec, cfg=self.margin, close_fee_rate=self.costs.rate_for(FeeRole.LIQUIDATION),
                                        wallet_available=available_margin, has_mark_series=True)
        except MarginError:
            return "LEVERAGE_INFEASIBLE", None
        if not stop_is_inside_liquidation(side, intent.stop_price, margin.liquidation_price):
            return "STOP_INSIDE_LIQUIDATION", None
        fee = self._price(qty, limit).fee
        if margin.initial_margin + fee > available_margin + 1e-12:
            return "INSUFFICIENT_MARGIN", None
        if used_margin + margin.initial_margin > equity * self.margin.max_margin_utilisation + 1e-12:
            return "MARGIN_UTILISATION_CAP", None
        order = ReservedOrder(intent, limit, intent.stop_price, qty, qty, margin.initial_margin,
                              margin.leverage, fee, qty * abs(limit - intent.stop_price))
        return "RESERVED", order

    def _price(self, qty: float, limit: float) -> PricedFill:
        return price_fill(role=FeeRole.ENTRY, qty=qty, price=limit, ref_price=limit, costs=self.costs)

    def is_duplicate_fill(self, order_id: str, ts_ms: int, fill_id: str, qty: float) -> bool:
        if not fill_id:
            raise ValueError("Expected a stable fill identity")
        previous = self._seen_fills.get(fill_id)
        if previous is not None:
            if previous != (order_id, ts_ms, qty):
                raise ValueError("Conflicting reuse of a fill identity")
            return True
        return False

    def book_fill(self, order_id: str, ts_ms: int, *, fill_id: str, qty: float,
                  book_position: Callable[[WorkingTransition], None] | None = None) -> WorkingTransition:
        """Book one qualified entry slice at the reserved price and leverage."""
        if self.is_duplicate_fill(order_id, ts_ms, fill_id, qty):
            return WorkingTransition(order_id, ts_ms, "DUPLICATE_FILL", fill_id=fill_id)
        self._require_time(ts_ms)
        order = self.order
        if order is None or order.intent.order_id != order_id or order.censored:
            raise ValueError("No matching observable order")
        if not order.intent.active_ms < ts_ms < order.intent.expires_ms:
            raise ValueError("Fill timestamp is outside the active order window")
        if not isfinite(qty) or qty <= 0:
            raise ValueError("Fill quantity must be positive and finite")
        amount, step = Decimal(str(qty)), Decimal(str(self.spec.qty_step))
        remaining = Decimal(str(order.remaining_qty))
        if amount % step or amount > remaining:
            raise ValueError("Fill quantity is off-step or above the reserved remainder")
        after = replace(order, remaining_qty=float(remaining - amount))
        transition = WorkingTransition(order_id, ts_ms, "PARTIAL_FILL" if after.remaining_qty else "FILLED", order=after,
                                 fill=self._price(qty, order.limit_price), fill_id=fill_id,
                                 margin_to_position=order.reserved_margin - after.reserved_margin,
                                 risk_to_position=order.reserved_risk - after.reserved_risk,
                                 fee_reserve_released=order.reserved_fee - after.reserved_fee,
                                 execution_liquidity=Liquidity.MAKER)
        if book_position is not None:
            book_position(transition)
        self.order = after if after.remaining_qty else None
        self._last_ms = ts_ms
        self._seen_fills[fill_id] = (order_id, ts_ms, qty)
        return transition

    def expire(self, ts_ms: int, *, coverage_confirmed: bool) -> WorkingTransition:
        """Release only the remainder when its deadline is observably reached."""
        self._require_time(ts_ms)
        order = self.order
        if order is None or order.censored or ts_ms != order.intent.expires_ms:
            raise ValueError("Expected an observable pending order at its expiration")
        if not coverage_confirmed:
            return self.censor(ts_ms, reason="EXPIRY_COVERAGE_UNCONFIRMED")
        return self._release(ts_ms, order, "EXPIRED")

    def cancel(self, ts_ms: int, *, order_id: str) -> WorkingTransition:
        """Release the remaining allocation on a known terminal cancellation."""
        self._require_time(ts_ms)
        order = self.order
        if (order is None or order.censored or order.intent.order_id != order_id
                or not order.intent.submitted_ms <= ts_ms < order.intent.expires_ms):
            raise ValueError("Expected a matching observable pending order to cancel")
        return self._release(ts_ms, order, "CANCELLED")

    def _release(self, ts_ms: int, order: ReservedOrder, status: str) -> WorkingTransition:
        self.order = None
        self._last_ms = ts_ms
        return WorkingTransition(order.intent.order_id, ts_ms, status, order,
                                 margin_released=order.reserved_margin, fee_reserve_released=order.reserved_fee,
                                 risk_released=order.reserved_risk)

    def censor(self, ts_ms: int, *, reason: str = "") -> WorkingTransition:
        self._require_time(ts_ms)
        if self.order is None or self.order.censored or ts_ms > self.order.intent.expires_ms:
            raise ValueError("Expected an observable pending order to censor")
        self.order = replace(self.order, censored=True)
        self._last_ms = ts_ms
        return WorkingTransition(self.order.intent.order_id, ts_ms, "CAPTURE_GAP", self.order, reason=reason)
