"""Market structure labels from confirmed alternating swings.

Compares consecutive same-kind swings:
- high vs prior high → HH / LH
- low vs prior low → HL / LL

Also builds legs between consecutive opposite swings and classifies
impulse vs correction from the prevailing HH/HL or LH/LL bias.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .fibonacci import FIB_RETRACEMENT, nearest_fib, retracement_ratio
from .swings import Swing

# label_by_swing was unused — removed


@dataclass(frozen=True)
class StructureEvent:
    event_id: int
    label: str  # HH|HL|LH|LL|SH|SL
    swing_id: int
    prev_swing_id: int | None
    ts_ms: int  # confirmation time (when label is known)
    pivot_ts_ms: int
    price: float


@dataclass(frozen=True)
class Leg:
    leg_id: int
    direction: str  # up|down
    start_swing_id: int
    end_swing_id: int
    start_ts_ms: int
    end_ts_ms: int
    start_price: float
    end_price: float
    length_abs: float
    length_pct: float
    kind: str  # impulse|correction|unknown
    retrace_pct: float  # how deep the *next* opposite leg retraced this one
    fib_ratio: float
    fib_label: str


def label_structure(swings: list[Swing]) -> list[StructureEvent]:
    """Emit structure labels at each swing's confirmation time."""
    events: list[StructureEvent] = []
    last_high: Swing | None = None
    last_low: Swing | None = None
    eid = 0
    for s in swings:
        if s.kind == "high":
            if last_high is None:
                label = "SH"  # first swing high
                prev_id = None
            else:
                label = "HH" if s.price > last_high.price else "LH"
                prev_id = last_high.swing_id
            events.append(
                StructureEvent(
                    event_id=eid,
                    label=label,
                    swing_id=s.swing_id,
                    prev_swing_id=prev_id,
                    ts_ms=s.confirm_ts_ms,
                    pivot_ts_ms=s.pivot_ts_ms,
                    price=s.price,
                )
            )
            eid += 1
            last_high = s
        else:
            if last_low is None:
                label = "SL"
                prev_id = None
            else:
                label = "HL" if s.price > last_low.price else "LL"
                prev_id = last_low.swing_id
            events.append(
                StructureEvent(
                    event_id=eid,
                    label=label,
                    swing_id=s.swing_id,
                    prev_swing_id=prev_id,
                    ts_ms=s.confirm_ts_ms,
                    pivot_ts_ms=s.pivot_ts_ms,
                    price=s.price,
                )
            )
            eid += 1
            last_low = s
    return events


def build_legs(
    swings: list[Swing],
    events: list[StructureEvent],
) -> list[Leg]:
    """Legs between consecutive opposite-kind confirmed swings + fib retrace of next leg."""
    if len(swings) < 2:
        return []

    # Alternate filter: keep chronological swings but pair opposite kinds only.
    ordered = sorted(swings, key=lambda s: (s.pivot_i, s.confirm_i))

    # Bias from recent structure: +1 bullish (HH/HL), -1 bearish (LH/LL).
    def bias_at(swing_id: int) -> int:
        # Look at labels up to and including this swing.
        bull = bear = 0
        for e in events:
            if e.swing_id > swing_id:
                break
            if e.label in ("HH", "HL"):
                bull += 1
            elif e.label in ("LH", "LL"):
                bear += 1
        if bull > bear:
            return 1
        if bear > bull:
            return -1
        return 0

    raw: list[dict] = []
    prev: Swing | None = None
    for s in ordered:
        if prev is None:
            prev = s
            continue
        if s.kind == prev.kind:
            # Same kind twice: replace prev if this pivot is more extreme in time order
            # (structure already labelled; legs need opposite anchors).
            prev = s
            continue
        direction = "up" if s.price > prev.price else "down"
        length_abs = abs(s.price - prev.price)
        mid = 0.5 * (abs(s.price) + abs(prev.price))
        length_pct = length_abs / mid if mid > 0 else float("nan")
        b = bias_at(s.swing_id)
        if b > 0:
            kind = "impulse" if direction == "up" else "correction"
        elif b < 0:
            kind = "impulse" if direction == "down" else "correction"
        else:
            kind = "unknown"
        raw.append(
            {
                "direction": direction,
                "start": prev,
                "end": s,
                "length_abs": length_abs,
                "length_pct": length_pct,
                "kind": kind,
            }
        )
        prev = s

    legs: list[Leg] = []
    for i, row in enumerate(raw):
        retrace = float("nan")
        fib_r = float("nan")
        fib_lab = ""
        if i + 1 < len(raw):
            nxt = raw[i + 1]
            # Next leg starts at this leg's end and ends at next opposite swing.
            retrace = retracement_ratio(
                row["start"].price, row["end"].price, nxt["end"].price
            )
            # For a down follow-through after up, ratio is positive in [0,1+] when C is between B and A.
            fib_r, fib_lab, _ = nearest_fib(abs(retrace), FIB_RETRACEMENT)
        legs.append(
            Leg(
                leg_id=i,
                direction=row["direction"],
                start_swing_id=row["start"].swing_id,
                end_swing_id=row["end"].swing_id,
                start_ts_ms=row["start"].pivot_ts_ms,
                end_ts_ms=row["end"].pivot_ts_ms,
                start_price=row["start"].price,
                end_price=row["end"].price,
                length_abs=float(row["length_abs"]),
                length_pct=float(row["length_pct"]),
                kind=row["kind"],
                retrace_pct=float(retrace) if np.isfinite(retrace) else float("nan"),
                fib_ratio=fib_r,
                fib_label=fib_lab,
            )
        )
    return legs


def structure_frame(events: list[StructureEvent]) -> pd.DataFrame:
    if not events:
        return pd.DataFrame(
            columns=[
                "event_id",
                "label",
                "swing_id",
                "prev_swing_id",
                "ts_ms",
                "pivot_ts_ms",
                "price",
            ]
        )
    return pd.DataFrame(
        [
            {
                "event_id": e.event_id,
                "label": e.label,
                "swing_id": e.swing_id,
                "prev_swing_id": e.prev_swing_id,
                "ts_ms": e.ts_ms,
                "pivot_ts_ms": e.pivot_ts_ms,
                "price": e.price,
            }
            for e in events
        ]
    )


def legs_frame(legs: list[Leg]) -> pd.DataFrame:
    if not legs:
        return pd.DataFrame(
            columns=[
                "leg_id",
                "direction",
                "start_swing_id",
                "end_swing_id",
                "start_ts_ms",
                "end_ts_ms",
                "start_price",
                "end_price",
                "length_abs",
                "length_pct",
                "kind",
                "retrace_pct",
                "fib_ratio",
                "fib_label",
            ]
        )
    return pd.DataFrame(
        [
            {
                "leg_id": lg.leg_id,
                "direction": lg.direction,
                "start_swing_id": lg.start_swing_id,
                "end_swing_id": lg.end_swing_id,
                "start_ts_ms": lg.start_ts_ms,
                "end_ts_ms": lg.end_ts_ms,
                "start_price": lg.start_price,
                "end_price": lg.end_price,
                "length_abs": lg.length_abs,
                "length_pct": lg.length_pct,
                "kind": lg.kind,
                "retrace_pct": lg.retrace_pct,
                "fib_ratio": lg.fib_ratio,
                "fib_label": lg.fib_label,
            }
            for lg in legs
        ]
    )
