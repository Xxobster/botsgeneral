AGENT_PROMPTS.md

# Copy-paste prompts for project agents

Skip **xgb** — it keeps Binance self-fetch.

---

## crypthor2

```
Context: We are consolidating candle acquisition. A new service "botsgeneral" runs ONE collector per VPS and writes a shared SQLite DB. This bot must STOP fetching/writing candles and READ from that DB instead. Trading (Bybit orders) stays on this bot's own API keys.

Shared DB (VPS 212.73.150.178): /var/lib/botsgeneral/shared_candles.db
Schema: table candles(exchange, symbol, timeframe, ts_ms, open, high, low, close, volume, quote_volume, trades, taker_buy_base, taker_buy_quote, updated_at_ms)
PK (exchange, symbol, timeframe, ts_ms). Live rows for this bot: exchange='bybit', timeframe='5m', symbols BTCUSDT/ETHUSDT/BNBUSDT/SOLUSDT as deployed.

Goals:
1. In live mode, disable: bybit bootstrap_klines, BybitKlineWS candle append, background binance.append_candles (and Bybit history fallback used only to feed live DB).
2. Keep evaluate()/strategy/order path intact.
3. Change merge_candle_sources / load_candles so live reads OHLCV from the shared DB (filter exchange=bybit, matching symbol+5m). Map ts_ms → the timestamp format existing code expects.
4. Add env SHARED_CANDLES_DB defaulting to /var/lib/botsgeneral/shared_candles.db.
5. On missing/stale candles (e.g. last bar older than 2× interval), log error and skip new entries (do not crash-loop orders).
6. Do not change backtest scripts unless needed for shared path helpers.
7. Document VPS: pull, restart crypthor-*.service; collector must already be running.

Repo: C:\projects\crypthor2 → git@github.com:Xxobster/crypthor2.git
After code works locally in principle, commit and push; deploy to /opt/crypthor on 212.73.150.178 and verify bot still evaluates without opening its own kline WS.
```

---

## karmaa_mp

```
Context: Shared candle collector "botsgeneral" writes /var/lib/botsgeneral/shared_candles.db on VPS 212.73.150.178. karmaa_mp must stop acquiring candles and read that DB. Trading stays on Xxobster5 keys.

This bot is nearly identical to crypthor2 live candle flow.

Live need: bybit BTCUSDT 5m only.

Goals:
1. Disable live: bootstrap_klines, BybitKlineWS append_candle, background binance.append_candles.
2. Point merge_candle_sources / bybit_candles.load_candles (live) at shared DB via env SHARED_CANDLES_DB=/var/lib/botsgeneral/shared_candles.db.
3. Map shared columns → existing DataFrame columns (timestamp/open/high/low/close/volume).
4. Stale-data guard: if newest bar too old, skip entries and alert in logs.
5. Leave strategy, sizing, order_manager, trade_log unchanged.
6. Commit/push git@github.com:Xxobster/karmaa_mp.git; deploy /root/karmaa_mp on 212.73.150.178; restart karmaa-mp-live.service / screen; confirm no private kline fetch in logs.
```

---

## divergences

```
Context: Shared collector botsgeneral owns candle writes on VPS 212.73.150.178 at /var/lib/botsgeneral/shared_candles.db.

divergences already has CandlesRepository (table candles with exchange/symbol/timeframe/ts_ms/OHLCV) — closest fit.

Fleet: ETHUSDT 4h, BTCUSDT 4h, ETHUSDT 1h (exchange=bybit).

Goals:
1. In src/live/bybit_runner.py: disable REST _refresh_candles/ingest_symbol writes and WS upsert_candles into the local divergence_lab.db for live.
2. Point live CandlesRepository db_path to SHARED_CANDLES_DB (/var/lib/botsgeneral/shared_candles.db) OR add a read-only adapter that queries the shared schema (compatible columns; ignore extra Binance columns).
3. Keep WS only if still needed for mark price / position monitoring — do NOT use it to persist klines. Prefer removing kline persistence entirely.
4. run_cycle() must still load_candles and trade via existing Bybit credentials (Xxobster3).
5. Stale candle guard before signal generation.
6. Research/backtest may keep local data/divergence_lab.db; only live path switches.
7. Commit/push git@github.com:Xxobster/divergences.git; deploy /opt/divergences on 212.73.150.178; restart divergences screens/services; verify no ingest_bybit upserts during live.
```

---

## news (crypto_alpha)

```
Context: Shared collector botsgeneral on VPS 94.156.189.76 writes Binance OHLCV into /var/lib/botsgeneral/shared_candles.db.
xgb on the same VPS is NOT migrated and keeps its own Binance pull — ignore xgb.

news currently polls Binance via ingest_historical_klines into database/crypto_alpha.db raw_klines each signal cycle. That ingest must stop for live.

Live need: binance BTCUSDT 4h market=futures, including quote_volume/trades/taker_buy_* for features.

Shared schema columns match raw_klines fields (plus exchange). For reads: exchange='binance', symbol='BTCUSDT', timeframe='4h'.

Goals:
1. In crypto_alpha/live/live_loop.py _signal(): remove/disable ingest_historical_klines for live.
2. Make load_klines_df (or a thin wrapper) read from SHARED_CANDLES_DB and present the same DataFrame shape raw_klines did (ts_ms, ohlcv, quote_volume, trades, taker_buy_base, taker_buy_quote). You may keep writing a local cache ONLY if unavoidable — prefer pure read from shared DB.
3. Keep Bybit ticker WS + Bybit trading (Xxobster6) unchanged.
4. Env SHARED_CANDLES_DB=/var/lib/botsgeneral/shared_candles.db.
5. Stale-data guard (4h bar lag).
6. Commit/push git@github.com:Xxobster/news.git; deploy /home/crypto_alpha on 94.156.189.76; restart live screen/systemd; confirm logs show no Binance kline REST ingest each poll.
```

---

## W.I.P

```
Context: Shared collector botsgeneral on VPS 94.156.189.76 writes Bybit candles to /var/lib/botsgeneral/shared_candles.db.
W.I.P live currently keeps candles in RAM (REST seed + Bybit WS 1h/4h). Switch live to read shared DB.

Fleet: BTCUSDT long, ETHUSDT short, BNBUSDT short — decision on 4h, base series 1h.
Collector will store bybit 1h (and optionally 4h). Prefer load 1h from shared DB and keep existing resample/4h confirm logic, OR load 4h if present — match current signal_engine semantics.

Goals:
1. Replace bootstrap get_klines + periodic REST 1h refresh + in-memory WS candle append used for signal history with a loader from SHARED_CANDLES_DB (exchange=bybit, timeframe=1h, symbols from live_fleet.json).
2. Trigger evaluate on new 4h close: either watch shared DB freshness for 4h/1h or keep a lightweight public WS that only signals "bar closed" without being the data source of truth.
3. Do not use trading account for market data.
4. Trade log SQLite stays local. /etc/wip/bybit.env trading keys unchanged (Xxobster7).
5. Stale-data guard.
6. This project has no git remote — init/create GitHub repo if appropriate OR document rsync deploy; deploy to /opt/wip on 94.156.189.76; restart wip-live.service/screens; verify no REST get_klines spam each 4h.
```
