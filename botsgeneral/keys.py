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
