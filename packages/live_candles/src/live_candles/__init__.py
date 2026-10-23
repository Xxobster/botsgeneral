"""Live shared-candle readers for VPS bots.

Two surfaces over one implementation:

* ``load_ohlcv`` / ``newest_ts_ms`` / ``is_fresh`` — integer ``ts_ms`` columns
  (botsgeneral.reader contract).
* ``load_candles`` / ``latest_ts_ms`` / ``candles_fresh`` — tz-aware ``timestamp``
  (copy-pasted shared_candles.py contract used by crypthor2, karmaa_mp, …).
"""
from live_candles.freshness import (
    LIVE_DATA_001,
    TipFreshnessResult,
    check_series_live_data_001,
    clear_data_unsafe,
    evaluate_tip_freshness,
    expected_closed_open_ms,
    fetch_binance_server_time_ms,
    fetch_bybit_server_time_ms,
    fetch_server_time_ms,
    gate_allows_new_entries,
    is_data_unsafe,
    read_data_unsafe,
    write_data_unsafe,
)
from live_candles.reader import is_fresh, load_ohlcv, newest_ts_ms, shared_db_path
from live_candles.shared import candles_fresh, latest_ts_ms, load_candles

__all__ = [
    "shared_db_path",
    "load_ohlcv",
    "newest_ts_ms",
    "is_fresh",
    "load_candles",
    "latest_ts_ms",
    "candles_fresh",
    "LIVE_DATA_001",
    "TipFreshnessResult",
    "expected_closed_open_ms",
    "evaluate_tip_freshness",
    "fetch_binance_server_time_ms",
    "fetch_bybit_server_time_ms",
    "fetch_server_time_ms",
    "check_series_live_data_001",
    "gate_allows_new_entries",
    "write_data_unsafe",
    "clear_data_unsafe",
    "read_data_unsafe",
    "is_data_unsafe",
]
