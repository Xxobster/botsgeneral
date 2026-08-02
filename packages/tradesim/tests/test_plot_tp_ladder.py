"""Plot helpers: multi-leg take-profit ladder extraction."""

from __future__ import annotations

from tradesim.contracts import Trade
from tradesim.research.plot import _tp_ladder


def _trade(**kw) -> Trade:
    base = dict(
        trade_id=1,
        symbol="TEST",
        side=1,
        entry_ts_ms=0,
        entry_price=100.0,
        entry_ref_price=100.0,
        qty=1.0,
        stop_price=95.0,
        target_price=110.0,
        liquidation_price=None,
        leverage=1.0,
        initial_margin=10.0,
        exit_ts_ms=60_000,
        exit_price=110.0,
        exit_reason="target",
        hold_bars=1,
        fees=0.0,
        funding=0.0,
        slippage_cost=0.0,
        gross_pnl=10.0,
        realized_pnl=10.0,
        return_units=0.1,
        mae=0.0,
        mfe=0.1,
        ambiguous_intrabar=False,
        resolved_by_touch=False,
        entry_bar_exit=False,
    )
    base.update(kw)
    return Trade(**base)


def test_tp_ladder_uses_planned_multi_levels():
    t = _trade(
        target_price=None,
        tp_levels=(("tp1", 105.0, 0.5), ("tp2", 110.0, 0.5)),
    )
    ladder = _tp_ladder(t)
    assert [p for _, p, _ in ladder] == [105.0, 110.0]
    assert ladder[0][0] == "tp1"
    assert ladder[1][2] == 0.5


def test_tp_ladder_falls_back_to_single_target():
    t = _trade(tp_levels=())
    ladder = _tp_ladder(t)
    assert len(ladder) == 1
    assert ladder[0][1] == 110.0
