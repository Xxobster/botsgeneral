from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np


def trade_ts_ms(t: dict[str, Any]) -> int:
    for k in ("updatedTime", "updated_ms", "createdTime", "created_ms"):
        raw = t.get(k)
        if raw in (None, ""):
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return 0


def days_active(since_ms: int, now_ms: int | None = None) -> float:
    """Calendar days from the PnL start stamp to now (UTC)."""
    import time as _time

    now = int(now_ms if now_ms is not None else _time.time() * 1000)
    return round(max(0.0, (now - int(since_ms)) / 86_400_000.0), 2)


def equity_curve_from_closed(
    closed: list[dict[str, Any]],
    *,
    max_points: int = 400,
) -> dict[str, Any]:
    """Cumulative realized Profit and Loss (PnL) vs close time. Vectorized cumsum."""
    empty = {"points": [], "final": 0.0, "n": 0}
    if not closed:
        return empty
    ordered = sorted(closed, key=trade_ts_ms)
    pnls = np.array(
        [float(t.get("closedPnl") or t.get("closed_pnl") or 0) for t in ordered],
        dtype=float,
    )
    ts = np.array([trade_ts_ms(t) for t in ordered], dtype=np.int64)
    if pnls.size == 0:
        return empty
    cum = np.cumsum(pnls)
    n = int(pnls.size)
    if n <= max_points:
        idx = np.arange(n)
    else:
        idx = np.linspace(0, n - 1, max_points).astype(np.int64)
        idx[-1] = n - 1
        idx = np.unique(idx)
    points = [{"t": int(ts[i]), "cum": float(cum[i])} for i in idx.tolist()]
    return {"points": points, "final": float(cum[-1]), "n": n}


def equity_curves_by_symbol(closed: list[dict[str, Any]], *, max_points: int = 300) -> dict[str, Any]:
    by: dict[str, list[dict[str, Any]]] = {}
    for t in closed:
        sym = str(t.get("symbol") or "?").upper()
        by.setdefault(sym, []).append(t)
    return {sym: equity_curve_from_closed(rows, max_points=max_points) for sym, rows in by.items()}


def parse_since_ms(since_date: str) -> int:
    """Parse a since stamp to UTC milliseconds.

    ``YYYY-MM-DD`` is UTC midnight (same window as before). Datetime forms keep
    the clock so a same-calendar-day leftover close can be excluded:

    ``2026-09-01T11:38:16Z``, ``2026-09-01 11:38:16``, or offset ISO-8601.
    Naive datetimes are treated as UTC.
    """
    raw = str(since_date).strip()
    if not raw:
        raise ValueError("empty since")
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    if len(raw) == 10:
        d = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return int(d.timestamp() * 1000)
    if len(raw) >= 11 and raw[10] == " ":
        raw = raw[:10] + "T" + raw[11:]
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _entry_px(t: dict[str, Any]) -> float | None:
    for k in ("avgEntryPrice", "entry", "avg_entry_price"):
        v = t.get(k)
        if v in (None, ""):
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _leg_qty(t: dict[str, Any]) -> float:
    for k in ("closedSize", "closed_size", "qty", "size"):
        v = t.get(k)
        if v in (None, ""):
            continue
        try:
            return abs(float(v))
        except (TypeError, ValueError):
            continue
    return 0.0


def _leg_pnl(t: dict[str, Any]) -> float:
    try:
        return float(t.get("closedPnl") or t.get("closed_pnl") or t.get("pnl") or 0)
    except (TypeError, ValueError):
        return 0.0


def group_closed_legs_to_roundtrips(
    closed: list[dict[str, Any]],
    *,
    window_ms: int = 7 * 24 * 3_600_000,
    entry_rel_eps: float = 1e-8,
) -> list[dict[str, Any]]:
    """Merge scale-out / partial exit legs that share one entry into one round-trip.

    Bybit closed-Profit-and-Loss (PnL) lists every take-profit fill as its own row.
    Counting those as separate trades inflates Human-Machine Interface (HMI)
    closed-trade counts (e.g. three identical 0.1 Solana takes from one 0.3 entry).
    """
    if not closed:
        return []
    ordered = sorted(closed, key=trade_ts_ms)
    groups: list[dict[str, Any]] = []
    for leg in ordered:
        sym = str(leg.get("symbol") or "").upper()
        side = str(leg.get("side") or "")
        entry = _entry_px(leg)
        ts = trade_ts_ms(leg)
        matched = None
        for g in groups:
            if g["symbol"] != sym or g["side"] != side:
                continue
            if entry is None or g["entry"] is None:
                continue
            base = max(abs(float(g["entry"])), 1e-12)
            if abs(float(entry) - float(g["entry"])) > max(entry_rel_eps * base, 1e-8):
                continue
            if ts - int(g["first_ms"]) > int(window_ms):
                continue
            matched = g
            break
        if matched is None:
            groups.append(
                {
                    "symbol": sym,
                    "side": side,
                    "entry": entry,
                    "exit": leg.get("avgExitPrice") or leg.get("exit"),
                    "legs": [leg],
                    "first_ms": ts,
                    "last_ms": ts,
                    "qty": _leg_qty(leg),
                    "closedPnl": _leg_pnl(leg),
                    "orderId": leg.get("orderId") or leg.get("order_id"),
                    "leverage": leg.get("leverage"),
                    "createdTime": leg.get("createdTime") or leg.get("created_ms"),
                    "updatedTime": leg.get("updatedTime") or leg.get("updated_ms") or ts,
                }
            )
            continue
        matched["legs"].append(leg)
        matched["last_ms"] = max(int(matched["last_ms"]), ts)
        matched["qty"] = float(matched["qty"]) + _leg_qty(leg)
        matched["closedPnl"] = float(matched["closedPnl"]) + _leg_pnl(leg)
        matched["updatedTime"] = matched["last_ms"]
        # Prefer the last exit price for display.
        matched["exit"] = leg.get("avgExitPrice") or leg.get("exit") or matched["exit"]

    out: list[dict[str, Any]] = []
    for g in groups:
        legs = g["legs"]
        row = {
            "orderId": g["orderId"],
            "symbol": g["symbol"],
            "side": g["side"],
            "qty": g["qty"],
            "closedSize": g["qty"],
            "avgEntryPrice": g["entry"],
            "avgExitPrice": g["exit"],
            "closedPnl": g["closedPnl"],
            "leverage": g["leverage"],
            "createdTime": g["createdTime"] or g["first_ms"],
            "updatedTime": g["updatedTime"] or g["last_ms"],
            "leg_count": len(legs),
            "leg_order_ids": [
                str(x.get("orderId") or x.get("order_id") or "")
                for x in legs
                if x.get("orderId") or x.get("order_id")
            ],
        }
        # Keep first leg extras that normalize_closed_trades may want.
        for k in ("orderType", "execType", "openFee", "closeFee", "cumEntryFee", "cumExitFee", "fillCount"):
            if k in legs[0] and k not in row:
                row[k] = legs[0].get(k)
        out.append(row)
    out.sort(key=lambda r: int(r.get("updatedTime") or 0), reverse=True)
    return out


def trade_metrics(
    closed: list[dict[str, Any]],
    *,
    group_roundtrips: bool = True,
) -> dict[str, Any]:
    """Vectorized metrics from closed-pnl rows (Bybit closed-pnl list items).

    Risk headline metrics prefer recovery factor + MaxDD% over trade Sharpe:
    trade Sharpe mixes heterogeneous hold times and absolute USDT PnL scale,
    so it is a weak live-risk signal for small n.

    By default, scale-out legs that share one entry are merged into round-trips
    before counting wins/losses (``n_trades``). ``n_legs`` keeps the raw Bybit
    fill count for diagnostics.
    """
    empty = {
        "n_trades": 0,
        "n_legs": 0,
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
    n_legs = len(closed or [])
    rows = group_closed_legs_to_roundtrips(closed) if group_roundtrips else list(closed or [])
    if not rows:
        empty["n_legs"] = n_legs
        return empty

    pnls = np.array([_leg_pnl(t) for t in rows], dtype=float)
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
        "n_legs": n_legs,
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

    # Bybit: openTime = current cycle open; createdTime = first-ever on symbol.
    opened_ms = _position_opened_at_ms(pos)

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


def _as_ms(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _position_opened_at_ms(pos: dict[str, Any]) -> int | None:
    """Current-cycle open time for a live Bybit position.

    Prefer ``openTime`` (this cycle). Never use ``createdTime`` — Bybit documents
    it as the first time a position was created on the symbol, so it stays at an
    old date across flat/reopen and breaks ``last_open`` / ``opened=``.
    """
    for k in ("openTime", "open_time", "opened_at_ms"):
        ts = _as_ms(pos.get(k))
        if ts is not None:
            return ts
    return None


def last_open_event(
    positions: list[dict[str, Any]],
    closed: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Most recent position-open event across live opens and closed rows.

    Takes the max timestamp from both sources (not live-only). Live rows use
    current-cycle ``openTime`` via ``opened_at_ms``; closed rows use Bybit
    closed-pnl ``createdTime`` (close time — best available without execution
    history) only when no newer live open exists.
    """
    best_ts = -1
    best_sym = None
    best_src = None
    for p in positions or []:
        ts = _position_opened_at_ms(p)
        if ts is None:
            continue
        if ts > best_ts:
            best_ts = ts
            best_sym = (p.get("symbol") or "").upper() or None
            best_src = "open"
    for t in closed or []:
        ts = _as_ms(t.get("createdTime")) or _as_ms(t.get("updatedTime"))
        if ts is None:
            continue
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
