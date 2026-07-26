"""Grade ``LLM1``'s ``simulate_path_exits`` against the conformance pack.

Engine: ``D:\\projects\\LLM1\\src\\llm1\\backtest\\path_exit_simulator.py``.

Shape of the translation:

* The engine works in return units against a notional of one, so every price-space number
  it reports is scaled back to cash by the fixture's quantity and entry price.
* It takes percentage brackets from its own fill, so the adapter derives the percentages
  that land on the fixture's absolute levels.
* It scans a *touch* series rather than the decision bars, so when a fixture supplies no
  lower timeframe the decision bars are passed as their own touch series. That is the
  convention the engine's callers use and it is the only way to run it at all.
* Its horizon is expressed in hours, so a maximum hold in bars is converted through the
  decision timeframe.

Run with::

    tradesim-conformance --engine llm1_adapter:build
"""

from __future__ import annotations

from typing import Any

from tradesim.conformance.adapter import NormalisedResult, NormalisedTrade
from tradesim.conformance.fixture_loader import Fixture

from _common import (
    ENTRY_BAR_SUFFIX,
    LLM1_ROOT,
    Case,
    ensure_path,
    normalised,
    unsupported_reason,
)

CAPABILITIES = ("touch", "max_hold")

REASONS = {"sl": "stop", "tp": "target", "timeout": "max_hold"}


class Llm1Adapter:
    name = "llm1.backtest.simulate_path_exits"
    version = "path_exit_simulator"

    def __init__(self, contract: str = "perp_bracket_portfolio") -> None:
        self.contract = contract
        ensure_path(LLM1_ROOT)

    def supports(self, fixture: Fixture) -> tuple[bool, str]:
        why = unsupported_reason(fixture, capabilities=CAPABILITIES)
        if why:
            return False, why
        case = Case(fixture.payload)
        if not (case.has_stop() and case.has_target()):
            return False, "engine requires both brackets; it has no unbracketed mode"
        if case.funding:
            return False, "path simulator models no funding (a separate module does)"
        return True, ""

    def run_fixture(self, fixture: Fixture) -> NormalisedResult:
        import numpy as np

        from llm1.backtest import path_exit_simulator as pes
        from llm1.backtest.simulator import CostConfig
        from llm1.data import catalog

        case = Case(fixture.payload)
        # The engine looks the decision timeframe up in a static table that stops at five
        # minutes. Registering the fixture's timeframe is plumbing, not a behaviour change.
        tf_name = f"tf{case.timeframe_ms}"
        catalog.TF_MS[tf_name] = case.timeframe_ms
        pes.TF_MS[tf_name] = case.timeframe_ms

        decision_ts = np.asarray([int(r[0]) for r in case.bars], dtype=np.int64)
        decision_open = np.asarray([float(r[1]) for r in case.bars], dtype=float)

        touch_rows = case.touch_rows or case.bars
        touch_ts = np.asarray([int(r[0]) for r in touch_rows], dtype=np.int64)
        touch_open = np.asarray([float(r[1]) for r in touch_rows], dtype=float)
        touch_high = np.asarray([float(r[2]) for r in touch_rows], dtype=float)
        touch_low = np.asarray([float(r[3]) for r in touch_rows], dtype=float)
        touch_close = np.asarray([float(r[4]) for r in touch_rows], dtype=float)

        signals = np.zeros(len(case.bars), dtype=int)
        signals[case.bar_index_of(int(case.signal["ts_ms"]))] = int(case.signal["side"])

        tp_frac, sl_frac = case.bracket_fracs()
        hold = case.max_hold_bars()
        span_ms = (
            hold * case.timeframe_ms
            if hold is not None
            else (len(case.bars) + 1) * case.timeframe_ms
        )
        config = pes.PathExitConfig(
            tp_pct=tp_frac,
            sl_pct=sl_frac,
            # Hours is the only unit the engine offers; the fixtures are minute bars, so
            # the horizon is rounded UP to the next whole hour rather than down, which
            # can only give the engine more room, never less.
            horizon_hours=max(1, -(-span_ms // 3_600_000)),
            decision_timeframe=tf_name,
            cost=CostConfig(
                fee_bps=case.taker * 10_000.0,
                slippage_bps=case.entry_slip * 10_000.0,
                entry_slippage_bps=case.entry_slip * 10_000.0,
                exit_market_slippage_bps=case.market_exit_slip * 10_000.0,
            ),
            allow_concurrent=False,
        )

        sim = pes.simulate_path_exits(
            decision_ts_ms=decision_ts,
            decision_open=decision_open,
            touch_ts_ms=touch_ts,
            touch_high=touch_high,
            touch_low=touch_low,
            touch_close=touch_close,
            touch_open=touch_open,
            signals=signals,
            config=config,
        )

        qty = case.qty()
        frame = sim.get("trades")
        trades: list[NormalisedTrade] = []
        if frame is not None and len(frame):
            for row in frame.to_dict("records"):
                trades.append(_trade(row, case, qty))

        realized = sum(t.realized_pnl for t in trades)
        return normalised(
            trades,
            starting_equity=case.starting_equity,
            ending_equity=case.starting_equity + realized,
            # The engine states this itself: liquidation is not modelled.
            liquidation_status="UNKNOWN",
            # One taker rate, charged on both sides. Reporting it twice is what the
            # engine actually does, and is the honest input to the maker/taker question.
            fill_rates=[float(sim.get("taker_fee_rate", 0.0))] * (2 * len(trades)),
        )


def _trade(row: dict[str, Any], case: Case, qty: float) -> NormalisedTrade:
    side = int(row["side"])
    entry_px = float(row["entry_px"])
    exit_px = float(row["exit_px"])
    notional = qty * entry_px
    entry_ms = int(row["entry_ms"])
    exit_ms = int(row["exit_ms"])
    entry_bar = exit_ms == entry_ms
    reason = REASONS.get(str(row["reason"]), str(row["reason"]))
    entry_fee = float(row["entry_fee_units"]) * notional
    exit_fee = float(row["exit_fee_units"]) * notional
    ref = float(row["entry_ref_px"])
    return NormalisedTrade(
        symbol=case.symbol,
        side=side,
        entry_ts_ms=entry_ms,
        exit_ts_ms=exit_ms,
        entry_ref_price=ref,
        entry_price=entry_px,
        exit_price=exit_px,
        qty=qty,
        exit_reason=reason + ENTRY_BAR_SUFFIX if entry_bar else reason,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        fees=entry_fee + exit_fee,
        funding=0.0,
        slippage_cost=abs(entry_px - ref) * qty,
        gross_pnl=side * (exit_px - entry_px) * qty,
        realized_pnl=float(row["net_pnl_units"]) * notional,
        hold_bars=max(0, (exit_ms - entry_ms) // case.timeframe_ms),
        entry_bar_exit=entry_bar,
        liquidation_price=None,
    )


def build() -> Llm1Adapter:
    return Llm1Adapter()
