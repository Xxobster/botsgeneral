# Indicators guide — Fibonacci price structure warehouse

**Package:** `C:\projects\botsgeneral\packages\indicators`  
**Warehouse:** `D:\projectsdata\indicators\indicators.sqlite`  
**Candle source:** `D:\projectsdata\candles\market_ohlcv.sqlite`  
**Frozen role:** this is the **only** shared module that computes confirmed swings,
higher-high / higher-low structure, Fibonacci retracements, and support/resistance
distances for research programs.

---

## 1. Why it exists

Strategy programs need the same price-structure features. Private per-repo swing/fib
helpers diverge and leak. This package:

1. reads every series already in the research candle warehouse (crypto, FX, indices, macros);
2. computes a **maximum-information** structure feature set with Fibonacci ratios;
3. stores results in one SQLite DB that programs **open and copy** from;
4. exposes calculate / update / fetch / update-all APIs + CLI.

---

## 2. Install / pin latest

```python
from indicators.ensure_source import prefer_botsgeneral_indicators
prefer_botsgeneral_indicators()
```

Or:

```text
pip install -e C:\projects\botsgeneral\packages\indicators
pip install -e C:\projects\botsgeneral\packages\market_data
```

Refuse to run if `indicators.__file__` is not under `botsgeneral`.

---

## 3. What is computed (Fibonacci-defined structure)

| Concept | Definition |
|---|---|
| **Confirmed swing high / low** | Fractal pivot: unique extreme of `left` bars before + `right` bars after (default 2/2). Known only after the right-side bar closes (causal). |
| **Structure labels** | Compare consecutive same-kind swings: **HH** / **LH** (highs), **HL** / **LL** (lows). First swing: **SH** / **SL**. |
| **Leg** | Move between consecutive opposite swings. Length in price and %. |
| **Impulse vs correction** | From structure bias: in HH/HL regime, up legs = impulse, down = correction (mirror for LH/LL). |
| **Retracement depth** | After leg A→B, next opposite swing C: `retrace = (B−C)/(B−A)`. Mapped to nearest Fibonacci **0.236 / 0.382 / 0.5 / 0.618 / 0.786**. |
| **Fibonacci grid** | On last completed leg: levels **0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.272, 1.618, 2, 2.618** + distance of close to retracement levels. |
| **Support / resistance** | Confirmed swing lows = support; swing highs = resistance. Per bar: nearest confirmed level below/above + % distance. |

All `bar_features` rows are **causal** — no look-ahead past confirmation.

---

## 4. SQLite tables (copy what you need)

| Table | Contents |
|---|---|
| `series` | One row per computed series + params + last bar |
| `swings` | Every confirmed swing |
| `structure_events` | HH/HL/LH/LL (and SH/SL) events |
| `legs` | Leg lengths, kind, Fibonacci retrace of the next move |
| `levels` | Confirmed S/R prices |
| `bar_features` | Dense per-bar matrix programs usually merge into research frames |
| `meta` | Warehouse metadata |

Primary key on feature tables: `(source, symbol, timeframe, swing_left, swing_right, …)`.

---

## 5. CLI

```text
indicators paths
indicators update --symbol BTCUSDT --timeframe 1h --source binance
indicators update-all
indicators update-all --timeframes 1h,4h,1d
indicators update-all --symbols BTCUSDT,ETHUSDT,DXY,SPX,XAUUSD
indicators update-all --timeframes all          # includes 1m/5m
indicators update-all --refresh                 # refresh candles first (network)
indicators coverage
indicators show --symbol BTCUSDT --timeframe 1h --table bar_features
indicators show --symbol BTCUSDT --timeframe 1h --table legs
```

Default `update-all` timeframes: **1h, 4h, 1d, 1w**. Add `15m` explicitly, or use
`--timeframes all` for every TF in the candle DB (including `1m`/`5m`).

---

## 6. Python API

```python
from indicators import (
    IndicatorDB,
    compute_structure,
    update_series,
    update_all,
    load_candles,
)

# One series
update_series("BTCUSDT", "1h", source="binance")

# Entire warehouse (pairs + indices + macros already in candles DB)
update_all()

# In-memory compute without writing
ohlcv = load_candles("EURUSD", "1h", source="dukascopy")
bundle = compute_structure(ohlcv, source="dukascopy", symbol="EURUSD", timeframe="1h")

# Programs: open DB, copy columns, close
db = IndicatorDB()
feats = db.load_bar_features("BTCUSDT", "1h", source="binance")
legs = db.load_legs("BTCUSDT", "1h", source="binance")
levels = db.load_levels("BTCUSDT", "1h", source="binance")
db.close()
```

---

## 7. Rules for strategy programs

1. Do **not** re-implement swing / Fibonacci / HH-HL helpers locally.
2. Call `prefer_botsgeneral_indicators()` (or editable install) before import.
3. Prefer reading `bar_features` / `legs` / `levels` from the warehouse; recompute only when experimenting with `swing_left` / `swing_right`.
4. Before train/test on derived columns, still run the shared **leakage** package.
5. Candle refresh before live-vs-backtest remains `ensure_candles` / `market_data`; indicator update is a separate step: `indicators update-all`.

---

## 8. Relation to other shared packages

| Package | Role |
|---|---|
| `market_data` | Research OHLCV warehouse |
| `indicators` | Structure + Fibonacci features on that OHLCV |
| `tradesim` | Execution / metrics engine |
| `leakage` | Causality audit before train/test |
