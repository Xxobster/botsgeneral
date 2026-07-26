"""Grade ``xgb``'s audit-v4 ``ThresholdExecutionSim`` against the conformance pack.

Engine: ``C:\\projects\\xgb\\utils\\audit_v4\\execution_sim.py``.

Shape of the translation:

* The engine wants percentage brackets computed from its own fill, so the adapter derives
  the percentages that land exactly on the fixture's absolute stop and target.
* It wants an instrument from its own static venue table, so the adapter registers the
  fixture's instrument under the fixture's symbol before the run.
* It expresses slippage in percent (``0.15`` meaning 0.15%), so rates are multiplied by
  one hundred on the way in.
* Its ``pnl`` is already net of fees and funding, so ``gross_pnl`` is reconstructed from
  the prices rather than read off the trade.

Run with::

    tradesim-conformance --engine xgb_adapter:build --tests <xgb tests, if any>
"""

from __future__ import annotations

from typing import Any

from tradesim.conformance.adapter import NormalisedResult, NormalisedTrade
from tradesim.conformance.fixture_loader import Fixture

from _common import (
    ENTRY_BAR_SUFFIX,
    XGB_ROOT,
    Case,
    ensure_path,
    normalised,
    unsupported_reason,
)

CAPABILITIES = ("touch", "funding", "liquidation", "max_hold")

#: xgb reason strings mapped onto the shared vocabulary.
REASONS = {
    "sl": "stop",
    "tp": "target",
    "max_hold": "max_hold",
    "liquidation": "liquidation",
    "eod_flat": "end_of_data",
}


class XgbAdapter:
    name = "xgb.audit_v4.ThresholdExecutionSim"
    version = "audit_v4"

    def __init__(self, contract: str = "perp_bracket_portfolio") -> None:
        self.contract = contract
        ensure_path(XGB_ROOT)

    def supports(self, fixture: Fixture) -> tuple[bool, str]:
        why = unsupported_reason(fixture, capabilities=CAPABILITIES)
        if why:
            return False, why
        case = Case(fixture.payload)
        if not case.has_stop():
            return False, "engine requires a stop; it has no unbracketed mode"
        if str(case.sizing.get("mode")) != "fixed_qty":
            return False, "engine sizes by a fixed quantity only"
        return True, ""

    def run_fixture(self, fixture: Fixture) -> NormalisedResult:
        import pandas as pd

        from utils.audit_v4 import venue
        from utils.audit_v4.execution_sim import ThresholdExecutionSim

        case = Case(fixture.payload)
        _register_instrument(venue, case)

        index = pd.to_datetime([int(r[0]) for r in case.bars], unit="ms", utc=True)
        ohlcv = pd.DataFrame(
            {
                "open": [float(r[1]) for r in case.bars],
                "high": [float(r[2]) for r in case.bars],
                "low": [float(r[3]) for r in case.bars],
                "close": [float(r[4]) for r in case.bars],
            },
            index=index,
        )
        signals = pd.Series(0, index=index, dtype=int)
        signals.iloc[case.bar_index_of(int(case.signal["ts_ms"]))] = int(case.signal["side"])

        funding = None
        if case.funding:
            funding = pd.Series(
                [float(r[1]) for r in case.funding],
                index=pd.to_datetime([int(r[0]) for r in case.funding], unit="ms", utc=True),
            )

        ltf = None
        if case.touch_rows:
            ltf = pd.DataFrame(
                {
                    "open": [float(r[1]) for r in case.touch_rows],
                    "high": [float(r[2]) for r in case.touch_rows],
                    "low": [float(r[3]) for r in case.touch_rows],
                    "close": [float(r[4]) for r in case.touch_rows],
                },
                index=pd.to_datetime(
                    [int(r[0]) for r in case.touch_rows], unit="ms", utc=True
                ),
            )

        tp_frac, sl_frac = case.bracket_fracs()
        sim = ThresholdExecutionSim(
            case.symbol,
            commission=case.taker,
            entry_slip_pct=case.entry_slip * 100.0,
            exit_slip_pct=0.0,
            market_exit_slip_pct=case.market_exit_slip * 100.0,
            leverage=case.leverage,
            fixed_qty=case.qty(),
            initial_cash=case.starting_equity,
            allow_simplified_mm=True,
            adverse_ambiguous=True,
        )
        hold = case.max_hold_bars()
        result = sim.run(
            ohlcv,
            signals,
            tp_pct=tp_frac,
            sl_pct=sl_frac,
            # The engine treats 0 as "no timeout"; the fixtures that omit a hold limit
            # mean the same thing, and a very large number expresses it without a branch.
            max_hold_bars=hold if hold is not None else 10**9,
            funding=funding,
            ltf_ohlcv=ltf,
        )

        raw_open = float(case.bars[case.entry_bar_index()][1])
        trades = [_trade(t, case, raw_open, result.fills) for t in result.trades]
        ending = (
            float(result.equity_curve.iloc[-1])
            if len(result.equity_curve)
            else case.starting_equity
        )
        return normalised(
            trades,
            starting_equity=case.starting_equity,
            ending_equity=ending,
            # The venue table carries no maintenance tiers, and the engine is run with
            # allow_simplified_mm, so its liquidation price is an approximation.
            liquidation_status="SIMPLIFIED",
            n_funding_charges=len(result.funding_events),
            # The engine records a cash fee, not the rate it used; the rate is recovered
            # from the fill so the maker-versus-taker question can still be asked of it.
            fill_rates=[
                float(f.fee) / abs(float(f.qty) * float(f.price)) for f in result.fills
            ],
        )


def _register_instrument(venue: Any, case: Case) -> None:
    """Teach the engine's static venue table about the fixture's instrument."""
    spec = venue.InstrumentSpec(
        symbol=case.symbol.lower(),
        tick_size=case.tick,
        qty_step=float(case.instrument["qty_step"]),
        min_qty=float(case.instrument["min_qty"]),
        min_notional=float(case.instrument["min_notional"]),
        mm_rate=float(case.instrument["maintenance_rate"]),
        max_leverage=float(case.instrument["max_leverage"]),
        tiers_available=False,
    )
    venue._INSTRUMENTS[case.symbol.lower()] = spec


def _trade(t: Any, case: Case, raw_open: float, fills: list[Any]) -> NormalisedTrade:
    side = 1 if t.side == "long" else -1
    entry_px = float(t.entry_px)
    exit_px = float(t.exit_px) if t.exit_px is not None else float("nan")
    qty = float(t.qty)
    entry_ms = int(t.entry_ts.value // 1_000_000)
    exit_ms = int(t.exit_ts.value // 1_000_000) if t.exit_ts is not None else 0
    entry_bar = exit_ms == entry_ms
    reason = REASONS.get(str(t.exit_reason), str(t.exit_reason))
    mine = [f for f in fills if f.trade_id == t.trade_id]
    entry_fee = sum(float(f.fee) for f in mine if f.reason == "entry")
    exit_fee = sum(float(f.fee) for f in mine if f.reason != "entry")
    return NormalisedTrade(
        symbol=case.symbol,
        side=side,
        entry_ts_ms=entry_ms,
        exit_ts_ms=exit_ms,
        entry_ref_price=raw_open,
        entry_price=entry_px,
        exit_price=exit_px,
        qty=qty,
        exit_reason=reason + ENTRY_BAR_SUFFIX if entry_bar else reason,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        fees=float(t.fees),
        funding=float(t.funding),
        slippage_cost=abs(entry_px - raw_open) * qty,
        gross_pnl=side * (exit_px - entry_px) * qty,
        realized_pnl=float(t.pnl),
        hold_bars=max(0, (exit_ms - entry_ms) // case.timeframe_ms),
        entry_bar_exit=entry_bar,
        liquidation_price=None,
    )


def build() -> XgbAdapter:
    return XgbAdapter()
