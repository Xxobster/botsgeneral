from __future__ import annotations

import tempfile
from pathlib import Path

from botsgeneral.db import CandleDB
from botsgeneral.discover.parsers import parse_bot
from botsgeneral.models import CandlePair, CandleRow, normalize_timeframe


def test_normalize_timeframe():
    assert normalize_timeframe("60") == "1h"
    assert normalize_timeframe("4h") == "4h"
    assert normalize_timeframe("5m") == "5m"


def test_db_upsert_and_freshness(tmp_path: Path):
    db = CandleDB(tmp_path / "t.db")
    rows = [
        CandleRow("bybit", "BTCUSDT", "5m", 1_000, 1, 2, 0.5, 1.5, 10),
        CandleRow("bybit", "BTCUSDT", "5m", 2_000, 1.5, 2.5, 1, 2, 11),
    ]
    assert db.upsert_candles(rows) == 2
    assert db.candle_count(CandlePair("bybit", "BTCUSDT", "5m")) == 2
    assert db.latest_ts(CandlePair("bybit", "BTCUSDT", "5m")) == 2_000
    db.replace_discovered([(CandlePair("bybit", "BTCUSDT", "5m"), "crypthor2")])
    assert len(db.list_discovered()) == 1
    db.close()


def test_wip_parser():
    root = Path(r"C:/projects/W.I.P")
    if not root.exists():
        return
    pairs = parse_bot(
        "wip",
        {
            "path": str(root),
            "exchange": "bybit",
            "parser": "wip_fleet",
            "also_fetch_timeframes": ["1h"],
        },
    )
    keys = {p.key() for p in pairs}
    assert ("bybit", "BTCUSDT", "4h") in keys
    assert ("bybit", "BTCUSDT", "1h") in keys
    assert ("bybit", "ETHUSDT", "4h") in keys


def test_news_parser():
    root = Path(r"C:/projects/news")
    if not root.exists():
        return
    pairs = parse_bot("news", {"path": str(root), "exchange": "binance", "parser": "news_yaml"})
    assert pairs == [CandlePair("binance", "BTCUSDT", "4h")]


def test_divergences_parser():
    root = Path(r"C:/projects/divergences")
    if not root.exists():
        return
    pairs = parse_bot(
        "divergences",
        {"path": str(root), "exchange": "bybit", "parser": "divergences_launch"},
    )
    keys = {p.key() for p in pairs}
    assert ("bybit", "ETHUSDT", "4h") in keys
    assert ("bybit", "BTCUSDT", "4h") in keys
    assert ("bybit", "ETHUSDT", "1h") in keys
