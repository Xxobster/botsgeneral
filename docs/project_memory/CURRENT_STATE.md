# Current State

**Last updated:** 2026-10-05 (winners avg PnL/trade + current equity)

Best winners table: **Avg PnL/trade** = mean closed-round-trip PnL for that pair.
**Equity** = current account total equity. Cache-bust `?v=20261005b`.

**Last updated:** 2026-10-05 (HMI pair winners; hide SM and LN3)

Public fleet page **https://bots94.duckdns.org/** shows **ln1 + ln2 only**.
SM and LN3 are not fetched or displayed. New section **Best winners by pair**
(VPS, bot, pair, trades, days, trades/day, PnL, WR, PF, RF, …) sits above
Open positions, sorted by profit factor. Live backup:
`/opt/botsgeneral/backups/hmi-20261005-pre-winners` on ln1.

**Last updated:** 2026-09-24 (HMI at site root on ln1 / bots94.duckdns.org)

Fleet Human-Machine Interface (HMI) hub lives on **ln1** `94.156.189.76`.
Public URLs (site **root**, not `/bots`): **https://bots94.duckdns.org/** and
**http://94.156.189.76/**. Login `admin` (password `/root/hmi_web_password` on ln1).
Agents on ln1 / ln2 / ln3 / sm; hub fans out over SSH (`/root/.ssh/hmi_hub`).
`sm` `212.73.150.149` no longer exposes any public HMI (hub disabled; `/bots` 404).

**Last updated:** 2026-09-24 (HMI hub moved to ln1 / cirlapp restored)

Fleet Human-Machine Interface (HMI) hub lives on **ln1** `94.156.189.76`.
Public URL: **https://cirlapp.duckdns.org/bots/** (DuckDNS A → `94.156.189.76`,
TLS via snap Certbot). Also `http://94.156.189.76/bots/`. Login `admin`.
Agents on ln1 / ln2 / ln3 / sm; hub fans out over SSH (`/root/.ssh/hmi_hub`).
Former hub host `sm` `212.73.150.149` no longer serves `/bots`.

**Last updated:** 2026-09-06 (HMI conf/risk columns + metric colors; cirl.duckdns DNS mismatch)

Fleet `http://212.73.150.149/bots/`: Active trades + Last 10 + Conf%/Risk% (from
LLM2 decide SQLite when present); account cards color realized/unrealized PnL,
profit factor (PF) and recovery factor (RF). Cache-bust `?v=20260906d`.

**`https://cirlapp.duckdns.org/bots/`** is the DuckDNS URL (domain name is
`cirlapp`, not `cirl`). TLS cert issued 2026-09-06; HTTP redirects to HTTPS.
`cirl.duckdns.org` is a different name and still points at `91.204.226.154`.

**Last updated:** 2026-09-06 (HMI main page: active trades, last 10, axes, trade counts)

Fleet dashboard `http://212.73.150.149/bots/` now shows **Active trades** and
**Last 10 trades** above Accounts; account cards show **Closed trades** count;
account Profit and Loss (PnL) curve has date (X) and money (Y) axis labels.

**Last updated:** 2026-09-04 (fleet Human-Machine Interface at `/bots`)

Fleet dashboard is live at `http://212.73.150.149/bots/` (HTTP basic auth).
Agents on ln1 / ln2 / ln3 / sm; hub on sm. First public fleet fetch ~6–13s
with warm closed-PnL cache. Grouping is **Xxobster account** (not install folder).

**Last updated:** 2026-08-25 (ln1 xgb / Xxobster2 removed from `bots`)

ln1 (`94.156.189.76`) host list is pivot + `xgb_match` + `tsm_vpa` +
`tsm_chandelier`. Retired Extreme Gradient Boosting / Xxobster2 is not in
`bots` / `bots sitrep`. Leftover Bybit positions remain on exchange
take-profit / stop-loss.

**Last updated:** 2026-08-05 (Yahoo tech equity daily panel)

**Tech equities (daily RESEARCH_PROXY):** frozen NDX-style list + QQQ via Yahoo →
`market_ohlcv.sqlite` (`source=yahoo`, `product=equity`). Refresh:
`python -m market_data.download_all --only yahoo_tech --timeframes 1d`.
Not delisting-aware / not full multi-TF free history.

**OI warehouse:** `D:\projectsdata\candles\market_oi.sqlite` — Binance Vision 5m (full
history for 14 research symbols; tip ~1m for all ~530 USDT perps) + Bybit V5
(`singleOpenInterest` as `oi`). CLI: `python -m market_data.download_oi` /
`botsgeneral research-oi [--all]`. Coverage CSV: `oi_coverage.csv`.

**tradesim hedge:** `research_sim_hedge()` / `position_mode="hedge"` — long and short may
be open together, each with own TP/SL. Default remains one-way.

**Indicators warehouse:** `D:\projectsdata\indicators\indicators.sqlite` — confirmed
swings, HH/HL structure, Fibonacci retracements, S/R distances for every series in
`market_ohlcv.sqlite`. Package: `packages/indicators`. Guide: `INDICATORS_GUIDE.md`.

**Research wallet:** **10_000 USDT** (margin-safe at 1× for BTC/ETH min size). Headline
money % = **return on invested notional**, not wallet %. Finplot: green/red entry→exit
price spans on exact bars; click entry for details including `pred_mean` when
`Signal.meta` was set (LLM packs); zones optional; custom panes via
`plot_backtest(extra_rows=…, on_axes=…)`. Limit entry:
`research_limit_entry_costs()` + `research_sim_limit_entry()` (maker, no slip).

**Leakage gate (new):** `C:\projects\botsgeneral\packages\leakage` — every agent must
run prefix-invariance / future-mutation via `leakage-check` or `run_leakage_audit`
before train/test. Guide: `docs/project_memory/LEAKAGE_TEST_GUIDE.md`. Also in
`TRADING_BOT_CURSOR_RULES_V2.zip`. xgb/LD not yet wired (migrate next).

**Research warehouse macros (new):** yields (FRED US02Y/US10Y/T10Y2Y), VIX, SPX/NDX,
crypto mcap/dominance, stablecoin mcap/flows, Fear & Greed — see CHANGELOG.
Refresh: `python -m botsgeneral.research_candles.download_all --only fred,yahoo,crypto_macro`.

## Phase

Collectors live for bots that opted in. **news** and **xgb** keep own Binance pulls.

**Candle roles (frozen):** Last (`binance`) for signals/fills/TP–SL; Mark (`binance_mark`)
for liquidation; both for go/no-go. See `DECISIONS.md`.

**Full reference:** `docs/project_memory/TRADESIM_ENGINE_AND_METRICS.md` (how the engine
runs + every metric formula, including why win rate < 50% is not automatically a loss).

**Metrics:** `MetricsReport.as_backtesting_stats()` mirrors kernc/`backtesting.py` keys
(plus longs/shorts, hold duration min/avg/max, SQN, Kelly, funding, HAC Sharpe).

**Candle refresh API:** `ensure_candles` / `tradesim-candles` — mandatory before every
backtest-versus-live comparison (`RULES.md`).

**Validation session:** `packages/tradesim/tools/validate_btc_session.py` ran against
BTCUSDT 1h (Last refreshed), 7 synthetic fills produced (entry-bar stop/TP observed),
xgb `audit_v4` path compared (expected named differences on forced OHLC), live log sample
from `C:\projects\xgb\log\btcusdt\trading.log` (5 latest placed trades listed).

**tradesim Phases 1 and 2 are complete and green. Phase 3 (per-repository migration) has
not started and is deliberately a separate session per repository.**

**Frozen how strategies talk to the engine:** see
`docs/project_memory/TRADESIM_BACKTEST_ENGINE_GUIDE.md` and
`STRATEGY_TO_TRADESIM_CONTRACT.md` (Binance candles / Bybit costs, next-open entry,
**limit TP/SL with no exit slip**, lower-TF same-bar resolution, historical funding,
**min exchange size** from Bybit instruments cache, 1× backtest leverage). Same guide is in
`C:\projects\BASE CURSOR\TRADING_BOT_CURSOR_RULES_V2.zip` as
`TRADESIM_BACKTEST_ENGINE_GUIDE.md`.

### Bybit instrument minimums (research sizing)

Fetched with account **Xxobster_local** (keys file under `BASE CURSOR`; secrets never cached)
into `D:\projectsdata\candles\bybit_instruments.sqlite`. Refresh:

```powershell
python -m tradesim.venue --account Xxobster_local refresh --from-registry
python -m tradesim.venue list
```

Registry pairs currently cached (USDT linear perpetuals; all `min_notional=5`):

| symbol | min_qty | qty_step | tick | max_lev |
|---|---:|---:|---:|---:|
| BTCUSDT | 0.001 | 0.001 | 0.1 | 100 |
| ETHUSDT | 0.01 | 0.01 | 0.01 | 100 |
| SOLUSDT | 0.1 | 0.1 | 0.01 | 100 |
| BNBUSDT | 0.01 | 0.01 | 0.1 | 50 |
| XRPUSDT | 0.1 | 0.1 | 0.0001 | 100 |
| DOGEUSDT | 1 | 1 | 1e-5 | 75 |
| ADAUSDT | 1 | 1 | 0.0001 | 75 |
| TRXUSDT | 1 | 1 | 1e-5 | 75 |
| XLMUSDT | 1 | 1 | 1e-5 | 50 |
| VETUSDT | 1 | 1 | 1e-6 | 25 |

`run_backtest(..., symbol="BTCUSDT")` or `research_instrument("BTCUSDT")` loads these into
`InstrumentSpec` for `SizingMode.MIN_EXCHANGE`.

### tradesim — the shared execution engine

Lives at `packages/tradesim`. One engine for every strategy, so an execution bug is fixed
once instead of four times, and so a backtest number can be traced to the engine that
produced it.

```powershell
pip install -e packages/tradesim[conformance]
pytest packages/tradesim/tests -q                                     # 104 passed
tradesim-conformance --engine tradesim --tests packages/tradesim/tests  # exit 0, 62/62
```

Current stamp: `tradesim 1.0.0 | contract perp_bracket_portfolio | fixtures c11352baf1cc |
62/62 identifiers | GREEN`. The commit field reads `UNKNOWN_DIRTY` until the tree is
committed, which is intentional: a number produced from an uncommitted tree is not
reproducible and the stamp says so.

**Status of the four engines** (full detail in `ENGINE_CONFORMANCE_BASELINE.md`):

| engine | fixtures | identifiers with a test binding | quotable? |
|---|---|---|---|
| tradesim | 50/50 | 62/62 | yes |
| xgb `audit_v4` | 15/50 | 0/62 | no |
| TSM-VPA `run_backtest` | 11/50 | 0/62 | no |
| LLM1 `simulate_path_exits` | 9/50 | 0/62 | no |

The three legacy engines all pass the simple entry-bar cases now, and all three still fail
EXEC-012 (ambiguity is resolved but never recorded) and EXEC-013 (entry-bar liquidation).
None of the three validates its input bars: all three accepted duplicated timestamps,
out-of-order timestamps, negative prices and a high below its low, and returned a trade.

**No live system was changed and nothing was committed.** tradesim depends on numpy and
pandas only and imports nothing from `botsgeneral`.

### Resume on tradesim

Phase 3 is one repository per session, in this order, each gated on a trade-by-trade parity
diff produced by `tradesim.parity`:

1. **TSM-VPA** — closest in shape (absolute brackets, isolated margin, funding), so the
   parity diff will be the most readable. Expect differences on gap-through stops
   (EXEC-004) and on leverage, which TSM-VPA derives from the stop rather than taking as
   configured.
2. **xgb** — expect differences on maker/taker fees (EXEC-003) and same-bar funding
   (EXEC-015).
3. **LLM1** — the largest change, because it works in return units and must move into
   quantity space to gain the whole QTY family.

### Architecture

**botsgeneral** writes shared OHLCV for migrated bots on each VPS. Separately, local research candles live at:

`D:\projectsdata\candles\market_ohlcv.sqlite`

Download / refresh:

```text
python -m botsgeneral.research_candles.download_all
python -m botsgeneral research-candles --only binance --symbols BTCUSDT --timeframes 5m
python -m botsgeneral research-candles --only binance --symbols BTCUSDT,ETHUSDT --timeframes 1m
```

`--timeframes 1m` fetches raw 1m (Vision archives + REST gap) and vectorially derives 1h/4h/1d/1w.

### BTC/ETH 1m (this machine)

| Symbol | 1m bars | 1m range | derived 1h / 4h / 1d / 1w |
|--------|---------|----------|---------------------------|
| BTCUSDT | 3,442,165 | 2020-01-01 → 2026-07-18 | yes |
| ETHUSDT | 3,442,171 | 2020-01-01 → 2026-07-18 | yes |

Vision has no 1m monthly zips before 2020-01 (2019-09..12 = 404).

### BTC/ETH candles / ENGINE-005

| source | price_type | product | source_endpoint |
|--------|------------|---------|-----------------|
| `binance` | `last` (legacy rows) | — | legacy/unset |
| `binance_mark` | `mark_price` | `USDⓈ-M` | `/fapi/v1/markPriceKlines` |

Mark history is stored separately from Last and never overwrites it. Mark 1m coverage starts
2020-01-01; 1h/4h/1d/1w are vectorially derived from Mark 1m.

Read-only verification:

```text
python -m botsgeneral.research_candles.verify_engine005
```

After repairing all gaps that Binance's endpoint could supply, Binance itself returns no rows
for 55 BTC and 66 ETH historical minutes (three shared outages plus 11 isolated ETH minutes).
These are left missing rather than silently fabricating liquidation-reference prices.

```text
python -m botsgeneral research-candles --only binance --symbols BTCUSDT,ETHUSDT --timeframes 1m --price-type mark
```

### Resume

1. Drop TradingView BTC.D CSVs into `D:\projectsdata\candles\imports\btcd\` if needed
2. Keep migrating remaining bots via AGENT_PROMPTS.md (except news/xgb)
3. If Binance/Vision blocked → activate VPN and re-run
