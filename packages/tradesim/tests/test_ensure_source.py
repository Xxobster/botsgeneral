"""ensure_source: pin + optional editable refresh."""

from __future__ import annotations

from pathlib import Path

from tradesim.ensure_source import (
    DEFAULT_BOTSGENERAL_TRADESIM_SRC,
    assert_botsgeneral_tradesim,
    ensure_latest_tradesim,
    prefer_botsgeneral_tradesim,
)


def test_prefer_botsgeneral_path():
    path = prefer_botsgeneral_tradesim(reload=False)
    assert "botsgeneral" in str(path).replace("\\", "/")
    assert path == assert_botsgeneral_tradesim()


def test_ensure_latest_without_pip():
    info = ensure_latest_tradesim(update=False)
    assert info["ok"] is True
    assert "botsgeneral" in str(info["file"]).replace("\\", "/")
    assert Path(DEFAULT_BOTSGENERAL_TRADESIM_SRC).is_dir()
