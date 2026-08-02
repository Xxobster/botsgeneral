# Copy-paste prompts for project agents

Skip **xgb** — it keeps Binance self-fetch.

**Standing rules (prepend mentally to every prompt):**  
Follow `C:\projects\botsgeneral\docs\project_memory\RULES.md` and keep that project’s `docs/project_memory/` updated. Prefer WebSocket, SQLite trade logs, screen+systemd auto-restart, vectorized code, walk-forward backtests locally only, max leverage + min size live unless told otherwise, maker fees when possible, TP ladder + BE from fill price, finplot for visuals, full sitrep metrics live vs backtest.

---

## crypthor2

```
Context: We are consolidating candle acquisition. A new service "botsgeneral" runs ONE collector per VPS and writes a shared SQLite DB. This bot must STOP fetching/writing candles and READ from that DB instead. Trading (Bybit orders) stays on this bot's own API keys.

Also respect standing stack rules in C:\projects\botsgeneral\docs\project_memory\RULES.md and update this project's docs/project_memory/.

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

Also respect standing stack rules in C:\projects\botsgeneral\docs\project_memory\RULES.md and update this project's docs/project_memory/.

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

Also respect standing stack rules in C:\projects\botsgeneral\docs\project_memory\RULES.md and update this project's docs/project_memory/.

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

Also respect standing stack rules in C:\projects\botsgeneral\docs\project_memory\RULES.md and update this project's docs/project_memory/.

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

Also respect standing stack rules in C:\projects\botsgeneral\docs\project_memory\RULES.md and update this project's docs/project_memory/. Use screen with explicit names; systemd auto-restart on reboot.

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

---

## ld (VPS 185.203.119.52)

```
Context: Three LD account groups (Xxobster9 / Xxobster10 / Xxobster11) run the same four pairs (BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT) on 1h. Old live code fetched Binance **spot** klines (`api.binance.com`). Research packs were trained from `market_ohlcv` with `source='binance'` = Binance **USD-M futures Last** (`fapi`). botsgeneral shared collector on this VPS writes that same futures series. Stop spot REST; read shared DB so live features match train/test candles.

Also respect standing stack rules in C:\projects\botsgeneral\docs\project_memory\RULES.md and the reader contract in C:\projects\botsgeneral\docs\project_memory\SHARED_CANDLES_READER.md. Update this project’s docs/project_memory/.

Shared DB (VPS 185.203.119.52): /var/lib/botsgeneral/shared_candles.db
Env: SHARED_CANDLES_DB=/var/lib/botsgeneral/shared_candles.db

Live need (all groups share these rows — same product as research warehouse):
  exchange = 'binance'   # USD-M futures Last (fapi) — matches market_ohlcv source=binance
  timeframe = '1h'
  symbols = BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT
  Do NOT use api.binance.com spot for features.

Schema PK (exchange, symbol, timeframe, ts_ms). Columns: open,high,low,close,volume + quote_volume/trades/taker_buy_* + updated_at_ms.
Writer upserts: inserts new bars; overwrites same ts_ms only when OHLCV/aux values change (exchange corrections). Never wipe history.

Helper (on VPS, PYTHONPATH=/opt/botsgeneral):
  from botsgeneral.reader import load_ohlcv, is_fresh
  df = load_ohlcv("binance", symbol, "1h", limit=6000)

Goals:
1. In ld/live/runner.py and ld/live/crosspair_runner.py: stop calling fetch_recent / Binance REST for strategy history. Keep sleep-until-1h-close scheduling.
2. Load completed 1h bars from SHARED_CANDLES_DB (prefer botsgeneral.reader.load_ohlcv). Map to the same DataFrame shape compute_live_features expects (DatetimeIndex UTC + ts_ms/OHLCV). Drop incomplete bar using open+1h <= now (same as drop_incomplete_bar).
3. Optional: keep writing a local cache sqlite under database/assets_live ONLY as a read-through cache of the shared DB — do not be the source of truth and do not call Binance for it.
4. Stale guard: if not is_fresh("binance", symbol, "1h", max_lag_bars=2), log and skip new entries (orders stay closed).
5. Bybit trading (xxobster9/10/11 via config/api_keys.json) unchanged.
6. HTF features continue to resample from the 1h series (no separate HTF fetch required).
7. Deploy /home/ld on 185.203.119.52; restart ld-live@*.service and ld-live-crosspair.service; confirm logs show no api.binance.com/api/v3/klines traffic and features still compute after each 1h close.
8. Confirm collector is up: `bots sitrep` shows binance BTC/ETH/SOL/BNB 1h fresh; `systemctl is-active botsgeneral-collector@185.203.119.52`.
```

---

## tradesim (any strategy repo — auto-update + Finplot)

Full prompt: `docs/project_memory/TRADESIM_PROGRAM_PROMPT.md`

```
Context: botsgeneral owns the shared backtest engine `tradesim` at
C:\projects\botsgeneral\packages\tradesim. Strategy programs must NOT vendor a
simulator and must NOT rely on a stale site-packages wheel.

Obey C:\projects\botsgeneral\docs\project_memory\RULES.md and
TRADESIM_BACKTEST_ENGINE_GUIDE.md. Update this project's docs/project_memory/.

Goals:
1. At the top of every backtest / plot / hunt entry script (before other tradesim
   imports), bootstrap the latest engine:

   import sys
   from pathlib import Path
   sys.path.insert(0, str(Path(r"C:\projects\botsgeneral\packages\tradesim\src")))
   from tradesim.ensure_source import ensure_latest_tradesim
   print(ensure_latest_tradesim(update=True))  # pip install -e + path pin

   Or CLI once per environment:
   tradesim-update
   python -m tradesim.ensure_source --update

2. Use tradesim for simulation, metrics, Finplot, candle ensure, venue sizing:
   run_backtest / simulate / compute_metrics / plot_backtest / ensure_candles.
   Do not keep a private Finplot helper.

3. Finplot defaults (shared plotter):
   - equity pane: realized step curve
   - price pane: short horizontal levels (±3 bars) with a cross at entry, SL,
     TP1/TP2/TP3; labels LONG|SHORT, SL, TP1…; green=winning trade, red=losing
   - no filled green/red boxes unless trade_style="zones"
   - no price-pane trade legend

4. Research wallet default is **10_000 USDT** (`RESEARCH_STARTING_EQUITY_USDT`) so
   1× + venue min size never fails margin on BTC/ETH. Headline money % is
   **return on invested notional**, not wallet %. Override only with
   `research_starting_equity(price=..., qty=..., leverage=1)` if you need a floor.

5. Before quoting numbers: tradesim conformance GREEN in the same environment.
   Save runs via BacktestStore / run_backtest store; reopen with
   tradesim-research open --run-id …

6. Do not deploy/live-change without explicit user authorization.

Deliverable: scripts updated, a one-line print of tradesim version+path on start,
and project memory note that this repo auto-updates tradesim via ensure_latest_tradesim.
```
