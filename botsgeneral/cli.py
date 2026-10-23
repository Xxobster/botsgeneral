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
    parser.add_argument(
        "--since",
        default=None,
        help="Override since stamp (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)",
    )
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

    p_hmi = sub.add_parser("hmi-snapshot", help="JSON snapshot for the bots Human-Machine Interface (this VPS)")
    p_hmi.add_argument("--json", action="store_true", default=True)
    p_agent = sub.add_parser("hmi-agent", help="Local HMI agent HTTP (127.0.0.1:8788)")
    p_agent.add_argument("--host", default=None)
    p_agent.add_argument("--port", type=int, default=None)
    p_hub = sub.add_parser("hmi-hub", help="HMI hub (serve /bots, fan-out to VPS agents)")
    p_hub.add_argument("--host", default=None)
    p_hub.add_argument("--port", type=int, default=None)

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
        help="Comma list: dukascopy,yahoo,yahoo_tech,binance,btcd,...",
    )
    p_rc.add_argument("--full", action="store_true", help="Full refetch (ignore incremental)")
    p_rc.add_argument(
        "--symbols",
        default="",
        help="Optional comma list (e.g. BTCUSDT,ETHUSDT or AAPL,MSFT,NVDA)",
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

    p_purge = sub.add_parser(
        "purge-unused-candles",
        help="Delete candle series not currently discovered for this VPS (keep served only)",
    )
    p_purge.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be deleted without writing",
    )
    sub.add_parser(
        "prune-incomplete-tips",
        help="Delete still-forming tip bars from shared DB (closed-bar identity)",
    )

    p_cmp = sub.add_parser(
        "compare-closed-bars",
        help="Gate: shared_candles tip OHLC vs market_ohlcv tip (Binance Last)",
    )
    p_cmp.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    p_cmp.add_argument("--timeframes", default="1h,4h,1w")
    p_cmp.add_argument("--shared-db", default="")
    p_cmp.add_argument("--warehouse-db", default="")

    p_oi = sub.add_parser(
        "research-oi",
        help="Download shared research open interest to D:\\projectsdata\\candles\\market_oi.sqlite",
    )
    p_oi.add_argument("--only", default="binance,bybit", help="Comma list: binance,bybit")
    p_oi.add_argument("--full", action="store_true", help="Full refetch (ignore incremental)")
    p_oi.add_argument("--symbols", default="", help="Optional comma list e.g. BTCUSDT,ETHUSDT")
    p_oi.add_argument(
        "--all",
        action="store_true",
        help="Discover all USDT linear perps (majors full history; others tip/1d)",
    )
    p_oi.add_argument("--bybit-timeframes", default="1h,1d")
    p_oi.add_argument("--workers", type=int, default=6)
    p_oi.add_argument("--tip-only", action="store_true")

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

    if args.cmd == "hmi-snapshot":
        from botsgeneral.hmi.jsonutil import dumps
        from botsgeneral.hmi.snapshot import build_snapshot

        snap = build_snapshot(
            keys_path=args.keys,
            registry_path=args.registry,
            report_cfg_path=args.report_cfg,
            vps_id=args.vps,
            since_date=args.since,
        )
        print(dumps(snap, indent=2))
        return 0

    if args.cmd == "hmi-agent":
        from botsgeneral.hmi.agent import serve as serve_agent

        kwargs = {}
        if args.host:
            kwargs["host"] = args.host
        if args.port:
            kwargs["port"] = args.port
        serve_agent(**kwargs)
        return 0

    if args.cmd == "hmi-hub":
        from botsgeneral.hmi.hub import serve as serve_hub

        kwargs = {}
        if args.host:
            kwargs["host"] = args.host
        if args.port:
            kwargs["port"] = args.port
        serve_hub(**kwargs)
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

    if args.cmd == "research-oi":
        from market_data.download_oi import run as run_oi

        only = {x.strip().lower() for x in args.only.split(",") if x.strip()}
        symbols = {x.strip().upper() for x in args.symbols.split(",") if x.strip()} or None
        btfs = tuple(
            x.strip().lower() for x in args.bybit_timeframes.split(",") if x.strip()
        )
        return run_oi(
            only=only,
            symbols=symbols,
            all_symbols=args.all,
            incremental=not args.full,
            bybit_timeframes=btfs or ("1h", "1d"),
            vision_workers=args.workers,
            tip_only=args.tip_only,
            db_path=args.db,
        )

    if args.cmd == "purge-unused-candles":
        from botsgeneral.db import CandleDB
        from botsgeneral.discover import detect_vps_id, discover_pairs, load_registry, unique_pairs

        registry = load_registry(args.registry)
        vps = args.vps or detect_vps_id(registry)
        items, warnings = discover_pairs(registry, vps)
        keep = {(p.exchange, p.symbol, p.timeframe) for p in unique_pairs(items)}
        db = CandleDB(args.db or registry.get("default_db_path") or "/var/lib/botsgeneral/shared_candles.db")
        present = db.list_series()
        would_remove = [
            {"exchange": e, "symbol": s, "timeframe": t, "bars": n}
            for e, s, t, n in present
            if (e, s, t) not in keep
        ]
        payload = {
            "vps": vps,
            "keep": sorted(list(keep)),
            "would_remove": would_remove,
            "warnings": warnings,
        }
        if args.dry_run:
            print(json.dumps(payload, indent=2))
            db.close()
            return 0
        if not keep:
            print(json.dumps({"error": "refusing purge: discover returned zero keep pairs", **payload}, indent=2))
            db.close()
            return 2
        stats = db.delete_series_except(keep)
        pruned = db.delete_incomplete_tips()
        db.close()
        print(json.dumps({"vps": vps, **stats, "pruned_incomplete_tips": pruned, "warnings": warnings}, indent=2))
        return 0

    if args.cmd == "prune-incomplete-tips":
        from botsgeneral.db import CandleDB
        from botsgeneral.discover import load_registry

        registry = load_registry(args.registry)
        db = CandleDB(args.db or registry.get("default_db_path") or "/var/lib/botsgeneral/shared_candles.db")
        n = db.delete_incomplete_tips()
        db.close()
        print(json.dumps({"pruned_incomplete_tips": n}, indent=2))
        return 0

    if args.cmd == "compare-closed-bars":
        from market_data.compare_closed_bars import main as cmp_main

        argv_cmp: list[str] = [
            "--symbols",
            args.symbols,
            "--timeframes",
            args.timeframes,
        ]
        if args.shared_db:
            argv_cmp.extend(["--shared-db", args.shared_db])
        elif args.db:
            argv_cmp.extend(["--shared-db", args.db])
        if args.warehouse_db:
            argv_cmp.extend(["--warehouse-db", args.warehouse_db])
        return cmp_main(argv_cmp)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
