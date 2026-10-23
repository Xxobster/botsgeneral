"""Tech equity universe + Yahoo 1d smoke (network)."""
from __future__ import annotations

from market_data.fetch_yahoo import fetch_yahoo
from market_data.universe import (
    YAHOO_TECH_EQUITY,
    YAHOO_TECH_FROZEN_AS_OF,
    YAHOO_TECH_SYMBOLS,
    YAHOO_TECH_TIMEFRAMES,
    all_yahoo_instruments,
)


def test_tech_equity_universe_frozen_and_unique():
    assert YAHOO_TECH_FROZEN_AS_OF
    assert YAHOO_TECH_TIMEFRAMES == ("1d",)
    assert len(YAHOO_TECH_EQUITY) >= 50
    syms = [i.symbol for i in YAHOO_TECH_EQUITY]
    assert len(syms) == len(set(syms))
    assert "AAPL" in YAHOO_TECH_SYMBOLS and "QQQ" in YAHOO_TECH_SYMBOLS
    assert "NVDA" in YAHOO_TECH_SYMBOLS


def test_all_yahoo_includes_tech():
    all_syms = {i.symbol for i in all_yahoo_instruments()}
    assert "AAPL" in all_syms and "SPX" in all_syms


def test_yahoo_fetch_aapl_1d():
    df = fetch_yahoo("AAPL", "1d")
    assert not df.empty
    assert df["ts_ms"].is_unique
    assert int(df["ts_ms"].iloc[0]) < int(df["ts_ms"].iloc[-1])
    # Multi-decade history for mega-caps on free Yahoo daily
    assert len(df) > 5000
