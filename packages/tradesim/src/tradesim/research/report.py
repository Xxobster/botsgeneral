"""Per-run report folders: strategy details + metrics + trades, reopen without resim.

Layout (default root ``D:/projectsdata/backtests/reports``)::

    {run_id}/
      REPORT.md          human summary (strategy + headline metrics)
      strategy.json      name, batch, model path, TP/SL, …
      metrics.json       full MetricsReport.as_dict()
      metrics.txt        headline + backtesting.py-compatible stats
      trades.csv
      equity.csv
      meta.json          run_id, fingerprints, store path, reopen command
      headline.txt

Reopen chart + metrics (no re-simulation)::

    tradesim-research open --run-id …
    # or
    from tradesim.research.report import open_report
    open_report(run_id)
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from ..contracts import SimResult
from ..metrics import MetricsReport, headline_table
from .defaults import (
    RESEARCH_REPORTS_DIR,
    RESEARCH_STORE_PATH,
)
from .store import BacktestStore, SavedRun

_SAFE = re.compile(r"[^A-Za-z0-9._+-]+")


@dataclass
class StrategyDetails:
    """Identity + risk parameters for a research / live pack replay."""

    name: str = ""
    strategy_id: str = ""
    strategy_version: str = ""
    batch: str = ""
    model_name: str = ""
    model_path: str = ""
    symbol: str = ""
    timeframe: str = ""
    decision_timeframe: str = ""
    touch_timeframe: str = ""
    tp_pct: float | None = None
    sl_pct: float | None = None
    tp_price: float | None = None
    sl_price: float | None = None
    max_hold_bars: int | None = None
    leverage: float | None = None
    features: list[str] = field(default_factory=list)
    trial_id: str = ""
    pack_path: str = ""
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> StrategyDetails:
        from dataclasses import fields

        if not data:
            return cls()
        known = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        for k, v in data.items():
            key = str(k)
            if key in known and key != "extra":
                kwargs[key] = v
            else:
                extra[key] = v
        nested = data.get("extra") if isinstance(data.get("extra"), dict) else {}
        if nested:
            extra = {**extra, **nested}
        if extra:
            kwargs["extra"] = extra
        if "features" in kwargs and kwargs["features"] is not None:
            kwargs["features"] = [str(x) for x in list(kwargs["features"])]
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Drop empty noise for cleaner JSON
        out: dict[str, Any] = {}
        for k, v in d.items():
            if v is None or v == "" or v == [] or v == {}:
                continue
            out[k] = v
        return out

    def markdown_block(self) -> str:
        d = self.to_dict()
        if not d:
            return "(no strategy details provided)"
        lines = ["| Field | Value |", "|---|---|"]
        for k, v in d.items():
            if k == "features":
                v = ", ".join(v) if isinstance(v, list) else v
            if k == "extra" and isinstance(v, dict):
                v = json.dumps(v, default=str)
            lines.append(f"| {k} | `{v}` |")
        return "\n".join(lines)


@dataclass(frozen=True)
class ReportPaths:
    root: Path
    run_id: str

    @property
    def folder(self) -> Path:
        return self.root / _safe_run_id(self.run_id)

    @property
    def meta(self) -> Path:
        return self.folder / "meta.json"

    @property
    def strategy(self) -> Path:
        return self.folder / "strategy.json"

    @property
    def metrics_json(self) -> Path:
        return self.folder / "metrics.json"

    @property
    def metrics_txt(self) -> Path:
        return self.folder / "metrics.txt"

    @property
    def trades(self) -> Path:
        return self.folder / "trades.csv"

    @property
    def equity(self) -> Path:
        return self.folder / "equity.csv"

    @property
    def report_md(self) -> Path:
        return self.folder / "REPORT.md"

    @property
    def headline(self) -> Path:
        return self.folder / "headline.txt"


def _safe_run_id(run_id: str) -> str:
    s = _SAFE.sub("_", str(run_id).strip()) or "run"
    return s[:180]


def default_reports_dir() -> Path:
    return Path(RESEARCH_REPORTS_DIR)


def default_store_path() -> Path:
    return Path(RESEARCH_STORE_PATH)


def _trades_frame(result: SimResult) -> pd.DataFrame:
    rows = []
    for t in result.trades:
        entry = float(t.entry_price)
        stop = float(t.stop_price)
        target = float(t.target_price) if t.target_price is not None else None
        side = int(t.side)
        if entry > 0:
            sl_pct = (stop - entry) / entry * 100.0
            tp_pct = (
                ((target - entry) / entry * 100.0)
                if target is not None
                else None
            )
            if side < 0:
                sl_pct = -sl_pct
                if tp_pct is not None:
                    tp_pct = -tp_pct
        else:
            sl_pct = None
            tp_pct = None
        rows.append(
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "side": side,
                "entry_ts_ms": t.entry_ts_ms,
                "exit_ts_ms": t.exit_ts_ms,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "qty": t.qty,
                "stop_price": t.stop_price,
                "target_price": t.target_price,
                "sl_pct": sl_pct,
                "tp_pct": tp_pct,
                "exit_reason": t.exit_reason,
                "fees": t.fees,
                "funding": t.funding,
                "gross_pnl": t.gross_pnl,
                "realized_pnl": t.realized_pnl,
                "return_units": t.return_units,
                "hold_bars": t.hold_bars,
                "entry_bar_exit": int(bool(t.entry_bar_exit)),
                "tp_levels": json.dumps(list(getattr(t, "tp_levels", ()) or ()), default=str),
            }
        )
    return pd.DataFrame(rows)


def _infer_tp_sl_from_trades(result: SimResult) -> dict[str, Any]:
    """Median absolute TP/SL % from closed trades when pack meta omitted them."""
    if not result.trades:
        return {}
    sls: list[float] = []
    tps: list[float] = []
    for t in result.trades:
        entry = float(t.entry_price)
        if entry <= 0:
            continue
        sls.append(abs(float(t.stop_price) - entry) / entry * 100.0)
        if t.target_price is not None:
            tps.append(abs(float(t.target_price) - entry) / entry * 100.0)
    out: dict[str, Any] = {}
    if sls:
        out["sl_pct_median_from_trades"] = float(pd.Series(sls).median())
    if tps:
        out["tp_pct_median_from_trades"] = float(pd.Series(tps).median())
    return out


def write_report(
    *,
    run_id: str,
    strategy_id: str,
    result: SimResult,
    metrics: MetricsReport,
    strategy_meta: Mapping[str, Any] | StrategyDetails | None = None,
    strategy_version: str = "",
    notes: str = "",
    reports_dir: str | Path | None = None,
    store_path: str | Path | None = None,
    fingerprints: Mapping[str, str] | None = None,
    symbol: str = "",
    decision_timeframe: str = "",
) -> ReportPaths:
    """Write a self-contained report folder. Does not re-simulate."""
    root = Path(reports_dir) if reports_dir is not None else default_reports_dir()
    paths = ReportPaths(root=root, run_id=run_id)
    paths.folder.mkdir(parents=True, exist_ok=True)

    if isinstance(strategy_meta, StrategyDetails):
        details = strategy_meta
    else:
        details = StrategyDetails.from_mapping(strategy_meta)

    if not details.strategy_id:
        details.strategy_id = strategy_id
    if not details.strategy_version and strategy_version:
        details.strategy_version = strategy_version
    if not details.name:
        details.name = strategy_id
    if not details.symbol and symbol:
        details.symbol = symbol
    if not details.decision_timeframe and decision_timeframe:
        details.decision_timeframe = decision_timeframe
        details.timeframe = details.timeframe or decision_timeframe
    if not details.notes and notes:
        details.notes = notes
    if details.tp_pct is None or details.sl_pct is None:
        inferred = _infer_tp_sl_from_trades(result)
        details.extra = {**details.extra, **inferred}

    headline = headline_table(metrics)
    metrics_dict = metrics.as_dict()
    bt_stats = metrics.as_backtesting_stats()

    paths.strategy.write_text(
        json.dumps(details.to_dict(), indent=2, default=str) + "\n", encoding="utf-8"
    )
    paths.metrics_json.write_text(
        json.dumps(metrics_dict, indent=2, default=str) + "\n", encoding="utf-8"
    )
    metrics_txt_lines = [
        headline.rstrip(),
        "",
        "backtesting.py-compatible stats:",
        *[f"  {k}: {v}" for k, v in bt_stats.items()],
        "",
        "strategy details:",
        details.markdown_block(),
    ]
    paths.metrics_txt.write_text("\n".join(metrics_txt_lines) + "\n", encoding="utf-8")
    paths.headline.write_text(headline, encoding="utf-8")

    trades_df = _trades_frame(result)
    if len(trades_df):
        trades_df.to_csv(paths.trades, index=False)
    else:
        paths.trades.write_text("", encoding="utf-8")

    eq = result.equity
    if eq is not None and len(eq):
        eq.to_csv(paths.equity, index=False)
    else:
        paths.equity.write_text("", encoding="utf-8")

    fps = dict(fingerprints or {})
    store = str(Path(store_path).resolve()) if store_path else str(default_store_path())
    meta = {
        "run_id": run_id,
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "store_path": store,
        "reports_dir": str(root.resolve()),
        "report_folder": str(paths.folder.resolve()),
        "bars_fingerprint": fps.get("bars_fingerprint", ""),
        "run_fingerprint": fps.get("run_fingerprint", ""),
        "run_fingerprint_short": fps.get("run_fingerprint_short", ""),
        "n_trades": len(result.trades),
        "starting_equity": result.starting_equity,
        "ending_equity": result.ending_equity,
        "wallet_blown": bool(metrics.wallet_blown),
        "reopen": {
            "cli": f'tradesim-research open --run-id {run_id}',
            "cli_from_folder": f'tradesim-research open --folder "{paths.folder}"',
            "python": (
                "from tradesim.research.report import open_report\n"
                f"open_report({run_id!r})"
            ),
        },
        "note": "Chart + metrics reload from the SQLite store (embedded bars). No re-simulation.",
    }
    paths.meta.write_text(json.dumps(meta, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        f"# TradeSim report — `{run_id}`",
        "",
        f"Created: `{meta['created_at_utc']}`",
        "",
        "## Strategy",
        "",
        details.markdown_block(),
        "",
        "## Headline metrics",
        "",
        "```",
        headline.rstrip(),
        "```",
        "",
        "## Reopen (no re-calculation)",
        "",
        "```text",
        meta["reopen"]["cli"],
        "```",
        "",
        f"- Store: `{store}`",
        f"- Fingerprint: `{fps.get('run_fingerprint_short') or fps.get('run_fingerprint') or 'n/a'}`",
        f"- Trades CSV: `{paths.trades.name}`",
        f"- Metrics JSON: `{paths.metrics_json.name}`",
        "",
    ]
    paths.report_md.write_text("\n".join(md), encoding="utf-8")
    return paths


def load_strategy_details(folder: str | Path) -> StrategyDetails:
    p = Path(folder) / "strategy.json"
    if not p.exists():
        return StrategyDetails()
    return StrategyDetails.from_mapping(json.loads(p.read_text(encoding="utf-8")))


def resolve_report_folder(
    run_id: str | None = None,
    *,
    folder: str | Path | None = None,
    reports_dir: str | Path | None = None,
) -> Path:
    if folder is not None:
        return Path(folder)
    if not run_id:
        raise ValueError("pass run_id= or folder=")
    root = Path(reports_dir) if reports_dir is not None else default_reports_dir()
    return ReportPaths(root=root, run_id=run_id).folder


def open_report(
    run_id: str | None = None,
    *,
    folder: str | Path | None = None,
    store_path: str | Path | None = None,
    reports_dir: str | Path | None = None,
    show: bool = True,
    max_bars: int = 0,
    max_zone_trades: int = 200,
    verify_fingerprint: str | None = None,
) -> SavedRun:
    """Re-open Finplot chart (full period) + metrics from a saved run — no resim."""
    report_folder = resolve_report_folder(
        run_id, folder=folder, reports_dir=reports_dir
    )
    meta: dict[str, Any] = {}
    meta_path = report_folder / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    rid = run_id or str(meta.get("run_id") or report_folder.name)
    db = Path(store_path) if store_path else Path(meta.get("store_path") or default_store_path())
    store = BacktestStore(db)
    saved = store.load_run(rid)

    if verify_fingerprint:
        got = saved.run_fingerprint or ""
        exp = verify_fingerprint
        if not (got == exp or got.startswith(exp) or exp.startswith(got[:12])):
            raise ValueError(f"fingerprint mismatch: expected {exp!r} got {got!r}")

    if saved.bars is None:
        raise FileNotFoundError(
            f"run {rid!r} has no embedded bars in {db} — cannot reopen chart without resim"
        )

    details = load_strategy_details(report_folder)
    if not details.to_dict() and saved.strategy_meta:
        details = StrategyDetails.from_mapping(saved.strategy_meta)
    from ..metrics import compute_metrics
    from .plot import plot_backtest

    metrics = None
    try:
        metrics = compute_metrics(saved.result, bars=saved.bars)
    except Exception:
        metrics = None

    title_bits = [
        details.name or saved.strategy_id,
        details.symbol or "",
        details.timeframe or details.decision_timeframe or "",
        f"[{rid}]",
    ]
    title = " ".join(x for x in title_bits if x)
    meta_dict = details.to_dict() or (saved.strategy_meta or None)

    print(
        f"reopening report run_id={rid}  "
        f"folder={report_folder}  "
        f"fingerprint={(saved.run_fingerprint or '')[:12]}  "
        f"bars={len(saved.bars)} trades={len(saved.result.trades)}  "
        f"(no re-simulation)"
    )
    plot_backtest(
        saved.bars,
        saved.result,
        title=title,
        metrics=metrics,
        strategy_meta=meta_dict,
        max_bars=int(max_bars),
        max_zone_trades=int(max_zone_trades),
        show=show,
        show_metrics_window=True,
    )
    return saved


def strategy_details_text(meta: Mapping[str, Any] | StrategyDetails | None) -> str:
    if isinstance(meta, StrategyDetails):
        details = meta
    else:
        details = StrategyDetails.from_mapping(meta)
    block = details.markdown_block()
    if block.startswith("(no"):
        return ""
    lines = ["strategy details:"]
    for row in block.splitlines():
        if row.startswith("|---") or row.startswith("| Field"):
            continue
        if row.startswith("|") and row.endswith("|"):
            parts = [p.strip().strip("`") for p in row.strip("|").split("|")]
            if len(parts) >= 2:
                lines.append(f"  {parts[0]}: {parts[1]}")
    return "\n".join(lines)
