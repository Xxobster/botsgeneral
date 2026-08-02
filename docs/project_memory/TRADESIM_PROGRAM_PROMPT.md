# Prompt: wire any strategy program to latest tradesim (auto-update)

Copy-paste into a project agent (xgb, TSM-VPA, LLM1, crypthor, …).

```
Context: botsgeneral owns the shared backtest engine `tradesim` at
C:\projects\botsgeneral\packages\tradesim. Strategy programs must NOT vendor a
simulator and must NOT rely on a stale site-packages wheel.

Obey C:\projects\botsgeneral\docs\project_memory\RULES.md and
TRADESIM_BACKTEST_ENGINE_GUIDE.md. Update this project's docs/project_memory/.

Goals:
1. At the top of every backtest / plot / hunt entry script (before other tradesim
   imports), bootstrap the latest engine:

   import sys
   from pathlib import Path
   sys.path.insert(0, str(Path(r"C:\projects\botsgeneral\packages\tradesim\src")))
   from tradesim.ensure_source import ensure_latest_tradesim
   print(ensure_latest_tradesim(update=True))  # pip install -e + path pin

   Or CLI once per environment:
   tradesim-update
   python -m tradesim.ensure_source --update

2. Use tradesim for simulation, metrics, Finplot, candle ensure, venue sizing:
   run_backtest / simulate / compute_metrics / plot_backtest / ensure_candles.
   Do not keep a private Finplot helper.

3. Finplot defaults (shared plotter):
   - equity pane: realized step curve
   - price pane: short horizontal levels (±3 bars) with a cross at entry, SL,
     TP1/TP2/TP3; labels LONG|SHORT, SL, TP1…; green=winning trade, red=losing
   - no filled green/red boxes unless trade_style="zones"
   - no price-pane trade legend

4. Research wallet default is **10_000 USDT** (`RESEARCH_STARTING_EQUITY_USDT`) so
   1× + venue min size never fails margin on BTC/ETH. Headline money % is
   **return on invested notional**, not wallet %. Override only with
   `research_starting_equity(price=..., qty=..., leverage=1)` if you need a floor.

5. Before quoting numbers: tradesim conformance GREEN in the same environment.
   Save runs via BacktestStore / run_backtest store; reopen with
   tradesim-research open --run-id …

6. Do not deploy/live-change without explicit user authorization.

Deliverable: scripts updated, a one-line print of tradesim version+path on start,
and project memory note that this repo auto-updates tradesim via ensure_latest_tradesim.
```
