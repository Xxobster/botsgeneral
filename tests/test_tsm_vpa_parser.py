from __future__ import annotations

import json
from pathlib import Path

from botsgeneral.discover.parsers import parse_bot


def test_tsm_vpa_parser(tmp_path: Path):
    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir()
    pack = {
        "account": "Xxobster5",
        "timeframe": "1d",
        "candles_exchange": "bybit",
        "symbols": ["VETUSDT", "SOLUSDT", "XLMUSDT", "XRPUSDT"],
    }
    (cfg_dir / "live_top4_stack2_rr15_v1.json").write_text(json.dumps(pack), encoding="utf-8")
    pairs = parse_bot(
        "tsm_vpa",
        {"path": str(tmp_path), "exchange": "bybit", "parser": "tsm_vpa_pack"},
    )
    keys = {p.key() for p in pairs}
    assert keys == {
        ("bybit", "VETUSDT", "1d"),
        ("bybit", "SOLUSDT", "1d"),
        ("bybit", "XLMUSDT", "1d"),
        ("bybit", "XRPUSDT", "1d"),
    }
