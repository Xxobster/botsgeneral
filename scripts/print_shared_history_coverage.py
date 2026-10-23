#!/usr/bin/env python3
import sqlite3
import sys
from datetime import datetime, timezone

db = sys.argv[1] if len(sys.argv) > 1 else "/var/lib/botsgeneral/shared_candles.db"
con = sqlite3.connect(db)
print("meta", con.execute("select key,value from meta where key in ('history_schema','vps_id')").fetchall())
rows = con.execute(
    """
    select exchange, symbol, timeframe, count(*), min(ts_ms), max(ts_ms)
    from candles
    group by 1, 2, 3
    order by 1, 2, 3
    """
).fetchall()
for ex, s, tf, n, mn, mx in rows:
    a = datetime.fromtimestamp(mn / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    b = datetime.fromtimestamp(mx / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    print(f"{ex:7} {s:8} {tf:3} n={n:7} {a} -> {b}")
con.close()
