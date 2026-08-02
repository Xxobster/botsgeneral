"""Unit tests for Bybit instrument parsing / cache (no live network required)."""

from __future__ import annotations

from pathlib import Path

from tradesim.venue.bybit import BybitInstrument, _parse_row
from tradesim.venue.cache import InstrumentCache


def test_parse_row_min_limits() -> None:
    row = {
        "symbol": "BTCUSDT",
        "status": "Trading",
        "contractType": "LinearPerpetual",
        "lotSizeFilter": {
            "minOrderQty": "0.001",
            "qtyStep": "0.001",
            "maxOrderQty": "100",
            "minNotionalValue": "5",
        },
        "priceFilter": {"tickSize": "0.10"},
        "leverageFilter": {"maxLeverage": "100"},
    }
    inst = _parse_row(row)
    assert inst.symbol == "BTCUSDT"
    assert inst.min_qty == 0.001
    assert inst.qty_step == 0.001
    assert inst.min_notional == 5.0
    assert inst.tick_size == 0.10
    spec = inst.to_instrument_spec()
    assert spec.min_qty == 0.001
    assert spec.source == "bybit_v5_instruments-info"


def test_instrument_cache_roundtrip(tmp_path: Path) -> None:
    cache = InstrumentCache(tmp_path / "inst.sqlite")
    item = BybitInstrument(
        symbol="ETHUSDT",
        tick_size=0.01,
        qty_step=0.01,
        min_qty=0.01,
        min_notional=5.0,
        max_qty=1000.0,
        max_leverage=50.0,
        status="Trading",
        retrieved_at_ms=1_700_000_000_000,
    )
    cache.upsert([item])
    got = cache.get("ethusdt")
    assert got is not None
    assert got.min_qty == 0.01
    assert got.min_notional == 5.0
    spec = cache.instrument_spec("ETHUSDT", refresh_if_missing=False)
    assert spec.symbol == "ETHUSDT"
    assert spec.min_qty == 0.01
