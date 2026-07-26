"""Load and content-hash the golden fixture pack.

The pack is one JSON file per case. A fixture declares the identifiers it covers, the
deterministic inputs, and the exact expected outputs. The pack hash goes into every
result stamp so a number can always be traced to the arbiter that graded its engine.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


@dataclass(frozen=True)
class Fixture:
    name: str
    ids: tuple[str, ...]
    kind: str
    title: str
    rationale: str
    payload: Mapping[str, Any]
    tolerance: float

    @property
    def expect(self) -> Mapping[str, Any]:
        return self.payload.get("expect", {})

    @property
    def expects_error(self) -> bool:
        return "error" in self.expect


def _load_one(path: Path) -> Fixture:
    payload = json.loads(path.read_text(encoding="utf-8"))
    ids = payload.get("ids")
    if not ids:
        single = payload.get("id")
        ids = [single] if single else []
    if not ids:
        raise ValueError(f"fixture {path.name} declares no identifier")
    return Fixture(
        name=path.stem,
        ids=tuple(ids),
        kind=payload.get("kind", "simulation"),
        title=payload.get("title", path.stem),
        rationale=payload.get("rationale", ""),
        payload=payload,
        tolerance=float(payload.get("tolerance", 1e-9)),
    )


def load_fixtures(directory: str | None = None) -> tuple[Fixture, ...]:
    """Read the pack. Only the installed pack is cached; it cannot change under us."""
    if directory is None:
        return _load_installed()
    return _read_dir(Path(directory))


def _read_dir(root: Path) -> tuple[Fixture, ...]:
    if not root.is_dir():
        raise FileNotFoundError(f"fixture directory not found: {root}")
    return tuple(_load_one(p) for p in sorted(root.glob("*.json")))


@lru_cache(maxsize=1)
def _load_installed() -> tuple[Fixture, ...]:
    return _read_dir(FIXTURE_DIR)


def fixtures_for(identifier: str) -> tuple[Fixture, ...]:
    return tuple(f for f in load_fixtures() if identifier in f.ids)


def covered_identifiers() -> frozenset[str]:
    out: set[str] = set()
    for fixture in load_fixtures():
        out.update(fixture.ids)
    return frozenset(out)


def fixture_pack_hash(directory: str | None = None) -> str:
    """SHA-256 over the byte content of every fixture, in filename order.

    Any change to any fixture changes the hash, which invalidates every stamp that
    quoted the old one. An explicitly named directory is always re-read: caching a
    caller's own pack by path would report a hash for content that has since changed,
    which is precisely the failure this hash exists to prevent.
    """
    if directory is None:
        return _installed_pack_hash()
    return _hash_dir(Path(directory))


@lru_cache(maxsize=1)
def _installed_pack_hash() -> str:
    return _hash_dir(FIXTURE_DIR)


def _hash_dir(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.glob("*.json")):
        h.update(path.name.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def fixture_pack_summary() -> dict[str, Any]:
    fixtures = load_fixtures()
    return {
        "n_fixtures": len(fixtures),
        "hash": fixture_pack_hash(),
        "identifiers": sorted(covered_identifiers()),
        "directory": str(FIXTURE_DIR),
    }
