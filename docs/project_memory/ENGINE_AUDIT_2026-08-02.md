# Engine audit — 2026-08-02

Classification of `metrics.py` / `backtest.py` / `engine.py` across active strategy repos
during the trading-platform promotion. Fill simulators must converge on `tradesim`.

## DUPLICATE_FILL_SIM (must migrate)

| Path | Status | Notes |
|------|--------|-------|
| `D:\projects\smartmoney\engine\backtest.py` | **Parity path exists** | `engine/tradesim_adapter.py` + `engine/parity_tests.py` |
| `C:\projects\divergences\src\backtesting\engine.py` | **Fleet on tradesim** | Prefer `scripts/run_fleet_tradesim.py`; legacy engine kept for comparison |
| `C:\projects\divergences\src\shadow\engine.py` | Secondary | Shadow fill path |
| `D:\projects\TSM-VPA\src\vpa\engine.py` | Orphan | Funding + liquidation; needs adapter |
| `C:\projects\emaslope\emaslope\backtest\engine.py` | Orphan | Fees/funding/MTM |
| `D:\projects\TSM-5min-scalp1\src\tsm5m\engine.py` | Orphan | Next-bar taker fills |
| `C:\projects\fib\src\fibbot\backtest.py` | Low priority | Backtesting.py third-party |
| `C:\projects\OB\src\obbot\backtest.py` | Low priority | Backtesting.py third-party |

## STRATEGY_LOCAL (keep)

Post-sim metrics (Sharpe/PSR/DSR/PBO), signal engines, CLI wrappers — not fill loops.
Examples: `divergences/src/divergence/engine.py`, `xgb/utils/audit_v4/metrics.py`,
`LD/ld/metrics.py`, `crypthor2/crypthor/backtest/v2/metrics.py`.

## Migration order

1. smartmoney — run existing parity tests; gate research on tradesim when green.
2. divergences — trade-ledger diff vs `run_fleet_tradesim`.
3. TSM-VPA — scaffold adapter before rewriting the event loop.

Policy: new research must call `tradesim.simulate` / `run_backtest`. Custom fill loops
are `RESEARCH_ONLY` legacy until parity-proven and retired.
