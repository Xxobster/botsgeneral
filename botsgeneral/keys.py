from __future__ import annotations

import json
import os
import re
from pathlib import Path


def load_env_file(path: str | Path) -> dict[str, str]:
    p = Path(path)
    out: dict[str, str] = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def parse_bybit_keys_file(path: str | Path) -> dict[str, dict[str, str]]:
    """Parse 'ACCOUNT: Name / API KEY: / API SECRET:' text file."""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    accounts: dict[str, dict[str, str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"ACCOUNT:\s*(.+)$", line, re.I)
        if m:
            current = m.group(1).strip()
            accounts[current] = {}
            continue
        if current is None:
            continue
        m = re.match(r"API KEY:\s*(.+)$", line, re.I)
        if m:
            accounts[current]["api_key"] = m.group(1).strip()
            continue
        m = re.match(r"API SECRET:\s*(.+)$", line, re.I)
        if m:
            accounts[current]["api_secret"] = m.group(1).strip()
            continue
    return {k: v for k, v in accounts.items() if v.get("api_key") and v.get("api_secret")}


def parse_xgb_api_keys_json(path: str | Path) -> dict[str, dict[str, str]]:
    """Parse xgb-style {account: {api_key, api_secret}} JSON (skip *_local)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for name, creds in data.items():
        if not isinstance(creds, dict):
            continue
        if str(name).lower().endswith("_local"):
            continue
        key = creds.get("api_key") or creds.get("API_KEY")
        secret = creds.get("api_secret") or creds.get("API_SECRET")
        if key and secret:
            out[str(name)] = {"api_key": str(key), "api_secret": str(secret)}
    return out


def canonicalize_account_name(name: str) -> str:
    """xxobster2 -> Xxobster2 for stable display / registry match."""
    n = name.strip()
    m = re.match(r"(?i)^xxobster(\d*)$", n)
    if m:
        return "Xxobster" + m.group(1)
    return n


def _merge_accounts(*dicts: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """Merge by canonical name; later sources fill missing only."""
    out: dict[str, dict[str, str]] = {}
    for d in dicts:
        for raw, creds in d.items():
            canon = canonicalize_account_name(raw)
            if canon not in out:
                out[canon] = dict(creds)
            else:
                # keep first complete; allow fill if incomplete
                if not out[canon].get("api_key") and creds.get("api_key"):
                    out[canon]["api_key"] = creds["api_key"]
                if not out[canon].get("api_secret") and creds.get("api_secret"):
                    out[canon]["api_secret"] = creds["api_secret"]
    return {k: v for k, v in out.items() if v.get("api_key") and v.get("api_secret")}


def resolve_accounts(keys_path: str | None = None) -> dict[str, dict[str, str]]:
    """Load and merge Bybit accounts from all known key sources (txt + xgb json)."""
    merged: list[dict[str, dict[str, str]]] = []

    candidates: list[str] = []
    if keys_path:
        candidates.append(keys_path)
    env_keys = os.environ.get("BOTSGENERAL_KEYS")
    if env_keys:
        candidates.append(env_keys)
    candidates.extend(
        [
            "/etc/botsgeneral/keys.env",
            "/etc/botsgeneral/bybit_keys.txt",
            str(Path.home() / ".botsgeneral" / "keys.env"),
            str(Path(r"c:\projects\BASE CURSOR\api keys bybit.txt")),
            # xgb accounts (Xxobster2 / Xxobster13 live here)
            "/home/xgb/config/api_keys.json",
            "/opt/xgb/config/api_keys.json",
            str(Path(r"c:\projects\xgb\config\api_keys.json")),
            "/etc/botsgeneral/xgb_api_keys.json",
        ]
    )
    # Extra JSON paths from env
    extra = os.environ.get("BOTSGENERAL_EXTRA_KEYS")
    if extra:
        candidates.extend(p.strip() for p in extra.split(os.pathsep) if p.strip())

    seen: set[str] = set()
    for c in candidates:
        p = Path(c)
        key = str(p.resolve()) if p.exists() else c
        if key in seen:
            continue
        if not p.exists():
            continue
        seen.add(key)
        try:
            if p.suffix.lower() == ".json":
                merged.append(parse_xgb_api_keys_json(p))
            elif p.suffix.lower() in {".env"} or p.name.endswith(".env"):
                env = load_env_file(p)
                parsed: dict[str, dict[str, str]] = {}
                for k, v in env.items():
                    m = re.match(r"(.+)_API_KEY$", k, re.I)
                    if m:
                        parsed.setdefault(m.group(1), {})["api_key"] = v
                    m = re.match(r"(.+)_API_SECRET$", k, re.I)
                    if m:
                        parsed.setdefault(m.group(1), {})["api_secret"] = v
                if parsed:
                    merged.append(parsed)
            else:
                merged.append(parse_bybit_keys_file(p))
        except Exception:
            continue

    return _merge_accounts(*merged)


def resolve_binance_keys(keys_path: str | None = None) -> dict[str, str]:
    """Load Binance API key/secret from standard locations (public klines work without)."""
    candidates = []
    if keys_path:
        candidates.append(keys_path)
    env = os.environ.get("BOTSGENERAL_BINANCE_KEYS")
    if env:
        candidates.append(env)
    candidates.extend(
        [
            "/etc/botsgeneral/binance_keys.txt",
            str(Path(r"c:\projects\BASE CURSOR\api key binance.txt")),
            str(Path(r"c:\projects\xgb\config\api_keys.json")),
        ]
    )
    for c in candidates:
        p = Path(c)
        if not p.exists():
            continue
        if p.suffix.lower() == ".json":
            # not binance in xgb bybit json — skip
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        key_m = re.search(r"BINANCE_API_KEY\s*:\s*(\S+)", text, re.I)
        sec_m = re.search(r"BINANCE_API_SECRET\s*:\s*(\S+)", text, re.I)
        if key_m and sec_m:
            return {"api_key": key_m.group(1).strip(), "api_secret": sec_m.group(1).strip()}
        env_map = load_env_file(p)
        if env_map.get("BINANCE_API_KEY") and env_map.get("BINANCE_API_SECRET"):
            return {
                "api_key": env_map["BINANCE_API_KEY"],
                "api_secret": env_map["BINANCE_API_SECRET"],
            }
    ak = os.environ.get("BINANCE_API_KEY")
    sk = os.environ.get("BINANCE_API_SECRET")
    if ak and sk:
        return {"api_key": ak, "api_secret": sk}
    return {}
