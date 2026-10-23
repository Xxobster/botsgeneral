from datetime import datetime, timezone

from botsgeneral.metrics import parse_since_ms
from botsgeneral.report import (
    _effective_since_for_symbol,
    _filter_closed_by_since,
    _later_iso_date,
)


def _ms(y: int, m: int, d: int) -> str:
    return str(int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000))


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


def test_account_since_floors_earlier_bot_symbol_date():
    """since_by_account 2026-08-25 must beat since_by_bot llm2 ETH 2026-08-21."""
    closed = [
        {"symbol": "ETHUSDT", "updatedTime": _ms(2026, 8, 22), "closedPnl": "old"},
        {"symbol": "ETHUSDT", "updatedTime": _ms(2026, 8, 25), "closedPnl": "new"},
        {"symbol": "BTCUSDT", "updatedTime": _ms(2026, 8, 6), "closedPnl": "btc-old"},
        {"symbol": "BTCUSDT", "updatedTime": _ms(2026, 8, 26), "closedPnl": "btc-new"},
    ]
    out = _filter_closed_by_since(
        closed,
        "2026-08-25",
        {"ETHUSDT": "2026-08-21", "SOLUSDT": "2026-08-21"},
    )
    pnls = [t["closedPnl"] for t in out]
    assert pnls == ["new", "btc-new"]
    assert _effective_since_for_symbol("2026-08-25", "ETHUSDT", {"ETHUSDT": "2026-08-21"}) == "2026-08-25"
    assert _effective_since_for_symbol("2026-08-21", "ETHUSDT", {"ETHUSDT": "2026-08-21"}) == "2026-08-21"


def test_xxobster2_aug26_excludes_leftover_xgb_eth_market():
    """Leftover Extreme Gradient Boosting Ether Market closes on 25 Aug stay out."""
    leftover_a = str(int(datetime(2026, 8, 25, 2, 20, 20, tzinfo=timezone.utc).timestamp() * 1000))
    leftover_b = str(int(datetime(2026, 8, 25, 12, 26, 21, tzinfo=timezone.utc).timestamp() * 1000))
    later = str(int(datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc).timestamp() * 1000))
    closed = [
        {"symbol": "ETHUSDT", "updatedTime": leftover_a, "closedPnl": "-0.5185"},
        {"symbol": "ETHUSDT", "updatedTime": leftover_b, "closedPnl": "-0.5314"},
        {"symbol": "ETHUSDT", "updatedTime": later, "closedPnl": "0.01"},
    ]
    out = _filter_closed_by_since(closed, "2026-08-26", {"ETHUSDT": "2026-08-26"})
    assert [t["closedPnl"] for t in out] == ["0.01"]


def test_parse_since_ms_date_is_utc_midnight():
    assert parse_since_ms("2026-09-01") == parse_since_ms("2026-09-01T00:00:00Z")
    assert parse_since_ms("2026-09-01T11:38:16Z") == parse_since_ms("2026-09-01 11:38:16")
    assert parse_since_ms("2026-09-01T11:38:16Z") > parse_since_ms("2026-09-01")


def test_datetime_since_excludes_same_day_earlier_close():
    """Xxobster4 DSR Solana close 02:00 UTC must not count after EMA start 11:38:16Z."""
    leftover = str(int(datetime(2026, 9, 1, 2, 0, 6, tzinfo=timezone.utc).timestamp() * 1000))
    after = str(int(datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000))
    closed = [
        {"symbol": "SOLUSDT", "updatedTime": leftover, "closedPnl": "0.1508"},
        {"symbol": "SOLUSDT", "updatedTime": after, "closedPnl": "1.0"},
    ]
    stamp = "2026-09-01T11:38:16Z"
    out = _filter_closed_by_since(closed, stamp, {"SOLUSDT": stamp})
    assert [t["closedPnl"] for t in out] == ["1.0"]
    assert _effective_since_for_symbol("2026-09-01", "SOLUSDT", {"SOLUSDT": stamp}) == stamp
    assert _later_iso_date("2026-09-01", stamp) == stamp
