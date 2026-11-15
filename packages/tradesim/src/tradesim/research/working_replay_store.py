"""Persist and fingerprint a qualified working-order replay ledger in SQLite."""

from contextlib import closing
from dataclasses import asdict, is_dataclass
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from ..working_replay import WorkingOrderReplay


def _json(data):
    def encode(item):
        if is_dataclass(item):
            return asdict(item)
        raise TypeError(f"Not serializable: {type(item)}")

    return json.dumps(data, default=encode, sort_keys=True, separators=(",", ":"), allow_nan=False)


def save_working_replay(path: Path, *, identity: dict, replay: WorkingOrderReplay) -> str:
    """Store the immutable run. Repeating it is a no-op only if its ledger matches."""
    required = {"protocol_sha256", "data_snapshot", "engine_sha256", "arm", "scenario"}
    if set(identity) != required or any(not isinstance(value, str) or not value for value in identity.values()):
        raise ValueError("Expected protocol, data snapshot, engine, arm and scenario identity")
    identity_json = _json(identity)
    run_id = sha256(identity_json.encode()).hexdigest()
    rows = [(kind, index, _json(item)) for kind, events in (
        ("order", replay.transitions), ("wallet", replay.wallet), ("fill", replay.fills),
        ("funding", replay.funding), ("trade", replay.trades), ("terminal_state", [replay.exposure_state()]),
    ) for index, item in enumerate(events)]
    ledger_sha = sha256(_json(rows).encode()).hexdigest()
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS working_replay_run (
                run_id TEXT PRIMARY KEY, identity_json TEXT NOT NULL, ledger_sha256 TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS working_replay_event (
                run_id TEXT NOT NULL REFERENCES working_replay_run(run_id), kind TEXT NOT NULL,
                sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(run_id, kind, sequence));
        """)
        with db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT ledger_sha256 FROM working_replay_run WHERE run_id=?", (run_id,)).fetchone()
            if prior is not None:
                if prior != (ledger_sha,):
                    raise ValueError("Replay identity already exists with a different ledger")
                return run_id
            db.execute("INSERT INTO working_replay_run VALUES (?,?,?)", (run_id, identity_json, ledger_sha))
            db.executemany("INSERT INTO working_replay_event VALUES (?,?,?,?)", ((run_id, *row) for row in rows))
    return run_id
