#!/usr/bin/env python3
"""Alert when a bot unit has been fail-closed (DATA_UNSAFE) or silent for too long.

Born from 2026-10-25..11-03: XRP/AVAX EMA-short bots logged ~45k DATA_UNSAFE
(CANDLE_STALE) for 9 days because the collector never loaded their pairs, with no alert.

A unit is HEALTHY if its last "clean decision" (a DECIDE line not immediately followed by
DATA_UNSAFE block_entry) is younger than --max-hours (default 3). Read-only; exit 1 if any
unit is unhealthy so a systemd timer / cron can alert on the exit code.

  python scripts/ops_data_unsafe_watch.py --logs '/opt/llm2-*/logs/ema_live.log' --max-hours 3
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime, timedelta, timezone

TAIL_BYTES = 8_000_000


def _ts(line: str):
    try:
        return datetime.strptime(line[:20], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def last_clean_decide(lines: list[str]):
    """Return (last_clean_decide_ts|None, data_unsafe_count_since_it)."""
    last = None
    unsafe_after = 0
    for i, ln in enumerate(lines):
        if " DECIDE " not in ln[:40]:
            if "DATA_UNSAFE" in ln[:40] and last is not None:
                unsafe_after += 1
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        t = _ts(ln)
        if t is None:
            continue
        if "DATA_UNSAFE block_entry" in nxt[:60] and _ts(nxt) == t:
            continue
        last, unsafe_after = t, 0
    return last, unsafe_after


def check(path: str, now: datetime, max_hours: float) -> dict:
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        lines = f.read().decode("utf-8", "replace").splitlines()
    last, unsafe = last_clean_decide(lines)
    age_h = None if last is None else round((now - last).total_seconds() / 3600, 2)
    bad = last is None or (now - last) > timedelta(hours=max_hours)
    return {"log": path, "last_clean_decide": last.isoformat() if last else None,
            "age_hours": age_h, "data_unsafe_since": unsafe, "unhealthy": bad}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default="/opt/llm2-*/logs/ema_live.log")
    ap.add_argument("--max-hours", type=float, default=3.0)
    ap.add_argument("--now", default=None, help="ISO UTC override (tests)")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now).astimezone(timezone.utc) if a.now else datetime.now(timezone.utc)
    res = [check(p, now, a.max_hours) for p in sorted(glob.glob(a.logs))]
    print(json.dumps(res, indent=1))
    bad = [r["log"] for r in res if r["unhealthy"]]
    if bad:
        print("UNHEALTHY (no clean DECIDE within %.1fh): %s" % (a.max_hours, ", ".join(bad)), file=sys.stderr)
    return 1 if bad or not res else 0


if __name__ == "__main__":
    raise SystemExit(main())
