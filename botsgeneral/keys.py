from __future__ import annotations

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


def resolve_accounts(keys_path: str | None = None) -> dict[str, dict[str, str]]:
    """Load accounts from env file or Bybit keys text file."""
    candidates = []
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
        ]
    )
    # Local Windows default used in this workspace
    local_txt = Path(r"c:\projects\BASE CURSOR\api keys bybit.txt")
    if local_txt.exists():
        candidates.append(str(local_txt))

    for c in candidates:
        p = Path(c)
        if not p.exists():
            continue
        if p.suffix.lower() in {".env"} or p.name.endswith(".env"):
            env = load_env_file(p)
            # Support ACCOUNT_Xxobster_KEY style or flat Xxobster_API_KEY
            parsed: dict[str, dict[str, str]] = {}
            for k, v in env.items():
                m = re.match(r"(.+)_API_KEY$", k, re.I)
                if m:
                    name = m.group(1)
                    parsed.setdefault(name, {})["api_key"] = v
                m = re.match(r"(.+)_API_SECRET$", k, re.I)
                if m:
                    name = m.group(1)
                    parsed.setdefault(name, {})["api_secret"] = v
            if parsed:
                return {k: v for k, v in parsed.items() if v.get("api_key") and v.get("api_secret")}
        else:
            return parse_bybit_keys_file(p)
    return {}


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
            import json

            data = json.loads(p.read_text(encoding="utf-8"))
            # common shapes: {"binance": {"api_key":...}} or flat
            if "binance" in data and isinstance(data["binance"], dict):
                d = data["binance"]
                key = d.get("api_key") or d.get("API_KEY")
                secret = d.get("api_secret") or d.get("API_SECRET")
                if key and secret:
                    return {"api_key": key, "api_secret": secret}
            key = data.get("BINANCE_API_KEY") or data.get("api_key")
            secret = data.get("BINANCE_API_SECRET") or data.get("api_secret")
            if key and secret:
                return {"api_key": str(key), "api_secret": str(secret)}
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
    # env vars
    ak = os.environ.get("BINANCE_API_KEY")
    sk = os.environ.get("BINANCE_API_SECRET")
    if ak and sk:
        return {"api_key": ak, "api_secret": sk}
    return {}
