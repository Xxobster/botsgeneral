"""Instrument universe for the shared research candle store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


from market_data.paths import candles_root

DEFAULT_ROOT = str(candles_root())
DEFAULT_DB = str(candles_root() / "market_ohlcv.sqlite")


@dataclass(frozen=True)
class DukascopyInstrument:
    symbol: str  # canonical research symbol
    instrument: str  # dukascopy-python instrument id
    start: datetime  # earliest reliable history
    note: str = ""


@dataclass(frozen=True)
class YahooInstrument:
    symbol: str
    yahoo: str
    note: str = ""


# Dukascopy CFD/spot feeds — download native 1h + 1d; derive 4h from 1h, 1w from 1d.
DUKASCOPY: tuple[DukascopyInstrument, ...] = (
    DukascopyInstrument("DXY", "DOLLAR.IDX/USD", datetime(2017, 12, 1, tzinfo=timezone.utc), "DXY-tracking CFD"),
    DukascopyInstrument("HKG40", "E_H-Kong", datetime(2013, 6, 3, tzinfo=timezone.utc), "HK40 CFD proxy, not official HSI"),
    DukascopyInstrument("XAUUSD", "XAU/USD", datetime(2003, 5, 5, tzinfo=timezone.utc), "spot gold CFD"),
    DukascopyInstrument("XAGUSD", "XAG/USD", datetime(2003, 5, 5, tzinfo=timezone.utc), "spot silver CFD"),
    DukascopyInstrument("WTI", "E_Light", datetime(2011, 9, 23, tzinfo=timezone.utc), "WTI-like light crude CFD"),
    DukascopyInstrument("BRENT", "E_Brent", datetime(2010, 12, 2, tzinfo=timezone.utc), "Brent CFD"),
    DukascopyInstrument("COPPER", "COPPER.CMD/USD", datetime(2011, 1, 1, tzinfo=timezone.utc), "copper CFD"),
    DukascopyInstrument("EURUSD", "EUR/USD", datetime(2003, 5, 5, tzinfo=timezone.utc)),
    DukascopyInstrument("GBPUSD", "GBP/USD", datetime(2003, 5, 5, tzinfo=timezone.utc)),
    DukascopyInstrument("USDJPY", "USD/JPY", datetime(2003, 5, 5, tzinfo=timezone.utc)),
    DukascopyInstrument("AUDUSD", "AUD/USD", datetime(2003, 5, 5, tzinfo=timezone.utc)),
    DukascopyInstrument("USDCAD", "USD/CAD", datetime(2003, 5, 5, tzinfo=timezone.utc)),
    DukascopyInstrument("USDCHF", "USD/CHF", datetime(2003, 5, 5, tzinfo=timezone.utc)),
    DukascopyInstrument("NZDUSD", "NZD/USD", datetime(2003, 5, 5, tzinfo=timezone.utc)),
    DukascopyInstrument("EURGBP", "EUR/GBP", datetime(2003, 5, 5, tzinfo=timezone.utc)),
    DukascopyInstrument("EURJPY", "EUR/JPY", datetime(2003, 5, 5, tzinfo=timezone.utc)),
    DukascopyInstrument("EURCHF", "EUR/CHF", datetime(2003, 5, 5, tzinfo=timezone.utc)),
)

# Yahoo daily (and limited 1h) for official/index cross-checks + risk macros
YAHOO: tuple[YahooInstrument, ...] = (
    YahooInstrument("HSI", "^HSI", "official Hang Seng Index daily"),
    YahooInstrument("DXY_ICE", "DX-Y.NYB", "ICE USD index futures continuous"),
    YahooInstrument("XAUUSD_FUT", "GC=F", "COMEX gold futures"),
    YahooInstrument("XAGUSD_FUT", "SI=F", "COMEX silver futures"),
    YahooInstrument("WTI_FUT", "CL=F", "NYMEX WTI futures"),
    YahooInstrument("BRENT_FUT", "BZ=F", "Brent futures"),
    YahooInstrument("COPPER_FUT", "HG=F", "copper futures"),
    YahooInstrument("EURUSD", "EURUSD=X"),
    YahooInstrument("GBPUSD", "GBPUSD=X"),
    YahooInstrument("USDJPY", "USDJPY=X"),
    YahooInstrument("AUDUSD", "AUDUSD=X"),
    YahooInstrument("USDCAD", "USDCAD=X"),
    YahooInstrument("USDCHF", "USDCHF=X"),
    YahooInstrument("NZDUSD", "NZDUSD=X"),
    YahooInstrument("EURGBP", "EURGBP=X"),
    YahooInstrument("EURJPY", "EURJPY=X"),
    YahooInstrument("EURCHF", "EURCHF=X"),
    # Cross-asset / LLM macros
    YahooInstrument("VIX", "^VIX", "CBOE volatility index"),
    YahooInstrument("SPX", "^GSPC", "S&P 500"),
    YahooInstrument("NDX", "^IXIC", "Nasdaq Composite"),
    YahooInstrument("DJI", "^DJI", "Dow Jones Industrial Average"),
    # Yield cross-checks (canonical daily yields live under FRED US02Y/US10Y/…)
    YahooInstrument("TNX", "^TNX", "CBOE 10Y Treasury yield (Yahoo)"),
    YahooInstrument("FVX", "^FVX", "CBOE 5Y Treasury yield (Yahoo)"),
    YahooInstrument("TYX", "^TYX", "CBOE 30Y Treasury yield (Yahoo)"),
    YahooInstrument("IRX", "^IRX", "CBOE 13-week T-bill yield (Yahoo)"),
)


@dataclass(frozen=True)
class FredInstrument:
    symbol: str
    series_id: str
    note: str = ""


# Official daily Treasury constant-maturity yields (percent)
FRED: tuple[FredInstrument, ...] = (
    FredInstrument("US02Y", "DGS2", "2-year Treasury constant maturity"),
    FredInstrument("US10Y", "DGS10", "10-year Treasury constant maturity"),
    FredInstrument("US03M", "DGS3MO", "3-month Treasury bill"),
    FredInstrument("T10Y2Y", "T10Y2Y", "10y–2y yield spread (recession signal)"),
)

# Union of symbols used across C:\projects trading bots
BINANCE_FUTURES_SYMBOLS: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "TRXUSDT",
    "XLMUSDT",
    "VETUSDT",
    "HYPEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
)

# Default Binance intervals to store. Pass --timeframes 1m for raw 1m + derived higher TFs.
BINANCE_TIMEFRAMES: tuple[str, ...] = ("5m", "15m", "1h", "4h", "1d", "1w")
# Valid intervals that can be requested via --timeframes (even if not in default list)
BINANCE_ALLOWED_TIMEFRAMES: tuple[str, ...] = (
    "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "1w",
)

# Macro: fetch these natively from Dukascopy; derive the rest
DUKASCOPY_NATIVE_TFS: tuple[str, ...] = ("1h", "1d")
