"""Local research candle store at D:\\projectsdata\\candles.

Download once via: python -m botsgeneral.research_candles.download_all
Load via: from botsgeneral.research_candles.db import ResearchCandleDB
"""

from botsgeneral.research_candles.db import DEFAULT_DB_PATH, ResearchCandleDB

__all__ = ["DEFAULT_DB_PATH", "ResearchCandleDB"]
