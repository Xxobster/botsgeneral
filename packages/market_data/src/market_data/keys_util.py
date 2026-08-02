"""Binance key resolution without depending on the botsgeneral ops package."""
from __future__ import annotations

import os
import re
from pathlib import Path


def _load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def resolve_binance_keys() -> dict[str, str]:
    ak = os.environ.get("BINANCE_API_KEY")
    sk = os.environ.get("BINANCE_API_SECRET")
    if ak and sk:
        return {"api_key": ak, "api_secret": sk}
    secrets = Path(os.environ.get("TRADING_SECRETS_ENV") or (Path.home() / ".trading" / "secrets.env"))
    env = _load_env_file(secrets)
    if env.get("BINANCE_API_KEY") and env.get("BINANCE_API_SECRET"):
        return {"api_key": env["BINANCE_API_KEY"], "api_secret": env["BINANCE_API_SECRET"]}
    # Optional fallback into botsgeneral if installed
    try:
        from botsgeneral.keys import resolve_binance_keys as _bg
        return _bg()
    except Exception:
        return {}
