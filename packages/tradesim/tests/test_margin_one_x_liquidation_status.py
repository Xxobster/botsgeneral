"""1× isolated margin with tiers must not leave liquidation_status UNKNOWN."""

from __future__ import annotations

from tradesim.contracts import LiquidationStatus, MarginConfig, MarginMode, Side
from tradesim.margin import build_margin_state
from tradesim.research.defaults import research_instrument, research_margin


def test_one_x_with_tiers_is_simplified_without_mark_series() -> None:
    inst = research_instrument("BTCUSDT")
    assert inst.tiers_available
    state = build_margin_state(
        side=Side.LONG,
        entry_price=50_000.0,
        qty=0.001,
        stop_price=49_000.0,
        spec=inst,
        cfg=research_margin(leverage=1.0),
        close_fee_rate=0.00055,
        wallet_available=10_000.0,
        has_mark_series=False,
    )
    assert state.liquidation_price is None
    assert state.status == LiquidationStatus.SIMPLIFIED


def test_one_x_with_tiers_and_mark_series_is_modelled() -> None:
    inst = research_instrument("BTCUSDT")
    state = build_margin_state(
        side=Side.LONG,
        entry_price=50_000.0,
        qty=0.001,
        stop_price=49_000.0,
        spec=inst,
        cfg=research_margin(leverage=1.0),
        close_fee_rate=0.00055,
        wallet_available=10_000.0,
        has_mark_series=True,
    )
    assert state.liquidation_price is None
    assert state.status == LiquidationStatus.MODELLED


def test_missing_tiers_stays_unknown() -> None:
    from tradesim.contracts import InstrumentSpec

    bare = InstrumentSpec(
        symbol="FAKEUSDT",
        tick_size=0.1,
        qty_step=0.001,
        min_qty=0.001,
        min_notional=5.0,
        max_leverage=50.0,
        maintenance_tiers=(),
    )
    assert not bare.tiers_available
    state = build_margin_state(
        side=Side.LONG,
        entry_price=50_000.0,
        qty=0.001,
        stop_price=49_000.0,
        spec=bare,
        cfg=MarginConfig(mode=MarginMode.ISOLATED, leverage=1.0),
        close_fee_rate=0.00055,
        wallet_available=10_000.0,
        has_mark_series=False,
    )
    assert state.status == LiquidationStatus.UNKNOWN
