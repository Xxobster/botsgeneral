"""Bounded BTCUSDT validation: refresh candles → 10 synthetic signals → tradesim vs xgb vs live log.

Run::

    python packages/tradesim/tools/validate_btc_session.py

No live deploy. No commits.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
XGB = Path(r"C:\projects\xgb")
LIVE_LOG = XGB / "log" / "btcusdt" / "trading.log"


def _ensure_path() -> None:
    for p in (str(ROOT), str(Path(__file__).resolve().parents[1] / "src"), str(XGB)):
        if p not in sys.path:
            sys.path.insert(0, p)


def load_bars(symbol: str, timeframe: str, source: str = "binance", n: int = 500):
    from botsgeneral.research_candles.db import ResearchCandleDB

    db = ResearchCandleDB()
    df = db.load(symbol, timeframe, source=source)
    db.close()
    if df.empty:
        raise SystemExit(f"no candles for {source} {symbol} {timeframe}")
    df = df.tail(n).reset_index(drop=True)
    from tradesim import BarSeries

    return BarSeries(
        ts_ms=np.array(df["ts_ms"].to_numpy(dtype=np.int64), copy=True),
        open=np.array(df["open"].to_numpy(dtype=float), copy=True),
        high=np.array(df["high"].to_numpy(dtype=float), copy=True),
        low=np.array(df["low"].to_numpy(dtype=float), copy=True),
        close=np.array(df["close"].to_numpy(dtype=float), copy=True),
        volume=(
            np.array(df["volume"].to_numpy(dtype=float), copy=True)
            if "volume" in df
            else None
        ),
        timeframe_ms={"1m": 60_000, "1h": 3_600_000}[timeframe],
        symbol=symbol,
    ), df


def build_signals(bars, cases: list[dict]):
    """Map named cases onto concrete bar indices near the end of the series."""
    from tradesim import Signal, Side

    # Force writable views (BarSeries may wrap read-only buffers).
    high = np.array(bars.high, dtype=float, copy=True)
    low = np.array(bars.low, dtype=float, copy=True)
    close = np.array(bars.close, dtype=float, copy=True)
    open_ = np.array(bars.open, dtype=float, copy=True)

    n = len(bars)
    base = n - 80
    out = []
    for i, case in enumerate(cases):
        idx = base + i * 6
        if idx + 5 >= n:
            raise SystemExit("not enough bars for synthetic cases")
        decision_ts = int(bars.ts_ms[idx])
        entry_open = float(open_[idx + 1])
        side = case["side"]
        stop_off = case["stop_offset"]
        tgt_off = case["target_offset"]
        if side > 0:
            stop = entry_open * (1 - stop_off)
            tgt = entry_open * (1 + tgt_off)
        else:
            stop = entry_open * (1 + stop_off)
            tgt = entry_open * (1 - tgt_off)
        if case.get("force") == "entry_bar_stop":
            if side > 0:
                low[idx + 1] = min(low[idx + 1], stop - entry_open * 0.001)
            else:
                high[idx + 1] = max(high[idx + 1], stop + entry_open * 0.001)
        elif case.get("force") == "entry_bar_tp":
            if side > 0:
                high[idx + 1] = max(high[idx + 1], tgt + entry_open * 0.001)
            else:
                low[idx + 1] = min(low[idx + 1], tgt - entry_open * 0.001)
        elif case.get("force") == "quiet":
            mid = entry_open
            high[idx + 1] = mid * 1.0002
            low[idx + 1] = mid * 0.9998
            close[idx + 1] = mid
        out.append(
            Signal(
                ts_ms=decision_ts,
                side=Side.LONG if side > 0 else Side.SHORT,
                symbol=bars.symbol,
                stop_price=stop,
                target_price=tgt,
                qty=0.001,
                max_hold_bars=case.get("max_hold", 12),
                tag=case["name"],
            )
        )
    from tradesim import BarSeries

    mutated = BarSeries(
        ts_ms=np.array(bars.ts_ms, dtype=np.int64, copy=True),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=None if bars.volume is None else np.array(bars.volume, copy=True),
        timeframe_ms=bars.timeframe_ms,
        symbol=bars.symbol,
    )
    return out, mutated


def run_tradesim(bars, signals):
    from tradesim import run_backtest
    from tradesim.research import research_instrument
    from tradesim.contracts import SizingConfig, SizingMode

    return run_backtest(
        strategy_id="validate-btc-session",
        bars=bars,
        signals=signals,
        instrument=research_instrument("BTCUSDT", refresh_if_missing=False),
        sizing=SizingConfig(mode=SizingMode.FIXED_QTY, fixed_qty=0.001),
        print_headline=True,
        store_path=None,
    )


def run_xgb(df_1h: pd.DataFrame, signals_meta: list[dict], tp_pct: float, sl_pct: float):
    sys.path.insert(0, str(XGB))
    from utils.audit_v4.execution_sim import ThresholdExecutionSim

    ohlcv = df_1h.set_index(pd.to_datetime(df_1h["ts_ms"], unit="ms", utc=True))[
        ["open", "high", "low", "close", "volume"]
    ].rename(columns=str.title)
    # build signal series: +1 / -1 at decision bars
    sig = pd.Series(0, index=ohlcv.index, dtype=int)
    for m in signals_meta:
        ts = pd.Timestamp(m["decision_ts_ms"], unit="ms", tz="UTC")
        if ts in sig.index:
            sig.loc[ts] = int(m["side"])
    sim = ThresholdExecutionSim(
        "btcusdt",
        commission=0.00055,
        entry_slip_pct=0.05,
        exit_slip_pct=0.0,
        market_exit_slip_pct=0.0,
        leverage=1.0,
        fixed_qty=0.001,
        initial_cash=10_000.0,
    )
    return sim.run(ohlcv, sig, tp_pct=tp_pct, sl_pct=sl_pct, max_hold_bars=12)


def parse_live_trades(path: Path, limit: int = 5) -> list[dict]:
    if not path.is_file():
        return []
    placed = re.compile(
        r"Trade placed: symbol=(?P<sym>\w+) side=(?P<side>\w+) price=(?P<px>[\d.]+) "
        r"size=(?P<qty>[\d.]+) TP=(?P<tp>[\d.]+) SL=(?P<sl>[\d.]+) \| bar_ts=(?P<bar>[^\s|]+ [^\s|]+)"
    )
    rows = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = placed.search(ln)
        if m:
            rows.append(m.groupdict())
    return rows[-limit:]


def main() -> int:
    _ensure_path()
    skip = "--skip-refresh" in sys.argv
    if not skip:
        print("=== 1) ensure candles (Last + Mark, 1h + 1m) ===")
        from tradesim.research import ensure_candles

        ensure_candles(
            ["BTCUSDT"], ["1h", "1m"], price_types=("last", "mark"), quiet=True
        )
    else:
        print("=== 1) skip candle refresh (--skip-refresh) ===")

    print("\n=== 2) load Last 1h (+ 1m available for touch) ===")
    bars, df = load_bars("BTCUSDT", "1h", "binance", n=400)
    try:
        touch, _ = load_bars("BTCUSDT", "1m", "binance", n=20_000)
    except SystemExit:
        touch = None
        print("(no 1m yet — same-bar resolve without LTF)")

    cases = [
        {"name": "quiet_hold", "side": 1, "stop_offset": 0.02, "target_offset": 0.02, "force": "quiet"},
        {"name": "entry_bar_stop", "side": 1, "stop_offset": 0.001, "target_offset": 0.05, "force": "entry_bar_stop"},
        {"name": "entry_bar_tp", "side": 1, "stop_offset": 0.05, "target_offset": 0.001, "force": "entry_bar_tp"},
        {"name": "short_entry_stop", "side": -1, "stop_offset": 0.001, "target_offset": 0.05, "force": "entry_bar_stop"},
        {"name": "short_entry_tp", "side": -1, "stop_offset": 0.05, "target_offset": 0.001, "force": "entry_bar_tp"},
        {"name": "long_wide", "side": 1, "stop_offset": 0.015, "target_offset": 0.015},
        {"name": "short_wide", "side": -1, "stop_offset": 0.015, "target_offset": 0.015},
        {"name": "long_tight_hold", "side": 1, "stop_offset": 0.01, "target_offset": 0.01, "max_hold": 3},
        {"name": "short_tight_hold", "side": -1, "stop_offset": 0.01, "target_offset": 0.01, "max_hold": 3},
        {"name": "min_size_long", "side": 1, "stop_offset": 0.02, "target_offset": 0.02},
    ]
    signals, bars = build_signals(bars, cases)

    print("\n=== 3) tradesim run ===")
    bundle = run_tradesim(bars, signals)
    m = bundle.metrics
    print("\nbacktesting.py-compatible stats:")
    for k, v in m.as_backtesting_stats().items():
        print(f"  {k}: {v}")

    print("\ntradesim trades:")
    for t in bundle.result.trades:
        print(
            f"  id={t.trade_id} tag={getattr(t, 'tag', '')} side={t.side} "
            f"entry={t.entry_price:.2f} exit={t.exit_price:.2f} reason={t.exit_reason} "
            f"hold={t.hold_bars} pnl={t.realized_pnl:.4f} fees={t.fees:.4f} fund={t.funding:.4f}"
        )
    print("\nfills:")
    for f in bundle.result.fills[:30]:
        print(
            f"  {f.ts_ms} {f.role} {f.side} qty={f.qty} px={f.price:.2f} fee={f.fee:.4f}"
        )
    print("\nfunding charges:")
    for c in bundle.result.funding_charges[:20]:
        print(f"  {c.ts_ms} rate={c.rate} cashflow={c.cashflow:.6f}")

    print("\n=== 4) xgb audit_v4 parity (same decision bars, 1% brackets approx) ===")
    meta = [
        {"decision_ts_ms": s.ts_ms, "side": int(s.side), "tag": s.tag}
        for s in signals
    ]
    # xgb uses pct from fill; use 1% / 1% for a coarse path check on wide cases
    try:
        xgb_res = run_xgb(df, meta, tp_pct=0.01, sl_pct=0.01)
        print(f"xgb trades: {len(xgb_res.trades)}")
        for t in xgb_res.trades:
            print(
                f"  id={t.trade_id} side={t.side} entry={t.entry_px:.2f} "
                f"exit={t.exit_px} reason={t.exit_reason} pnl={t.pnl:.4f} "
                f"fees={t.fees:.4f} fund={t.funding:.4f}"
            )
        print(
            "NOTE: xgb path uses uniform tp/sl pct and its own signal→fill indexing; "
            "forced OHLC mutations apply only to tradesim. Expect named differences, "
            "not bit-identical trades on forced cases."
        )
    except Exception as exc:
        print(f"xgb parity skipped: {exc!r}")

    print("\n=== 5) latest live trades from xgb log ===")
    live = parse_live_trades(LIVE_LOG, limit=5)
    print(f"log: {LIVE_LOG} ({'missing' if not LIVE_LOG.is_file() else 'ok'})")
    for row in live:
        print(
            f"  {row['bar']} {row['side']} qty={row['qty']} "
            f"px={row['px']} TP={row['tp']} SL={row['sl']}"
        )
    if live:
        print(
            "Replay of these 5 into tradesim needs the same fill+TP/SL policy and "
            "funding series; candle refresh already done above for that next step."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
