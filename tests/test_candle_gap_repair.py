"""Gap repair fills interior holes from the REST source and refuses a mismatched source."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

from botsgeneral.db import CandleDB
from botsgeneral.models import CandleRow

SPEC = importlib.util.spec_from_file_location("gap", Path(__file__).resolve().parents[1] / "scripts" / "candle_gap_repair.py")
gap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gap)

H = 3_600_000
T0 = 1_790_000_000_000 // H * H


def row(t, px=100.0):
    return CandleRow("binance", "BTCUSDT", "1h", t, px, px + 1, px - 1, px, 1.0)


def make_db(tmp_path):
    p = tmp_path / "c.db"
    db = CandleDB(p)
    db.upsert_candles([row(T0 + i * H) for i in range(10) if i not in (4, 5, 6)])
    db.close()
    return p


def count(p):
    return sqlite3.connect(p).execute("select count(*) from candles").fetchone()[0]


def test_dry_run_does_not_write(tmp_path, monkeypatch):
    p = make_db(tmp_path)
    monkeypatch.setattr(gap.time, "time", lambda: (T0 + 20 * H) / 1000)
    assert gap.main(["--db", str(p), "--days", "3650"]) == 0
    assert count(p) == 7


def test_apply_fills_hole(tmp_path, monkeypatch):
    p = make_db(tmp_path)
    monkeypatch.setattr(gap.time, "time", lambda: (T0 + 20 * H) / 1000)
    monkeypatch.setattr(gap.time, "sleep", lambda s: None)
    monkeypatch.setitem(gap.FETCH, "binance", lambda s, tf, a, b, now: [row(t) for t in range(a, b + 1, H)])
    assert gap.main(["--db", str(p), "--days", "3650", "--apply"]) == 0
    assert count(p) == 10
    assert gap.find_gaps(sqlite3.connect(p), 0) == []


def test_source_mismatch_is_refused(tmp_path, monkeypatch):
    p = make_db(tmp_path)
    monkeypatch.setattr(gap.time, "time", lambda: (T0 + 20 * H) / 1000)
    monkeypatch.setitem(gap.FETCH, "binance", lambda s, tf, a, b, now: [row(t, px=200.0) for t in range(a, b + 1, H)])
    assert gap.main(["--db", str(p), "--days", "3650", "--apply"]) == 1
    assert count(p) == 7
