# Changelog

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
