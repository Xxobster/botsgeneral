"""Chronological single-symbol driver for qualified passive paper events.

An upstream adapter must certify receipt/market clocks, venue sequence, quote
freshness, coverage, and executable entry/target quantities. This module owns
neither the public-feed adaptation nor a model of the venue's private queue.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite

import numpy as np

from .contracts import CostConfig, MarginConfig, PositionMode, Side, SimConfig, SizingConfig, round_to_tick
from .engine import SymbolStream, _Engine
from .sizing import minimum_executable_qty
from .working_orders import WorkingIntent, WorkingOrderSlot, WorkingTransition


@dataclass(frozen=True)
class PaperWalletPoint:
    ts_ms: int
    cash: float
    equity: float
    position_qty: float
    position_margin: float
    reserved_margin: float
    reserved_fee: float


class WorkingOrderReplay:
    """Use the same position, fee, funding and exit ledger as the bar engine."""

    def __init__(self, stream: SymbolStream, *, costs: CostConfig, margin: MarginConfig,
                 sim: SimConfig, risk_fraction: float, hold_bars: int,
                 notional_ceiling: float | None = None) -> None:
        if (stream.signals or stream.mark_bars is None or stream.touch_bars is not None
                or stream.funding_ts_ms is not None or stream.funding_rate is not None):
            raise ValueError("Event replay requires aligned timestamp envelopes and no bar-scheduled signals")
        if not (sim.stop_trigger == margin.liquidation_trigger == "mark" and sim.stop_is_stop_market
                and sim.take_profit_is_limit and not sim.allow_concurrent_positions and not sim.close_at_end_of_data
                and PositionMode.coerce(sim.position_mode) == PositionMode.ONE_WAY
                and isfinite(sim.starting_equity) and sim.starting_equity > 0):
            raise ValueError("Expected Mark protection, a resting target and no artificial closing fill")
        if type(hold_bars) is not int or hold_bars <= 0:
            raise ValueError("Holding window must be a positive bar count")
        self._engine = _Engine(streams=[stream], costs=costs, margin=margin, sizing=SizingConfig(),
                               sim=sim, run_id="", attach_stamp=False)
        self._rt = self._engine.runtimes[stream.symbol]
        self._slot = WorkingOrderSlot(stream.instrument, margin, costs, risk_fraction, notional_ceiling)
        self._hold = hold_bars
        self._last_ms = -1
        self._last_price_event_ms = -1
        self._target: float | None = None
        self._settlements: set[int] = set()
        self._censored = False
        self.transitions: list[WorkingTransition] = []
        self.wallet: list[PaperWalletPoint] = []

    @property
    def fills(self):
        return tuple(self._engine.fills)

    @property
    def trades(self):
        return tuple(self._engine.trades)

    @property
    def funding(self):
        return tuple(self._engine.funding_charges)

    @property
    def censored(self):
        return self._censored

    def _event(self, ts_ms, mark=None):
        if self._censored:
            raise ValueError("Replay prefix is censored")
        if type(ts_ms) is not int or ts_ms < self._last_ms:
            raise ValueError("Paper event clock moved backwards")
        if mark is not None and not (isfinite(mark) and mark > 0):
            raise ValueError("Expected a causal positive Mark")
        idx = int(np.searchsorted(self._rt.stream.bars.ts_ms, ts_ms, side="right")) - 1
        if idx < 0 or ts_ms >= int(self._rt.stream.bars.ts_ms[idx]) + self._rt.stream.bars.timeframe_ms:
            raise ValueError("Paper event falls outside the declared envelope")
        return idx

    def _record(self, ts_ms, mark):
        self._last_ms = ts_ms
        pos = self._rt.positions[0] if self._rt.positions else None
        order = self._slot.order
        equity = self._engine.cash + self._engine._unrealized({self._rt.stream.symbol: mark})
        self.wallet.append(PaperWalletPoint(ts_ms, self._engine.cash, equity, pos.qty if pos else 0.0,
                                           pos.initial_margin if pos else 0.0, order.reserved_margin if order else 0.0,
                                           order.reserved_fee if order else 0.0))

    def submit(self, intent: WorkingIntent, *, target: float, mark: float):
        self._event(intent.submitted_ms, mark)
        self._check_due_events(intent.submitted_ms)
        side = Side.coerce(intent.side)
        if (not isfinite(target) or target <= 0 or int(side) * (target - intent.limit_price) <= 0
                or abs(round_to_tick(target, self._slot.spec.tick_size) - target) >= 1e-10):
            raise ValueError("Expected a resting target on its executable grid")
        equity = self._engine.cash + self._engine._unrealized({self._rt.stream.symbol: mark})
        used = self._engine._used_margin()
        if self._engine._ruined and not self._engine.sim.allow_trading_after_ruin:
            transition = WorkingTransition(intent.order_id, intent.submitted_ms, "WALLET_RUINED")
        else:
            transition = self._slot.admit(intent, equity=equity, used_margin=used,
                                          available_margin=equity - used, position_open=bool(self._rt.positions))
            if transition.order is not None:
                self._target = target
        self.transitions.append(transition)
        self._record(intent.submitted_ms, mark)
        return transition

    def veto(self, intent: WorkingIntent, *, mark: float) -> WorkingTransition:
        """Record an eligible decision blocked by the frozen arm filter."""
        self._event(intent.submitted_ms, mark)
        self._check_due_events(intent.submitted_ms)
        transition = WorkingTransition(intent.order_id, intent.submitted_ms, "FILTER_VETO")
        self.transitions.append(transition)
        self._record(intent.submitted_ms, mark)
        return transition

    def fill(self, order_id: str, ts_ms: int, *, fill_id: str, qty: float, mark: float,
             last: float, executable_exit: float, protection_attested_ms: int | None = None):
        if self._slot.is_duplicate_fill(order_id, ts_ms, fill_id, qty):
            return WorkingTransition(order_id, ts_ms, "DUPLICATE_FILL", fill_id=fill_id)
        idx = self._event(ts_ms, mark)
        self._require_price_time(ts_ms)
        self._check_due_events(ts_ms, at_timeout_point=True)
        if not all(isfinite(v) and v > 0 for v in (last, executable_exit)):
            raise ValueError("Entry slice needs an executable exit quote for its immediate protection")
        if ts_ms in self._settlements:
            raise ValueError("Funding and fill timestamp tie needs certified chronology")

        def book_position(transition):
            self._engine._apply_reserved_entry_fill(self._rt, transition, target_price=self._target,
                                                    entry_bar_index=idx, max_hold_bars=self._hold)

        if protection_attested_ms is not None and (type(protection_attested_ms) is not int or protection_attested_ms < ts_ms):
            raise ValueError("Attested protection cannot precede the fill it protects")
        transition = self._slot.book_fill(order_id, ts_ms, fill_id=fill_id, qty=qty, book_position=book_position)
        if transition.status != "DUPLICATE_FILL":
            transition = replace(transition, protection_theoretical_ms=ts_ms, protection_attested_ms=protection_attested_ms)
            self.transitions.append(transition)
            self.point(ts_ms, mark=mark, last=last, executable_exit=executable_exit, target_qty=0.0)
        return transition

    def _require_price_time(self, ts_ms: int) -> None:
        if ts_ms <= self._last_price_event_ms:
            raise ValueError("Aggregate or censor same-millisecond price and fill events upstream")

    def point(self, ts_ms: int, *, mark: float, last: float, executable_exit: float, target_qty: float):
        idx = self._event(ts_ms, mark)
        self._require_price_time(ts_ms)
        deadline = self._check_due_events(ts_ms, at_timeout_point=True)
        if not all(isfinite(v) and v > 0 for v in (last, executable_exit)):
            raise ValueError("Expected causal positive Last and exit quote")
        if ts_ms in self._settlements and self._rt.positions:
            raise ValueError("Funding and a price-event tie needs certified chronology")
        if not isfinite(target_qty) or target_qty < 0:
            raise ValueError("Expected nonnegative qualified target capacity")
        if self._rt.positions:
            pos = self._rt.positions[0]
            if 0 < target_qty < pos.qty and ts_ms != deadline:
                raise ValueError("Partial take-profit requires a separately qualified execution path")
            if target_qty >= pos.qty and pos.qty < minimum_executable_qty(self._slot.spec, pos.target_price):
                raise ValueError("Target quantity fails the instrument minimum")
            self._engine._resolve_reserved_position_point(self._rt, pos, ts_ms=ts_ms, mark=mark,
                last=last, executable_exit=executable_exit, target_qualified=target_qty >= pos.qty, bar_index=idx,
                hold_expired=ts_ms == deadline)
            if not self._rt.positions and self._slot.order is not None:
                self.transitions.append(self._slot.cancel(ts_ms, order_id=self._slot.order.intent.order_id))
        self._last_price_event_ms = ts_ms
        self._record(ts_ms, mark)

    def _check_due_events(self, ts_ms, *, at_timeout_point=False, at_expiration=False):
        order = self._slot.order
        if order is not None and (ts_ms > order.intent.expires_ms or (ts_ms == order.intent.expires_ms and not at_expiration)):
            raise ValueError("Process pending expiration at its timestamp before the next event")
        if not self._rt.positions:
            return None
        pos = self._rt.positions[0]
        bars = self._rt.stream.bars
        deadline = int(bars.ts_ms[pos.entry_bar_index]) + self._hold * bars.timeframe_ms
        if ts_ms > deadline or (ts_ms == deadline and not (at_timeout_point or at_expiration)):
            raise ValueError("Missing exact holding deadline event")
        return deadline

    def settle(self, ts_ms: int, *, rate: float, mark: float):
        self._event(ts_ms, mark)
        self._check_due_events(ts_ms)
        if not isfinite(rate) or ts_ms in self._settlements:
            raise ValueError("Invalid or repeated funding settlement")
        if self._engine.fills and self._engine.fills[-1].ts_ms == ts_ms:
            raise ValueError("Funding and fill timestamp tie needs certified chronology")
        self._settlements.add(ts_ms)
        if self._rt.positions:
            self._engine._book_funding(self._rt.positions[0], ts_ms, rate, mark)
        self._record(ts_ms, mark)

    def expire(self, ts_ms: int, *, mark: float):
        self._event(ts_ms, mark)
        self._check_due_events(ts_ms, at_expiration=True)
        transition = self._slot.expire(ts_ms, coverage_confirmed=True)
        self.transitions.append(transition)
        self._record(ts_ms, mark)
        return transition

    def censor(self, ts_ms: int, *, reason: str = "COVERAGE_GAP") -> None:
        """Declare the exposed prefix indeterminate (gap, unorderable tie, unknown remainder).

        An unorderable tie (funding vs fill/exit, fill vs expiry) raises ValueError upstream of any
        booking. The adapter answers by calling this with the reason: the result is explicit, never a
        fabricated fill or exit.
        """
        self._event(ts_ms)
        if self._slot.order is None and not self._rt.positions:
            self._last_ms = ts_ms
            self.transitions.append(WorkingTransition("", ts_ms, "COVERAGE_GAP_FLAT", reason=reason))
            return
        self._check_due_events(ts_ms, at_timeout_point=True, at_expiration=True)
        if self._slot.order is not None:
            self.transitions.append(self._slot.censor(ts_ms, reason=reason))
        else:
            self.transitions.append(WorkingTransition(self._rt.positions[0].meta.get("working_order_id", ""), ts_ms, "CAPTURE_GAP", reason=reason))
        self._last_ms = ts_ms
        self._censored = True

    def exposure_state(self) -> dict:
        """Record whether results end flat, pending, exposed or censored."""
        return {"last_event_ms": self._last_ms, "censored": self._censored,
                "pending_order": self._slot.order, "position_qty": self._rt.positions[0].qty if self._rt.positions else 0.0}
