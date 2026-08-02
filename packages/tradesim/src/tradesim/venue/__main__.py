"""CLI: refresh / list Bybit instrument minimum sizes.

Examples::

    python -m tradesim.venue refresh --symbols BTCUSDT,ETHUSDT,SOLUSDT
    python -m tradesim.venue refresh --from-registry
    python -m tradesim.venue list
    python -m tradesim.venue show BTCUSDT
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .bybit import DEFAULT_ACCOUNT, DEFAULT_KEYS_PATH
from .cache import DEFAULT_CACHE, InstrumentCache


def _symbols_from_registry() -> list[str]:
    """Union of symbols listed in bots_registry*.yaml (no hard PyYAML dependency)."""
    import re

    roots = [
        Path(__file__).resolve().parents[5] / "config" / "bots_registry.local.yaml",
        Path(__file__).resolve().parents[5] / "config" / "bots_registry.yaml",
        Path(r"C:\projects\botsgeneral\config\bots_registry.local.yaml"),
        Path(r"C:\projects\botsgeneral\config\bots_registry.yaml"),
    ]
    symbols: set[str] = set()
    # Inline list: symbols: [BTCUSDT, ETHUSDT, ...]
    inline = re.compile(
        r"symbols\s*:\s*\[([^\]]+)\]",
        re.IGNORECASE,
    )
    # Block list items under a symbols: key
    block_item = re.compile(r"^\s*-\s*([A-Z0-9]+USDT)\s*$", re.IGNORECASE)
    for path in roots:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for m in inline.finditer(text):
            for part in m.group(1).split(","):
                sym = part.strip().strip("\"'")
                if sym.upper().endswith("USDT"):
                    symbols.add(sym.upper())
        in_symbols = False
        for line in text.splitlines():
            if re.match(r"^\s*symbols\s*:\s*$", line, re.I):
                in_symbols = True
                continue
            if in_symbols:
                m = block_item.match(line)
                if m:
                    symbols.add(m.group(1).upper())
                    continue
                if line.strip() and not line.strip().startswith("#") and not line.startswith(" ") and not line.startswith("\t"):
                    in_symbols = False
                elif line.strip() and not m and not line.strip().startswith("#"):
                    # indented non-list key ends the block
                    if re.match(r"^\s+\w+:", line):
                        in_symbols = False
    if not symbols:
        raise SystemExit("no symbols found in bots_registry*.yaml")
    return sorted(symbols)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tradesim-venue")
    parser.add_argument("--db", default=str(DEFAULT_CACHE))
    parser.add_argument("--keys", default=str(DEFAULT_KEYS_PATH))
    parser.add_argument("--account", default=DEFAULT_ACCOUNT)
    parser.add_argument(
        "--public",
        action="store_true",
        help="skip auth (instrument specs are public; default uses Xxobster_local)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ref = sub.add_parser("refresh", help="pull limits from Bybit into the cache")
    p_ref.add_argument("--symbols", default="", help="comma-separated, e.g. BTCUSDT,ETHUSDT")
    p_ref.add_argument(
        "--from-registry",
        action="store_true",
        help="union of symbols in bots_registry.local.yaml / bots_registry.yaml",
    )
    p_ref.add_argument(
        "--all-linear",
        action="store_true",
        help="entire Bybit linear USDT perpetual universe",
    )

    sub.add_parser("list", help="print cached instruments")
    p_show = sub.add_parser("show", help="print one cached (or freshly fetched) symbol")
    p_show.add_argument("symbol")

    args = parser.parse_args(argv)
    cache = InstrumentCache(args.db)

    # Propagate key path into fetch helpers via env-less monkey: set module defaults.
    import tradesim.venue.bybit as bybit_mod

    bybit_mod.DEFAULT_KEYS_PATH = Path(args.keys)
    bybit_mod.DEFAULT_ACCOUNT = args.account
    use_auth = not args.public

    if args.cmd == "refresh":
        symbols: list[str] | None
        if args.all_linear:
            symbols = None
        elif args.from_registry:
            symbols = _symbols_from_registry()
        elif args.symbols.strip():
            symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        else:
            raise SystemExit("pass --symbols, --from-registry, or --all-linear")
        items = cache.refresh(symbols, use_auth=use_auth)
        print(f"cached {len(items)} instruments -> {cache.path}")
        print(
            f"{'symbol':<14} {'min_qty':>12} {'qty_step':>12} {'min_notional':>14} "
            f"{'tick':>10} {'max_lev':>8}"
        )
        for i in items:
            print(
                f"{i.symbol:<14} {i.min_qty:>12g} {i.qty_step:>12g} {i.min_notional:>14g} "
                f"{i.tick_size:>10g} {i.max_leverage:>8g}"
            )
        return 0

    if args.cmd == "list":
        items = cache.all()
        if not items:
            print("(cache empty — run: python -m tradesim.venue refresh --from-registry)")
            return 0
        print(
            f"{'symbol':<14} {'min_qty':>12} {'qty_step':>12} {'min_notional':>14} "
            f"{'tick':>10} {'max_lev':>8}  retrieved"
        )
        for i in items:
            print(
                f"{i.symbol:<14} {i.min_qty:>12g} {i.qty_step:>12g} {i.min_notional:>14g} "
                f"{i.tick_size:>10g} {i.max_leverage:>8g}  {i.retrieved_at_ms}"
            )
        return 0

    if args.cmd == "show":
        spec = cache.instrument_spec(args.symbol, refresh_if_missing=True)
        print(
            f"{spec.symbol}: tick={spec.tick_size} qty_step={spec.qty_step} "
            f"min_qty={spec.min_qty} min_notional={spec.min_notional} "
            f"max_leverage={spec.max_leverage}"
        )
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
