#!/usr/bin/env python3
"""Find and fill holes inside every candle series in shared_candles.db.

The collector only fetches the tip of pairs a bot is serving right now and never back-fills
an interior hole (2026-10-22: ln2 lost Binance BTCUSDT 1h 2026-09-09 → 10-07 after the Quad
BTC bot stopped and the EMA BTC probe started a month later). This oneshot, run by
``botsgeneral-gap-repair.timer``, scans each (exchange, symbol, timeframe) series over the
last ``--days`` days, downloads the missing closed bars from the same exchange REST source,
checks the bar at the gap edge matches what is stored, and upserts. It never deletes rows.

  python scripts/candle_gap_repair.py            # dry run: print gaps
  python scripts/candle_gap_repair.py --apply    # fill them
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from botsgeneral.db import CandleDB  # noqa: E402
from botsgeneral.models import CandleRow  # noqa: E402

log = logging.getLogger("candle_gap_repair")

STEP_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}
BYBIT_INTERVAL = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D", "1w": "W"}


def _get_json(url: str) -> object:
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2**attempt)
    return None


def fetch_binance(symbol: str, tf: str, start: int, end: int, now_ms: int) -> list[CandleRow]:
    """USD-M futures klines (the collector's Binance source), closed bars in [start, end]."""
    out: list[CandleRow] = []
    cur = start
    while cur <= end:
        url = (
            "https://fapi.binance.com/fapi/v1/klines"
            f"?symbol={symbol}&interval={tf}&startTime={cur}&endTime={end}&limit=1500"
        )
        rows = _get_json(url) or []
        if not rows:
            break
        for k in rows:
            if int(k[6]) >= now_ms:  # still forming
                continue
            out.append(
                CandleRow("binance", symbol, tf, int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                          float(k[5]), float(k[7]), int(k[8]), float(k[9]), float(k[10]))
            )
        nxt = int(rows[-1][0]) + STEP_MS[tf]
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.2)
    return out


def fetch_bybit(symbol: str, tf: str, start: int, end: int, now_ms: int) -> list[CandleRow]:
    """Bybit v5 linear klines (LastPrice), closed bars in [start, end]."""
    out: dict[int, CandleRow] = {}
    cur = start
    step = STEP_MS[tf]
    while cur <= end:
        stop = min(end, cur + 999 * step)
        url = (
            "https://api.bybit.com/v5/market/kline"
            f"?category=linear&symbol={symbol}&interval={BYBIT_INTERVAL[tf]}&start={cur}&end={stop}&limit=1000"
        )
        d = _get_json(url) or {}
        for k in (d.get("result") or {}).get("list") or []:
            t = int(k[0])
            if t + step > now_ms:
                continue
            out[t] = CandleRow("bybit", symbol, tf, t, float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                               float(k[5]), float(k[6]))
        cur = stop + step
        time.sleep(0.2)
    return [out[t] for t in sorted(out)]


FETCH = {"binance": fetch_binance, "bybit": fetch_bybit}


def find_gaps(con: sqlite3.Connection, since_ms: int) -> list[tuple[str, str, str, list[tuple[int, int]]]]:
    found = []
    series = con.execute("select exchange, symbol, timeframe from candles group by 1, 2, 3").fetchall()
    for ex, sym, tf in series:
        step = STEP_MS.get(tf)
        if step is None or ex not in FETCH:
            continue
        ts = [r[0] for r in con.execute(
            "select ts_ms from candles where exchange=? and symbol=? and timeframe=? and ts_ms>=? order by ts_ms",
            (ex, sym, tf, since_ms),
        )]
        gaps = [(a, b) for a, b in zip(ts, ts[1:]) if b - a > step]
        if gaps:
            found.append((ex, sym, tf, gaps))
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.environ.get("SHARED_CANDLES_DB", "/var/lib/botsgeneral/shared_candles.db"))
    ap.add_argument("--days", type=int, default=400, help="scan window (default 400 days)")
    ap.add_argument("--apply", action="store_true", help="download and upsert the missing bars")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    now_ms = int(time.time() * 1000)
    ro = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=60)
    todo = find_gaps(ro, now_ms - args.days * 86_400_000)
    if not todo:
        log.info("no gaps in %s (last %s days)", args.db, args.days)
        return 0
    db = CandleDB(args.db) if args.apply else None
    failed = 0
    for ex, sym, tf, gaps in todo:
        step = STEP_MS[tf]
        missing = sum((b - a) // step - 1 for a, b in gaps)
        log.warning("%s %s %s: %d gap(s), %d missing bar(s), first %s", ex, sym, tf, len(gaps), missing,
                    [(time.strftime("%Y-%m-%d %H:%M", time.gmtime(a / 1000)),
                      time.strftime("%Y-%m-%d %H:%M", time.gmtime(b / 1000))) for a, b in gaps[:3]])
        if db is None:
            continue
        try:
            # Same source as stored bars? Compare the bar on the edge of the first gap.
            a0 = gaps[0][0]
            edge = FETCH[ex](sym, tf, a0, a0, now_ms)
            stored = ro.execute(
                "select close from candles where exchange=? and symbol=? and timeframe=? and ts_ms=?", (ex, sym, tf, a0)
            ).fetchone()
            if edge and stored and abs(edge[0].close - float(stored[0])) > 1e-9 * max(1.0, abs(float(stored[0]))):
                log.error("%s %s %s: REST close %s != stored %s at gap edge, not filling", ex, sym, tf,
                          edge[0].close, stored[0])
                failed += 1
                continue
            rows: list[CandleRow] = []
            for a, b in gaps:
                rows += FETCH[ex](sym, tf, a + step, b - step, now_ms)
            n = db.upsert_candles(rows)
            log.warning("%s %s %s: fetched %d, upserted %d (missing was %d)", ex, sym, tf, len(rows), n, missing)
        except Exception:
            failed += 1
            log.exception("%s %s %s: repair failed", ex, sym, tf)
    if db is not None:
        db.close()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
