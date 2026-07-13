from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, order=True)
class CandlePair:
    exchange: str  # bybit | binance
    symbol: str  # BTCUSDT
    timeframe: str  # 5m | 1h | 4h | 15m

    def key(self) -> tuple[str, str, str]:
        return (self.exchange, self.symbol, self.timeframe)

    def __str__(self) -> str:
        return f"{self.exchange}:{self.symbol}:{self.timeframe}"


@dataclass
class CandleRow:
    exchange: str
    symbol: str
    timeframe: str
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float | None = None
    trades: int | None = None
    taker_buy_base: float | None = None
    taker_buy_quote: float | None = None

    def as_db_tuple(self, updated_at_ms: int) -> tuple[Any, ...]:
        return (
            self.exchange,
            self.symbol,
            self.timeframe,
            self.ts_ms,
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume,
            self.quote_volume,
            self.trades,
            self.taker_buy_base,
            self.taker_buy_quote,
            updated_at_ms,
        )


# Human TF → Bybit v5 interval code
BYBIT_INTERVAL = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "2h": "120",
    "4h": "240",
    "6h": "360",
    "12h": "720",
    "1d": "D",
    "1w": "W",
}

# Bybit code → human TF
BYBIT_INTERVAL_REV = {v: k for k, v in BYBIT_INTERVAL.items()}

# Human TF → Binance interval (same for most)
BINANCE_INTERVAL = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "12h": "12h",
    "1d": "1d",
    "1w": "1w",
}

TF_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


def normalize_timeframe(tf: str) -> str:
    t = (tf or "").strip().lower().replace("min", "m")
    aliases = {
        "60": "1h",
        "240": "4h",
        "5": "5m",
        "15": "15m",
        "1": "1m",
        "1hour": "1h",
        "4hour": "4h",
        "4hr": "4h",
    }
    return aliases.get(t, t)


def normalize_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper().replace("/", "").replace("-", "").replace("_", "")
