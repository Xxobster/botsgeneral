# Strategy → tradesim contract (frozen 2026-07-26)

This is the language every strategy must speak. The engine does not invent signals; it
takes the points you give it and executes them as close to live as the data allows.

**Strategy-facing guide (copy into every strategy chat):**  
`TRADESIM_BACKTEST_ENGINE_GUIDE.md` in the Trading Bot Cursor Rules pack, and  
`docs/project_memory/TRADESIM_BACKTEST_ENGINE_GUIDE.md` in botsgeneral.

**Live venue:** Bybit USDT perpetual  
**Backtest market data:** Binance USDⓈ-M perpetual Open-High-Low-Close-Volume (OHLCV)  
Label every Binance-OHLCV result `RESEARCH_PROXY` — good enough for strategy research,
not a live/backtest parity PASS on its own.

**Price series (frozen 2026-07-26):**

| Role | Series | Warehouse |
|---|---|---|
| Signals, fills, TP/SL touches (Last trigger) | **Last** OHLCV | `source=binance` |
| Liquidation (and Mark-triggered TP/SL if live uses it) | **Mark** OHLCV | `source=binance_mark` |
| Go/no-go liquidation evidence | **Both** | — |

Last-only research is incomplete for liquidation parity. Mark-only backtests are forbidden.

---

## 1. What the strategy must give (per trade)

| Field | Required | Meaning |
|---|---|---|
| `symbol` | yes | e.g. `BTCUSDT` |
| `decision_ts_ms` | yes | Open time of the **closed** decision candle (UTC). Signal is known only after this candle closes. |
| `side` | yes | `+1` long, `-1` short |
| `stop_price` **or** `stop_offset` | yes | Absolute SL, or fraction of the **actual fill** (engine applies it after fill) |
| `target_price` **or** `target_offset` | yes | Absolute TP, or fraction of the actual fill |
| `qty` | yes | Fixed size (contracts / coins). Same unit the live bot will use. |
| `max_hold_bars` | no | Force a **market** exit after N decision bars (timeout **does** use market-exit slippage) |
| `tp_legs` | no | Multi-leg TP (fractions must sum to 1.0) |
| `break_even` / `trail` | no | Only if the live bot will do the same |

**Hard rule for the strategy:** features and the decision use only data available at
`decision_ts_ms`. No lookahead. Walk-forward / train–test is the research harness’s job;
the engine only executes the trade list of each fold.

---

## 2. Frozen execution defaults (engine side)

| Setting | Frozen default |
|---|---|
| Entry | **Market (default):** next open + entry slippage + **taker** fee. **Limit (opt-in):** fill at limit when touched, **maker** fee, **no** entry slip (`research_limit_entry_costs` + `research_sim_limit_entry` / `Signal.entry_order`) |
| Take-profit | **Limit** order → fill **at the TP price** when touched. **No exit slippage** |
| Stop-loss | **Limit** order → fill **at the SL price** when touched. **No exit slippage** |
| Fees | **Taker** on every fill by default (Bybit non-VIP **0.055%** = `0.00055`). Limit entry / proven resting TP may use **maker** **0.02%** = `0.0002` |
| Fee rate basis | Bybit costs even though candles are Binance — research must not be cheaper than live |
| Sizing | **Fixed quantity** from the signal (assumed filled at retail size) |
| Leverage in backtest | **1×** (see §5) |
| Same-bar TP and SL both inside one decision candle | Resolve on a **lower timeframe**; if still both hit → **SL first** |
| Entry-bar checks | SL/TP live from the fill instant — **no free bar** |

Slippage:

- `entry_slippage`: project-frozen (typical 0.02%–0.15%) — **market entry only** (ignored for `entry_order=LIMIT`)
- `market_exit_slippage`: **timeout / max-hold / end-of-data only** — never TP or SL

---

## 3. Gaps — what we do (limit TP/SL)

Under this contract TP and SL are limits that you assume fill at small size:

- When the level is **touched**, fill at the **limit price** (no slip).
- When a bar **opens beyond** the level, still assume fill at the **limit price** (not a
  worse gap open). That matches “small size, order fills” and is more optimistic than a
  stop-market; it is intentional here.

Timeout / max-hold exits remain market orders and use market-exit slippage.

---

## 4. Funding — best approach (not an average)

**Best:** charge **actual historical funding rates** at each settlement while the position
is open (usually every 8 hours).

`cashflow ≈ -side × qty × mark_price(T) × rate`  
(positive rate → long pays, short receives)

Window: `entry_ts ≤ T < exit_ts`.

Do **not** use a flat average — funding clusters in trends and averages under-charge the
regimes you care about.

---

## 5. Leverage and liquidation

- Backtest at **1×** with fixed size (PnL of the path).  
- Live: leverage from SL so liquidation sits beyond the SL  
  (`floor(1 / (sl_pct + mm_buffer + mark_buffer))`, then haircut).  
- Optional sanity: re-run once at live leverage and confirm zero liquidations on gaps.

---

## 6. Lower timeframe — when to refresh candles

| Decision TF | Preferred touch TF |
|---|---|
| 4h / 1d | 15m, else 5m, else 1m |
| 1h | 5m, else 1m |
| 15m / 5m | 1m |
| 1m | adverse (SL first) if both touched |

Warehouse: `D:\projectsdata\candles\market_ohlcv.sqlite`

Refresh **before a campaign** (or when the calendar window moves): decision TF + touch TF
+ funding for every symbol. Not after every trial.

---

## 7. Binance backtest / Bybit live

Binance OHLCV for research (`RESEARCH_PROXY`). Bybit fee (and funding assumptions when
available) in the cost model. Shadow / micro-live on Bybit earns real parity.

---

## 8. Minimal example

```text
Strategy (after 1h close at T):
  side = long, qty = 0.01, stop = 95, target = 110

Engine:
  entry at next 1h open ± entry slip, taker fee
  from that bar (including it): lower TF decides 95 vs 110
  TP/SL fill at 110 or 95 exactly — no exit slip
  funding settlements while open
  exit taker fee on the fill notional
```
