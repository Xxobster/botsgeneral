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
    """Vectorized metrics from closed-pnl rows (Bybit closed-pnl list items).

    Risk headline metrics prefer recovery factor + MaxDD% over trade Sharpe:
    trade Sharpe mixes heterogeneous hold times and absolute USDT PnL scale,
    so it is a weak live-risk signal for small n.
    """
    empty = {
        "n_trades": 0,
        "wins": 0,
        "losses": 0,
        "winrate": None,
        "realized_pnl": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "profit_factor": None,
        "avg_pnl": None,
        "avg_win": None,
        "avg_loss": None,
        "payoff": None,
        "sharpe": None,
        "max_drawdown": None,
        "max_dd_pct": None,
        "recovery_factor": None,
    }
    if not closed:
        return empty

    pnls = np.array([float(t.get("closedPnl") or t.get("closed_pnl") or 0) for t in closed], dtype=float)
    n = int(pnls.size)
    wins_mask = pnls > 0
    losses_mask = pnls < 0
    wins = int(np.sum(wins_mask))
    losses = int(np.sum(losses_mask))
    gross_profit = float(np.sum(pnls[wins_mask])) if wins else 0.0
    gross_loss = float(np.abs(np.sum(pnls[losses_mask]))) if losses else 0.0
    realized = float(np.sum(pnls))
    wr = wins / n if n else None
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else None)
    avg_win = float(np.mean(pnls[wins_mask])) if wins else None
    avg_loss = float(np.mean(pnls[losses_mask])) if losses else None  # negative
    payoff = (
        (avg_win / abs(avg_loss))
        if avg_win is not None and avg_loss is not None and abs(avg_loss) > 1e-12
        else None
    )

    # Trade-level Sharpe (kept for JSON; not the live headline risk metric)
    std = float(np.std(pnls, ddof=1)) if n > 1 else 0.0
    mean = float(np.mean(pnls))
    sharpe = (mean / std) if std > 1e-12 else None

    # Equity curve drawdown on cumulative realized
    eq = np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    max_dd = float(np.min(dd)) if dd.size else 0.0
    # MaxDD as fraction of peak equity-on-curve (0 if peak never positive)
    peak_at_dd = float(peak[int(np.argmin(dd))]) if dd.size else 0.0
    max_dd_pct = (max_dd / peak_at_dd) if peak_at_dd > 1e-12 else None
    recovery_factor = (realized / abs(max_dd)) if abs(max_dd) > 1e-12 else (float("inf") if realized > 0 else None)

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
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff": payoff,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "max_dd_pct": max_dd_pct,
        "recovery_factor": recovery_factor,
    }


def _f(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def enrich_open_position(pos: dict[str, Any]) -> dict[str, Any]:
    """Add open time + % distance to nearer of TP/SL (Bybit position fields)."""
    out = dict(pos)
    mark = _f(pos.get("markPrice")) or _f(pos.get("avgPrice"))
    avg = _f(pos.get("avgPrice"))
    tp = _f(pos.get("takeProfit"))
    sl = _f(pos.get("stopLoss"))
    side = str(pos.get("side") or "").lower()
    is_long = side in ("buy", "long")

    to_tp_pct = None
    to_sl_pct = None
    if mark is not None and mark > 0:
        if tp is not None and tp > 0:
            # Signed: positive = price still needs to move that many % toward TP
            to_tp_pct = ((tp - mark) / mark * 100.0) if is_long else ((mark - tp) / mark * 100.0)
        if sl is not None and sl > 0:
            to_sl_pct = ((mark - sl) / mark * 100.0) if is_long else ((sl - mark) / mark * 100.0)

    closer = None
    closer_pct = None
    candidates: list[tuple[str, float]] = []
    if to_tp_pct is not None:
        candidates.append(("TP", abs(to_tp_pct)))
    if to_sl_pct is not None:
        candidates.append(("SL", abs(to_sl_pct)))
    if candidates:
        closer, closer_pct = min(candidates, key=lambda x: x[1])

    opened_ms = None
    for k in ("createdTime", "created_time", "updatedTime"):
        v = pos.get(k)
        if v is not None and str(v).isdigit():
            opened_ms = int(v)
            break

    out["markPrice"] = mark
    out["avgPrice"] = avg if avg is not None else pos.get("avgPrice")
    out["takeProfit"] = tp
    out["stopLoss"] = sl
    out["to_tp_pct"] = to_tp_pct
    out["to_sl_pct"] = to_sl_pct
    out["closer_exit"] = closer
    out["closer_pct"] = closer_pct
    out["opened_at_ms"] = opened_ms
    return out


def last_open_event(
    positions: list[dict[str, Any]],
    closed: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Most recent position open: prefer live opens, else latest closed entry time."""
    best_ts = -1
    best_sym = None
    best_src = None
    for p in positions or []:
        ts = int(p.get("opened_at_ms") or p.get("createdTime") or 0)
        if ts > best_ts:
            best_ts = ts
            best_sym = (p.get("symbol") or "").upper() or None
            best_src = "open"
    if best_ts < 0:
        for t in closed or []:
            ts = int(t.get("createdTime") or t.get("updatedTime") or 0)
            if ts > best_ts:
                best_ts = ts
                best_sym = (t.get("symbol") or "").upper() or None
                best_src = "closed"
    if best_ts < 0 or not best_sym:
        return None
    return {"ts_ms": best_ts, "symbol": best_sym, "source": best_src}


def fmt_ts_utc(ts_ms: int | None) -> str:
    if not ts_ms:
        return "-"
    try:
        return datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(ts_ms)


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


def fmt_signed_pct(x: float | None, digits: int = 2) -> str:
    """Format an already-percent value (e.g. 1.25 -> '+1.25%')."""
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "-"
    return f"{x:+.{digits}f}%"
