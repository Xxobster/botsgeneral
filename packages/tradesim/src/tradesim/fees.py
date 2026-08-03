"""Fees on executed notional, per fill.

Bybit's linear/USDT formula is ``Trading Fee = Order Value x Fee Rate`` where
``Order Value = Quantity x Executed Price``. Two consequences the standard spells out
because they are the two things simulators get wrong:

* the open and the close are two separate fees, not one blended round-trip rate;
* slippage changes the executable price and is then multiplied by the rate. It is never
  added into the rate. Charging ``qty * ref_price * (fee + slip)`` overstates the fee and
  understates the price impact, and the two errors do not cancel.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import CostConfig, FeeRole, Liquidity, Side, round_to_tick


@dataclass(frozen=True)
class PricedFill:
    price: float
    ref_price: float
    qty: float
    notional: float
    fee: float
    fee_rate: float
    liquidity: str
    slippage_cost: float


def apply_entry_slippage(ref_price: float, side: Side, costs: CostConfig, tick: float) -> float:
    """Move an entry fill adversely: a long pays up, a short sells down."""
    slip = costs.effective_entry_slippage
    price = ref_price * (1.0 + int(side) * slip) if slip else ref_price
    if tick > 0:
        # Round away from the trader, so rounding never manufactures a better entry.
        price = round_to_tick(price, tick, "ceil" if int(side) > 0 else "floor")
    return price


def resolve_limit_entry_price(
    *,
    ref_price: float,
    side: Side,
    tick: float,
    limit_price: float | None = None,
    limit_offset: float | None = None,
) -> float:
    """Passive limit price for a Post-Only style entry.

    Absolute ``limit_price`` wins. Else ``limit_offset`` is a non-negative fraction
    placed on the *passive* side of ``ref_price`` (long buys below, short sells above).
    Both omitted → limit equals the reference (rest at the entry reference price).
    """
    if limit_price is not None:
        price = float(limit_price)
    elif limit_offset is not None:
        off = abs(float(limit_offset))
        # Long: buy below ref; short: sell above ref.
        price = float(ref_price) * (1.0 - int(side) * off)
    else:
        price = float(ref_price)
    if tick > 0:
        # Round passively (never make the limit more aggressive).
        price = round_to_tick(price, tick, "floor" if int(side) > 0 else "ceil")
    return price


def limit_entry_would_cross(*, side: Side, ref_price: float, limit_price: float) -> bool:
    """True when a buy limit is at/above the reference or a sell limit at/below it."""
    if int(side) > 0:
        return float(limit_price) > float(ref_price) + 1e-15
    return float(limit_price) < float(ref_price) - 1e-15


def limit_entry_touched(*, side: Side, bar_high: float, bar_low: float, limit_price: float) -> bool:
    """Whether the entry bar's range reaches a resting limit."""
    if int(side) > 0:
        return float(bar_low) <= float(limit_price) + 1e-12
    return float(bar_high) >= float(limit_price) - 1e-12


def price_fill(
    *,
    role: FeeRole | str,
    qty: float,
    price: float,
    ref_price: float,
    costs: CostConfig,
    liquidity: Liquidity | None = None,
) -> PricedFill:
    liq = costs.liquidity_for(role) if liquidity is None else liquidity
    rate = costs.rate_for(role, liquidity=liq)
    notional = abs(qty * price)
    return PricedFill(
        price=float(price),
        ref_price=float(ref_price),
        qty=float(qty),
        notional=notional,
        fee=notional * rate,
        fee_rate=rate,
        liquidity=liq.value if isinstance(liq, Liquidity) else str(liq),
        slippage_cost=abs(qty) * abs(price - ref_price),
    )


def round_trip_cost_estimate(costs: CostConfig) -> float:
    """Diagnostic only: entry slip plus two taker fees, in return units.

    Never use this in place of per-branch net-of-fee magnitudes when turning a
    probability into a trade (standard section 9.5). It exists so a report can print the
    number a reader expects to see, clearly labelled as an approximation.
    """
    return costs.effective_entry_slippage + 2.0 * costs.taker_rate
