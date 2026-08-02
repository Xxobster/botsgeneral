# Standing rules (Xxobster trading stack)

These apply to **all** bot projects. botsgeneral is infrastructure (candles/sitrep/pnl); strategy/backtest rules apply when working on crypthor2, divergences, karmaa_mp, news, W.I.P, xgb, etc.

## Memory & docs

- Always keep `docs/project_memory/` updated (see `C:\projects\BASE CURSOR\project_memory_example`).
- Keyword **sitrep** = full situation report: live PnL/trades/bot health, or research/optimization progress — never a one-liner.

## Data & APIs

- Prefer **WebSocket** for market data and trading feeds (fastest path). REST only for bootstrap/history/fallback.
- **SQLite** over CSV for candles, trade logs, features.
- Binance credentials: `C:\projects\BASE CURSOR\api key binance.txt` (also mirror under `C:\projects\xgb` where used). Public klines OK; still load keys when auth is needed.
- Bybit trading keys: `C:\projects\BASE CURSOR\api keys bybit.txt` — never commit secrets.
- Candle acquisition for the fleet: **botsgeneral** one collector per VPS → `/var/lib/botsgeneral/shared_candles.db`. Trading bots **read** shared DB after migration; **xgb** keeps its own Binance pull by explicit choice.
- Reader contract: `docs/project_memory/SHARED_CANDLES_READER.md` + `botsgeneral.reader.load_ohlcv`. Upsert is incremental (insert new; overwrite same `ts_ms` only when OHLCV changes).
- VPS **185.203.119.52** (LD): collector serves Binance USD-M **1h** for BTC/ETH/SOL/BNB once for all Xxobster9/10/11 groups — see `AGENT_PROMPTS.md` → ld.
- Local research / backtest OHLCV warehouse (Windows): `D:\projectsdata\candles\market_ohlcv.sqlite` via `botsgeneral.research_candles` (Dukascopy macro/FX, Yahoo equity/VIX, FRED yields, CoinGecko/blockchain mcap, DefiLlama stablecoins, Fear & Greed, Binance futures crypto). Do not re-download the same series per project when this DB already has it.
- **Training / hunt / LLM feature rule (mandatory):** Models that predict price (cross-pair, first-touch, LLM context, etc.) MUST pull features from this warehouse — including yields (US02Y/US10Y/T10Y2Y), VIX, SPX/NDX, BTC/ETH/TOTAL mcap & BTC.D, stablecoin mcap/flows, FNG — whenever those series are in the candidate feature space. Refresh with `python -m botsgeneral.research_candles.download_all --only fred,yahoo,crypto_macro` (skips series that are still fresh). Live bots MUST refresh every symbol referenced by the deployed pack’s feature list (same sources); never leave macros frozen via forward-fill.
- **Refresh candles on demand** from any program before a backtest or live comparison:

```text
python -m tradesim.research.candles --symbols BTCUSDT --timeframes 1h,1m --price-type both
# or
python -m botsgeneral research-candles --only binance --symbols BTCUSDT --timeframes 1h,1m --price-type both
```

```python
from tradesim.research import ensure_candles
ensure_candles(["BTCUSDT"], ["1h", "1m"], price_types=("last", "mark"))
```

  Default for crypto research: **Last + Mark**. Last for fills / TP–SL path; Mark for liquidation.

## VPS ops

- Launch live bots in **screen** with **explicit session names**.
- **Auto-restart on reboot**: systemd (preferred) and/or `@reboot` screen scripts.
- Deploy: develop locally → push GitHub → pull/restart on VPS. Make changes visible on the live host.
- If something breaks (SSH, disk, OOM, rate limit): retry/reload until the task is finished.

## Compute locality

- Backtests, optimization, ML training, research plots: **this Windows machine only**, never on the VPS.
- VPS = live bots + botsgeneral collector only.

## Shared backtest engine (mandatory)

Every strategy program (xgb, TSM-VPA, LLM1, crypthor, …) that backtests, optimizes, plots,
or compares live vs backtest **must** use the **latest** `tradesim` package from botsgeneral —
not a vendored copy, not GitHub `backtesting.py`, not a per-repo reimplementation, not a
stale `site-packages` install.

- **Code path (source of truth):** `C:\projects\botsgeneral\packages\tradesim`
- **Operator guide:** `docs/project_memory/TRADESIM_BACKTEST_ENGINE_GUIDE.md` (also in
  `TRADING_BOT_CURSOR_RULES_V2.zip`)
- **Copy-paste prompt for strategy repos:** `docs/project_memory/TRADESIM_PROGRAM_PROMPT.md`
  (also mirrored under `AGENT_PROMPTS.md` → tradesim)
- **Install / auto-update in the project environment:**

```text
tradesim-update
# or
python -m tradesim.ensure_source --update
# or
pip install -e C:\projects\botsgeneral\packages\tradesim[conformance,plot]
```

```python
# First lines of every backtest / plot / hunt script:
import sys
from pathlib import Path
sys.path.insert(0, str(Path(r"C:\projects\botsgeneral\packages\tradesim\src")))
from tradesim.ensure_source import ensure_latest_tradesim
print(ensure_latest_tradesim(update=True))  # refreshes editable install + pins path
```

  `ensure_latest_tradesim(update=True)` runs `pip install -e …` into the **current**
  interpreter, then reloads so Finplot/metrics/engine edits under botsgeneral are picked
  up without a manual reinstall. Use `update=False` only for a fast path-pin assert.
  Refuse to run if `tradesim.__file__` does not contain `botsgeneral`.

  Prefer the botsgeneral research virtual environment when it is newer / has the
  conformance extras (e.g. `C:\projects\botsgeneral\.venv-tradesim-clean`), or keep the
  strategy venv synced to the same editable install.
- Before quoting numbers: `tradesim-conformance --engine tradesim --tests …` must be GREEN
  in that same environment.
- Plotting, metrics, sizing, candle refresh and venue limits all go through this package
  (`run_backtest`, `compute_metrics`, `ensure_candles`, `plot_backtest`, …).
- Preferred call: `run_backtest(..., strategy_meta={name, batch, model_path, tp_pct, sl_pct, …})`.
  Defaults write SQLite + a report folder and open full-period chart+metrics on interactive
  terminals (`plot=False` / `TRADESIM_NO_PLOT=1` for batch hunts).
- **Save / reload a finished backtest** (no re-simulation):

```text
# after run_backtest(...) — defaults already save
tradesim-research list --db D:/projectsdata/backtests/tradesim_runs.sqlite
tradesim-research show --db ... --run-id <id>
tradesim-research plot --db ... --run-id <id> --verify-fingerprint <prefix>
tradesim-research open --run-id <id>   # report folder + full-period chart/metrics, no resim
# report files: D:/projectsdata/backtests/reports/<run_id>/ (REPORT.md, strategy.json, metrics, trades.csv)
```

  Compare `run_fingerprint` (printed on save) to prove it is the exact same chart/data.

## Code style

- **Vectorized** calculations; avoid Python loops; optimize for speed.
- Live trade log in SQLite with full detail (fills, fees, TP/SL, pnl, timestamps).

## Strategy / backtest quality bar

- Prioritize: **Sharpe**, **# trades**, **PnL**, **winrate**, profit factor.
- Targets: Sharpe **> 1** (aim **> 4**), WR **> 60%** (best **> 65%**, ideal **80%+**), ideally **1–2+ trades/month** minimum viable; excellent = **1–2 trades/day** with high WR.
- Always report: period, # trades, avg trades/month, WR, PnL, Sharpe, profit factor, and other viability metrics.
- Longest possible history; **walk-forward** matching live; separate train/test with **zero leakage**.
- **Before any train/test:** run shared `C:\projects\botsgeneral\packages\leakage`
  (prefix-invariance + future-mutation) via `prefer_botsgeneral_leakage()` /
  `leakage-check`. Guide: `docs/project_memory/LEAKAGE_TEST_GUIDE.md`. Separate
  train/test files are hardening only. Hard-fail columns → `LEAKAGE_POTENTIAL`.
- Include **Bybit fees** + realistic **slippage** for market entries; limit entries can ignore slippage.
- Prefer **maker** (reduce fees) live when the strategy allows.
- Try multiple / multi timeframes (fractal markets).
- Both long and short preferred; long-only or short-only OK if reason is clear (bull bias caveat).
- After BTC/ETH winners: optimize SOL, VET, BNB, XRP, TRX, DOGE, XLM, ADA with **per-coin best params**.
- Document best strategy + params **per coin**.

## Exits & leverage (live)

- Use TP1/TP2/TP3 with best % allocation from backtests (e.g. 50/25/25); move SL to BE after TP1 or TP2 when backtests say so.
- Live TP/SL from **actual fill price**.
- Leverage: highest safe for the strategy so account funding is minimal; live default = **max leverage + min position size** unless user says otherwise.
- Choose leverage from backtests for long and short.

## Visualization

- Use **finplot** via **`tradesim.research.plot.plot_backtest`** only (shared plotter).
- Default trade markers: short horizontal lines (±3 bars) with a cross at entry,
  stop-loss, and each take-profit; labels `LONG`/`SHORT`, `SL`, `TP1`/`TP2`/`TP3`.
  **Green** = winning trade, **red** = losing trade. No filled boxes by default
  (`trade_style="zones"` restores the old rectangles). No price-pane trade legend;
  equity pane keeps its legend.
- That is why every project that plots through tradesim sees the same style — do not
  keep a private Finplot bypass.
- **Extra panes / custom overlays** (indicators, volume, Relative Strength Index (RSI), …):
  use the built-in hooks — do **not** fork a private Finplot layout.
  - `extra_rows=N` — empty panes under the price chart (shared X-axis).
  - `extra_row_heights=(…)` — optional Finplot height weights (default `0.45` each).
  - `on_axes(view)` — callback after equity/price/trades are drawn, before `show()`.
  - Return value is a `PlotView` (`ax_equity`, `ax_price`, `extra_axes`, clipped
    `bars_df` / `equity_df`, `fplt`). Still unpackable as axes when `extra_rows=0`.
  - Or `show=False`, draw yourself on `view.extra_axes[i]`, then `view.fplt.show()`.

```python
from tradesim.research.plot import plot_backtest

def add_rsi(view):
    view.fplt.plot(rsi.index, rsi.values, ax=view.extra_axes[0], legend="RSI")

plot_backtest(bars, result, extra_rows=1, on_axes=add_rsi)
```

## Live vs backtest

- Compare live metrics to backtest (WR, Sharpe, PF, trade rate). Investigate and fix discrepancies.
- **Mandatory:** before every backtest-versus-live-log comparison, **automatically refresh** the
  required research candles (decision timeframe + lower timeframe for same-bar resolve,
  Last and Mark) via `ensure_candles` / `tradesim-candles` / `botsgeneral research-candles`.
  Do not compare against a stale warehouse.
- Shared execution engine for new work: **`tradesim`** (not GitHub `backtesting.py`). Metrics
  include the backtesting.py-compatible set via `MetricsReport.as_backtesting_stats()`.
