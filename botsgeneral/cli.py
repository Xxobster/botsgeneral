from __future__ import annotations

import argparse
import json
import logging
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="botsgeneral", description="Shared candle collector & ops")
    parser.add_argument("--registry", default=None, help="Path to bots_registry.yaml")
    parser.add_argument("--db", default=None, help="Path to shared_candles.db")
    parser.add_argument("--vps", default=None, help="VPS id override (e.g. 94.156.189.76)")
    parser.add_argument("--keys", default=None, help="Bybit keys file or keys.env")
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("collect", help="Run candle collector (long-running)")
    p_disc = sub.add_parser("discover", help="Print discovered candle pairs and exit")
    p_disc.add_argument("--json", action="store_true")
    p_sit = sub.add_parser("sitrep", help="Host + bot + candle freshness report")
    p_sit.add_argument("--json", action="store_true")
    p_pnl = sub.add_parser("pnl", help="PnL / equity summary across accounts")
    p_pnl.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.vps:
        os.environ["BOTSGENERAL_VPS"] = args.vps
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "collect":
        from botsgeneral.collect import run_collect

        return run_collect(registry_path=args.registry, db_path=args.db, vps_id=args.vps)

    if args.cmd == "discover":
        from botsgeneral.discover import detect_vps_id, discover_pairs, load_registry, unique_pairs

        registry = load_registry(args.registry)
        vps = args.vps or detect_vps_id(registry)
        items, warnings = discover_pairs(registry, vps)
        pairs = unique_pairs(items)
        payload = {
            "vps": vps,
            "pairs": [
                {"exchange": p.exchange, "symbol": p.symbol, "timeframe": p.timeframe, "bot": b}
                for p, b in items
            ],
            "unique": [str(p) for p in pairs],
            "warnings": warnings,
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"VPS: {vps}")
            for row in payload["pairs"]:
                print(f"  {row['exchange']:7} {row['symbol']:10} {row['timeframe']:4} <- {row['bot']}")
            print("Unique:", ", ".join(payload["unique"]) or "(none)")
            for w in warnings:
                print("WARN:", w)
        return 0

    if args.cmd == "sitrep":
        from botsgeneral.sitrep import build_sitrep, print_sitrep

        report = build_sitrep(registry_path=args.registry, db_path=args.db, vps_id=args.vps)
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print_sitrep(report)
        return 0

    if args.cmd == "pnl":
        from botsgeneral.pnl import build_pnl, print_pnl

        report = build_pnl(keys_path=args.keys, registry_path=args.registry)
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print_pnl(report)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
