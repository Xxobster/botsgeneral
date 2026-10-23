# Shared candles DB — reader contract (VPS)

**Writer (only):** `botsgeneral` collector → `/var/lib/botsgeneral/shared_candles.db`  
**Readers:** every live bot on that VPS. Do **not** open your own Binance/Bybit kline REST/WS for strategy history once migrated.

## Path

```text
SHARED_CANDLES_DB=/var/lib/botsgeneral/shared_candles.db
```

Default on Linux VPS. Override with env `SHARED_CANDLES_DB` if needed.

## Schema

Table `candles`:

| Column | Notes |
|---|---|
| `exchange` | `binance` (USD-M futures) or `bybit` |
| `symbol` | e.g. `BTCUSDT` |
| `timeframe` | `1m` `5m` `15m` `1h` `4h` `1d` … |
| `ts_ms` | **Bar open** time UTC milliseconds |
| `open,high,low,close,volume` | OHLCV |
| `quote_volume, trades, taker_buy_base, taker_buy_quote` | Binance extras (nullable on Bybit) |
| `updated_at_ms` | Last upsert time (bumped only when values change) |

**PK:** `(exchange, symbol, timeframe, ts_ms)`

Writer behaviour: insert new bars; on same key, overwrite **only if** OHLCV/aux differ (exchange corrections). History is never wiped.

## VPS 94.156.189.76 + 185.203.119.52 (LLM2 live)

Collectors serve Binance USD-M futures Last for structure / signal candles
(orders remain on Bybit). Registry bot: `llm2` on both hosts (primary fleet on 94;
additional packs on 185).

| exchange | symbols | timeframes |
|---|---|---|
| `binance` | `BTCUSDT`, `ETHUSDT`, `SOLUSDT` | `1h`, `4h`, `1w` |

Unused leftover series are purged with `botsgeneral purge-unused-candles`.

Note: shared `binance` rows are **USD-M futures Last** (`fapi.binance.com`), which is the same
series as research warehouse `market_ohlcv.source='binance'` (not Binance spot). The collector
writes via `market_data.fetch_binance.fetch_klines` (closed bars only; flat/volume-0 junk
dropped). Gate tip identity with `botsgeneral compare-closed-bars`. Target trading venue
remains Bybit → overall evidence class is still `RESEARCH_PROXY` until native Bybit OHLCV
is used for signals.

## Python helper (preferred)

```python
import os
os.environ.setdefault("SHARED_CANDLES_DB", "/var/lib/botsgeneral/shared_candles.db")

from botsgeneral.reader import load_ohlcv, is_fresh

df = load_ohlcv("binance", "BTCUSDT", "1h", limit=6000)
# columns: ts_ms, open, high, low, close, volume, ...
if not is_fresh("binance", "BTCUSDT", "1h", max_lag_bars=2):
    # skip new entries — do not crash-loop orders
    ...
```

Install / path: code lives in `/opt/botsgeneral` on the VPS (`PYTHONPATH=/opt/botsgeneral` or the botsgeneral venv).

## Raw SQL

```sql
SELECT ts_ms, open, high, low, close, volume,
       quote_volume, trades, taker_buy_base, taker_buy_quote, updated_at_ms
FROM candles
WHERE exchange = 'binance'
  AND symbol = 'BTCUSDT'
  AND timeframe = '1h'
ORDER BY ts_ms ASC;
```

Use `WAL` mode (already set by writer). Open **read-only** if your SQLite build supports it:

```python
sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
```

## Stale guard

After a 1h close, the newest row’s `ts_ms` should be the open of that closed bar. If `now - (ts_ms + timeframe_ms)` exceeds ~2 bars, treat data as stale: log + skip entries (no new risk).

## What bots must stop doing

- Per-bot Binance/Bybit kline REST bootstrap each cycle  
- Per-bot kline WebSocket that **writes** a private candle DB  
- Deleting/replacing the whole shared history  

Trading (orders) stays on each bot’s own Bybit keys.
