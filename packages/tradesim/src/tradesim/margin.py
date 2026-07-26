"""Leverage, initial and maintenance margin, and the liquidation price.

The liquidation price is solved, not approximated. For a position of ``qty`` opened at
``entry`` with ``margin`` posted, liquidation is the price ``P`` where the position's
equity has fallen to its maintenance requirement::

    equity(P)      = margin + side * qty * (P - entry) - close_fee(P)
    maintenance(P) = qty * P * mm_rate - deduction

Setting them equal and solving:

    long : P = (qty*entry - margin - deduction) / (qty * (1 - mm_rate - fee_rate))
    short: P = (qty*entry + margin + deduction) / (qty * (1 + mm_rate + fee_rate))

With no fee and no tier deduction this reduces to the familiar
``entry * (1 - 1/leverage + mm_rate)`` to first order, but it keeps the fee to close and
the venue's tier deduction, which the shorthand silently drops.

``1 / leverage`` distance and OHLC-distance proxies are not deployment evidence
(standard section 13.3). Which of those a run actually used is reported as the
liquidation status, and it is never a silent pass.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .contracts import (
    InstrumentSpec,
    LiquidationStatus,
    MaintenanceTier,
    MarginConfig,
    MarginMode,
    Side,
    round_to_tick,
)


class MarginError(ValueError):
    """Raised when a margin configuration cannot be satisfied at all."""


@dataclass(frozen=True)
class MarginState:
    leverage: float
    initial_margin: float
    maintenance_rate: float
    maintenance_deduction: float
    liquidation_price: float | None
    tier: MaintenanceTier
    status: LiquidationStatus


def leverage_from_stop(
    entry_price: float,
    stop_price: float,
    cfg: MarginConfig,
    spec: InstrumentSpec,
) -> float:
    """Lowest operational leverage that keeps liquidation beyond the stop.

    ``floor(1 / (stop_pct + maintenance_buffer + mark_buffer))``, capped by the venue
    limit. This is a starting point, not a licence: the caller still has to check the
    solved liquidation price against the stop, because the shorthand ignores fees and
    tier deductions.
    """
    if entry_price <= 0:
        raise MarginError("entry price must be positive")
    stop_pct = abs(entry_price - stop_price) / entry_price
    denom = stop_pct + cfg.maintenance_buffer + cfg.mark_buffer
    if denom <= 0:
        return float(spec.max_leverage)
    lev = math.floor(1.0 / denom)
    return float(max(1.0, min(lev, spec.max_leverage)))


def liquidation_price(
    *,
    side: Side,
    entry_price: float,
    qty: float,
    posted_margin: float,
    mm_rate: float,
    deduction: float = 0.0,
    close_fee_rate: float = 0.0,
    tick_size: float = 0.0,
) -> float | None:
    """Solve for the price at which equity meets the maintenance requirement."""
    if qty <= 0 or entry_price <= 0:
        return None
    sign = int(side)
    if sign > 0:
        denom = qty * (1.0 - mm_rate - close_fee_rate)
        if denom <= 0:
            return None
        price = (qty * entry_price - posted_margin - deduction) / denom
        if price <= 0:
            return None  # cannot be liquidated by price alone at this margin
        # Round toward the entry so the modelled liquidation triggers no later than the
        # real one.
        return round_to_tick(price, tick_size, "ceil") if tick_size else price
    denom = qty * (1.0 + mm_rate + close_fee_rate)
    price = (qty * entry_price + posted_margin + deduction) / denom
    if price <= 0:
        return None
    return round_to_tick(price, tick_size, "floor") if tick_size else price


def build_margin_state(
    *,
    side: Side,
    entry_price: float,
    qty: float,
    stop_price: float | None,
    spec: InstrumentSpec,
    cfg: MarginConfig,
    close_fee_rate: float,
    wallet_available: float,
    has_mark_series: bool,
) -> MarginState:
    notional = abs(qty * entry_price)
    if cfg.leverage is not None:
        leverage = float(min(cfg.leverage, spec.max_leverage))
    elif stop_price is not None:
        leverage = leverage_from_stop(entry_price, stop_price, cfg, spec)
    else:
        raise MarginError(
            "leverage is not configured and there is no stop to derive it from; "
            "set MarginConfig.leverage explicitly rather than guessing"
        )
    if leverage <= 0:
        raise MarginError("leverage must be positive")

    tier = spec.tier_for_notional(notional)
    leverage = float(min(leverage, tier.max_leverage))
    mm_rate = tier.mm_rate
    deduction = tier.deduction

    initial_margin = notional / leverage
    fee_rate = close_fee_rate if cfg.include_close_fee_in_liquidation else 0.0

    # Isolated risks only the margin posted to this position. Cross risks whatever the
    # wallet can still absorb, so the liquidation sits further away.
    posted = initial_margin if cfg.mode == MarginMode.ISOLATED else max(
        initial_margin, wallet_available
    )

    liq = liquidation_price(
        side=side,
        entry_price=entry_price,
        qty=qty,
        posted_margin=posted,
        mm_rate=mm_rate,
        deduction=deduction,
        close_fee_rate=fee_rate,
        tick_size=spec.tick_size,
    )

    if liq is None:
        status = LiquidationStatus.UNKNOWN
    elif spec.tiers_available and has_mark_series:
        status = LiquidationStatus.MODELLED
    else:
        status = LiquidationStatus.SIMPLIFIED

    return MarginState(
        leverage=leverage,
        initial_margin=initial_margin,
        maintenance_rate=mm_rate,
        maintenance_deduction=deduction,
        liquidation_price=liq,
        tier=tier,
        status=status,
    )


def stop_is_inside_liquidation(
    side: Side, stop_price: float | None, liq_price: float | None
) -> bool:
    """True when the stop would be reached before liquidation on a continuous path."""
    if stop_price is None or liq_price is None:
        return True
    return int(side) * stop_price > int(side) * liq_price


def maintenance_margin(qty: float, price: float, tier: MaintenanceTier) -> float:
    return max(0.0, abs(qty * price) * tier.mm_rate - tier.deduction)


def worst_status(statuses) -> LiquidationStatus:
    """The least reassuring status in a run, so a report cannot quote the best one."""
    rank = {
        LiquidationStatus.MODELLED: 0,
        LiquidationStatus.SIMPLIFIED: 1,
        LiquidationStatus.UNKNOWN: 2,
    }
    seen = list(statuses)
    if not seen:
        return LiquidationStatus.UNKNOWN
    return max(seen, key=lambda s: rank[s])
