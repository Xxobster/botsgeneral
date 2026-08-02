"""Ensure research candles are fresh before a backtest or live comparison.

Any program can call this before running tradesim::

    from tradesim.research import ensure_candles
    ensure_candles(symbols=["BTCUSDT"], timeframes=["1h", "1m"], price_types=("last", "mark"))

CLI (same thing)::

    python -m tradesim.research.candles --symbols BTCUSDT --timeframes 1h,1m --price-type both
    python -m botsgeneral research-candles --only binance --symbols BTCUSDT --timeframes 1h,1m --price-type both

**Rule:** every backtest-versus-live comparison MUST call ``ensure_candles`` (or the
equivalent CLI) first so Last and Mark series cover the comparison window.
"""

from __future__ import annotations

import argparse
from typing import Sequence


def ensure_candles(
    symbols: Sequence[str],
    timeframes: Sequence[str],
    *,
    price_types: Sequence[str] = ("last", "mark"),
    incremental: bool = True,
    quiet: bool = False,
) -> int:
    """Refresh Binance research Open-High-Low-Close-Volume (OHLCV) into the warehouse.

    Returns the ``download_all.run`` exit code (0 = ok).
    """
    try:
        from market_data.download_all import run
    except ImportError as exc:
        raise ImportError(
            "ensure_candles needs botsgeneral installed in this environment "
            "(pip install -e . from the botsgeneral repo root)"
        ) from exc

    syms = {str(s).strip().upper() for s in symbols if str(s).strip()}
    tfs = {str(t).strip().lower() for t in timeframes if str(t).strip()}
    pts = tuple(str(p).strip().lower() for p in price_types if str(p).strip())
    if not syms or not tfs:
        raise ValueError("symbols and timeframes are required")
    if "both" in pts:
        pts = ("last", "mark")
    # download_all prints full warehouse coverage; suppress noise for callers.
    import contextlib
    import io

    buf = io.StringIO()
    ctx = contextlib.redirect_stdout(buf) if quiet else contextlib.nullcontext()
    with ctx:
        code = int(
            run(
                only={"binance"},
                incremental=incremental,
                symbols=syms,
                timeframes=tfs,
                price_types=pts or ("last", "mark"),
            )
        )
    if quiet:
        # still print a one-liner so the caller knows it ran
        print(f"ensure_candles: symbols={sorted(syms)} timeframes={sorted(tfs)} price_types={pts} exit={code}")
    return code


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tradesim-candles",
        description="Refresh research candles needed for a backtest / live comparison",
    )
    p.add_argument("--symbols", required=True, help="e.g. BTCUSDT or BTCUSDT,ETHUSDT")
    p.add_argument("--timeframes", required=True, help="e.g. 1h,1m")
    p.add_argument(
        "--price-type",
        default="both",
        help="last, mark, or both (default both — Last fills + Mark liquidation)",
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="ignore incremental cursors; refetch from instrument start",
    )
    args = p.parse_args(argv)
    symbols = [x.strip() for x in args.symbols.split(",") if x.strip()]
    timeframes = [x.strip() for x in args.timeframes.split(",") if x.strip()]
    raw = [x.strip().lower() for x in args.price_type.split(",") if x.strip()]
    price_types = ("last", "mark") if "both" in raw else tuple(raw)
    return ensure_candles(
        symbols,
        timeframes,
        price_types=price_types,
        incremental=not args.full,
    )


if __name__ == "__main__":
    raise SystemExit(main())
