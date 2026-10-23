"""Load static strategy summaries shipped with the HMI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_CATALOG: dict[str, Any] | None = None


def catalog_path() -> Path:
    return Path(__file__).resolve().parent / "strategy_catalog.yaml"


def load_catalog() -> dict[str, Any]:
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG
    p = catalog_path()
    if not p.exists():
        _CATALOG = {"bots": {}, "families": {}}
        return _CATALOG
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    _CATALOG = data if isinstance(data, dict) else {"bots": {}, "families": {}}
    return _CATALOG


def summaries_for_bots(bot_names: list[str], registry: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """One summary block per bot name (registry notes + catalog)."""
    cat = load_catalog()
    bots_cat = cat.get("bots") or {}
    families = cat.get("families") or {}
    reg_bots = (registry or {}).get("bots") or {}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in bot_names:
        key = str(name)
        if key in seen:
            continue
        seen.add(key)
        cfg = reg_bots.get(key) or {}
        entry = dict(bots_cat.get(key) or {})
        family_id = str(entry.get("family") or _family_guess(key))
        family = dict(families.get(family_id) or {})
        title = str(entry.get("title") or cfg.get("label") or key)
        summary = str(entry.get("summary") or family.get("summary") or cfg.get("notes") or "")
        out.append(
            {
                "bot": key,
                "label": str(cfg.get("label") or key),
                "title": title,
                "family": family_id,
                "family_title": family.get("title") or family_id,
                "summary": summary,
                "rules": entry.get("rules") or family.get("rules") or [],
                "timeframe": entry.get("timeframe") or cfg.get("timeframe"),
                "symbols": entry.get("symbols") or cfg.get("symbols") or [],
                "venue": entry.get("venue") or "Bybit USDT linear perpetual",
                "signal_venue": entry.get("signal_venue") or cfg.get("exchange"),
                "readiness": entry.get("readiness") or family.get("readiness") or "LIVE_STOP / RESEARCH_ONLY",
                "notes": str(cfg.get("notes") or entry.get("notes") or ""),
                "local_path": cfg.get("path_local") or entry.get("local_path"),
            }
        )
    return out


def _family_guess(bot: str) -> str:
    b = str(bot).lower()
    if b.startswith("llm2"):
        return "llm2"
    if b.startswith("tsm_chandelier") or "chandelier" in b:
        return "tsm_chandelier"
    if b.startswith("tsm_vpa") or b == "tsm-vpa":
        return "tsm_vpa"
    if b.startswith("crypthor"):
        return "crypthor"
    if b.startswith("karmaa"):
        return "karmaa_mp"
    if b.startswith("diver"):
        return "divergences"
    if b in {"news", "crypto_alpha"}:
        return "news"
    if b.startswith("xgb"):
        return "xgb"
    if b == "ld":
        return "ld"
    return "other"
