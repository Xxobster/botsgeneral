# tradesim — how the backtest engine works, and every metric

**Audience:** anyone reading a tradesim report or wiring a strategy to the engine.  
**Code:** `packages/tradesim`  
**Authoritative metrics:** `tradesim.metrics.compute_metrics` (one implementation — do not reimplement in strategy repos).  
**Frozen companion guides:** `TRADESIM_BACKTEST_ENGINE_GUIDE.md`, `STRATEGY_TO_TRADESIM_CONTRACT.md`.

---

## 0. Win rate — the common misunderstanding

### What win rate *is*

\[
\text{win rate} = \frac{\text{number of trades with realized PnL} > 0}{\text{number of resolved trades}}
\]

A trade is a **win** only if its **net** realized profit and loss (PnL) after fees, slippage and funding is strictly greater than zero. Break-even trades (`pnl == 0`) are **not** wins.

We also print a **Wilson 95% confidence interval** around that rate. A win rate from 5 trades is not the same evidence as a win rate from 500 trades; the interval says so.

### What win rate is *not*

**Win rate below 50% does not mean the strategy loses money.**

Profitability is about **expectancy** (average money per trade), not about how often you are right:

\[
\text{expectancy} = (\text{win rate} \times \text{average win}) + ((1 - \text{win rate}) \times \text{average loss})
\]

(`average loss` is a negative number.)

Example:

| | |
|---|---|
| Win rate | 40% |
| Average win | +\$200 |
| Average loss | −\$80 |
| Expectancy | \(0.40 \times 200 + 0.60 \times (-80) = +\$32\) per trade → **profitable** |

Opposite example:

| | |
|---|---|
| Win rate | 70% |
| Average win | +\$50 |
| Average loss | −\$150 |
| Expectancy | \(0.70 \times 50 + 0.30 \times (-150) = -\$10\) per trade → **losing** |

That is why this project’s gates emphasize **profit factor**, **Sharpe**, **drawdown** and **pooled out-of-sample trades** — not a hard “win rate must be > 50%” rule. Win rate is **reported**; it is not a universal hard gate (see Trading Bot Research Standard V2 / Frozen Default Gates V2.1).

### How this relates to take-profit / stop-loss geometry

If your take-profit (TP) is twice as far as your stop-loss (SL) (reward:risk ≈ 2:1), a strategy can be profitable with win rate well below 50%. If TP and SL are symmetric (1:1) **and** fees eat both sides, you typically need win rate **above** ~50% after costs. Always read win rate **together with** payoff ratio and expectancy.

### What we print

```text
win rate : 40.00%  [32.1%, 48.5%] Wilson 95%
payoff   : 2.500   avg win 200.00 / avg loss -80.00
expectancy : 32.0000 per trade
profit factor : 1.67
```

If you only look at “40%” and conclude “losing strategy”, you are reading the wrong number.

---

## 1. What the engine is

`tradesim` is a **shared execution simulator** for bracketed perpetual / futures strategies. It does **not** invent signals. A strategy (or research harness) supplies:

1. Open-High-Low-Close-Volume (OHLCV) bars (decision timeframe; optional lower “touch” timeframe).  
2. A list of `Signal` intents (time, side, stop, target, optional size / max hold / multi-leg TP).  
3. Instrument rules (tick, quantity step, min quantity / notional), costs, margin, sizing, simulation policy.

The engine walks time chronologically and produces:

- trades, fills, funding charges, skips  
- mark-to-market equity curve  
- a `MetricsReport`  
- a **conformance stamp** (green stamp required before quoting numbers as evidence)

It is **not** the GitHub library `backtesting.py`. That library can still exist in legacy projects (e.g. xgb); new shared research uses tradesim. For familiar key names, call `MetricsReport.as_backtesting_stats()`.

---

## 2. End-to-end simulation flow

```text
Signals (known at candle close)
        │
        ▼
Entry fill at NEXT bar open (+ entry slip, taker fee)
        │
        ▼
Same entry bar: resolve stop / target / liquidation / trail / break-even
        │  (no free bar of immunity)
        ▼
Each later bar: same shared resolve_bar()
        │
        ├── TP limit touch → fill at TP (no exit slip)
        ├── SL limit touch → fill at SL (no exit slip)
        ├── both touch → lower TF; if still both → SL first
        ├── funding at each historical settlement while open
        ├── max_hold / end_of_data → market exit (may use market-exit slip)
        └── wallet ≤ 0 → WALLET BLOWN, stop trading
        │
        ▼
Wallet equity curve → compute_metrics() → headline + as_backtesting_stats()
```

### 2.1 Causality

- A signal at `Signal.ts_ms` is known only **after** that candle’s close.  
- Default fill reference: **next open** (`EntryRef.NEXT_OPEN`).  
- Features/signals must not use future data; the engine does not police feature code, but it refuses retroactive fills at the decision close.

### 2.2 Price series roles (frozen)

| Role | Series | Warehouse |
|---|---|---|
| Signals, fills, TP/SL path (Last trigger) | **Last** OHLCV | `source=binance` |
| Liquidation (and Mark-triggered TP/SL if live uses Mark) | **Mark** OHLCV | `source=binance_mark` |
| Go/no-go liquidation evidence | **Both** | — |

Research data is Binance → label results `RESEARCH_PROXY`. Live venue is Bybit USDT perpetual.

### 2.3 Fees and slippage (Bybit-aligned)

- Fee per fill: `fee = qty × executed_price × rate`  
- Default rate: taker **0.055%** (`0.00055`) on every role unless proven maker fills are frozen.  
- Entry slippage moves the fill price; it is **not** added into the fee rate.  
- TP/SL: limit fills at the level, **no exit slippage**.  
- Timeout / max-hold / end-of-data: market exit; may use `market_exit_slippage`.

### 2.4 Sizing and wallet

- Research default: starting equity **10_000 USDT** (margin-safe at 1× for BTC/ETH min size), leverage **1×**, size = smallest exchange-legal quantity (`SizingMode.MIN_EXCHANGE`) unless `Signal.qty` is set. Headline money % = return on invested notional, not wallet %.
- Instrument limits come from Bybit (`tradesim.venue` / `research_instrument`).  
- If equity ≤ 0 → `wallet_blown`, trading stops.

### 2.5 Entry bar (non-negotiable)

The bar that fills the entry is resolved for stop, target, liquidation and trailing/break-even in the **same** step. Same-bar exits are labelled (e.g. `stop_entry_bar`) and counted in `entry_bar_exit_rate`. Above ~25% entry-bar exits, the stop is likely inside single-bar noise — the report must say so.

### 2.6 Candle refresh before live comparison

Before every backtest-versus-live-log comparison, refresh the needed series:

```text
python -m tradesim.research.candles --symbols BTCUSDT --timeframes 1h,1m --price-type both
```

```python
from tradesim.research import ensure_candles
ensure_candles(["BTCUSDT"], ["1h", "1m"], price_types=("last", "mark"))
```

---

## 3. Trade-level accounting

For each closed `Trade`:

| Field | Meaning |
|---|---|
| `gross_pnl` | Price PnL from entry → exit on quantity (before fees/funding) |
| `fees` | Sum of fees on all fills for that trade |
| `funding` | Sum of funding cashflows while open (negative = paid) |
| `slippage_cost` | Cost implied by fill price vs reference |
| `realized_pnl` | Net wallet effect of the trade (after fees and funding) |
| `return_units` | `realized_pnl / \|entry_qty × entry_price\|` |
| `hold_bars` | Decision bars held; **0** if exit on the entry bar |
| `exit_reason` | e.g. `stop`, `target`, `stop_entry_bar`, `max_hold`, `liquidation` |

**Win / loss classification uses `realized_pnl`, not gross price move alone.** A trade that is slightly green on price but red after two taker fees is a **loss**.

---

## 4. Metric catalogue (every field)

All formulas below are implemented in `tradesim/metrics.py` unless noted.  
`n` = number of resolved trades. Empty trade list → many fields are `NaN`, not fake zeros.

### 4.1 Counts and coverage

| Field | Formula / definition |
|---|---|
| `n_trades` | Count of closed trades |
| `n_longs` / `n_shorts` | Count with `side > 0` / `side < 0` |
| `start_ts_ms` / `end_ts_ms` | First / last timestamp on the equity curve |
| `span_days` | `(end − start) / 86_400_000` |
| `trades_per_month` | `n_trades / (span_days / 30.4375)` |

### 4.2 Wallet and return

| Field | Formula / definition |
|---|---|
| `starting_equity` | Simulation start cash (research default 10_000 USDT) |
| `invested_notional` | Sum of entry notionals (`qty × entry`) across closed trades |
| `return_on_invested` | `net_pnl / invested_notional` — headline money % for fixed-qty research |
| `ending_equity` | Final mark-to-market wallet equity |
| `equity_peak` | `max(equity curve)` |
| `net_pnl` | `ending_equity − starting_equity` |
| `total_return` | `net_pnl / starting_equity` |
| `cagr` | \((E_T / E_0)^{365/\text{span_days}} − 1\) when defined and \(E_T > 0\) |
| `buy_hold_return` | `close_last / close_first − 1` on the decision bars (if bars passed into `compute_metrics`) |
| `volatility_annualised` | `std(daily equity returns, ddof=1) × sqrt(annualisation_days)` (default days = 365) |
| `wallet_blown` | True if equity hit ≤ 0 (or summary flag) |
| `ruined_at_ts_ms` | Timestamp when trading stopped after ruin |

### 4.3 Trade distribution (including win rate)

| Field | Formula / definition |
|---|---|
| `win_rate` | `#(realized_pnl > 0) / n` |
| `win_rate_ci_low` / `win_rate_ci_high` | Wilson score interval at 95% (`z = 1.96`) |
| `profit_factor` | `sum(wins) / \|sum(losses)\|` pooled; **never** capped; **never** average of fold PFs. Zero gross loss → `+∞` with an insufficient-sample note (not an automatic pass) |
| `expectancy` | `mean(realized_pnl)` in account currency |
| `expectancy_return_units` | `mean(return_units)` |
| `avg_win` / `avg_loss` | Mean of positive / negative `realized_pnl` (`avg_loss` is negative) |
| `median_win` / `median_loss` | Medians of the same sets |
| `payoff_ratio` | `avg_win / \|avg_loss\|` when both exist |
| `best_trade` / `worst_trade` | Max / min `realized_pnl` |
| `best_trade_pct` / `worst_trade_pct` / `avg_trade_pct` | Max / min / mean of `return_units` |
| `cvar_5` | Mean of the worst 5% of trade PnLs (empirical) |
| `long_pnl` / `short_pnl` | Sum of `realized_pnl` by side |
| `long_win_rate` / `short_win_rate` | Win rate within each side |

### 4.4 Duration

| Field | Formula / definition |
|---|---|
| `avg_hold_bars` / `min_hold_bars` / `max_hold_bars` | Mean / min / max of `Trade.hold_bars` |
| `avg_hold_hours` / `min_hold_hours` / `max_hold_hours` | Mean / min / max of `(exit_ts_ms − entry_ts_ms) / 3_600_000` |

### 4.5 Streaks and trade-quality scores

| Field | Formula / definition |
|---|---|
| `max_consecutive_wins` / `max_consecutive_losses` | Longest run of `pnl > 0` / `pnl < 0` in chronological trade order |
| `sqn` | Van Tharp System Quality Number: \(\sqrt{n} \times \mathrm{mean}(\mathrm{pnl}) / \mathrm{std}(\mathrm{pnl})\) (`ddof=1`) |
| `kelly_fraction` | Classical Kelly: \(p - (1-p)/b\) with \(p =\) win rate, \(b =\) payoff ratio (diagnostic; not auto position size) |
| `recovery_factor` | `net_pnl / max_drawdown` (currency units) when drawdown > 0 |

### 4.6 Risk on the equity curve (headline risk)

**Important:** Sharpe / Sortino / drawdown use **chronological mark-to-market wallet equity**, including unrealized PnL, flat days, fees and funding — **not** a series of closed-trade returns. Closed-trade Sharpe is forbidden as the deployment headline.

Daily returns \(r_t = E_t / E_{t-1} - 1\) from `result.daily_equity`.

| Field | Formula / definition |
|---|---|
| `sharpe.raw_periodic` | \(\mathrm{mean}(r) / \mathrm{std}(r)\) (`ddof=1`), risk-free default 0 |
| `sharpe.annualised` | `raw_periodic × sqrt(annualisation_days)` (default 365) |
| `sharpe.hac_raw` / `hac_annualised` | Same mean over Newey–West / Bartlett long-run variance (serial-dependence aware) |
| `sortino_annualised` | \(\mathrm{mean}(r) / \mathrm{downside\ deviation} × sqrt(annualisation_days)\); downside = RMSE of negative returns only; no negatives → `+∞` |
| `max_drawdown` | Peak-to-trough drop in equity (currency) |
| `max_drawdown_pct` | Max of `(peak − equity) / peak` |
| `max_drawdown_duration_days` | Longest underwater spell × period length |
| `avg_drawdown_pct` | Mean drawdown fraction while underwater |
| `avg_drawdown_duration_days` | Mean length of underwater episodes |
| `calmar` | `cagr / max_drawdown_pct` when defined |

### 4.7 Execution honesty

| Field | Formula / definition |
|---|---|
| `exposure` | Fraction of equity observations with `open_positions > 0` |
| `turnover` | `sum(\|fill notional\|) / starting_equity` |
| `total_fees` / `total_slippage` / `total_funding` | Sums across trades (or engine summary) |
| `n_liquidations` | Trades whose exit reason starts with liquidation |
| `n_skips` / `skip_counts` | Orders that never became positions, by reason |
| `entry_bar_exits` / `entry_bar_exit_rate` | Exits on the entry bar / rate |
| `ambiguous_intrabar` / `ambiguous_rate` | Bars where both TP and SL were reachable |
| `liquidation_status` | `MODELLED` / `SIMPLIFIED` / `UNKNOWN` |

### 4.8 Mapping to `backtesting.py` names

`report.as_backtesting_stats()` exposes the familiar labels (`Win Rate [%]`, `Sortino Ratio`, `Avg. Trade Duration`, …) plus tradesim extras (`# Longs`, `# Shorts`, `Funding [$]`, …). Values are the same underlying fields; percentages are ×100 where the label says `[%]`.

---

## 5. How to read a headline (order of attention)

1. **Conformance stamp** — if not GREEN, numbers are not quotable evidence.  
2. **Wallet blown?** — if yes, path died; do not decorate the corpse.  
3. **Sample size** — `n_trades`, trades/month, Wilson interval on win rate.  
4. **Expectancy + profit factor + payoff** — is there edge after costs?  
5. **Sharpe (raw + annualised + HAC) and Sortino** — risk-adjusted on MTM equity.  
6. **Max drawdown (size and duration)** — survivability.  
7. **Entry-bar exit rate / ambiguous rate** — execution realism red flags.  
8. **Win rate** — descriptive only; never alone.

---

## 6. What the engine deliberately does *not* do

- Does not train models, select features, or walk-forward for you.  
- Does not treat win rate > 50% as a pass/fail gate.  
- Does not use closed-trade Sharpe as the headline.  
- Does not average fold profit factors.  
- Does not silently fill OHLC gaps or invent missing funding.  
- Does not claim Bybit live parity from Binance Last candles alone (`RESEARCH_PROXY`).

---

## 7. Code map

| Concern | Module |
|---|---|
| Types (bars, signals, trades, costs) | `tradesim.contracts` |
| Chronological simulation | `tradesim.engine` |
| Single bar exit resolution (entry + later) | `tradesim.exits` |
| Fees / slippage pricing | `tradesim.fees` |
| Funding | `tradesim.funding` |
| Margin / liquidation price | `tradesim.margin` |
| Quantity / min exchange size | `tradesim.sizing` |
| Metrics (this document) | `tradesim.metrics` |
| Research one-call runner | `tradesim.research.run_backtest` |
| Candle refresh | `tradesim.research.ensure_candles` |
| Bybit instrument limits | `tradesim.venue` |
| Golden fixtures + stamp | `tradesim.conformance` |

Install and check:

```text
pip install -e packages/tradesim[conformance]
pytest packages/tradesim/tests -q
tradesim-conformance --engine tradesim --tests packages/tradesim/tests
```

---

## 8. Short FAQ

**Q: My win rate is 45%. Is the strategy bad?**  
A: Not from that alone. Check expectancy, profit factor and payoff. A 2:1 TP:SL system often lives below 50% wins and still makes money.

**Q: Why is a “winning price move” sometimes a losing trade?**  
A: Fees (and funding) are charged on fills. Net `realized_pnl` can flip the sign.

**Q: Why is Sharpe “bad” when most trades win?**  
A: Headline Sharpe uses **daily wallet equity**, including flat days and open drawdowns — not the fraction of winning trades.

**Q: Where do I get the same labels as `backtesting.py`?**  
A: `bundle.metrics.as_backtesting_stats()`.
