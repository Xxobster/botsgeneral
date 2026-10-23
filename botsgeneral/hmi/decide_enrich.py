"""Enrich HMI trades/positions with LLM2 decide confidence and risk percents."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def _f(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        if x != x:  # NaN
            return None
        return x
    except (TypeError, ValueError):
        return None


def _pct(v: Any) -> float | None:
    x = _f(v)
    return None if x is None else round(x, 4)


def _extract_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Pull display fields from a decide / detail JSON blob."""
    qd = payload.get("qty_detail") if isinstance(payload.get("qty_detail"), dict) else {}
    conf = _pct(payload.get("confidence_pct"))
    if conf is None and payload.get("confidence") is not None:
        c = _f(payload.get("confidence"))
        if c is not None:
            conf = round(c * 100.0, 4)
    if conf is None and qd.get("confidence_pct") is not None:
        conf = _pct(qd.get("confidence_pct"))

    risk = _pct(payload.get("risk_pct"))
    if risk is None and payload.get("intended_risk_fraction") is not None:
        rf = _f(payload.get("intended_risk_fraction"))
        if rf is not None:
            risk = round(rf * 100.0, 4)
    if risk is None and payload.get("risk_fraction") is not None:
        rf = _f(payload.get("risk_fraction"))
        if rf is not None:
            risk = round(rf * 100.0, 4)
    if risk is None and qd.get("risk_pct") is not None:
        risk = _pct(qd.get("risk_pct"))
    if risk is None and qd.get("risk_fraction") is not None:
        rf = _f(qd.get("risk_fraction"))
        if rf is not None:
            risk = round(rf * 100.0, 4)

    actual = _pct(payload.get("actual_risk_pct"))
    if actual is None and qd.get("actual_risk_pct") is not None:
        actual = _pct(qd.get("actual_risk_pct"))
    if actual is None and qd.get("actual_risk_fraction") is not None:
        ar = _f(qd.get("actual_risk_fraction"))
        if ar is not None:
            actual = round(ar * 100.0, 4)

    mode = payload.get("sizing_mode") or qd.get("sizing_mode")
    # Only surface when the pack recorded a risk/confidence sizing path.
    if conf is None and risk is None and actual is None:
        return {}
    if mode and str(mode) not in ("CONFIDENCE_RISK", "RISK_FRACTION") and conf is None and risk is None:
        # Still allow if explicit pct fields exist.
        pass

    display_risk = actual if actual is not None else risk
    out: dict[str, Any] = {
        "confidence_pct": conf,
        "risk_pct": risk,
        "actual_risk_pct": actual,
        "display_risk_pct": display_risk,
        "sizing_mode": mode,
        "confidence_source": payload.get("confidence_source") or qd.get("confidence_source"),
    }
    return {k: v for k, v in out.items() if v is not None}


def _order_ids_from_result(order_result: Any) -> list[str]:
    ids: list[str] = []
    if not isinstance(order_result, dict):
        return ids
    for k in ("order_id", "orderId"):
        v = order_result.get(k)
        if v:
            ids.append(str(v))
    placed = order_result.get("placed") if isinstance(order_result.get("placed"), dict) else {}
    resp = placed.get("response") if isinstance(placed.get("response"), dict) else {}
    res = resp.get("result") if isinstance(resp.get("result"), dict) else {}
    if res.get("orderId"):
        ids.append(str(res["orderId"]))
    tpsl = order_result.get("tpsl") if isinstance(order_result.get("tpsl"), dict) else {}
    for leg in ("tp", "sl"):
        body = tpsl.get(leg)
        items = body if isinstance(body, list) else ([body] if isinstance(body, dict) else [])
        for item in items:
            if not isinstance(item, dict):
                continue
            r = item.get("result") if isinstance(item.get("result"), dict) else {}
            if r.get("orderId"):
                ids.append(str(r["orderId"]))
            if item.get("orderId"):
                ids.append(str(item["orderId"]))
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _side_norm(side: Any) -> str:
    s = str(side or "").strip().lower()
    if s in ("buy", "long", "1"):
        return "Buy"
    if s in ("sell", "short", "-1"):
        return "Sell"
    if s.startswith("b"):
        return "Buy"
    if s.startswith("s"):
        return "Sell"
    return str(side or "")


def _iter_state_dbs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    out: list[Path] = []
    state = root / "state"
    if state.is_dir():
        out.extend(sorted(state.glob("*.sqlite")))
        out.extend(sorted(state.glob("*.db")))
    out.extend(sorted(root.glob("*.sqlite")))
    # de-dupe
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        if p.is_file():
            uniq.append(p)
    return uniq


def load_bot_decide_index(bot_id: str, bot_path: str | Path) -> list[dict[str, Any]]:
    """Load filled/open decide rows that carry confidence or risk."""
    rows: list[dict[str, Any]] = []
    for db in _iter_state_dbs(Path(bot_path)):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        try:
            tabs = {
                r[0]
                for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "pivot_decisions" in tabs:
                for bar_ms, raw in con.execute(
                    "SELECT bar_ts_ms, payload_json FROM pivot_decisions"
                ):
                    try:
                        payload = json.loads(raw or "{}")
                    except json.JSONDecodeError:
                        continue
                    fields = _extract_fields(payload)
                    if not fields:
                        continue
                    orr = payload.get("order_result")
                    filled = False
                    if isinstance(orr, dict):
                        filled = bool(orr.get("ok") and (orr.get("filled") or orr.get("stage") == "filled_tpsl" or orr.get("order_id")))
                    action = str(payload.get("action") or "")
                    if not filled and action not in ("ENTER_LIMIT", "ENTER", "ENTER_MARKET"):
                        # keep FLAT with conf only if needed for opens? skip
                        if not (isinstance(orr, dict) and orr.get("ok")):
                            continue
                    qd = payload.get("qty_detail") if isinstance(payload.get("qty_detail"), dict) else {}
                    rec = {
                        "bot_id": bot_id,
                        "bar_ts_ms": int(bar_ms),
                        "symbol": str(payload.get("symbol") or "").upper(),
                        "side": _side_norm(payload.get("side")),
                        "qty": _f(payload.get("qty") or payload.get("order_qty") or qd.get("qty")),
                        "entry_px": _f(
                            payload.get("avg_price")
                            or payload.get("entry_price")
                            or payload.get("limit_price")
                            or qd.get("entry_price")
                        ),
                        "order_ids": _order_ids_from_result(orr),
                        "filled": filled,
                        **fields,
                    }
                    rows.append(rec)
            if "decisions" in tabs:
                # micro_runner: detail JSON; symbol from path not in row — leave blank, match by order ids / time
                has_side = True
                for bar_ms, side, raw in con.execute(
                    "SELECT bar_ts_ms, side, detail FROM decisions"
                ):
                    try:
                        payload = json.loads(raw or "{}")
                    except json.JSONDecodeError:
                        continue
                    fields = _extract_fields(payload)
                    if not fields:
                        continue
                    oid = None
                    try:
                        oid = str(
                            ((payload.get("order") or {}).get("result") or {}).get("orderId")
                            or payload.get("order_id")
                            or ""
                        ) or None
                    except Exception:  # noqa: BLE001
                        oid = None
                    order_ids = [oid] if oid else []
                    # also from nested order_result if present
                    order_ids.extend(_order_ids_from_result(payload.get("order_result")))
                    rows.append(
                        {
                            "bot_id": bot_id,
                            "bar_ts_ms": int(bar_ms),
                            "symbol": str(payload.get("symbol") or "").upper(),
                            "side": _side_norm(side if has_side else payload.get("side")),
                            "qty": _f(payload.get("order_qty") or payload.get("qty")),
                            "order_ids": [x for x in order_ids if x],
                            "filled": payload.get("order_retCode") in (0, "0"),
                            **fields,
                        }
                    )
        except sqlite3.Error:
            continue
        finally:
            con.close()
    return rows


def build_decide_index_for_bots(
    registry: dict[str, Any], bot_ids: list[str]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Return (by_order_id, soft_rows) for the given bots."""
    bots_cfg = registry.get("bots") or {}
    by_order: dict[str, dict[str, Any]] = {}
    soft: list[dict[str, Any]] = []
    for bot_id in bot_ids:
        cfg = bots_cfg.get(bot_id) or {}
        path = cfg.get("path")
        if not path:
            continue
        for rec in load_bot_decide_index(bot_id, path):
            soft.append(rec)
            for oid in rec.get("order_ids") or []:
                prev = by_order.get(oid)
                if prev is None or (
                    prev.get("confidence_pct") is None and rec.get("confidence_pct") is not None
                ):
                    by_order[oid] = rec
    return by_order, soft


def _apply_fields(target: dict[str, Any], rec: dict[str, Any] | None) -> None:
    if not rec:
        return
    for k in (
        "confidence_pct",
        "risk_pct",
        "actual_risk_pct",
        "display_risk_pct",
        "sizing_mode",
        "confidence_source",
        "bot_id",
    ):
        if rec.get(k) is not None and target.get(k) is None:
            target[k] = rec[k]


def match_decide_to_trade(
    trade: dict[str, Any],
    by_order: dict[str, dict[str, Any]],
    soft: list[dict[str, Any]],
) -> dict[str, Any] | None:
    oid = str(trade.get("order_id") or trade.get("orderId") or "")
    if oid and oid in by_order:
        return by_order[oid]
    for leg_oid in trade.get("leg_order_ids") or []:
        if leg_oid and str(leg_oid) in by_order:
            return by_order[str(leg_oid)]
    # Soft match: symbol + exit qty <= entry qty (scale-out legs) near bar time.
    # Closed PnL side is the exit leg, so side is not required to match.
    sym = str(trade.get("symbol") or "").upper()
    qty = _f(trade.get("qty") or trade.get("closed_size") or trade.get("closedSize"))
    entry = _f(trade.get("entry") or trade.get("avgEntryPrice"))
    created = int(trade.get("created_ms") or trade.get("createdTime") or 0)
    updated = int(trade.get("updated_ms") or trade.get("updatedTime") or 0)
    best = None
    best_score = 1e99
    for rec in soft:
        if not rec.get("filled"):
            continue
        if rec.get("symbol") and sym and rec["symbol"] != sym:
            continue
        rq = rec.get("qty")
        if qty is not None and rq is not None:
            # Partial / scale exits are smaller than the entry decide qty.
            if float(qty) > float(rq) + max(1e-9, abs(float(rq)) * 1e-4):
                continue
        ep = rec.get("entry_px")
        if entry is not None and ep is not None:
            base = max(abs(float(ep)), 1e-12)
            if abs(float(entry) - float(ep)) > max(1e-6, 1e-8 * base):
                continue
        bar = int(rec.get("bar_ts_ms") or 0)
        if not bar:
            continue
        if created:
            dt = created - bar
            if dt < -5 * 60_000 or dt > 12 * 3_600_000:
                continue
            score = abs(dt)
        elif updated:
            score = abs(updated - bar)
        else:
            continue
        # Prefer exact qty, then larger entry covering this exit.
        if qty is not None and rq is not None:
            score += abs(float(rq) - float(qty)) * 1e-6
        if score < best_score:
            best_score = score
            best = rec
    return best


def enrich_trades_and_positions(
    *,
    trades: list[dict[str, Any]] | None,
    positions: list[dict[str, Any]] | None,
    registry: dict[str, Any],
    bot_ids: list[str],
) -> None:
    """In-place attach confidence_pct / risk_pct when decide DBs have them."""
    if not bot_ids:
        return
    llmish = [b for b in bot_ids if str(b).startswith("llm2")]
    if not llmish:
        return
    try:
        by_order, soft = build_decide_index_for_bots(registry, llmish)
    except Exception:  # noqa: BLE001
        return
    for t in trades or []:
        _apply_fields(t, match_decide_to_trade(t, by_order, soft))
    for p in positions or []:
        sym = str(p.get("symbol") or "").upper()
        side = _side_norm(p.get("side"))
        qty = _f(p.get("size") or p.get("qty"))
        best = None
        best_score = 1e99
        for rec in soft:
            if not rec.get("filled"):
                continue
            if rec.get("symbol") and sym and rec["symbol"] != sym:
                continue
            if rec.get("side") and side and rec["side"] != side:
                continue
            rq = rec.get("qty")
            if qty is not None and rq is not None:
                # After first scale-out, open size is the runner (< entry qty).
                if float(qty) > float(rq) + max(1e-9, abs(float(rq)) * 1e-4):
                    continue
            bar = int(rec.get("bar_ts_ms") or 0)
            if not bar:
                continue
            score = -bar  # prefer newest
            if qty is not None and rq is not None:
                score += abs(float(rq) - float(qty)) * 1e-9
            if score < best_score:
                best_score = score
                best = rec
        _apply_fields(p, best)
