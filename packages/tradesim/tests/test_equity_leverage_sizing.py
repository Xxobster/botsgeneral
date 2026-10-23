"""EQUITY_LEVERAGE_NOTIONAL: notional = equity × fraction × leverage."""

from __future__ import annotations

from tradesim import SizingConfig, SizingMode
from tradesim.sizing import desired_qty


def test_equity_leverage_notional_formula():
    cfg = SizingConfig(
        mode=SizingMode.EQUITY_LEVERAGE_NOTIONAL,
        equity_fraction=0.01,
        compound=True,
    )
    # equity 10_000, 1%, 15x => notional 1_500 => qty 1.5 at price 1000
    qty, unit = desired_qty(
        cfg=cfg,
        price=1000.0,
        stop_price=980.0,
        equity=10_000.0,
        leverage=15.0,
        size_mult=1.0,
    )
    assert unit == "equity_leverage_notional"
    assert qty == 1.5


def test_equity_leverage_size_mult_doubles_notional():
    cfg = SizingConfig(mode=SizingMode.EQUITY_LEVERAGE_NOTIONAL, equity_fraction=0.01)
    qty, _ = desired_qty(
        cfg=cfg,
        price=100.0,
        stop_price=98.0,
        equity=1_000.0,
        leverage=10.0,
        size_mult=2.0,
    )
    # notional = 1000 * 0.01 * 10 * 2 = 200 => qty = 2
    assert qty == 2.0
