from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np


def parse_since_ms(since_date: str) -> int:
    """Parse YYYY-MM-DD as UTC midnight → ms."""
    d = datetime.strptime(since_date.strip()[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000)


def trade_metrics(closed: list[dict[str, Any]]) -> dict[str, Any]:
    """Vectorized metrics from closed-pnl rows (Bybit closed-pnl list items)."""
    if not closed:
        return {
            "n_trades": 0,
            "wins": 0,
            "losses": 0,
            "winrate": None,
            "realized_pnl": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "profit_factor": None,
            "avg_pnl": None,
            "sharpe": None,
            "max_drawdown": None,
        }

    pnls = np.array([float(t.get("closedPnl") or t.get("closed_pnl") or 0) for t in closed], dtype=float)
    n = int(pnls.size)
    wins = int(np.sum(pnls > 0))
    losses = int(np.sum(pnls < 0))
    gross_profit = float(np.sum(pnls[pnls > 0])) if wins else 0.0
    gross_loss = float(np.abs(np.sum(pnls[pnls < 0]))) if losses else 0.0
    realized = float(np.sum(pnls))
    wr = wins / n if n else None
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else None)

    # Trade-level Sharpe (mean/std of trade returns); annualization not applied (heterogeneous hold times)
    std = float(np.std(pnls, ddof=1)) if n > 1 else 0.0
    mean = float(np.mean(pnls))
    sharpe = (mean / std) if std > 1e-12 else None

    # Equity curve drawdown on cumulative realized
    eq = np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    max_dd = float(np.min(dd)) if dd.size else 0.0

    return {
        "n_trades": n,
        "wins": wins,
        "losses": losses,
        "winrate": wr,
        "realized_pnl": realized,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": pf,
        "avg_pnl": mean,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
    }


def fmt_pct(x: float | None) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "-"
    return f"{100 * x:.1f}%"


def fmt_num(x: float | None, digits: int = 4) -> str:
    if x is None:
        return "-"
    if isinstance(x, float) and math.isinf(x):
        return "inf"
    return f"{x:.{digits}f}"
