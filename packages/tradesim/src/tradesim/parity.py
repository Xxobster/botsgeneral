"""Trade-by-trade parity diff between two engines on one common configuration.

Migration tool. Before a repository is switched over, the incumbent engine and tradesim
run the same configuration and every difference is explained in writing. A difference
that cannot be explained is a defect in one of the two, and until it is understood the
numbers from both are unquotable.

Matching is by entry timestamp within a tolerance, because a genuine off-by-one in entry
timing is exactly the kind of difference this is looking for: an unmatched trade on
either side is reported rather than quietly paired with its neighbour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

import math

import pandas as pd

FIELDS = (
    "entry_ts_ms",
    "exit_ts_ms",
    "side",
    "entry_price",
    "exit_price",
    "qty",
    "exit_reason",
    "fees",
    "funding",
    "realized_pnl",
)


@dataclass(frozen=True)
class Tolerance:
    price: float = 1e-8
    qty: float = 1e-9
    money: float = 1e-8
    ts_ms: int = 0
    ignore_reason: bool = False


@dataclass
class ParityDiff:
    left_name: str
    right_name: str
    matched: int = 0
    only_left: list[Mapping[str, Any]] = field(default_factory=list)
    only_right: list[Mapping[str, Any]] = field(default_factory=list)
    differences: list[Mapping[str, Any]] = field(default_factory=list)
    aggregate: dict[str, Any] = field(default_factory=dict)

    @property
    def identical(self) -> bool:
        return not self.only_left and not self.only_right and not self.differences

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.differences)

    def summary(self) -> str:
        lines = [
            "",
            "=" * 84,
            f"PARITY  {self.left_name}  vs  {self.right_name}",
            "=" * 84,
            f"matched trades      : {self.matched}",
            f"only in {self.left_name:<12}: {len(self.only_left)}",
            f"only in {self.right_name:<12}: {len(self.only_right)}",
            f"field differences   : {len(self.differences)}",
        ]
        for key, value in self.aggregate.items():
            lines.append(f"{key:<20}: {value}")
        if self.identical:
            lines.append("\nThe two engines agree trade for trade within tolerance.")
        else:
            lines.append(
                "\nEvery difference below must be explained in writing before either "
                "engine's numbers are quoted."
            )
            for d in self.differences[:50]:
                lines.append(
                    f"  entry {d['entry_ts_ms']}  {d['field']}: "
                    f"{d['left']} vs {d['right']}  (delta {d['delta']})"
                )
            if len(self.differences) > 50:
                lines.append(f"  ... and {len(self.differences) - 50} more")
            for row in self.only_left[:20]:
                lines.append(f"  only in {self.left_name}: entry {row['entry_ts_ms']}")
            for row in self.only_right[:20]:
                lines.append(f"  only in {self.right_name}: entry {row['entry_ts_ms']}")
        lines.append("=" * 84)
        return "\n".join(lines)


def _as_records(trades: Iterable[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in trades:
        if isinstance(t, Mapping):
            out.append({f: t.get(f) for f in FIELDS})
        else:
            out.append({f: getattr(t, f, None) for f in FIELDS})
    return sorted(out, key=lambda r: (r["entry_ts_ms"] or 0, r["exit_ts_ms"] or 0))


def _tolerance_for(field_name: str, tol: Tolerance) -> float:
    if field_name in ("entry_price", "exit_price"):
        return tol.price
    if field_name == "qty":
        return tol.qty
    if field_name in ("fees", "funding", "realized_pnl"):
        return tol.money
    if field_name in ("entry_ts_ms", "exit_ts_ms"):
        return float(tol.ts_ms)
    return 0.0


def diff_trades(
    left: Iterable[Any],
    right: Iterable[Any],
    *,
    left_name: str = "left",
    right_name: str = "right",
    tolerance: Tolerance | None = None,
) -> ParityDiff:
    tol = tolerance or Tolerance()
    lrecs = _as_records(left)
    rrecs = _as_records(right)
    result = ParityDiff(left_name=left_name, right_name=right_name)

    used_right: set[int] = set()
    for lrec in lrecs:
        match_idx = None
        for j, rrec in enumerate(rrecs):
            if j in used_right:
                continue
            if abs(int(lrec["entry_ts_ms"] or 0) - int(rrec["entry_ts_ms"] or 0)) <= tol.ts_ms:
                match_idx = j
                break
        if match_idx is None:
            result.only_left.append(lrec)
            continue
        used_right.add(match_idx)
        rrec = rrecs[match_idx]
        result.matched += 1
        for field_name in FIELDS:
            lv, rv = lrec[field_name], rrec[field_name]
            if field_name == "exit_reason":
                if tol.ignore_reason:
                    continue
                if str(lv) != str(rv):
                    result.differences.append(
                        {
                            "entry_ts_ms": lrec["entry_ts_ms"],
                            "field": field_name,
                            "left": lv,
                            "right": rv,
                            "delta": "",
                        }
                    )
                continue
            if lv is None or rv is None:
                if lv != rv:
                    result.differences.append(
                        {
                            "entry_ts_ms": lrec["entry_ts_ms"],
                            "field": field_name,
                            "left": lv,
                            "right": rv,
                            "delta": "",
                        }
                    )
                continue
            delta = float(lv) - float(rv)
            if abs(delta) > _tolerance_for(field_name, tol):
                result.differences.append(
                    {
                        "entry_ts_ms": lrec["entry_ts_ms"],
                        "field": field_name,
                        "left": lv,
                        "right": rv,
                        "delta": delta,
                    }
                )
    for j, rrec in enumerate(rrecs):
        if j not in used_right:
            result.only_right.append(rrec)

    result.aggregate = _aggregate(lrecs, rrecs, left_name, right_name)
    return result


def _aggregate(
    lrecs: Sequence[Mapping[str, Any]],
    rrecs: Sequence[Mapping[str, Any]],
    left_name: str,
    right_name: str,
) -> dict[str, Any]:
    def total(recs: Sequence[Mapping[str, Any]], key: str) -> float:
        return float(sum(float(r[key] or 0.0) for r in recs))

    out: dict[str, Any] = {
        f"n_trades {left_name}": len(lrecs),
        f"n_trades {right_name}": len(rrecs),
    }
    for key in ("realized_pnl", "fees", "funding"):
        lt, rt = total(lrecs, key), total(rrecs, key)
        out[f"{key} delta"] = f"{lt:,.6f} - {rt:,.6f} = {lt - rt:,.6f}"
    l_entry_bar = sum(1 for r in lrecs if "entry_bar" in str(r["exit_reason"]))
    r_entry_bar = sum(1 for r in rrecs if "entry_bar" in str(r["exit_reason"]))
    out["entry-bar exits"] = f"{left_name} {l_entry_bar} vs {right_name} {r_entry_bar}"
    return out


def run_parity(
    *,
    left_engine: Callable[[], Any],
    right_engine: Callable[[], Any],
    left_name: str = "incumbent",
    right_name: str = "tradesim",
    tolerance: Tolerance | None = None,
) -> ParityDiff:
    """Run two zero-argument callables that each return an object with ``.trades``."""
    left_result = left_engine()
    right_result = right_engine()
    return diff_trades(
        getattr(left_result, "trades", left_result),
        getattr(right_result, "trades", right_result),
        left_name=left_name,
        right_name=right_name,
        tolerance=tolerance,
    )
