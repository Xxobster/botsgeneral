"""Grade ``TSM-VPA``'s ``run_backtest`` against the conformance pack.

Engine: ``D:\\projects\\TSM-VPA\\src\\vpa\\engine.py``.

Shape of the translation:

* The engine sizes from a risk fraction rather than a quantity, so the adapter solves for
  the risk fraction that reproduces the fixture's quantity at the fixture's stop distance.
* It derives leverage from the stop when isolated margin is on, which is a different
  policy from the fixture's declared leverage. The adapter leaves that alone and lets the
  numbers disagree where they disagree — that is the finding, not a bug in the adapter.
* Its signals carry absolute stop and target prices, so those pass through unchanged.

Run with::

    tradesim-conformance --engine tsmvpa_adapter:build
"""

from __future__ import annotations

from typing import Any

from tradesim.conformance.adapter import NormalisedResult, NormalisedTrade
from tradesim.conformance.fixture_loader import Fixture

from _common import (
    TSMVPA_ROOT,
    Case,
    ensure_path,
    normalised,
    unsupported_reason,
)

CAPABILITIES = ("funding", "liquidation", "max_hold")

REASONS = {
    "stop": "stop",
    "stop_samebar_adverse": "stop",
    "target": "target",
    "liquidation": "liquidation",
    "max_hold": "max_hold",
    "end_of_data": "end_of_data",
}


class TsmVpaAdapter:
    name = "vpa.engine.run_backtest"
    version = "TSM-VPA"

    def __init__(self, contract: str = "perp_bracket_portfolio") -> None:
        self.contract = contract
        ensure_path(TSMVPA_ROOT)

    def supports(self, fixture: Fixture) -> tuple[bool, str]:
        why = unsupported_reason(fixture, capabilities=CAPABILITIES)
        if why:
            return False, why
        case = Case(fixture.payload)
        if not case.has_stop():
            return False, "engine sizes from the stop distance; a stop is mandatory"
        if case.touch_rows:
            return False, "engine resolves on decision bars only; no touch timeframe"
        return True, ""

    def run_fixture(self, fixture: Fixture) -> NormalisedResult:
        import pandas as pd

        from vpa.engine import run_backtest
        from vpa.margin import MarginContract
        from vpa.strategy import Signal

        case = Case(fixture.payload)
        stop, target = case.brackets()
        side = int(case.signal["side"])
        fill = case.expected_fill()
        qty = case.qty()

        df = pd.DataFrame(
            {
                "ts_ms": [int(r[0]) for r in case.bars],
                "open": [float(r[1]) for r in case.bars],
                "high": [float(r[2]) for r in case.bars],
                "low": [float(r[3]) for r in case.bars],
                "close": [float(r[4]) for r in case.bars],
                "volume": [float(r[5]) if len(r) > 5 else 0.0 for r in case.bars],
            }
        )

        signal = Signal(
            side="long" if side > 0 else "short",
            signal_ts_ms=int(case.signal["ts_ms"]),
            entry_ts_ms=int(case.bars[case.entry_bar_index()][0]),
            entry_ref_price=fill,
            stop_price=float(stop),
            target_price=float(target) if target is not None else fill * (1.0 + side * 10.0),
            signal_low=float(case.bars[case.bar_index_of(int(case.signal["ts_ms"]))][3]),
            signal_high=float(case.bars[case.bar_index_of(int(case.signal["ts_ms"]))][2]),
            pattern="conformance",
            stack_score=0.0,
        )

        funding = None
        if case.funding:
            funding = pd.DataFrame(
                {
                    "funding_time_ms": [int(r[0]) for r in case.funding],
                    "funding_rate": [float(r[1]) for r in case.funding],
                }
            )

        hold = case.max_hold_bars()
        # Solve the risk fraction that produces the fixture's quantity: the engine
        # computes qty = equity * risk_frac / |entry - stop|.
        risk_frac = qty * abs(fill - float(stop)) / case.starting_equity
        result = run_backtest(
            df,
            [signal],
            starting_equity=case.starting_equity,
            risk_frac=risk_frac,
            taker_fee=case.taker,
            slippage=case.entry_slip,
            max_hold_bars=hold if hold is not None else 10**9,
            symbol=case.symbol,
            funding=funding,
            contract=MarginContract(
                margin_mode=str(case.margin.get("mode", "isolated")),
                mm_buffer=float(case.margin.get("maintenance_buffer", 0.005)),
                mark_buffer=float(case.margin.get("mark_buffer", 0.002)),
                maint_margin_rate=float(case.instrument["maintenance_rate"]),
                max_margin_utilization=float(
                    case.sim.get("max_margin_utilisation") or 1.0
                ),
            ),
            use_isolated_margin=True,
        )

        raw_open = float(case.bars[case.entry_bar_index()][1])
        trades = [_trade(t, case, raw_open) for t in result.trades]
        return normalised(
            trades,
            starting_equity=float(result.starting_equity),
            ending_equity=float(result.ending_equity),
            # Approximate isolated linear model, no maintenance tiers.
            liquidation_status="SIMPLIFIED",
            fill_rates=[case.taker] * (2 * len(trades)),
            skip_counts=(
                {"SKIP_INSUFFICIENT_MARGIN": int(result.skipped_margin)}
                if getattr(result, "skipped_margin", 0)
                else {}
            ),
        )


def _trade(t: Any, case: Case, raw_open: float) -> NormalisedTrade:
    side = 1 if t.side == "long" else -1
    raw_reason = str(t.exit_reason)
    entry_bar = raw_reason.endswith("_entry_bar")
    base = raw_reason[: -len("_entry_bar")] if entry_bar else raw_reason
    mapped = REASONS.get(base, base)
    entry_px = float(t.entry_price)
    exit_px = float(t.exit_price)
    qty = float(t.qty)
    # The engine reports one fee total. It charges the same taker rate on both fills, so
    # the split is recovered rather than left unreported.
    entry_fee = case.taker * qty * entry_px
    return NormalisedTrade(
        symbol=case.symbol,
        side=side,
        entry_ts_ms=int(t.entry_ts_ms),
        exit_ts_ms=int(t.exit_ts_ms),
        entry_ref_price=raw_open,
        entry_price=entry_px,
        exit_price=exit_px,
        qty=qty,
        exit_reason=mapped + "_entry_bar" if entry_bar else mapped,
        entry_fee=entry_fee,
        exit_fee=float(t.fees) - entry_fee,
        slippage_cost=abs(entry_px - raw_open) * qty,
        fees=float(t.fees),
        funding=float(t.funding),
        gross_pnl=side * (exit_px - entry_px) * qty,
        realized_pnl=float(t.pnl),
        hold_bars=max(0, (int(t.exit_ts_ms) - int(t.entry_ts_ms)) // case.timeframe_ms),
        ambiguous=base == "stop_samebar_adverse",
        entry_bar_exit=entry_bar,
        liquidation_price=float(t.liq_price) if t.liq_price else None,
    )


def build() -> TsmVpaAdapter:
    return TsmVpaAdapter()
