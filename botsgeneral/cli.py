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
    parser.add_argument("--report-cfg", default=None, help="Path to report.yaml (since_date)")
    parser.add_argument("--since", default=None, help="Override since date YYYY-MM-DD")
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("collect", help="Run candle collector (long-running)")
    p_disc = sub.add_parser("discover", help="Print discovered candle pairs and exit")
    p_disc.add_argument("--json", action="store_true")
    p_sit = sub.add_parser("sitrep", help="Host + bot + candle freshness report")
    p_sit.add_argument("--json", action="store_true")
    p_pnl = sub.add_parser("pnl", help="Quick wallet/positions summary")
    p_pnl.add_argument("--json", action="store_true")

    p_rep = sub.add_parser(
        "report",
        help="Full fleet report: health + PnL since date by account/coin (phone-friendly)",
    )
    p_rep.add_argument("--json", action="store_true")

    p_tr = sub.add_parser("trades", help="Trade drilldown for one account/bot [SYMBOL]")
    p_tr.add_argument("account", help="Account (Xxobster4) or bot name (crypthor2)")
    p_tr.add_argument("symbol", nargs="?", default=None, help="Optional SYMBOL e.g. BTCUSDT")
    p_tr.add_argument("--json", action="store_true")

    sub.add_parser("backfill", help="Force max-history candle backfill once then exit")

    p_rc = sub.add_parser(
        "research-candles",
        help="Download shared research candles to D:\\projectsdata\\candles",
    )
    p_rc.add_argument(
        "--only",
        default="dukascopy,yahoo,binance,btcd",
        help="Comma list: dukascopy,yahoo,binance,btcd",
    )
    p_rc.add_argument("--full", action="store_true", help="Full refetch (ignore incremental)")
    p_rc.add_argument(
        "--symbols",
        default="",
        help="Optional comma list of symbols to update only (e.g. BTCUSDT,ETHUSDT)",
    )
    p_rc.add_argument(
        "--timeframes",
        default="",
        help="Optional comma list of TFs to update only (e.g. 5m,1h,4h,1d,1w)",
    )
    p_rc.add_argument(
        "--price-type",
        default="last",
        help="Binance only: last, mark, or both. Mark stored as source=binance_mark",
    )

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

    if args.cmd == "backfill":
        os.environ["BOTSGENERAL_FORCE_BACKFILL"] = "1"
        from botsgeneral.collect import Collector

        c = Collector(registry_path=args.registry, db_path=args.db, vps_id=args.vps)
        c._discovery_and_bootstrap()
        c.db.close()
        return 0

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

    if args.cmd == "report":
        from botsgeneral.report import build_fleet_report, print_fleet_report

        report = build_fleet_report(
            keys_path=args.keys,
            registry_path=args.registry,
            report_cfg_path=args.report_cfg,
            vps_id=args.vps,
            since_date=args.since,
        )
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print_fleet_report(report)
        return 0

    if args.cmd == "trades":
        from botsgeneral.report import build_trades_report, print_trades_report

        report = build_trades_report(
            account_or_bot=args.account,
            symbol=args.symbol,
            keys_path=args.keys,
            registry_path=args.registry,
            report_cfg_path=args.report_cfg,
            since_date=args.since,
        )
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print_trades_report(report)
        return 0

    if args.cmd == "research-candles":
        from botsgeneral.research_candles.download_all import run

        only = {x.strip().lower() for x in args.only.split(",") if x.strip()}
        symbols = {x.strip().upper() for x in args.symbols.split(",") if x.strip()} or None
        timeframes = {x.strip().lower() for x in args.timeframes.split(",") if x.strip()} or None
        raw_pt = [x.strip().lower() for x in args.price_type.split(",") if x.strip()]
        price_types = ("last", "mark") if "both" in raw_pt else (tuple(raw_pt) or ("last",))
        return run(
            only=only,
            incremental=not args.full,
            symbols=symbols,
            timeframes=timeframes,
            price_types=price_types,
        )

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
