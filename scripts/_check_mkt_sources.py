import sqlite3
from pathlib import Path

p = Path(r"D:\projectsdata\candles\market_ohlcv.sqlite")
con = sqlite3.connect(str(p))
rows = con.execute(
    """
    SELECT source, symbol, timeframe, price_type, COUNT(*), MIN(ts_ms), MAX(ts_ms)
    FROM market_ohlcv
    WHERE symbol IN ('BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT') AND timeframe='1h'
    GROUP BY 1,2,3,4
    ORDER BY 1,2
    """
).fetchall()
for r in rows:
    print(r)
