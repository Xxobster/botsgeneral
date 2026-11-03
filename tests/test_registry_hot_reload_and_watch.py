"""Collector hot-reloads the registry; the DATA_UNSAFE watchdog flags blind units."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

from botsgeneral import collect

SPEC = importlib.util.spec_from_file_location("w", Path(__file__).resolve().parents[1] / "scripts" / "ops_data_unsafe_watch.py")
w = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w)


def test_reload_picks_up_new_bot_and_keeps_old_on_error(tmp_path):
    reg = tmp_path / "r.yaml"
    reg.write_text(yaml.safe_dump({"vps": {"x": {"bots": ["a"]}}}))
    c = collect.Collector.__new__(collect.Collector)
    c._registry_path = str(reg)
    c.registry = {"vps": {"x": {"bots": ["a"]}}}
    reg.write_text(yaml.safe_dump({"vps": {"x": {"bots": ["a", "b"]}}}))
    c._reload_registry()
    assert c.registry["vps"]["x"]["bots"] == ["a", "b"]
    reg.write_text("::: not yaml [")
    c._reload_registry()
    assert c.registry["vps"]["x"]["bots"] == ["a", "b"]  # kept last good


def log(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body)
    return str(p)


def test_watch_flags_stale_unit(tmp_path):
    ok = log(tmp_path, "ok.log", "2026-11-03T04:00:03Z DECIDE {}\n2026-11-03T04:00:04Z QTY {}\n")
    blind = log(tmp_path, "blind.log",
                "2026-10-25T11:00:03Z DECIDE {}\n" + "".join(
                    f"2026-11-03T0{h}:00:01Z DECIDE {{}}\n2026-11-03T0{h}:00:01Z DATA_UNSAFE block_entry code=CANDLE_STALE\n" for h in range(1, 5)))
    now = "2026-11-03T05:00:00+00:00"
    r_ok = w.check(ok, w.datetime.fromisoformat(now), 3)
    r_blind = w.check(blind, w.datetime.fromisoformat(now), 3)
    assert not r_ok["unhealthy"]
    assert r_blind["unhealthy"] and r_blind["data_unsafe_since"] == 4
    assert w.main(["--logs", str(tmp_path / "*.log"), "--now", now]) == 1
