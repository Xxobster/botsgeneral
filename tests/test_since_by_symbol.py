from botsgeneral.report import _filter_closed_by_since


def test_filter_closed_by_symbol_since():
    closed = [
        {"symbol": "BTCUSDT", "updatedTime": "1784505600000", "closedPnl": "1"},  # 2026-07-20
        {"symbol": "BTCUSDT", "updatedTime": "1784592000000", "closedPnl": "2"},  # 2026-07-21
        {"symbol": "ETHUSDT", "updatedTime": "1784678400000", "closedPnl": "3"},  # 2026-07-22
        {"symbol": "ETHUSDT", "updatedTime": "1784764800000", "closedPnl": "4"},  # 2026-07-23
    ]
    out = _filter_closed_by_since(
        closed,
        "2026-07-09",
        {"BTCUSDT": "2026-07-21", "ETHUSDT": "2026-07-23"},
    )
    pnls = [t["closedPnl"] for t in out]
    assert pnls == ["2", "4"]
