"""Binance kline WS: persist closed bars only (no network)."""

from __future__ import annotations

import json

from botsgeneral.fetch.binance_ws import (
    WS_FUTURES,
    candle_from_kline,
    parse_ws_message,
    stream_name,
)
from botsgeneral.models import CandlePair


def _k(*, closed: bool) -> dict:
    return {
        "t": 1_700_000_000_000,
        "T": 1_700_000_899_999,
        "s": "ETHUSDT",
        "i": "15m",
        "o": "1900.0",
        "h": "1910.0",
        "l": "1890.0",
        "c": "1905.0",
        "v": "12.5",
        "q": "23000.0",
        "n": 42,
        "x": closed,
        "V": "6.0",
        "Q": "11000.0",
    }


def test_market_ws_url():
    assert WS_FUTURES.endswith("/market/ws")


def test_stream_name():
    assert stream_name(CandlePair("binance", "ETHUSDT", "15m")) == "ethusdt@kline_15m"
    assert stream_name(CandlePair("binance", "BTCUSDT", "1h")) == "btcusdt@kline_1h"


def test_forming_bar_dropped():
    assert candle_from_kline(_k(closed=False)) is None
    raw = json.dumps({"e": "kline", "s": "ETHUSDT", "k": _k(closed=False)})
    assert parse_ws_message(raw) is None


def test_closed_bar_kept():
    row = candle_from_kline(_k(closed=True))
    assert row is not None
    assert row.exchange == "binance"
    assert row.symbol == "ETHUSDT"
    assert row.timeframe == "15m"
    assert row.ts_ms == 1_700_000_000_000
    assert row.close == 1905.0
    wrapped = json.dumps({"stream": "ethusdt@kline_15m", "data": {"e": "kline", "s": "ETHUSDT", "k": _k(closed=True)}})
    parsed = parse_ws_message(wrapped)
    assert parsed is not None
    assert parsed.close == 1905.0


def test_subscribe_ack_ignored():
    assert parse_ws_message(json.dumps({"result": None, "id": 1})) is None
