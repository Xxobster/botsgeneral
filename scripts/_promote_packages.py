"""One-shot package promotion: market_data + live_candles + path resolver + adapters.

Run from botsgeneral root:
  python scripts/_promote_packages.py
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_RC = ROOT / "botsgeneral" / "research_candles"
DST_MD = ROOT / "packages" / "market_data" / "src" / "market_data"
DST_LC = ROOT / "packages" / "live_candles" / "src" / "live_candles"
ADAPTERS_SRC = ROOT / "packages" / "tradesim" / "adapters"
ADAPTERS_DST = ROOT / "packages" / "tradesim" / "migration" / "adapters"


def rewrite_md_imports(text: str) -> str:
    text = text.replace("from botsgeneral.research_candles.", "from market_data.")
    text = text.replace("import botsgeneral.research_candles.", "import market_data.")
    text = text.replace("botsgeneral.research_candles.", "market_data.")
    # Binance keys: keep optional botsgeneral import with env fallback later in file patch
    return text


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def extract_market_data() -> None:
    if DST_MD.exists():
        shutil.rmtree(DST_MD)
    DST_MD.mkdir(parents=True)
    for py in SRC_RC.glob("*.py"):
        if py.name in {"__init__.py", "__main__.py"}:
            continue
        text = rewrite_md_imports(py.read_text(encoding="utf-8"))
        # Path literals -> trading_data_root helpers
        text = text.replace(
            'DEFAULT_ROOT = r"D:\\projectsdata\\candles"',
            'from market_data.paths import candles_root\n\nDEFAULT_ROOT = str(candles_root())',
        )
        text = text.replace(
            'DEFAULT_DB = rf"{DEFAULT_ROOT}\\market_ohlcv.sqlite"',
            'DEFAULT_DB = str(candles_root() / "market_ohlcv.sqlite")',
        )
        text = text.replace(
            'IMPORT_DIR = Path(r"D:\\projectsdata\\candles\\imports\\btcd")',
            'from market_data.paths import candles_root\n\nIMPORT_DIR = candles_root() / "imports" / "btcd"',
        )
        text = text.replace(
            'r"D:\\projectsdata\\candles\\imports\\total_mcap\\\\"',
            'str(candles_root() / "imports" / "total_mcap") + "\\\\"',
        )
        text = text.replace(
            'Path(r"D:\\projectsdata\\candles\\imports\\total_mcap")',
            'candles_root() / "imports" / "total_mcap"',
        )
        # fetch_binance keys — use local helper
        if py.name == "fetch_binance.py":
            text = text.replace(
                "from botsgeneral.keys import resolve_binance_keys",
                "from market_data.keys_util import resolve_binance_keys",
            )
        write(DST_MD / py.name, text)

    # paths helper inside market_data
    write(
        DST_MD / "paths.py",
        '''"""Resolved research-data paths (override with TRADING_DATA_ROOT)."""
from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_ROOT = Path(r"D:\\projectsdata")


def trading_data_root() -> Path:
    raw = os.environ.get("TRADING_DATA_ROOT")
    return Path(raw) if raw else _DEFAULT_ROOT


def candles_root() -> Path:
    return trading_data_root() / "candles"


def market_ohlcv_db() -> Path:
    return candles_root() / "market_ohlcv.sqlite"
''',
    )

    write(
        DST_MD / "keys_util.py",
        '''"""Binance key resolution without depending on the botsgeneral ops package."""
from __future__ import annotations

import os
import re
from pathlib import Path


def _load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def resolve_binance_keys() -> dict[str, str]:
    ak = os.environ.get("BINANCE_API_KEY")
    sk = os.environ.get("BINANCE_API_SECRET")
    if ak and sk:
        return {"api_key": ak, "api_secret": sk}
    secrets = Path(os.environ.get("TRADING_SECRETS_ENV") or (Path.home() / ".trading" / "secrets.env"))
    env = _load_env_file(secrets)
    if env.get("BINANCE_API_KEY") and env.get("BINANCE_API_SECRET"):
        return {"api_key": env["BINANCE_API_KEY"], "api_secret": env["BINANCE_API_SECRET"]}
    # Optional fallback into botsgeneral if installed
    try:
        from botsgeneral.keys import resolve_binance_keys as _bg
        return _bg()
    except Exception:
        return {}
''',
    )

    write(
        DST_MD / "__init__.py",
        '''"""Research OHLCV warehouse (formerly botsgeneral.research_candles)."""
from market_data.db import DEFAULT_DB_PATH, ResearchCandleDB

__all__ = ["DEFAULT_DB_PATH", "ResearchCandleDB"]
''',
    )
    write(
        DST_MD / "__main__.py",
        "from market_data.download_all import main\n\nif __name__ == '__main__':\n    raise SystemExit(main())\n",
    )

    write(
        ROOT / "packages" / "market_data" / "pyproject.toml",
        '''[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "market_data"
version = "1.0.0"
description = "Shared research OHLCV warehouse (Binance, Dukascopy, Yahoo, FRED)"
requires-python = ">=3.10"
license = { text = "Proprietary" }
dependencies = [
  "numpy>=1.24.0",
  "pandas>=2.0.0",
  "requests>=2.31.0",
]

[project.optional-dependencies]
research = [
  "yfinance>=0.2.40",
  "dukascopy-python>=4.0.0",
]

[project.scripts]
market-data-download = "market_data.download_all:main"

[tool.setuptools.packages.find]
where = ["src"]
include = ["market_data*"]
''',
    )

    # Shim old package
    shim_dir = SRC_RC
    # Remove moved modules but keep shim
    for py in list(shim_dir.glob("*.py")):
        if py.name in {"__init__.py", "__main__.py"}:
            continue
        py.unlink()
    write(
        shim_dir / "__init__.py",
        '''"""Compatibility shim — prefer ``import market_data``."""
from market_data import DEFAULT_DB_PATH, ResearchCandleDB
from market_data import db, download_all, universe  # noqa: F401

__all__ = ["DEFAULT_DB_PATH", "ResearchCandleDB"]
''',
    )
    write(
        shim_dir / "__main__.py",
        "from market_data.download_all import main\n\nif __name__ == '__main__':\n    raise SystemExit(main())\n",
    )
    # Also expose submodules for ``from botsgeneral.research_candles.db import ...``
    for mod in [
        "db",
        "download_all",
        "universe",
        "timestamps",
        "resample",
        "fetch_binance",
        "fetch_binance_vision",
        "fetch_btcd",
        "fetch_crypto_macro",
        "fetch_dukascopy",
        "fetch_fred",
        "fetch_yahoo",
        "repair_mark_gaps",
        "verify_engine005",
        "paths",
        "keys_util",
    ]:
        write(
            shim_dir / f"{mod}.py",
            f"from market_data.{mod} import *  # noqa: F403\n",
        )


def create_live_candles() -> None:
    if DST_LC.exists():
        shutil.rmtree(DST_LC)
    DST_LC.mkdir(parents=True)

    write(
        DST_LC / "__init__.py",
        '''"""Live shared-candle readers for VPS bots.

Two surfaces over one implementation:

* ``load_ohlcv`` / ``newest_ts_ms`` / ``is_fresh`` — integer ``ts_ms`` columns
  (botsgeneral.reader contract).
* ``load_candles`` / ``latest_ts_ms`` / ``candles_fresh`` — tz-aware ``timestamp``
  (copy-pasted shared_candles.py contract used by crypthor2, karmaa_mp, …).
"""
from live_candles.reader import is_fresh, load_ohlcv, newest_ts_ms, shared_db_path
from live_candles.shared import candles_fresh, latest_ts_ms, load_candles

__all__ = [
    "shared_db_path",
    "load_ohlcv",
    "newest_ts_ms",
    "is_fresh",
    "load_candles",
    "latest_ts_ms",
    "candles_fresh",
]
''',
    )

    write(
        DST_LC / "models.py",
        '''"""Minimal symbol/timeframe helpers (no botsgeneral dependency)."""
from __future__ import annotations

TF_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


def normalize_symbol(symbol: str) -> str:
    return str(symbol).upper().strip().replace("/", "").replace("-", "")


def normalize_timeframe(timeframe: str) -> str:
    return str(timeframe).strip().lower()
''',
    )

    write(
        DST_LC / "reader.py",
        '''"""ts_ms surface — formerly botsgeneral.reader."""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import pandas as pd

from live_candles.models import TF_MS, normalize_symbol, normalize_timeframe

DEFAULT_DB = "/var/lib/botsgeneral/shared_candles.db"


def shared_db_path(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("SHARED_CANDLES_DB") or os.environ.get("BOTSGENERAL_DB")
    if env:
        return Path(env)
    return Path(DEFAULT_DB)


def load_ohlcv(
    exchange: str,
    symbol: str,
    timeframe: str,
    *,
    db_path: str | Path | None = None,
    limit: int | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> pd.DataFrame:
    path = shared_db_path(db_path)
    ex = str(exchange).lower().strip()
    sym = normalize_symbol(symbol)
    tf = normalize_timeframe(timeframe)
    clauses = ["exchange = ?", "symbol = ?", "timeframe = ?"]
    params: list[Any] = [ex, sym, tf]
    if start_ms is not None:
        clauses.append("ts_ms >= ?")
        params.append(int(start_ms))
    if end_ms is not None:
        clauses.append("ts_ms <= ?")
        params.append(int(end_ms))
    where = " AND ".join(clauses)
    sql = f"""
        SELECT ts_ms, open, high, low, close, volume,
               quote_volume, trades, taker_buy_base, taker_buy_quote, updated_at_ms
        FROM candles
        WHERE {where}
        ORDER BY ts_ms ASC
    """
    if limit is not None and int(limit) > 0:
        sql = f"""
            SELECT * FROM (
                SELECT ts_ms, open, high, low, close, volume,
                       quote_volume, trades, taker_buy_base, taker_buy_quote, updated_at_ms
                FROM candles
                WHERE {where}
                ORDER BY ts_ms DESC
                LIMIT {int(limit)}
            ) ORDER BY ts_ms ASC
        """
    with sqlite3.connect(str(path), timeout=30) as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    if df.empty:
        return df
    df["ts_ms"] = df["ts_ms"].astype("int64")
    return df


def newest_ts_ms(
    exchange: str,
    symbol: str,
    timeframe: str,
    *,
    db_path: str | Path | None = None,
) -> int | None:
    path = shared_db_path(db_path)
    with sqlite3.connect(str(path), timeout=30) as conn:
        row = conn.execute(
            """
            SELECT MAX(ts_ms) FROM candles
            WHERE exchange=? AND symbol=? AND timeframe=?
            """,
            (str(exchange).lower(), normalize_symbol(symbol), normalize_timeframe(timeframe)),
        ).fetchone()
    if not row or row[0] is None:
        return None
    return int(row[0])


def is_fresh(
    exchange: str,
    symbol: str,
    timeframe: str,
    *,
    db_path: str | Path | None = None,
    max_lag_bars: float = 2.0,
    now_ms: int | None = None,
) -> bool:
    tf = normalize_timeframe(timeframe)
    tf_ms = int(TF_MS.get(tf) or 0)
    if tf_ms <= 0:
        return False
    last = newest_ts_ms(exchange, symbol, tf, db_path=db_path)
    if last is None:
        return False
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    age_after_close = now - (last + tf_ms)
    return age_after_close <= max_lag_bars * tf_ms
''',
    )

    write(
        DST_LC / "shared.py",
        '''"""timestamp-datetime surface — formerly per-project shared_candles.py."""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

import pandas as pd

from live_candles.models import TF_MS, normalize_symbol, normalize_timeframe
from live_candles.reader import shared_db_path

log = logging.getLogger(__name__)


def interval_ms(interval: str) -> int:
    return TF_MS.get(normalize_timeframe(interval), 300_000)


def load_candles(
    symbol: str,
    interval: str,
    *,
    exchange: str = "bybit",
    db_path: Path | str | None = None,
) -> pd.DataFrame:
    path = Path(db_path) if db_path else shared_db_path()
    empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    if not path.exists():
        log.error("Shared candles DB missing: %s", path)
        return empty

    sym = normalize_symbol(symbol)
    tf = normalize_timeframe(interval)
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30) as conn:
            df = pd.read_sql(
                """
                SELECT ts_ms, open, high, low, close, volume
                FROM candles
                WHERE exchange=? AND symbol=? AND timeframe=?
                ORDER BY ts_ms
                """,
                conn,
                params=(exchange.lower(), sym, tf),
            )
    except Exception:
        log.exception(
            "Failed reading shared candles %s %s %s from %s", exchange, sym, tf, path
        )
        return empty

    if df.empty:
        log.error("No shared candles for %s %s %s in %s", exchange, sym, tf, path)
        return empty

    df["timestamp"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    return df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def latest_ts_ms(
    symbol: str,
    interval: str,
    *,
    exchange: str = "bybit",
    db_path: Path | str | None = None,
) -> int | None:
    path = Path(db_path) if db_path else shared_db_path()
    if not path.exists():
        return None
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30) as conn:
            row = conn.execute(
                """
                SELECT MAX(ts_ms) FROM candles
                WHERE exchange=? AND symbol=? AND timeframe=?
                """,
                (exchange.lower(), normalize_symbol(symbol), normalize_timeframe(interval)),
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except Exception:
        log.exception("latest_ts_ms failed for %s %s", symbol, interval)
        return None


def candles_fresh(
    symbol: str,
    interval: str,
    *,
    exchange: str = "bybit",
    db_path: Path | str | None = None,
    max_age_mult: float = 2.0,
    now_ms: int | None = None,
) -> tuple[bool, int | None, str]:
    last = latest_ts_ms(symbol, interval, exchange=exchange, db_path=db_path)
    if last is None:
        return False, None, "no candles in shared DB"
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    max_lag = int(interval_ms(interval) * max_age_mult)
    lag = now - last
    if lag > max_lag:
        return False, last, f"stale last_ts_ms={last} lag_ms={lag} max_ms={max_lag}"
    return True, last, "ok"
''',
    )

    write(
        ROOT / "packages" / "live_candles" / "pyproject.toml",
        '''[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "live_candles"
version = "1.0.0"
description = "Read-only shared candle DB helpers for live trading bots"
requires-python = ">=3.10"
license = { text = "Proprietary" }
dependencies = [
  "pandas>=2.0.0",
]

[tool.setuptools.packages.find]
where = ["src"]
include = ["live_candles*"]
''',
    )


def update_botsgeneral_reader_shim() -> None:
    write(
        ROOT / "botsgeneral" / "reader.py",
        '''"""Compatibility shim — prefer ``from live_candles import ...``."""
from live_candles.reader import (  # noqa: F401
    DEFAULT_DB,
    is_fresh,
    load_ohlcv,
    newest_ts_ms,
    shared_db_path,
)

__all__ = ["DEFAULT_DB", "shared_db_path", "load_ohlcv", "newest_ts_ms", "is_fresh"]
''',
    )


def patch_tradesim_paths() -> None:
    paths_py = ROOT / "packages" / "tradesim" / "src" / "tradesim" / "paths.py"
    write(
        paths_py,
        '''"""Resolved research/backtest paths (override with TRADING_DATA_ROOT)."""
from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_ROOT = Path(r"D:\\projectsdata")


def trading_data_root() -> Path:
    raw = os.environ.get("TRADING_DATA_ROOT")
    return Path(raw) if raw else _DEFAULT_ROOT


def candles_root() -> Path:
    return trading_data_root() / "candles"


def bybit_instruments_db() -> Path:
    return candles_root() / "bybit_instruments.sqlite"


def backtests_root() -> Path:
    return trading_data_root() / "backtests"


def tradesim_store_path() -> Path:
    return backtests_root() / "tradesim_runs.sqlite"


def tradesim_reports_dir() -> Path:
    return backtests_root() / "reports"


def tradesim_runs_dir() -> Path:
    return backtests_root() / "runs"
''',
    )

    defaults = ROOT / "packages" / "tradesim" / "src" / "tradesim" / "research" / "defaults.py"
    text = defaults.read_text(encoding="utf-8")
    text = re.sub(
        r"# Canonical research artifacts \(Windows research machine\).\n"
        r"RESEARCH_STORE_PATH = r\"D:\\\\projectsdata\\\\backtests\\\\tradesim_runs\.sqlite\"\n"
        r"RESEARCH_REPORTS_DIR = r\"D:\\\\projectsdata\\\\backtests\\\\reports\"\n",
        "# Canonical research artifacts (override with TRADING_DATA_ROOT).\n"
        "from tradesim.paths import tradesim_reports_dir, tradesim_store_path\n\n"
        "RESEARCH_STORE_PATH = str(tradesim_store_path())\n"
        "RESEARCH_REPORTS_DIR = str(tradesim_reports_dir())\n",
        text,
    )
    defaults.write_text(text, encoding="utf-8", newline="\n")

    cache = ROOT / "packages" / "tradesim" / "src" / "tradesim" / "venue" / "cache.py"
    ctext = cache.read_text(encoding="utf-8")
    ctext = ctext.replace(
        'DEFAULT_CACHE = Path(r"D:\\projectsdata\\candles\\bybit_instruments.sqlite")',
        "from tradesim.paths import bybit_instruments_db\n\nDEFAULT_CACHE = bybit_instruments_db()",
    )
    cache.write_text(ctext, encoding="utf-8", newline="\n")

    candles = ROOT / "packages" / "tradesim" / "src" / "tradesim" / "research" / "candles.py"
    if candles.exists():
        t = candles.read_text(encoding="utf-8")
        t = t.replace(
            "from botsgeneral.research_candles.download_all import run",
            "from market_data.download_all import run",
        )
        candles.write_text(t, encoding="utf-8", newline="\n")


def move_adapters() -> None:
    if not ADAPTERS_SRC.exists():
        return
    if ADAPTERS_DST.exists():
        shutil.rmtree(ADAPTERS_DST)
    ADAPTERS_DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(ADAPTERS_SRC), str(ADAPTERS_DST))
    write(
        ADAPTERS_DST.parent / "__init__.py",
        '"""Optional migration/parity adapters — not part of the tradesim wheel."""\n',
    )
    write(
        ADAPTERS_DST / "__init__.py",
        '"""Parity adapters for foreign engines (xgb, LLM1, TSM-VPA)."""\n',
    )
    # pyproject migration extra note — patched separately


def main() -> int:
    extract_market_data()
    print("market_data extracted")
    create_live_candles()
    print("live_candles created")
    update_botsgeneral_reader_shim()
    print("reader shim updated")
    patch_tradesim_paths()
    print("tradesim paths patched")
    move_adapters()
    print("adapters moved to migration/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
