"""Unit tests for closed-bar freshness semantics."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from live_candles.shared import candles_fresh
from live_candles.reader import is_fresh


def _seed(db: Path, *, last_open_ms: int, timeframe: str = "1h") -> None:
    con = sqlite3.connect(str(db))
    try:
        con.execute(
            """
            CREATE TABLE candles (
                exchange TEXT, symbol TEXT, timeframe TEXT, ts_ms INTEGER,
                open REAL, high REAL, low REAL, close REAL, volume REAL,
                PRIMARY KEY (exchange, symbol, timeframe, ts_ms)
            )
            """
        )
        con.execute(
            "INSERT INTO candles VALUES (?,?,?,?,?,?,?,?,?)",
            ("binance", "BTCUSDT", timeframe, last_open_ms, 1, 1, 1, 1, 1),
        )
        con.commit()
    finally:
        con.close()


class TestCandlesFresh(unittest.TestCase):
    def test_just_closed_bar_present_is_fresh(self):
        step = 3_600_000
        # 12:00:05 UTC-equivalent: expected closed open = 11:00
        now = 12 * step + 5_000
        expected = 11 * step
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            db = Path(td) / "c.db"
            _seed(db, last_open_ms=expected)
            ok, last, reason = candles_fresh(
                "BTCUSDT", "1h", exchange="binance", db_path=db, now_ms=now
            )
            self.assertTrue(ok, reason)
            self.assertEqual(last, expected)
            self.assertTrue(
                is_fresh("binance", "BTCUSDT", "1h", db_path=db, now_ms=now)
            )

    def test_missing_just_closed_within_grace_awaits(self):
        step = 3_600_000
        now = 12 * step + 5_000
        stale_last = 10 * step  # one bar behind expected 11:00
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            db = Path(td) / "c.db"
            _seed(db, last_open_ms=stale_last)
            ok, last, reason = candles_fresh(
                "BTCUSDT",
                "1h",
                exchange="binance",
                db_path=db,
                now_ms=now,
                close_grace_ms=180_000,
            )
            self.assertFalse(ok)
            self.assertIn("awaiting_just_closed", reason)
            self.assertFalse(
                is_fresh("binance", "BTCUSDT", "1h", db_path=db, now_ms=now)
            )

    def test_old_open_lag_formula_no_longer_false_stale_when_bar_present(self):
        """Regression: now-last_open ~= 2h at hour+1s must not false-stale if bar ok."""
        step = 3_600_000
        now = 12 * step + 1_600  # 1.6s into the hour
        expected = 11 * step
        # old formula: lag = now-expected ~= 3601600 < 7200000 → was ok;
        # critical case is expected present: must be fresh under new formula too.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            db = Path(td) / "c.db"
            _seed(db, last_open_ms=expected)
            ok, _, reason = candles_fresh(
                "BTCUSDT", "1h", exchange="binance", db_path=db, now_ms=now
            )
            self.assertTrue(ok, reason)


if __name__ == "__main__":
    unittest.main()
