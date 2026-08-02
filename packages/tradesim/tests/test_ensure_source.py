"""ensure_source: fail-closed version assertion (no runtime pip)."""

from __future__ import annotations

from pathlib import Path

from tradesim.ensure_source import (
    assert_botsgeneral_tradesim,
    assert_engine_version,
    ensure_latest_tradesim,
    prefer_botsgeneral_tradesim,
)

BOTSGENERAL_TRADESIM = Path(r"C:\projects\botsgeneral\packages\tradesim")


def test_prefer_botsgeneral_path():
    path = prefer_botsgeneral_tradesim()
    assert "botsgeneral" in str(path).replace("\\", "/")
    assert path == assert_botsgeneral_tradesim()


def test_ensure_latest_without_pip():
    info = ensure_latest_tradesim(update=False)
    assert info["ok"] is True
    assert "botsgeneral" in str(info["file"]).replace("\\", "/")
    assert BOTSGENERAL_TRADESIM.is_dir()


def test_assert_engine_version():
    info = assert_engine_version(require_under=BOTSGENERAL_TRADESIM)
    assert info["ok"] is True
    assert info["version"]
