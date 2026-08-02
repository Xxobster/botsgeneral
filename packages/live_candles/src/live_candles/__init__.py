"""Live shared-candle readers for VPS bots.

Two surfaces over one implementation:

* ``load_ohlcv`` / ``newest_ts_ms`` / ``is_fresh`` — integer ``ts_ms`` columns
  (botsgeneral.reader contract).
* ``load_candles`` / ``latest_ts_ms`` / ``candles_fresh`` — tz-aware ``timestamp``
  (copy-pasted shared_candles.py contract used by crypthor2, karmaa_mp, …).
"""
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
]
