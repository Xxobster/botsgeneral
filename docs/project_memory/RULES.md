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

## VPS ops

- Launch live bots in **screen** with **explicit session names**.
- **Auto-restart on reboot**: systemd (preferred) and/or `@reboot` screen scripts.
- Deploy: develop locally → push GitHub → pull/restart on VPS. Make changes visible on the live host.
- If something breaks (SSH, disk, OOM, rate limit): retry/reload until the task is finished.

## Compute locality

- Backtests, optimization, ML training, research plots: **this Windows machine only**, never on the VPS.
- VPS = live bots + botsgeneral collector only.

## Code style

- **Vectorized** calculations; avoid Python loops; optimize for speed.
- Live trade log in SQLite with full detail (fills, fees, TP/SL, pnl, timestamps).

## Strategy / backtest quality bar

- Prioritize: **Sharpe**, **# trades**, **PnL**, **winrate**, profit factor.
- Targets: Sharpe **> 1** (aim **> 4**), WR **> 60%** (best **> 65%**, ideal **80%+**), ideally **1–2+ trades/month** minimum viable; excellent = **1–2 trades/day** with high WR.
- Always report: period, # trades, avg trades/month, WR, PnL, Sharpe, profit factor, and other viability metrics.
- Longest possible history; **walk-forward** matching live; separate train/test with **zero leakage**.
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

- Use **finplot** for visual trade reviews (pattern as in crypthor).
- Use project `backtest.py` / scripts pattern as in xgb/crypthor.

## Live vs backtest

- Compare live metrics to backtest (WR, Sharpe, PF, trade rate). Investigate and fix discrepancies.
