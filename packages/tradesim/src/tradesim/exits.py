"""THE shared exit-resolution function.

Exactly one function decides what a bar does to an open position, and it is called for
the entry bar and for every later bar. There is no separate entry-bar code path, and
``resolve_bar`` cannot even tell which kind of bar it is looking at — it takes a set of
protective levels and a price path, and says what happened. The engine labels the result
afterwards.

That structural choice is deliberate. The defect this package exists to prevent is a bar
loop that opens a position and then begins exit checking on the *following* bar. The way
to make that defect unwritable is to leave nowhere to write it.

Intrabar chronology (standard section 10). An OHLC candle does not reveal whether its
high or its low came first. This module therefore works from the bar's open, which is the
one price whose position in the path is known:

1. Any level the OPEN is already through was crossed by the gap. The most adverse of them
   resolves, filled at the open (or worse), and it is flagged as gapped.
2. Otherwise the path starts inside every level. Only the NEAREST adverse level can be
   reached first, so a deeper liquidation cannot pre-empt a shallower stop on a
   continuous path — which is exactly the invariant standard section 13.4 requires.
3. If the nearest adverse level and the nearest target are both inside the bar, the bar
   is ambiguous. With lower-timeframe bars the ambiguity is settled by replaying them
   through this same function; without them the adverse branch is taken and the trade is
   labelled so its frequency and PnL sensitivity can be reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, Sequence

from .contracts import (
    REASON_BREAK_EVEN,
    REASON_LIQUIDATION,
    REASON_STOP,
    REASON_TARGET,
    REASON_TRAILING,
    Bar,
    BreakEvenConfig,
    SameBarPolicy,
    Side,
    TrailConfig,
    round_to_tick,
)


class AmbiguousBarError(RuntimeError):
    """Raised when the same-bar policy is RAISE and a bar contains both outcomes."""


@dataclass(frozen=True)
class TargetLevel:
    label: str
    price: float
    qty_fraction: float


@dataclass(frozen=True)
class ProtectiveLevels:
    """The levels that are live for a position at the START of a bar."""

    side: Side
    entry_price: float
    stop: float | None = None
    stop_reason: str = REASON_STOP
    liquidation: float | None = None
    targets: tuple[TargetLevel, ...] = ()

    @property
    def sign(self) -> int:
        return int(self.side)


@dataclass(frozen=True)
class ExitEvent:
    reason: str
    price: float
    ts_ms: int
    qty_fraction: float
    label: str = ""
    gapped: bool = False
    terminal: bool = True


@dataclass(frozen=True)
class ExitPolicy:
    same_bar: SameBarPolicy = SameBarPolicy.ADVERSE
    take_profit_is_limit: bool = True
    stop_is_stop_market: bool = False
    market_exit_slippage: float = 0.0
    tick_size: float = 0.0


@dataclass
class BarResolution:
    events: list[ExitEvent] = field(default_factory=list)
    terminal: bool = False
    ambiguous: bool = False
    resolved_by_touch: bool = False
    high: float = float("-inf")
    low: float = float("inf")

    @property
    def closed(self) -> bool:
        return self.terminal


# --------------------------------------------------------------------------------------
# Single-bar resolution
# --------------------------------------------------------------------------------------


def _adverse_reached_at(price: float, level: float, sign: int) -> bool:
    """True when ``price`` is at or beyond ``level`` in the losing direction."""
    return price <= level if sign > 0 else price >= level


def _favourable_reached_at(price: float, level: float, sign: int) -> bool:
    return price >= level if sign > 0 else price <= level


def _fill_price(raw: float, sign: int, slip: float, tick: float) -> float:
    """Move a fill adversely by ``slip`` and put it back on the tick grid."""
    price = raw * (1.0 - sign * slip) if slip else raw
    if tick > 0:
        price = round_to_tick(price, tick, "floor" if sign > 0 else "ceil")
    return price


def resolve_bar(
    levels: ProtectiveLevels,
    bar: Bar,
    *,
    policy: ExitPolicy,
    touch_bars: Sequence[Bar] | None = None,
) -> BarResolution:
    """Decide what this bar does to the position described by ``levels``.

    ``touch_bars`` are lower-timeframe bars covering this bar's window; when present the
    bar is replayed through this same function sub-bar by sub-bar, which resolves every
    ordering question with data instead of with a convention.
    """
    if touch_bars:
        return _resolve_with_touch(levels, touch_bars, policy)

    res = BarResolution(high=bar.high, low=bar.low)
    sign = levels.sign

    # --- 1. levels the open is already through -------------------------------------
    gapped_adverse = _adverse_levels(levels)
    crossed = [
        (price, reason)
        for price, reason in gapped_adverse
        if _adverse_reached_at(bar.open, price, sign)
    ]
    if crossed:
        # The most adverse level wins: if the open is already past both the stop and the
        # liquidation, the position was liquidated, not stopped.
        price, reason = min(crossed, key=lambda pr: sign * pr[0])
        raw = bar.open if _adverse_reached_at(bar.open, price, sign) else price
        if reason == REASON_LIQUIDATION:
            raw = bar.open if sign * bar.open < sign * price else price
        elif not policy.stop_is_stop_market:
            raw = price  # a genuine stop-limit rests at its level
        fill = _fill_price(raw, sign, policy.market_exit_slippage, policy.tick_size)
        res.events.append(
            ExitEvent(reason, fill, bar.ts_ms, 1.0, gapped=True, terminal=True)
        )
        res.terminal = True
        return res

    targets = _sorted_targets(levels)
    crossed_targets = [
        t for t in targets if _favourable_reached_at(bar.open, t.price, sign)
    ]
    if crossed_targets:
        _fill_targets(res, crossed_targets, levels, bar, policy, gapped=True)
        if res.terminal:
            return res

    # --- 2. nearest adverse level on a continuous path ------------------------------
    remaining = [t for t in targets if t not in crossed_targets]
    nearest_adverse = _nearest_adverse(levels, bar.open)
    adverse_hit = nearest_adverse is not None and _adverse_reached_at(
        bar.low if sign > 0 else bar.high, nearest_adverse[0], sign
    )
    next_target = remaining[0] if remaining else None
    target_hit = next_target is not None and _favourable_reached_at(
        bar.high if sign > 0 else bar.low, next_target.price, sign
    )

    if adverse_hit and target_hit:
        res.ambiguous = True
        if policy.same_bar == SameBarPolicy.RAISE:
            raise AmbiguousBarError(
                f"bar {bar.ts_ms} contains both {nearest_adverse[1]} at "
                f"{nearest_adverse[0]} and {next_target.label} at {next_target.price}; "
                "supply touch_bars or choose a same-bar policy"
            )
        if policy.same_bar == SameBarPolicy.ADVERSE:
            target_hit = False
        else:
            adverse_hit = False

    if adverse_hit:
        price, reason = nearest_adverse
        slip = policy.market_exit_slippage if policy.stop_is_stop_market else 0.0
        if reason == REASON_LIQUIDATION:
            slip = policy.market_exit_slippage
        fill = _fill_price(price, sign, slip, policy.tick_size)
        res.events.append(ExitEvent(reason, fill, bar.ts_ms, 1.0, terminal=True))
        res.terminal = True
        return res

    if target_hit:
        hit = [
            t
            for t in remaining
            if _favourable_reached_at(bar.high if sign > 0 else bar.low, t.price, sign)
        ]
        _fill_targets(res, hit, levels, bar, policy, gapped=False)

    return res


def _fill_targets(
    res: BarResolution,
    hits: Iterable[TargetLevel],
    levels: ProtectiveLevels,
    bar: Bar,
    policy: ExitPolicy,
    *,
    gapped: bool,
) -> None:
    sign = levels.sign
    hit_labels = {leg.label for leg in hits}
    for leg in hits:
        if policy.take_profit_is_limit:
            # A resting limit fills at its own price. A favourable gap does not hand it
            # a better price, and it never slips.
            fill = leg.price
        else:
            fill = _fill_price(
                leg.price, sign, policy.market_exit_slippage, policy.tick_size
            )
        res.events.append(
            ExitEvent(
                REASON_TARGET,
                fill,
                bar.ts_ms,
                leg.qty_fraction,
                label=leg.label,
                gapped=gapped,
                terminal=False,
            )
        )
    # The position is exhausted when no take-profit leg is left standing. Counting the
    # fractions filled on THIS bar would miss legs filled on earlier bars, which is how a
    # multi-leg plan ends up limping to the end of the data with a dust position.
    if not [t for t in levels.targets if t.label not in hit_labels]:
        res.terminal = True
        if res.events:
            res.events[-1] = replace(res.events[-1], terminal=True)


def _adverse_levels(levels: ProtectiveLevels) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    if levels.stop is not None:
        out.append((levels.stop, levels.stop_reason))
    if levels.liquidation is not None:
        out.append((levels.liquidation, REASON_LIQUIDATION))
    return out


def _nearest_adverse(
    levels: ProtectiveLevels, path_start: float
) -> tuple[float, str] | None:
    sign = levels.sign
    candidates = [
        (price, reason)
        for price, reason in _adverse_levels(levels)
        if sign * price < sign * path_start
    ]
    if not candidates:
        return None
    # Nearest in the adverse direction: the highest level for a long, lowest for a short.
    return max(candidates, key=lambda pr: sign * pr[0])


def _sorted_targets(levels: ProtectiveLevels) -> list[TargetLevel]:
    sign = levels.sign
    return sorted(levels.targets, key=lambda t: sign * t.price)


def _resolve_with_touch(
    levels: ProtectiveLevels,
    touch_bars: Sequence[Bar],
    policy: ExitPolicy,
) -> BarResolution:
    """Replay a decision bar's lower-timeframe path through the same resolver."""
    aggregate = BarResolution(resolved_by_touch=True)
    current = levels
    for sub in touch_bars:
        aggregate.high = max(aggregate.high, sub.high)
        aggregate.low = min(aggregate.low, sub.low)
        step = resolve_bar(current, sub, policy=policy)
        aggregate.ambiguous = aggregate.ambiguous or step.ambiguous
        for event in step.events:
            aggregate.events.append(event)
        if step.terminal:
            aggregate.terminal = True
            break
        if step.events:
            filled = {e.label for e in step.events if e.reason == REASON_TARGET}
            current = replace(
                current,
                targets=tuple(t for t in current.targets if t.label not in filled),
            )
    return aggregate


# --------------------------------------------------------------------------------------
# Level maintenance between bars
# --------------------------------------------------------------------------------------


def update_protective_levels(
    levels: ProtectiveLevels,
    *,
    high: float,
    low: float,
    trail: TrailConfig | None,
    break_even: BreakEvenConfig | None,
    break_even_armed: bool,
    legs_filled: int,
    tick_size: float,
) -> tuple[ProtectiveLevels, bool]:
    """Apply trailing and break-even using a bar's extremes, for use from the NEXT bar.

    Standard section 10: never activate break-even before the fill that triggers it, and
    never let a trailing stop use a future high or low from the candle it is resolving.
    So this runs only after a bar has been resolved without closing the position, and its
    output is what the following bar sees. Lower-timeframe replay gets the tighter answer
    for free, because each sub-bar is resolved and then updates the next.
    """
    sign = levels.sign
    stop = levels.stop
    reason = levels.stop_reason
    extreme = high if sign > 0 else low

    if break_even is not None and not break_even_armed:
        armed = False
        if break_even.trigger_price is not None:
            armed = _favourable_reached_at(extreme, break_even.trigger_price, sign)
        elif break_even.trigger_offset is not None:
            trigger = levels.entry_price * (1.0 + sign * break_even.trigger_offset)
            armed = _favourable_reached_at(extreme, trigger, sign)
        elif break_even.trigger_on_leg is not None:
            armed = legs_filled > break_even.trigger_on_leg
        if armed:
            be_stop = levels.entry_price * (1.0 + sign * break_even.stop_offset)
            be_stop = round_to_tick(be_stop, tick_size, "nearest") if tick_size else be_stop
            if stop is None or sign * be_stop > sign * stop:
                stop, reason = be_stop, REASON_BREAK_EVEN
            break_even_armed = True

    if trail is not None:
        active = True
        if trail.activation_offset is not None:
            activation = levels.entry_price * (1.0 + sign * trail.activation_offset)
            active = _favourable_reached_at(extreme, activation, sign)
        if active:
            candidate = extreme * (1.0 - sign * trail.distance)
            if tick_size:
                candidate = round_to_tick(candidate, tick_size, "nearest")
            improvement = 0.0 if stop is None else sign * (candidate - stop)
            if stop is None or improvement > max(trail.step, 0.0):
                stop = candidate
                reason = REASON_TRAILING

    if stop == levels.stop and reason == levels.stop_reason:
        return levels, break_even_armed
    return replace(levels, stop=stop, stop_reason=reason), break_even_armed


def resolve_bar_exit(
    side: Side | int,
    stop: float | None,
    target: float | None,
    liq: float | None,
    bar: Bar,
    *,
    entry_price: float | None = None,
    touch_bars: Sequence[Bar] | None = None,
    policy: ExitPolicy | None = None,
) -> ExitEvent | None:
    """Single-target convenience wrapper over :func:`resolve_bar`.

    Kept because it is the smallest possible way to ask the question, and because a
    foreign adapter can call it directly.
    """
    s = Side.coerce(side)
    levels = ProtectiveLevels(
        side=s,
        entry_price=float(entry_price if entry_price is not None else bar.open),
        stop=stop,
        liquidation=liq,
        targets=((TargetLevel("tp", float(target), 1.0),) if target is not None else ()),
    )
    res = resolve_bar(levels, bar, policy=policy or ExitPolicy(), touch_bars=touch_bars)
    return res.events[-1] if res.terminal and res.events else None
