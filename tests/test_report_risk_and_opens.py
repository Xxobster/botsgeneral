"""Tests for live report risk metrics + open-position enrichment."""
from __future__ import annotations

from botsgeneral.metrics import enrich_open_position, last_open_event, trade_metrics


def test_trade_metrics_recovery_and_max_dd_pct():
    closed = [
        {"closedPnl": "1.0"},
        {"closedPnl": "-0.5"},
        {"closedPnl": "2.0"},
        {"closedPnl": "-0.4"},
    ]
    m = trade_metrics(closed)
    assert m["n_trades"] == 4
    assert abs(m["realized_pnl"] - 2.1) < 1e-9
    assert m["max_drawdown"] < 0
    assert m["max_dd_pct"] is not None and m["max_dd_pct"] < 0
    assert m["recovery_factor"] is not None and m["recovery_factor"] > 0
    assert m["payoff"] is not None and m["payoff"] > 0


def test_enrich_open_long_closer_is_sl():
    pos = enrich_open_position(
        {
            "symbol": "ETHUSDT",
            "side": "Buy",
            "avgPrice": "2000",
            "markPrice": "2010",
            "takeProfit": "2200",
            "stopLoss": "1990",
            "createdTime": "1700000000000",
        }
    )
    assert pos["opened_at_ms"] == 1700000000000
    assert pos["closer_exit"] == "SL"
    assert abs(pos["closer_pct"] - abs((2010 - 1990) / 2010 * 100)) < 1e-9
    assert pos["to_tp_pct"] > pos["to_sl_pct"] > 0


def test_enrich_open_short_closer_is_tp():
    pos = enrich_open_position(
        {
            "symbol": "BTCUSDT",
            "side": "Sell",
            "markPrice": "100",
            "takeProfit": "99",
            "stopLoss": "110",
            "createdTime": "1700000001000",
        }
    )
    assert pos["closer_exit"] == "TP"
    assert abs(pos["closer_pct"] - 1.0) < 1e-9


def test_last_open_prefers_live_position():
    opens = [
        enrich_open_position(
            {"symbol": "ETHUSDT", "side": "Buy", "markPrice": "1", "createdTime": "100"}
        ),
        enrich_open_position(
            {"symbol": "BTCUSDT", "side": "Buy", "markPrice": "1", "createdTime": "300"}
        ),
    ]
    closed = [{"symbol": "SOLUSDT", "createdTime": "200"}]
    lo = last_open_event(opens, closed)
    assert lo == {"ts_ms": 300, "symbol": "BTCUSDT", "source": "open"}


def test_last_open_falls_back_to_closed():
    lo = last_open_event([], [{"symbol": "SOLUSDT", "createdTime": "999"}])
    assert lo == {"ts_ms": 999, "symbol": "SOLUSDT", "source": "closed"}
