# indicators

Shared **Fibonacci price-structure** indicator warehouse for every trading program.

## Install

```text
pip install -e C:\projects\botsgeneral\packages\indicators
pip install -e C:\projects\botsgeneral\packages\market_data
```

Or at the top of every script:

```python
from indicators.ensure_source import prefer_botsgeneral_indicators
prefer_botsgeneral_indicators()
```

## Warehouse

| Role | Path |
|---|---|
| Indicators DB | `D:\projectsdata\indicators\indicators.sqlite` |
| Candle source | `D:\projectsdata\candles\market_ohlcv.sqlite` |

Tables: `series`, `swings`, `structure_events`, `legs`, `levels`, `bar_features`, `meta`.

## CLI

```text
indicators paths
indicators update --symbol BTCUSDT --timeframe 1h
indicators update-all
indicators update-all --timeframes 1h,4h,1d --symbols BTCUSDT,ETHUSDT,DXY,SPX
indicators update-all --refresh
indicators coverage
indicators show --symbol BTCUSDT --timeframe 1h --table bar_features
```

Default `update-all` covers timeframes `15m,1h,4h,1d,1w` for every series in the candle
warehouse (crypto, FX, indices, macros). Use `--timeframes all` to include `1m`/`5m`.

## What is computed

- Confirmed swing highs / lows (fractal, left=right=2 by default)
- Structure labels: HH / HL / LH / LL (plus first SH / SL)
- Legs between opposite swings: length, impulse vs correction, Fibonacci retracement depth
- Fibonacci grid on the last completed leg (0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.272, 1.618, 2, 2.618)
- Distance to prior confirmed support / resistance

All bar features are **causal** (a swing is visible only after its right-side confirmation bar).

## Program usage

```python
from indicators import IndicatorDB, update_series, compute_structure

update_series("BTCUSDT", "1h", source="binance")

db = IndicatorDB()
feats = db.load_bar_features("BTCUSDT", "1h", source="binance")
legs = db.load_legs("BTCUSDT", "1h", source="binance")
# copy / merge into your research frame, then close
db.close()
```

See `docs/project_memory/INDICATORS_GUIDE.md`.
