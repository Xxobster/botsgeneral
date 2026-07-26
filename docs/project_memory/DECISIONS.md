# Decisions

## 2026-07-26 — TP/SL are limits with no exit slippage

User correction to the 2026-07-25 contract:

- Take-profit and stop-loss are **limit** orders: fill at the level when touched.
- **No exit slippage** on TP or SL (small size → assumed fill).
- Entry remains next open + entry slip + taker fee.
- Fees remain **taker** on all fills unless a project later freezes proven maker fills.
- Timeout / max-hold remains a market exit and may use market-exit slippage.
- Gap through a limit TP/SL still fills **at the limit price** (not the gap open).

Canonical strategy guide added to the rules pack as `TRADESIM_BACKTEST_ENGINE_GUIDE.md`
and mirrored in botsgeneral `docs/project_memory/`.

## 2026-07-25 — Frozen strategy↔tradesim contract (user answers)

Canonical copy: `STRATEGY_TO_TRADESIM_CONTRACT.md`. Summary of what was locked:

- **Data:** Binance USD-M OHLCV for research (`RESEARCH_PROXY`); live on Bybit USDT perp.
  Cost model uses **Bybit taker 0.055%** so research is not cheaper than live.
- **Entry:** next open + entry slip. **TP and SL:** market exits, **taker on every fill**,
  market-exit slip on exits.
- **Same-bar:** resolve on lower TF (1h→5m/1m, 4h→15m/5m/1m, …); if still both hit → SL
  first. No free entry bar.
- **Gaps:** order executes at the gap open (worse than the level), not at the wished price.
- **Funding:** actual historical settlement rates while open — not a flat average.
- **Size:** fixed quantity; assume fill (no min-notional theatre for small retail size).
- **Leverage:** backtest at 1×; live leverage from SL so liq sits beyond SL. Optional
  sanity re-run at live leverage to confirm zero liquidations on gaps.

## 2026-07-25 — tradesim: the shared execution engine, and how xgb and LLM1 were reconciled

The build order was mandated: the conformance pack came first, the engine second. The pack
is a registry of 62 identifiers, 50 hand-computed golden fixtures, and a checker that
treats a missing test binding exactly like a failing test. See
`ENGINE_CONFORMANCE_BASELINE.md` for the measured before-picture of all four engines.

### Where xgb and LLM1 disagreed, and what tradesim does

The instruction was to extract from both rather than invent. In eleven places the two
engines behave differently and a choice had to be made. In every case the rule applied was
the same: **prefer the behaviour that is harder to get away with in live trading.** A
backtest exists to talk you out of a bad idea, so where two defensible answers exist, the
pessimistic one is the useful one.

1. **Stop-loss order type.** xgb fills a stop at the bracket price unless the bar's open
   already gapped past it. LLM1 treats it as a stop-market with adverse slippage and fills
   worse than the stop on a gap. **Chosen: LLM1.** A stop is a market order once triggered;
   filling at the level is a small, systematic, always-favourable lie.
2. **Take-profit order type.** xgb fills a target at the limit price with no slippage;
   LLM1 does the same. **Both agreed, kept:** a limit that is touched fills at the limit.
   tradesim additionally offers a market take-profit that does slip, because some
   strategies exit on a signal rather than a resting order (EXEC-005).
3. **Fee rate per fill.** xgb charges one commission rate on every fill. LLM1 charges one
   taker rate on every fill. **Chosen: neither.** tradesim charges by the liquidity role of
   the individual fill, so a resting take-profit is billed maker and a stop is billed
   taker. Both engines fail EXEC-003 on this, and the error is not small: at 0.1% taker
   against 0.04% maker it is 60 basis points of round-trip cost on every winning trade.
4. **Where slippage lands.** xgb expresses slippage in percent and moves the price. LLM1
   expresses it in basis points and moves the price, and states explicitly that it is not
   added to the fee rate. **Chosen: LLM1's convention** — slippage moves the price, fees
   are charged on the executed price. Folding slippage into the fee rate is the more common
   shortcut and it silently mis-charges the fee.
5. **Ambiguous bars.** Both resolve adversely when the stop and the target are inside one
   bar. Neither records that it happened. **Chosen: resolve adversely and flag it.** The
   flag is the point: a strategy whose profit depends on ambiguous bars is a strategy whose
   backtest is measuring the resolution convention, not the edge.
6. **Intrabar disambiguation.** LLM1 scans a finer touch series; xgb accepts an optional
   lower timeframe and walks its sub-bars. **Chosen: xgb's shape** — an explicit touch
   timeframe for the decision bar only — plus a rule neither has: if the touch data does
   not fully cover the decision bar, the resolution is marked as convention-derived rather
   than data-derived, and a warning is raised (DATA-005).
7. **Funding.** xgb settles at the bar whose timestamp matches the funding index while a
   position is open. LLM1's path simulator has no funding at all; a separate module applies
   it over a half-open `[entry, exit)` window afterwards. **Chosen: xgb's chronology with
   LLM1's window definition** — settle inside the loop so funding can move the wallet and
   therefore move the liquidation price, and charge over `[entry, exit)` so a settlement
   exactly at the exit is not double-counted against the next trade.
8. **Funding on a same-bar round trip.** xgb drops it; LLM1 has no opinion. **Chosen:
   charge it** (EXEC-015). A position that existed across a settlement paid it, regardless
   of how briefly it existed.
9. **Liquidation.** xgb computes an approximate isolated liquidation price and checks it
   after the stop. LLM1 does not model it and says so. **Chosen: xgb's ordering** (stop
   before liquidation, because a stop is closer to the entry when it is inside the
   liquidation level) **with a fidelity label neither has.** Every result carries a
   `liquidation_status` of `MODELLED`, `SIMPLIFIED` or `UNKNOWN` so a reader knows whether
   the number rests on maintenance-margin tiers or on an approximation.
10. **Quantity feasibility.** xgb silently returns without opening when a quantity rounds
    below the minimum. LLM1 silently skips a signal it cannot price. **Chosen: neither
    silence.** An infeasible order is recorded as a typed skip with a reason
    (`SKIP_QTY_ROUNDS_TO_ZERO`, `SKIP_MIN_NOTIONAL`, `SKIP_MIN_QTY_RISK_CAP`,
    `SKIP_INSUFFICIENT_MARGIN`, `SKIP_MARGIN_UTILISATION_CAP`) and counted. A backtest that
    quietly drops the trades a live account would have rejected is measuring a strategy
    nobody can trade.
11. **Input validation.** Neither validates. Both accepted duplicated timestamps,
    out-of-order timestamps, negative prices and a high below its low. **Chosen: fail
    closed.** Bad bars raise before any simulation runs (DATA-001, DATA-002).

### Standing consequences

- **One resolution function.** `tradesim.exits.resolve_bar` is the only place an exit is
  decided, and the engine calls it from exactly one site. The entry bar cannot be given a
  free pass because there is no second branch in which to forget it.
- **A missing binding is a failure.** An identifier with no test that declares it is graded
  exactly like a failing test. Demonstrated: deleting the EXEC-014 tests leaves all 50
  fixtures passing and still fails the run.
- **The pack has teeth.** Demonstrated: reintroducing entry-bar immunity fails 13
  identifiers including the required EXEC-010, EXEC-012 and EXEC-013.
- **Stamps, not vibes.** Every public entry point takes a run identifier and returns a
  conformance stamp carrying the engine version, the git commit or `UNKNOWN_DIRTY`, the
  fixture-pack hash, the config digest and the identifier score. `assert_quotable` refuses
  a number whose stamp is not green.
- **No live-system changes.** tradesim is a new, self-contained distribution under
  `packages/tradesim`. It depends on numpy and pandas only, imports nothing from
  `botsgeneral`, and no bot has been migrated onto it yet. Migration is Phase 3, one
  repository at a time, gated on a trade-by-trade parity diff.

## 2026-07-16 — Local research candle warehouse

- **Path:** `D:\projectsdata\candles\market_ohlcv.sqlite` (Windows research machine only; not VPS live feed).
- **Sources kept separate** via `source` column: `dukascopy`, `yahoo`, `binance`, `tradingview`, `coingecko` — never merge CFD/futures/spot under one silent label.
- **Macro/FX:** Dukascopy primary for intraday (DXY, HKG40 CFD ≠ official HSI, XAU/XAG, WTI/Brent, majors). Yahoo for official HSI daily + futures cross-checks.
- **Crypto:** Binance USD-M futures for the union of project symbols (BTC/ETH/SOL + alts + HYPE/AVAX/LINK/DOT).
- **BTC.D:** Prefer TradingView `CRYPTOCAP:BTC.D` CSV dropped into `D:\projectsdata\candles\imports\btcd\`; CoinGecko daily is approximate only.
- **VPS `shared_candles.db` unchanged** — live bot collector stays per-VPS; this warehouse is for local backtests/research.

## 2026-07-13 — Shared candle architecture

- **One collector per VPS** (not central sync, not Windows-hosted feed).
- **Keep exchange per bot:** Bybit for crypthor2/karmaa_mp/divergences/W.I.P live; **news** and **xgb** use own Binance pulls (`serve_candles: false`).
- **Auto-discovery** from each bot’s config + process/screen/systemd scan every 60s — do not maintain a manual candle list for new coins.
- **Canonical SQLite** `/var/lib/botsgeneral/shared_candles.db` with `exchange,symbol,timeframe,ts_ms` PK.
- **Bybit public WS** for live confirmed klines (multi-topic one connection); Binance REST only for bots that still opt into shared Binance pairs (none on 94.156 after news opt-out).
- **Xxobster** keys for PnL/ops only when needed; market klines are public.
- Trading bots keep **their own** Bybit accounts for orders after migration.
- Standing trading rules live in `RULES.md` (shared across the stack).

## 2026-07-13 — news discarded shared candles

- **news** set `serve_candles: false`; live restored own Binance REST into `/home/crypto_alpha` SQLite (needs taker fields for vol_imb; matches backtest).

## Non-goals for botsgeneral

- No strategy optimization or ML training in this repo.
- No placing orders.
- No replacing xgb **or news** candle fetch until explicitly requested.
