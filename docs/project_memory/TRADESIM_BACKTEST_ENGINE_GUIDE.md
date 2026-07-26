# tradesim backtest engine — strategy guide

**Audience:** every strategy repository that will call the shared backtest engine.  
**Engine package:** `packages/tradesim` (install from the `botsgeneral` repo).  
**Frozen:** 2026-07-26  
**Companion:** this file is part of Trading Bot Cursor Rules v2; keep it next to the research standard.

---

## 1. What the engine is (and is not)

The engine does **not** invent entries, take-profits or stop-losses.  
Your strategy produces a list of trades. The engine walks candle data and answers:

> Given these entry / take-profit (TP) / stop-loss (SL) points, what would have happened with live-like fills, fees and funding?

It then reports win rate, Sharpe ratio, Sortino ratio, max drawdown, number of trades, longs/shorts, fees, funding, and related metrics.

**Your job:** causal signals and points (no looking ahead).  
**Engine’s job:** honest execution of those points.

Walk-forward, train/test splits and feature building stay in the strategy / research harness. Pass the engine only the trade list for the fold you are evaluating.

---

## 2. Exact data the strategy must give

### 2.1 Per trade (required)

| Field | Type | Meaning |
|---|---|---|
| `symbol` | string | e.g. `BTCUSDT` |
| `decision_ts_ms` | int | Open time (UTC milliseconds) of the **closed** decision candle. The signal is known only **after** this candle closes. |
| `side` | `+1` or `-1` | Long or short |
| `stop_price` **or** `stop_offset` | float | Absolute SL, **or** fraction of the **actual entry fill** (engine applies the fraction after the fill) |
| `target_price` **or** `target_offset` | float | Absolute TP, **or** fraction of the actual entry fill |
| `qty` | float | Fixed size (same unit the live bot will trade) |

### 2.2 Per trade (optional)

| Field | Meaning |
|---|---|
| `max_hold_bars` | Force a **market** exit after N decision bars (this exit **does** use market-exit slippage) |
| `tp_legs` | Multi-leg TP; quantity fractions must sum to `1.0` |
| `break_even` | Move SL to break-even after a trigger (only if live does the same) |
| `trail` | Trailing stop (only if live does the same) |

### 2.3 Hard rules for the strategy

1. Features and the decision use **only** data available at `decision_ts_ms`. No future candles, no centered windows, no full-history normalization fitted on the test period.
2. Do **not** compute SL/TP from a fill price you invent. Either give absolute levels you will also use live, or give **offsets** and let the engine attach them to the **simulated** fill.
3. One decision per closed decision candle (same rule as live).

---

## 3. How the engine executes (frozen defaults)

| Step | Behaviour |
|---|---|
| Market data | Binance USDⓈ-M perpetual Open-High-Low-Close-Volume (OHLCV) for research. Label results `RESEARCH_PROXY`. Live trading is on Bybit USDT perpetual. |
| Entry | Fill at the **next candle’s open** after `decision_ts_ms`, with **entry slippage**, **taker** fee. |
| Take-profit | **Limit** order. When price **touches** the TP level → fill **exactly at the TP price**. **No exit slippage.** |
| Stop-loss | **Limit** order. When price **touches** the SL level → fill **exactly at the SL price**. **No exit slippage.** |
| Fees | **Taker** rate on every fill by default (Bybit non-VIP **0.055%** = `0.00055`), so research is not cheaper than live. Entry is a market-style fill; TP/SL are limit *prices* but still charged taker unless a project later freezes proven maker fills. |
| Sizing | Fixed `qty` from the signal. Assumed filled (retail size). |
| Leverage (backtest) | **1×**. Live: derive leverage from SL so liquidation sits beyond the SL. |
| Funding | Actual historical funding rates at each settlement while the position is open (not a flat average). |
| Same candle hits both TP and SL | Resolve on a **lower timeframe**. If both still hit on one lower bar → **SL wins**. |
| Entry bar | SL and TP are active from the fill instant on that same bar. **No free bar of immunity.** |

### Entry slippage only

- `entry_slippage`: project-frozen (typical starting range about 0.02%–0.15%).  
- `market_exit_slippage`: used only for **timeout / max-hold / end-of-data** market exits — **not** for TP or SL.

### Gaps and limit TP/SL

If a bar opens beyond the TP or SL level, the engine still assumes the resting limit **fills at the limit price** (your policy: small size, orders fill). That is optimistic versus a stop-market, and is intentional under this contract.

---

## 4. Lower timeframe for TP vs SL order

When the decision candle’s high/low contains **both** TP and SL, the engine walks a finer series:

| Decision timeframe | Preferred touch timeframe |
|---|---|
| 4h / 1d | 15m, else 5m, else 1m |
| 1h | 5m, else 1m |
| 15m | 1m |
| 5m | 1m |
| 1m | none → SL first if both touched |

If touch data does not fully cover that decision bar → fall back to **SL first**.

### When to refresh candles (research machine)

Warehouse: `D:\projectsdata\candles\market_ohlcv.sqlite`

Refresh **before a walk-forward campaign** (or when the test calendar window moves):

1. Decision timeframe OHLCV for every symbol in the campaign  
2. Touch timeframe(s) from the table above  
3. Historical funding for those symbols  

You do **not** need to refresh after every single trial — only when the window or symbol/timeframe set changes.

Example:

```text
python -m botsgeneral research-candles --only binance --symbols BTCUSDT,ETHUSDT --timeframes 1m,5m,1h,4h
```

---

## 5. How to call the engine (shape)

Exact Python API lives in `tradesim` (`simulate` / `simulate_portfolio`). Conceptually:

```text
inputs:
  - OHLCV bars (decision TF)
  - optional touch OHLCV (lower TF)
  - optional funding series (settlement_ts, rate)
  - list of signals (section 2)
  - CostConfig: taker_rate=0.00055, entry_slippage=..., market_exit_slippage for timeouts only
  - SimConfig: entry = next_open, starting_equity=..., leverage=1x

output:
  - trades (entry/exit times & prices, reason, fees, funding, pnl, …)
  - equity curve
  - metrics (win rate, Sharpe, Sortino, max drawdown, trade counts, …)
  - conformance stamp (required before quoting numbers)
```

Install (from `botsgeneral`):

```text
pip install -e packages/tradesim
```

A number **without** a green conformance stamp is not quotable evidence (rules v2.2).

---

## 6. Mental model (one trade)

```text
1h candle closes at T → strategy emits:
   long, qty=0.01, stop=95, target=110

Engine:
  fill entry at open of next 1h bar ± entry slip, taker fee
  from that bar onward (including that bar):
      walk 5m/1m if available to see whether 95 or 110 was touched first
      if both on same lower bar → stop at 95 (limit, no slip)
      if only target → exit at 110 (limit, no slip)
  while open: apply each historical funding settlement
  on exit: taker fee on the exit fill (no TP/SL slip)
```

---

## 7. What you must not do

- Fill the entry at the signal candle’s close  
- Start SL/TP checks only on the bar **after** entry  
- Assume TP always wins when both levels sit in one candle  
- Ignore funding on perpetuals when a history series exists  
- Quote full-history optimised results as if they were walk-forward out-of-sample  
- Change fee/slip/TP-SL assumptions after looking at out-of-sample results  

---

## 8. Checklist before a research run

- [ ] Signals use only closed-candle data at `decision_ts_ms`  
- [ ] Each trade has side, stop, target, fixed `qty`  
- [ ] Decision + touch candles refreshed for the backtest window  
- [ ] Funding series present (or funding explicitly marked unavailable)  
- [ ] Entry slip frozen; TP/SL have **zero** exit slip  
- [ ] Walk-forward folds defined **before** looking at test metrics  
- [ ] Result carries a green tradesim conformance stamp before you publish numbers  

---

## 9. Where the engine lives

| Item | Location |
|---|---|
| Library | `C:\projects\botsgeneral\packages\tradesim` |
| This contract (botsgeneral copy) | `docs/project_memory/STRATEGY_TO_TRADESIM_CONTRACT.md` |
| This guide (rules pack) | `TRADESIM_BACKTEST_ENGINE_GUIDE.md` (this file) |
| Full methodology | `TRADING_BOT_RESEARCH_STANDARD_V2.md` |
| Frozen gates | `FROZEN_DEFAULT_GATES_V2_1.md` |

Phase 3 migrations wire each strategy repo onto `tradesim` one repository at a time. Until then, treat this file as the interface contract every new backtest path must implement.
