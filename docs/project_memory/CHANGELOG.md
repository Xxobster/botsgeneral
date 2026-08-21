# Changelog

## 2026-08-19 — Binance kline WebSocket + running-only demand

- Collector subscribes Binance USD-M klines on WebSocket (closed bars only);
  last-5 REST remains reconnect gap-fill. Bybit WS unchanged.
- Discover default is **running bots only**. Static llm2 leftover 1h/4h/1w/1m
  is not fetched unless a live pack/unit asks. Pivot `--pack` strategy.json
  is the demand source.
- Windows `BOTSGENERAL_VPS` default is `local` (live-pack scan for backtests).
- Do not bump `history_schema` for this change.

## 2026-08-05 — Finplot trade inspect shows LLM prediction (pred_mean)

- `Trade.meta` freezes `Signal.meta` at open (engine → trade); SQLite store
  persists `meta_json` when saving runs.
- Click-inspect popup shows primary score keys (`pred_mean`, `p_hat`, `edge`, …)
  plus size/book context when present.
- Optional plot overlays: `plot_backtest(predictions={entry_ts_ms: float}, …)` or
  `trade_annotations` if meta was not on the trade.
- LLM2 signal builders stamp signed `pred_mean` (+ `abs_mean`) into signal meta
  for multitrade / single-book / translate paths.

## 2026-08-05 — Finplot entry→exit trade spans

- `tradesim.research.plot`: each position is a solid line from
  (entry bar, entry price) → (exit bar, exit price); green if
  realized PnL > 0, red otherwise; circle at entry, cross at exit.
- Default `trade_style` remains lines/spans; zones still add the hold box.
- Same-bar exits bump the span one bar so the segment is still visible.
- Tests: span endpoints + color; same-bar span unit test.

## 2026-08-21 — Fleet report: risk metrics + open detail

- Replace headline `Sharpe(trades)` with **RF** (recovery factor =
  realized/|MaxDD|), **MaxDD%** (drawdown vs peak closed-PnL equity curve),
  and **Payoff** (avg win / |avg loss|). Trade Sharpe remains in JSON only —
  poor live-risk signal for small n / mixed hold times.
- Open positions: `opened=` UTC time + `to_TP`/`to_SL` % distance to the
  nearer exit (Bybit `takeProfit`/`stopLoss` vs mark).
- Under opens: `last_open SYMBOL @ timestamp` (live open preferred, else
  latest closed entry).
- Bybit position fetch now includes mark/TP/SL/createdTime.

## 2026-08-05 — Collector always-on (enable + ensure timer)

- Service: `StartLimitIntervalSec=0` so crash-loop never stops restarts;
  `Restart=always` kept.
- Timer every 2 min: `botsgeneral-collector-ensure.timer` re-enables and
  starts the host collector if someone stopped/disabled it.
- Install: `bash deploy/install_collector_always_on.sh <VPS_IP>` on each host.

## 2026-08-05 — Purge unused shared series; register LLM2 on VPS 94

- Registry: VPS `94.156.189.76` bots include `llm2` (primary live fleet was already
  there; collector had only been serving tsm-vpa, leaving Binance stale).
- CLI: `botsgeneral purge-unused-candles` (+ `--dry-run`) keeps only discovered
  series so leftover Binance/Bybit rows cannot diverge calculations.
- CLI: `botsgeneral prune-incomplete-tips` — delete still-forming tip bars (collector
  also prunes after every upsert/poll). Fixes stale mid-week 1w leftovers.
- Goal remains closed-bar OHLC identity with `market_ohlcv` (schemas stay separate).
- Purged leftovers on 94/212/185; sample OHLC history checks green for served Binance.

## 2026-08-05 — Shared Binance candles baked onto market_ohlcv fetcher

- Live collector `botsgeneral.fetch.binance_rest` calls
  `market_data.fetch_binance.fetch_klines(..., price_type=last)` — one download
  path for research warehouse and `shared_candles.db` (schemas stay separate).
- Closed-bar + junk policy shared (`drop_incomplete_bars` / `drop_junk_bars`);
  forming tip never written. Bybit REST also drops incomplete tip.
- CLI gate: `botsgeneral compare-closed-bars` (shared tip OHLC vs warehouse tip).
- `history_schema` → `"6"` to force re-backfill after bake on all VPS collectors.
- Deployed to collectors `@94` / `@212` / `@185` (active). VPS 185 LLM2 Binance
  tips (BTC/ETH/SOL × 1h/4h/1w) closed-bar OHLC-identical to live fapi Last
  (= `market_ohlcv` tip after heal). VPS 212 news `binance:BTCUSDT:4h` tip OK.

## 2026-08-05 — VPS 185: LLM2 Binance structure candles

- Registry: VPS `185.203.119.52` bots = `[llm2]` (`serve_candles: true`, Binance
  futures Last; BTC/ETH/SOL @ 1h + `also_fetch` 4h/1w). Path `/home/llm2`.
- `history_schema` bumped to `"5"` to force full backfill on collector start.
- Collector `botsgeneral-collector@185.203.119.52` **enabled/active**; discovered
  9 pairs; bootstrap complete (e.g. BTC 1h ~60k bars).
- Docs: SHARED_CANDLES_READER + VPS map for LLM2 (replaces empty-bot LD-only note).

## 2026-08-05 — Yahoo tech equity daily panel (frozen NDX-style)

- `YAHOO_TECH_EQUITY` universe (~100 names + QQQ), frozen 2026-08-03 — survivors bias;
  RESEARCH_PROXY via Yahoo free daily history (not CRSP point-in-time).
- CLI: `python -m market_data.download_all --only yahoo_tech --timeframes 1d`
  (alias `tech_equity`); also included under `--only yahoo`.
- Symbols filter: `--symbols AAPL,MSFT,NVDA`. Default equity TF: **1d**.
- Index helper: `NDX100` → `^NDX` (legacy `NDX` remains `^IXIC` composite).
- Rows: `source=yahoo`, `product=equity` in `market_ohlcv.sqlite`.

## 2026-08-05 — Finplot click-to-inspect (default tidy chart)

- `trade_labels="none"` (default): no piled outcome tags on the chart.
- Left-click an **entry candle** opens a small trade detail panel (side, reason,
  hold, qty, prices, pnl, fees); empty bars open full metrics. Reuses one dialog
  per key (`trade_inspect` / `metrics`).
- `trade_labels="on_chart"` restores the previous piled tags.

## 2026-08-04 — Metrics: exit counts TP / SL / other

- Headline + stats: `n_exits_tp`, `n_exits_sl`, `n_exits_other` (entry-bar suffix
  stripped; stop/trailing/break-even = SL; target = TP; rest = other) plus per-reason
  `exit_reason_counts`.

## 2026-08-04 — Chart labels readable + simultaneous open metrics

- Finplot: floored row step (no smudge), entry-bar piles, collapse dense clusters
  to `+N more entries`, cap outcome tags, constant TP/SL % only in metrics
  (mixed % once per unique level).
- Metrics: max/avg simultaneous open trades, total and long/short (time-weighted);
  headline + `as_backtesting_stats`.

## 2026-08-04 — Finplot: piled entry-bar tags; constant TP/SL % only in metrics

- Outcome lines (side / reason / hold / qty / pnl) start at the **entry bar** and
  pile upward (wins) or downward (losses) with pixel row spacing that reflows on zoom.
- When every trade uses the same take-profit / stop-loss %, those % tags are **not**
  drawn on the chart (lines/boxes still drawn); shown once in the metrics window.
- Mixed TP/SL % still labels each level, side-aware (long TP above, SL below, short
  mirrored).

## 2026-08-04 — Finplot labels: side-aware TP/SL + zoom-adaptive stack

- Take-profit / stop-loss tags sit on the level: long TP above, long SL below;
  short TP below, short SL above (pyqtgraph text anchors, not win/loss offset).
- `AdaptiveLabelBoard` packs overlapping labels in **pixel** space and re-layouts on
  view range changes so zoom keeps rows tight but readable.
- Outcome tags still green/red; wins stack up, losses down; levels pack first.
- Tests: `tests/test_plot_finplot.py`.

## 2026-08-03 — Research open interest warehouse (`market_oi.sqlite`)

- New OI downloader in `market_data`: Binance Vision daily metrics (5m, multi-year) +
  REST tip (`openInterestHist`), Bybit V5 `/market/open-interest` with cursor pagination.
- DB: `D:\projectsdata\candles\market_oi.sqlite`, PK `(exchange, symbol, timeframe, ts_ms)`.
- Fields: `oi` (base-asset; Bybit=`singleOpenInterest`), `oi_usd`, `oi_sum` (Bybit both-sides),
  plus Binance long/short ratio columns from Vision metrics.
- CLI: `python -m market_data.download_oi` / `botsgeneral research-oi`
  (`--all` discovers all USDT linear perps; majors get full history, others tip/1d).
- Tests: `packages/market_data/tests/test_oi.py` (4 passed).

## 2026-08-03 — Hedge mode (long + short together) + RULES_V2

- `PositionMode.HEDGE` / `research_sim_hedge()`: one long and one short may be open on the
  same symbol at once, each with its own take-profit and stop-loss.
- One-way default unchanged (second signal → `SKIP_POSITION_LIMIT`).
- Docs: guide §3.2, RULES, trading-bot-core; rebuilt RULES_V2 zip.
- Tests: `tests/test_hedge_mode.py` (4); full suite 139 passed.

## 2026-08-03 — Shared `indicators` package (Fibonacci price structure) + RULES_V2

- New package `packages/indicators`: confirmed swings, HH/HL/LH/LL, leg lengths,
  Fibonacci retracements/extensions, distance to confirmed S/R.
- Warehouse: `D:\projectsdata\indicators\indicators.sqlite` (tables: swings,
  structure_events, legs, levels, bar_features, series).
- CLI: `indicators update` / `update-all` / `coverage` / `show`; API:
  `compute_structure`, `update_series`, `update_all`, `IndicatorDB`.
- Docs: `INDICATORS_GUIDE.md`; RULES + trading-bot-core; rebuilt
  `TRADING_BOT_CURSOR_RULES_V2.zip`.
- Tests: 3 passed. `update-all` run over candle warehouse structure TFs.

## 2026-08-03 — Limit entry (maker fee, no slippage) + RULES_V2 zip

- `EntryOrder.LIMIT` / `SimConfig.entry_order` / `Signal.entry_order` (+ `limit_price` /
  `limit_offset`): Post-Only style fill at limit when touched, **maker** fee, **no**
  entry slip; crossing → `SKIP_LIMIT_WOULD_CROSS`, miss → `SKIP_LIMIT_NOT_FILLED`.
- Helpers: `research_limit_entry_costs()`, `research_sim_limit_entry()`; real Bybit
  `RESEARCH_MAKER_RATE=0.0002` (research costs no longer force maker=taker).
- Docs: RULES, TRADESIM guide §3.1, trading-bot-core; rebuilt
  `C:\projects\BASE CURSOR\TRADING_BOT_CURSOR_RULES_V2.zip`.
- Tests: `tests/test_limit_entry.py` + full suite 135 passed.

## 2026-08-02 — Finplot extra panes / on_axes hooks + RULES_V2 zip

- `plot_backtest(..., extra_rows=, extra_row_heights=, on_axes=)` returns `PlotView`
  (`ax_equity`, `ax_price`, `extra_axes`, clipped frames) so programs can add RSI /
  volume / custom overlays without a private Finplot fork.
- Documented in `RULES.md` Visualization, `TRADESIM_BACKTEST_ENGINE_GUIDE.md`,
  `trading-bot-core.mdc`; rebuilt `C:\projects\BASE CURSOR\TRADING_BOT_CURSOR_RULES_V2.zip`.
- Tests: `tests/test_plot_finplot.py` (extra rows + callback; 5 passed).

## 2026-08-02 — Research wallet 10k + ROI on invested notional

- `$100` at 1× rejects BTC min-size opens (margin / 60% utilisation). Default
  `RESEARCH_STARTING_EQUITY_USDT` is **10_000** again.
- Metrics headline: **net PnL USDT** and **return_on_invested** =
  `net_pnl / sum(entry_notional)`; wallet `%` is secondary.
- Helper: `research_starting_equity(price=..., qty=..., leverage=1)`.

## 2026-08-02 — tradesim auto-update + line/cross Finplot

- `ensure_latest_tradesim(update=True)` / CLI `tradesim-update` re-installs editable
  botsgeneral tradesim into the current environment and pins `sys.path`.
- Finplot default `trade_style="lines"`: ±3-bar horizontals + cross at entry/SL/TPn;
  labels LONG|SHORT, SL, TP1…; green=win, red=loss (no filled boxes).
- Prompt: `docs/project_memory/TRADESIM_PROGRAM_PROMPT.md` + `AGENT_PROMPTS.md`.

## 2026-08-02 — Per-VPS PuTTY/OpenSSH keys (ln1/ln2/ln3/sm)

- Generated dedicated Ed25519 keypairs for aliases `ln1` `ln2` `ln3` `sm`
  (IPs 94.156.189.76, 212.73.150.178, 185.203.119.52, 212.73.150.149).
- Files under `%USERPROFILE%\.ssh\` (not in git): `{alias}`, `{alias}.pub`, `{alias}.ppk`.
- Installed + verified public keys on ln1/ln2/ln3/sm (OpenSSH). ln1 was later
  reachable and completed 2026-08-02.
- `~\.ssh\config` Host entries for the four aliases; `docs/project_memory/VPS.md` updated.

## 2026-08-01 — Shared `leakage` package + RULES_V2 update

- Added `packages/leakage` (prefix-invariance, future-mutation, forward-corr,
  name-scan, train/test geometry, `LEAKAGE_POTENTIAL` registry, CLI `leakage-check`).
- Tests: 10 passed.
- Docs: `LEAKAGE_TEST_GUIDE.md`; Research Standard V2 §7.5; `trading-bot-core.mdc`
  leakage gate; rebuilt `C:\projects\BASE CURSOR\TRADING_BOT_CURSOR_RULES_V2.zip`.
- xgb / LD wiring deferred (migration prompts for those repos).

## 2026-08-01 — VPS 185 shared Binance 1h for LD groups

- Collector serves `binance` 1h BTC/ETH/SOL/BNB for all LD account groups (9/10/11).
- Upsert: insert-only history; overwrite same bar only when OHLCV/aux differs.
- Reader API: `botsgeneral.reader` + `SHARED_CANDLES_READER.md` + AGENT_PROMPTS `ld`.

## 2026-08-01 — VPS 185.203.119.52 (LD)

- Installed `bots` CLI; pinned `/etc/botsgeneral/vps_id`.
- Registry: `ld` + optional `xgb`/`xgb_match`; all `serve_candles: false`.
- Shared candle collector **disabled** — LD fetches Binance klines itself.

## 2026-07-31 (tradesim latest-engine rule in RULES_V2 zip)

- trading-bot-core + RESEARCH_STANDARD §4.4 + RULES: every program must use latest
  `C:\projects\botsgeneral\packages\tradesim` via `prefer_botsgeneral_tradesim()`,
  `run_backtest` + report folders, reopen with `tradesim-research open` (no resim).
- Rebuilt `C:\projects\BASE CURSOR\TRADING_BOT_CURSOR_RULES_V2.zip`.

## 2026-07-31 (tradesim full report folders)

- Every `run_backtest` writes `D:\projectsdata\backtests\reports\{run_id}\`
  (REPORT.md, strategy.json with name/batch/model path/TP/SL, metrics, trades.csv)
  plus the existing SQLite store with embedded bars.
- Reopen without re-sim: `tradesim-research open --run-id …` (full-period chart + metrics).
- Finplot default `max_bars=0` = whole period; strategy details shown in metrics window.
- Interactive terminals open chart+metrics automatically (`TRADESIM_NO_PLOT=1` to disable).

## 2026-07-31 (macro training rule + incremental fetch)

- RULES / trading-bot-core / RESEARCH_STANDARD_V2: training must use shared
  `market_ohlcv` macros; live must refresh pack-referenced macros; skip fresh series.
- `download_all` skips yahoo/fred/crypto_macro series still inside freshness windows.
- `cross_pair_live` skips recently updated macros and bounds Yahoo lookbacks; VPS deploy
  for xgb + xgb_match.
- Rebuilt `C:\projects\BASE CURSOR\TRADING_BOT_CURSOR_RULES_V2.zip` with the same rule text.

- Research DB (`market_ohlcv.sqlite`) gains: FRED **US02Y / US10Y / US03M / T10Y2Y**,
  Yahoo **VIX / SPX / NDX / DJI** (+ TNX/FVX/TYX/IRX yield cross-checks), CoinGecko
  **BTC_MCAP / ETH_MCAP / TOTAL_MCAP / BTC.D / ETH.D**, DefiLlama **STABLE_MCAP /
  STABLE_FLOW / USDT_MCAP / USDC_MCAP / DAI_MCAP**, alternative.me **FNG**.
- New fetchers: `fetch_fred.py`, `fetch_crypto_macro.py`. Download via
  `python -m botsgeneral.research_candles.download_all --only fred,yahoo,crypto_macro`.

## 2026-07-31 (multi metrics windows + multi-TP on chart)

- Every Finplot chart opens its own cascaded metrics dialog (callers no longer
  suppress all but the first). Click still reopens that chart's metrics.
- Multi-leg take-profit: engine freezes `Trade.tp_levels`; plotter draws a dashed
  line + label for each level (and markers on TP fills).

## 2026-08-01 (Finplot: zones only, no trade icons/legend)

- Price pane: always draw take-profit / stop-loss zones by default (`max_zone_trades=0`
  = all visible trades); remove triangle/cross/circle entry-exit icons; remove the
  long trade-pane legend. Equity pane legend unchanged.
- Explains why other projects now see green/red boxes: they call shared
  `tradesim.research.plot.plot_backtest`.

## 2026-07-31 (plot: no zone borders + realized equity curve)

- Finplot zones: remove white RectROI border and entry midline between TP/SL fills.
- Equity pane defaults to **realized** step curve (moves on closed trades only).
  Formal Sharpe/drawdown still use mark-to-market; pass `equity_mode="mtm"` to plot MTM.

## 2026-07-31 (zones + $100 + save/reload)

- **Zones invisible root cause:** Finplot `add_rect`/`add_line`/`add_text` mis-convert
  pandas Timestamps (width collapsed to ~0.01). Plotter now uses candle **integer
  indices** for take-profit / stop-loss bands, lines and labels.
- Screenshot wallet 10k came from **xgb `plot_freq_hunt_packs` / `tradesim_freq_hunt`**
  still hardcoding `starting_equity=10_000` (not a stale tradesim). Both now use
  `RESEARCH_STARTING_EQUITY_USDT` (100).
- `prefer_botsgeneral_tradesim()` / `assert_botsgeneral_tradesim()` so programs refuse
  a non-botsgeneral install.
- `BacktestStore` embeds OHLC + `bars_fingerprint` / `run_fingerprint`; CLI
  `tradesim-research plot --run-id …` reloads chart+metrics without re-simulating.

## 2026-07-26 (plot dark fix + $100 research wallet)

- Finplot price pane stayed white because finplot paints odd rows with
  `odd_plot_background` (default `#eaeaea`). Now both panes use `#131722`, equity
  height ~20% (`axis_height_factor`), TP/SL zones more visible.
- Research starting equity frozen at **100 USDT** (`RESEARCH_STARTING_EQUITY_USDT`);
  xgb live-model backtest script updated.

## 2026-07-26 (mandatory latest tradesim)

- RULES + DECISIONS: all strategy programs must use latest `C:\projects\botsgeneral\packages\tradesim`
  (editable install / path), prefer botsgeneral research venv when newer; no local engine forks.

## 2026-07-26 (xgb uses tradesim TV plot)

- Root cause of white charts / missing features from xgb: `scripts/tradesim_backtest_live_models.py`
  still used a local marker-only Finplot helper. It now calls `tradesim.research.plot.plot_backtest`.
- Candle invisibility: default Finplot bull body is white-on-white; also LOD on long histories.
  Fixed with filled teal/red bodies + higher `lod_candles`. TP/SL zones capped on huge trade sets.

## 2026-07-26 (TradingView-style finplot)

- Dark background; TP/SL translucent zones (~10% opacity); entry/SL/TP lines; % labels;
  markers snapped to candle opens (fixes floating triangles); click opens full metrics
  window. `run_backtest(..., plot=True)` passes metrics into the plotter.

## 2026-07-26 (finplot equity + legend)

- Finplot review now matches `backtesting.py` layout: **equity panel on top**, price below;
  Peak / Final / Max-drawdown markers; win/loss trade lines; explicit icon legend.

## 2026-07-26 (engine + metrics documentation)

- Added `TRADESIM_ENGINE_AND_METRICS.md`: full simulation flow, every metric formula,
  and an explicit win-rate FAQ (win rate < 50% ≠ automatic loss; expectancy / payoff
  decide profitability). Linked from the strategy engine guide.

## 2026-07-26 (metrics + candle ensure + validation)

- Expanded `tradesim.metrics` to cover kernc/`backtesting.py` stats (durations, SQN,
  Kelly, buy&hold, volatility, avg drawdown, equity peak, long/short split, streaks) plus
  `MetricsReport.as_backtesting_stats()`.
- `ensure_candles` / CLI `tradesim-candles`: any program can refresh Last+Mark for the
  symbols/timeframes a backtest needs. RULES: every BT-vs-live comparison must refresh
  candles first.
- Validation tool: `packages/tradesim/tools/validate_btc_session.py` (synthetic 10-case
  session + xgb path + live log sample from `C:\projects\xgb\log\btcusdt\trading.log`).

## 2026-07-26 (Last vs Mark)

- Frozen: **Last** OHLCV for fills and (Last-triggered) TP/SL; **Mark** for liquidation;
  **both** for go/no-go. Mark-only backtests forbidden. See `DECISIONS.md`.

## 2026-07-26 (Bybit min position size)

- `tradesim.venue`: pull USDT-perp `minOrderQty` / `qtyStep` / `minNotionalValue` /
  `tickSize` via Bybit V5 using **Xxobster_local**; cache SQLite at
  `D:\projectsdata\candles\bybit_instruments.sqlite`.
- CLI: `python -m tradesim.venue refresh --from-registry` (or `--symbols`, `--all-linear`).
- `research_instrument(symbol)` / `run_backtest(symbol=...)` feed `MIN_EXCHANGE` sizing.
- Refreshed 10 registry pairs; all currently require **5 USDT** minimum notional.

## 2026-07-26 (research runner)

- Research defaults: **100 USDT** wallet (was 10_000; updated 2026-07-26), **min exchange size**, wallet-blown flag with
  timestamp, full metrics persisted per `strategy_id` in SQLite.
- New API: `tradesim.run_backtest(..., store_path=..., plot=True)` and CLI
  `tradesim-research list|show|trades`. Optional Finplot via `tradesim[plot]`.
- Not a third-party `backtest.py` — metrics come from `tradesim.metrics`.

## 2026-07-26

- TP/SL execution policy corrected: **limit fills at the level, no exit slippage**; entry
  still next-open + entry slip; taker fees; timeout may still slip.
- Added **`TRADESIM_BACKTEST_ENGINE_GUIDE.md`** for strategy repos (also packed into
  `TRADING_BOT_CURSOR_RULES_V2.zip`). Updated `STRATEGY_TO_TRADESIM_CONTRACT.md`.

## 2026-07-25

- Frozen **`STRATEGY_TO_TRADESIM_CONTRACT.md`**: what every strategy must emit, and the
  default execution policy (next open, all-taker market TP/SL, lower-TF resolution, historical
  funding, fixed size, Binance OHLCV research / Bybit live costs).
- New distribution **`packages/tradesim`**: the shared trade-execution engine for every
  strategy repository. Installable with `pip install -e packages/tradesim`, depends on
  numpy and pandas only, imports nothing from `botsgeneral`. No live system touched, no bot
  migrated yet.
- **Conformance pack built first**, as mandated: `registry.py` (62 identifiers across DATA,
  CAUS, EXEC, FUND, QTY, METR, VALD, PORT), 50 hand-computed golden fixtures,
  `adapter.py`, `checker.py`, `stamp.py`, and the `tradesim-conformance` console script.
  A missing test binding is graded exactly like a failing test.
- **Engine modules**: `exits.py` (the single shared bar-resolution function), `engine.py`
  (chronological loop, single symbol and shared-wallet portfolio), `fees.py`, `funding.py`,
  `margin.py`, `sizing.py`, `metrics.py`, `parity.py`, `contracts.py`.
- Capabilities: two timeframes with a decision bar and an optional touch bar; entry at next
  open, next close or same close; stop, target, multi-leg partial take-profits, trailing
  stop, break-even stop, maximum hold, liquidation, end-of-data flatten; isolated and cross
  margin; fixed quantity, fixed notional and risk-fraction sizing; per-fill maker/taker
  fees; historical funding inside the loop.
- **104 tests pass in a clean virtual environment; `tradesim-conformance --engine tradesim
  --tests packages/tradesim/tests` exits zero at 62/62 identifiers.**
- **Defect demonstration:** reintroducing entry-bar immunity fails 13 identifiers including
  the required EXEC-010, EXEC-012 and EXEC-013. Reverted; engine.py restored byte-for-byte.
- **Missing-binding demonstration:** deleting the EXEC-014 tests leaves all 50 fixtures
  passing and still fails the run for a missing binding. Restored.
- **`ENGINE_CONFORMANCE_BASELINE.md`**: all four engines graded. tradesim 50/50 fixtures and
  62/62 bound identifiers; xgb 15/50; TSM-VPA 11/50; LLM1 9/50; and **none of the three
  legacy engines binds a single identifier**, so no number any of them produces is quotable
  today. Foreign grading adapters live in `packages/tradesim/adapters/`.
- `DECISIONS.md` records all eleven places xgb and LLM1 disagreed and which behaviour won.

## 2026-07-23

- XLMUSDT **15m** Last + Mark loaded (Vision + REST gap fill after Binance came back).

## 2026-07-22

- SOLUSDT **15m** Last + Mark loaded into `market_ohlcv.sqlite` (`binance` / `binance_mark`).

## 2026-07-19

- Binance **mark price** klines: REST `/fapi/v1/markPriceKlines` + Vision `markPriceKlines`; stored as `source=binance_mark` (last remains `source=binance`).
- CLI: `--price-type last|mark|both`. BTCUSDT/ETHUSDT mark **1m** + derived 1h/4h/1d/1w loaded.
- ENGINE-005 provenance migration: `price_type=mark_price`, `product=USDⓈ-M`, and
  `source_endpoint=/fapi/v1/markPriceKlines` on all `binance_mark` rows.
- Repaired 12,960 BTC and 4,320 ETH missing Mark minutes from REST. Remaining Binance-source
  gaps (55 BTC / 66 ETH minutes) return no rows from the official endpoint and are not fabricated.
- Added read-only `verify_engine005` and vectorized gap detection/repair utilities.

## 2026-07-18

- BTCUSDT + ETHUSDT **1m** raw via Binance Vision monthly/daily zips + REST gap fill; vectorized derive **1h/4h/1d/1w**.
- `--timeframes 1m` supported; Vision used automatically for large 1m backfills (REST alone too slow).

## 2026-07-16

- Local **research candle warehouse** at `D:\projectsdata\candles\market_ohlcv.sqlite`.
- New package `botsgeneral.research_candles`: Dukascopy (DXY/HKG40/gold/oil/FX), Yahoo (HSI + futures cross-checks), Binance futures (project crypto universe), BTC.D (TradingView CSV import + CoinGecko approx).
- CLI: `python -m botsgeneral research-candles` or `python -m botsgeneral.research_candles.download_all`.
- Native 1h/1d from Dukascopy; vectorized 4h from 1h and 1w from 1d. Binance stores native 5m/15m/1h/4h/1d/1w.

## 2026-07-13 (evening)

- Max candle history (`history_bars: 0` + `history_schema: 3`) — paginate until exchange empty.
- Phone report: `bots` / `bots trades <account|bot> [SYMBOL]`; since date in `/etc/botsgeneral/report.yaml`.
- Disk cleanup script `deploy/cleanup_disk.sh`.
- Confirmed architecture: botsgeneral = OHLCV only; each trading bot computes its own indicators and decides.
