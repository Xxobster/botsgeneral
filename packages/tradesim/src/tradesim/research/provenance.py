"""Gather run provenance for research backtests (no network)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..version import ENGINE_NAME, ENGINE_VERSION

# packages/tradesim/src/tradesim/research/provenance.py → botsgeneral/
_BOTSGENERAL_ROOT = Path(__file__).resolve().parents[5]

_PROVENANCE_KEYS = (
    "engine_name",
    "engine_version",
    "engine_git_commit",
    "strategy_git_commit",
    "config_hash",
    "data_snapshot_id",
    "dependency_lock_hash",
    "random_seed",
    "created_at_utc",
)


def _git_head(repo: Path | None) -> str | None:
    if repo is None or not Path(repo).is_dir():
        return None
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    commit = (out.stdout or "").strip()
    return commit or None


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _config_hash(config: Mapping[str, Any] | None) -> str | None:
    if config is None:
        return None
    payload = json.dumps(config, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _dependency_lock_hash(repo_root: Path | None = None) -> str | None:
    root = Path(repo_root) if repo_root is not None else _BOTSGENERAL_ROOT
    for name in ("uv.lock", "requirements.txt", "requirements.lock"):
        digest = _file_sha256(root / name)
        if digest:
            return digest
    return None


def _data_snapshot_id(data_path: str | Path | None) -> str | None:
    if data_path is None:
        return None
    path = Path(data_path)
    if not path.exists():
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    # Path + size + mtime_ns is stable enough for local OHLCV DBs without hashing GB files.
    raw = f"{path.resolve()}|{st.st_size}|{getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9))}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def collect_provenance(
    *,
    config: Mapping[str, Any] | None = None,
    config_hash: str | None = None,
    strategy_git_commit: str | None = None,
    strategy_cwd: str | Path | None = None,
    data_snapshot_id: str | None = None,
    data_path: str | Path | None = None,
    random_seed: int | None = None,
    engine_repo: str | Path | None = None,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    """Collect provenance fields for a research run (local only, no network).

    Keys (also persisted as explicit SQLite columns when available)::

        engine_name, engine_version, engine_git_commit, strategy_git_commit,
        config_hash, data_snapshot_id, dependency_lock_hash, random_seed,
        created_at_utc
    """
    engine_root = Path(engine_repo) if engine_repo is not None else _BOTSGENERAL_ROOT
    strat_commit = strategy_git_commit
    if strat_commit is None:
        strat_commit = os.environ.get("STRATEGY_GIT_COMMIT") or os.environ.get(
            "TRADESIM_STRATEGY_GIT_COMMIT"
        )
    if strat_commit is None:
        cwd = Path(strategy_cwd) if strategy_cwd is not None else Path.cwd()
        strat_commit = _git_head(cwd)

    seed = random_seed
    if seed is None:
        env_seed = os.environ.get("TRADESIM_RANDOM_SEED", "").strip()
        if env_seed:
            try:
                seed = int(env_seed)
            except ValueError:
                seed = None

    snap = data_snapshot_id
    if snap is None:
        snap = _data_snapshot_id(data_path)

    cfg_hash = config_hash if config_hash is not None else _config_hash(config)

    created = created_at_utc
    if not created:
        created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    return {
        "engine_name": ENGINE_NAME,
        "engine_version": ENGINE_VERSION,
        "engine_git_commit": _git_head(engine_root),
        "strategy_git_commit": strat_commit,
        "config_hash": cfg_hash,
        "data_snapshot_id": snap,
        "dependency_lock_hash": _dependency_lock_hash(engine_root),
        "random_seed": seed,
        "created_at_utc": created,
    }


def provenance_column_values(prov: Mapping[str, Any] | None) -> tuple[Any, ...]:
    """Ordered values matching ``PROVENANCE_COLUMNS`` for SQL binds."""
    p = prov or {}
    return tuple(p.get(k) for k in _PROVENANCE_KEYS)


PROVENANCE_COLUMNS = _PROVENANCE_KEYS
