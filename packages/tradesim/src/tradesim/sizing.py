"""Order sizing, exchange normalisation, and explicit refusal.

Every order that does not become a position leaves a reason code behind. Nothing here
silently resizes an order, silently drops it, or rounds it to zero. If the minimum
executable order breaches the frozen risk cap, the answer is to skip the trade — not to
round up and take more risk than the policy allows (standard section 12.2).
"""

from __future__ import annotations

from dataclasses import dataclass

import math

from .contracts import (
    InstrumentSpec,
    SizingConfig,
    SizingMode,
    SkipReason,
    round_to_step,
)


@dataclass(frozen=True)
class SizingOutcome:
    qty: float
    requested_qty: float
    skip_reason: SkipReason | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.skip_reason is None and self.qty > 0


def minimum_executable_qty(spec: InstrumentSpec, price: float) -> float:
    """``ceil_to_step(max(min_qty, min_notional / price))``."""
    if price <= 0:
        return math.inf
    needed = max(spec.min_qty, spec.min_notional / price)
    return round_to_step(needed, spec.qty_step, "ceil")


def desired_qty(
    *,
    cfg: SizingConfig,
    price: float,
    stop_price: float | None,
    equity: float,
    signal_qty: float | None = None,
    signal_notional: float | None = None,
    signal_risk_fraction: float | None = None,
) -> tuple[float, str]:
    """Raw quantity before any exchange rounding, plus the unit it came from."""
    if signal_qty is not None:
        return float(signal_qty), "signal_qty"
    if signal_notional is not None:
        return float(signal_notional) / price, "signal_notional"

    if cfg.mode == SizingMode.FIXED_QTY:
        return float(cfg.fixed_qty), "fixed_qty"
    if cfg.mode == SizingMode.FIXED_NOTIONAL:
        return float(cfg.fixed_notional) / price, "fixed_notional"

    risk_per_unit = None if stop_price is None else abs(price - stop_price)
    if not risk_per_unit:
        raise ValueError(
            f"sizing mode {cfg.mode.value} needs a stop distance, but the signal has "
            "no usable stop"
        )
    if cfg.mode == SizingMode.RISK_FRACTION:
        frac = signal_risk_fraction if signal_risk_fraction is not None else cfg.risk_fraction
        return (equity * float(frac)) / risk_per_unit, "risk_fraction"
    if cfg.mode == SizingMode.FIXED_RISK_CASH:
        return float(cfg.fixed_risk_cash) / risk_per_unit, "fixed_risk_cash"
    raise ValueError(f"unhandled sizing mode {cfg.mode}")


def normalise_order(
    *,
    raw_qty: float,
    price: float,
    stop_price: float | None,
    equity: float,
    spec: InstrumentSpec,
    cfg: SizingConfig,
) -> SizingOutcome:
    """Apply exchange rules and the frozen risk cap, refusing rather than adjusting."""
    if not math.isfinite(raw_qty) or raw_qty <= 0:
        return SizingOutcome(
            0.0, raw_qty, SkipReason.QTY_ROUNDS_TO_ZERO, "requested quantity is not positive"
        )

    min_qty = minimum_executable_qty(spec, price) * max(1.0, cfg.min_qty_safety_buffer)

    # The risk cap is checked against the SMALLEST order the venue would accept, and it
    # is checked BEFORE rounding. When the venue minimum already over-risks, that is the
    # informative diagnosis; "quantity rounds to zero" would describe the symptom and
    # hide the cause.
    if cfg.max_risk_fraction is not None and stop_price is not None:
        risk_per_unit = abs(price - stop_price)
        cap_cash = equity * float(cfg.max_risk_fraction)
        if risk_per_unit > 0 and min_qty * risk_per_unit > cap_cash + 1e-12:
            return SizingOutcome(
                0.0,
                raw_qty,
                SkipReason.MIN_QTY_EXCEEDS_RISK_CAP,
                f"minimum executable quantity {min_qty:g} risks "
                f"{min_qty * risk_per_unit:.6g} against a frozen cap of {cap_cash:.6g}",
            )

    qty = round_to_step(raw_qty, spec.qty_step, "floor")
    if qty <= 0:
        return SizingOutcome(
            0.0,
            raw_qty,
            SkipReason.QTY_ROUNDS_TO_ZERO,
            f"{raw_qty:g} floors to zero on a step of {spec.qty_step:g}",
        )

    if cfg.max_risk_fraction is not None and stop_price is not None:
        risk_per_unit = abs(price - stop_price)
        cap_cash = equity * float(cfg.max_risk_fraction)
        if risk_per_unit > 0:
            max_qty_by_risk = round_to_step(cap_cash / risk_per_unit, spec.qty_step, "floor")
            if qty > max_qty_by_risk:
                qty = max_qty_by_risk

    if qty < spec.min_qty - 1e-12:
        return SizingOutcome(
            0.0,
            raw_qty,
            SkipReason.BELOW_MIN_QTY,
            f"{qty:g} is below the venue minimum quantity {spec.min_qty:g}",
        )
    if qty > spec.max_qty:
        return SizingOutcome(
            0.0,
            raw_qty,
            SkipReason.ABOVE_MAX_QTY,
            f"{qty:g} exceeds the venue maximum quantity {spec.max_qty:g}",
        )
    notional = qty * price
    if notional < spec.min_notional - 1e-12:
        return SizingOutcome(
            0.0,
            raw_qty,
            SkipReason.BELOW_MIN_NOTIONAL,
            f"notional {notional:.6g} is below the venue minimum {spec.min_notional:g}",
        )

    return SizingOutcome(qty, raw_qty)


def split_legs(
    qty: float, fractions: list[float], spec: InstrumentSpec
) -> tuple[list[float], str | None]:
    """Split a position into partial-exit legs on the quantity step.

    Every leg must be independently executable and the legs must sum to the position.
    If any leg rounds to zero or falls below the venue minimum, the configuration is
    non-deployable and the caller must refuse it — never quietly collapse it into a
    single exit or shift the percentages.
    """
    if not fractions:
        return [qty], None
    legs: list[float] = []
    allocated = 0.0
    for frac in fractions[:-1]:
        leg = round_to_step(qty * float(frac), spec.qty_step, "floor")
        legs.append(leg)
        allocated += leg
    legs.append(round_to_step(qty - allocated, spec.qty_step, "floor"))
    residual = qty - sum(legs)
    if residual > spec.qty_step * 0.5:
        legs[-1] = round_to_step(legs[-1] + residual, spec.qty_step, "floor")
    for i, leg in enumerate(legs):
        if leg <= 0:
            return legs, f"leg {i} rounds to zero on a step of {spec.qty_step:g}"
        if leg < spec.min_qty - 1e-12:
            return legs, f"leg {i} of {leg:g} is below the minimum quantity {spec.min_qty:g}"
    return legs, None
