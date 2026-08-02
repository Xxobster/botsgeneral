"""Compatibility shim — prefer ``import market_data``."""
from market_data import DEFAULT_DB_PATH, ResearchCandleDB
from market_data import db, download_all, universe  # noqa: F401

__all__ = ["DEFAULT_DB_PATH", "ResearchCandleDB"]
