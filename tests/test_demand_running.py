"""Collector demand: running bots only; pack scan; no leftover 1m."""

from __future__ import annotations

import json
from pathlib import Path

from botsgeneral.discover import discover_pairs
from botsgeneral.discover.demand import (
    pack_pairs_from_strategy,
    pairs_from_running_packs,
    refine_bot_pairs,
    symbols_from_cmdline,
)
from botsgeneral.models import CandlePair


def test_pack_strategy_symbol_tf(tmp_path: Path):
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "strategy.json").write_text(
        json.dumps(
            {
                "symbol": "SOLUSDT",
                "timeframe": "15m",
                "signal_source": "binance",
            }
        ),
        encoding="utf-8",
    )
    pairs = pack_pairs_from_strategy(pack)
    assert pairs == [CandlePair("binance", "SOLUSDT", "15m")]


def test_running_pack_scan_and_symbol_filter(tmp_path: Path):
    pack = tmp_path / "ethpack"
    pack.mkdir()
    (pack / "strategy.json").write_text(
        json.dumps({"symbol": "ETHUSDT", "timeframe": "15m", "signal_source": "binance"}),
        encoding="utf-8",
    )
    blob = f"python -m llm2.live.pivot_runner --pack {pack} --symbol ETHUSDT"
    assert pairs_from_running_packs(blob) == [CandlePair("binance", "ETHUSDT", "15m")]
    assert symbols_from_cmdline(blob) == {"ETHUSDT"}
    mixed = (
        "/opt/tsm-vpa/venv/bin/python scripts/run_live_bot.py --symbol VETUSDT --pack /opt/tsm-vpa/configs/x.json\n"
        "/opt/tsm-chandelier/venv/bin/python scripts/run_live_bot.py --symbol SOLUSDT\n"
    )
    assert symbols_from_cmdline(mixed, path_token="/opt/tsm-vpa") == {"VETUSDT"}
    refined = refine_bot_pairs(
        name="llm2",
        bcfg={"timeframe": "1h", "also_fetch_timeframes": ["4h", "1w"]},
        pairs=[
            CandlePair("binance", "BTCUSDT", "1h"),
            CandlePair("binance", "BTCUSDT", "4h"),
        ],
        proc_blob=blob,
        vps_id="94.156.189.76",
    )
    assert refined == [CandlePair("binance", "ETHUSDT", "15m")]


def test_required_history_uses_bot_need_not_research_depth():
    from botsgeneral.discover.demand import required_history_bars

    assert required_history_bars({"min_history_bars": 3000}, "15m") == 3000
    assert required_history_bars(
        {"min_history_bars": 5000, "min_history_bars_by_tf": {"1h": 2000, "5m": 5000}},
        "1h",
    ) == 2000
    assert required_history_bars({"min_history_bars": 200}, "1h") == 500  # tf floor


def test_only_running_skips_stopped_bot():
    registry = {
        "vps": {"9.9.9.9": {"bots": ["ghost"]}},
        "bots": {
            "ghost": {
                "serve_candles": True,
                "exchange": "binance",
                "parser": "none",
                "symbols": ["BTCUSDT"],
                "timeframe": "1m",
                "path": "/opt/does-not-exist-ghost",
                "process_match": ["definitely_not_running_xyz"],
            }
        },
    }
    items, _ = discover_pairs(registry, "9.9.9.9", only_running=True)
    assert items == []
    items_all, _ = discover_pairs(registry, "9.9.9.9", only_running=False)
    assert any(p.timeframe == "1m" for p, _ in items_all)
