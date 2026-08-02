"""CLI: list / show / plot / open saved backtests without re-running the simulation.

Examples::

    tradesim-research list --db D:/projectsdata/backtests/tradesim_runs.sqlite
    tradesim-research show --db ... --run-id my-run
    tradesim-research plot --db ... --run-id my-run
    tradesim-research open --run-id my-run
    tradesim-research open --folder D:/projectsdata/backtests/reports/my-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .defaults import RESEARCH_REPORTS_DIR, RESEARCH_STORE_PATH
from .store import BacktestStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tradesim-research")
    parser.add_argument(
        "--db",
        default=RESEARCH_STORE_PATH,
        help="SQLite path where run_backtest stored results",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list recorded backtests")
    p_list.add_argument("--strategy", default=None)

    p_show = sub.add_parser("show", help="print metrics JSON for one run")
    p_show.add_argument("--run-id", required=True)

    p_trades = sub.add_parser("trades", help="print trades table for one run")
    p_trades.add_argument("--run-id", required=True)

    p_plot = sub.add_parser(
        "plot",
        help="re-open Finplot + metrics from a saved run (no re-simulation)",
    )
    p_plot.add_argument("--run-id", required=True)
    p_plot.add_argument(
        "--verify-fingerprint",
        default=None,
        help="optional expected run_fingerprint (full or short prefix)",
    )
    p_plot.add_argument(
        "--max-bars",
        type=int,
        default=0,
        help="0 = full period (default); >0 clips the candle window",
    )

    p_open = sub.add_parser(
        "open",
        help="re-open report folder chart+metrics (no re-simulation)",
    )
    p_open.add_argument("--run-id", default=None)
    p_open.add_argument(
        "--folder",
        default=None,
        help="path to D:/projectsdata/backtests/reports/<run_id>",
    )
    p_open.add_argument(
        "--reports-dir",
        default=RESEARCH_REPORTS_DIR,
        help="reports root when resolving --run-id",
    )
    p_open.add_argument(
        "--verify-fingerprint",
        default=None,
        help="optional expected run_fingerprint (full or short prefix)",
    )
    p_open.add_argument(
        "--max-bars",
        type=int,
        default=0,
        help="0 = full period (default)",
    )

    args = parser.parse_args(argv)
    store = BacktestStore(args.db)

    if args.cmd == "list":
        df = store.list_runs(args.strategy)
        if df.empty:
            print("(no runs)")
            return 0
        print(df.to_string(index=False))
        blown = df[df["wallet_blown"] == 1]
        if len(blown):
            print(f"\n*** {len(blown)} run(s) with WALLET BLOWN ***")
            print(blown[["run_id", "strategy_id", "ruined_at_ts_ms"]].to_string(index=False))
        return 0

    if args.cmd == "show":
        saved = store.load_run(args.run_id)
        print(json.dumps(saved.metrics, indent=2, default=str))
        if saved.strategy_meta:
            print("\nstrategy_meta:")
            print(json.dumps(saved.strategy_meta, indent=2, default=str))
        print(
            f"\nbars_fingerprint={saved.bars_fingerprint}\n"
            f"run_fingerprint={saved.run_fingerprint}\n"
            f"embedded_bars={'yes' if saved.bars is not None else 'no'} "
            f"n_trades={len(saved.result.trades)} "
            f"wallet={saved.result.starting_equity} -> {saved.result.ending_equity}"
        )
        if saved.metrics.get("wallet_blown"):
            print(
                f"\n*** WALLET BLOWN at ts_ms={saved.metrics.get('ruined_at_ts_ms')} ***",
                file=sys.stderr,
            )
        return 0

    if args.cmd == "trades":
        print(store.load_trades(args.run_id).to_string(index=False))
        return 0

    if args.cmd == "plot":
        saved = store.load_run(args.run_id)
        if args.verify_fingerprint:
            got = saved.run_fingerprint or ""
            exp = args.verify_fingerprint
            if not (got == exp or got.startswith(exp) or exp.startswith(got[:12])):
                print(
                    f"fingerprint mismatch: expected {exp!r} got {got!r}",
                    file=sys.stderr,
                )
                return 1
        if saved.bars is None:
            print(
                "this run has no embedded bars — re-save with run_backtest(..., store_path=...) "
                "on a current tradesim, or pass bars into BacktestStore.save(bars=...)",
                file=sys.stderr,
            )
            return 1
        from ..metrics import compute_metrics
        from .plot import plot_backtest

        metrics = None
        try:
            metrics = compute_metrics(saved.result, bars=saved.bars)
        except Exception:
            metrics = None
        print(
            f"reloading run_id={saved.run_id}  "
            f"fingerprint={(saved.run_fingerprint or '')[:12]}  "
            f"bars={len(saved.bars)} trades={len(saved.result.trades)}  "
            f"wallet={saved.result.starting_equity:.2f}  (no re-simulation)"
        )
        plot_backtest(
            saved.bars,
            saved.result,
            title=f"{saved.strategy_id} [{saved.run_id}]",
            metrics=metrics,
            strategy_meta=saved.strategy_meta,
            max_bars=int(args.max_bars),
            show=True,
        )
        return 0

    if args.cmd == "open":
        if not args.run_id and not args.folder:
            print("pass --run-id and/or --folder", file=sys.stderr)
            return 2
        from .report import open_report

        try:
            open_report(
                args.run_id,
                folder=args.folder,
                store_path=args.db,
                reports_dir=args.reports_dir,
                max_bars=int(args.max_bars),
                verify_fingerprint=args.verify_fingerprint,
                show=True,
            )
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
