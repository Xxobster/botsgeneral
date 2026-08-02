"""Persist LEAKAGE_POTENTIAL column marks for agents and rebuild gates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .types import ColumnStatus, Finding, Severity


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_registry(path: str | Path | None) -> dict:
    if path is None:
        return {"updated_at_utc": None, "columns": {}}
    p = Path(path)
    if not p.is_file():
        return {"updated_at_utc": None, "columns": {}}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid leakage registry at {p}")
    data.setdefault("columns", {})
    return data


def save_registry(path: str | Path, data: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at_utc"] = _utc()
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_registry_from_findings(
    path: str | Path,
    findings: Iterable[Finding],
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
    engine_note: str = "",
) -> dict:
    """Mark columns with findings as LEAKAGE_POTENTIAL; keep history."""
    data = load_registry(path)
    cols: dict = data.setdefault("columns", {})
    now = _utc()
    for f in findings:
        if f.column is None:
            continue
        if f.severity is Severity.HARD or f.severity is Severity.ADVISORY:
            entry = cols.get(f.column, {})
            reasons = list(entry.get("reasons", []))
            reason = f"{f.check.value}: {f.message}"
            if reason not in reasons:
                reasons.append(reason)
            entry.update(
                {
                    "status": ColumnStatus.LEAKAGE_POTENTIAL.value,
                    "reasons": reasons,
                    "first_seen_utc": entry.get("first_seen_utc") or now,
                    "last_seen_utc": now,
                    "symbol": symbol or entry.get("symbol"),
                    "timeframe": timeframe or entry.get("timeframe"),
                    "engine_note": engine_note or entry.get("engine_note", ""),
                }
            )
            cols[f.column] = entry
    data["columns"] = cols
    save_registry(path, data)
    return data


def leakage_potential_columns(path: str | Path | None) -> list[str]:
    data = load_registry(path)
    out = []
    for name, meta in data.get("columns", {}).items():
        if meta.get("status") == ColumnStatus.LEAKAGE_POTENTIAL.value:
            out.append(name)
    return sorted(out)


def assert_no_leakage_potential(
    path: str | Path | None,
    feature_columns: Iterable[str],
) -> None:
    """Raise if any requested feature is still marked LEAKAGE_POTENTIAL."""
    banned = set(leakage_potential_columns(path))
    hit = sorted(banned.intersection(set(feature_columns)))
    if hit:
        raise RuntimeError(
            "refusing train/test: feature columns marked LEAKAGE_POTENTIAL: "
            + ", ".join(hit)
            + f" (registry={path})"
        )
