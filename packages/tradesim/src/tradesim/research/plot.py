"""Optional Finplot review of a tradesim backtest.

TradingView-inspired layout:

* **top panel** (~20% height) — **realized** equity (steps when trades close; use
  ``equity_mode="mtm"`` for mark-to-market every bar)
* **bottom panel** (~80%) — dark ``#131722`` candlesticks; each trade is a **green/red
  line from (entry bar, entry price) to (exit bar, exit price)** so opens and closes
  sit on the exact bars. Per-trade outcome text is **off by default** (tidy); click an
  **entry candle** for side / hold / pnl details. Pass ``trade_labels="on_chart"`` for
  piled tags.
* **metrics window** — full strategy metrics on open / click empty bars

Requires: ``pip install tradesim[plot]``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from ..contracts import BarSeries, SimResult, Trade
from ..metrics import MetricsReport, headline_table

# TradingView-ish dark palette
TV_BG = "#131722"
TV_FG = "#d1d4dc"
TV_GRID = "#2a2e39"
TV_BULL = "#26a69a"
TV_BEAR = "#ef5350"
TV_ENTRY = "#ffffff"
TV_SL_LINE = "#ffffff"
# Filled hold boxes (trade_style="zones" / "boxes") — outcome colour, not TP/SL colour.
TV_WIN_ZONE = (38, 166, 154, 90)
TV_LOSS_ZONE = (239, 83, 80, 90)
# Kept for older callers that referenced these names.
TV_TP_ZONE = TV_WIN_ZONE
TV_SL_ZONE = TV_LOSS_ZONE

COLOR_EQUITY = "#42a5f5"
COLOR_PEAK = "#26c6da"
COLOR_FINAL = "#90caf9"
COLOR_MAX_DD = "#ef5350"
COLOR_WIN = "#26a69a"
COLOR_LOSS = "#ef5350"
COLOR_LONG_ENTRY = "#26a69a"
COLOR_SHORT_ENTRY = "#ef5350"
COLOR_EXIT_WIN = "#66bb6a"
COLOR_EXIT_LOSS = "#ef5350"

# Equity row ~20% of window, price ~80% (finplot axis_height_factor math).
_EQUITY_HEIGHT = 0.25
_PRICE_HEIGHT = 1.0
_DEFAULT_EXTRA_HEIGHT = 0.45
# Horizontal level marker extends this many bars left and right of the event.
_DEFAULT_LINE_HALF_BARS = 3
# Adaptive label packing — floor prevents step_y≈0 (smudged / stacked text).
_LABEL_LINE_PX = 14
_LABEL_GAP_PX = 3
_LABEL_CLUSTER_X_PX = 40
_LABEL_MAX_STACK = 64
_LABEL_NEARBY_BARS = 1.25
_LEVEL_PCT_ROUND = 4
# Cap how many full outcome lines are drawn (zones/crosses still drawn for all).
_LABEL_MAX_OUTCOMES = 48
# Within a local entry cluster, show this many full tags then "+N more".
_LABEL_CLUSTER_MAX_FULL = 5
# Minimum price-unit step between pile rows (never collapse to zero).
_LABEL_STEP_PRICE_FRAC = 0.0015
_LABEL_STEP_YSPAN_FRAC = 0.004




@dataclass
class PlotView:
    """Result of ``plot_backtest`` — axes plus the clipped frames for overlays.

    Sequence protocol keeps older unpacking working when there are exactly two panes::

        ax_eq, ax_px = plot_backtest(...)          # only if extra_rows == 0
        view = plot_backtest(..., extra_rows=1)
        fplt.plot(..., ax=view.extra_axes[0])
    """

    fplt: Any
    axes: list[Any]
    ax_equity: Any
    ax_price: Any
    extra_axes: list[Any] = field(default_factory=list)
    bars_df: pd.DataFrame | None = None
    equity_df: pd.DataFrame | None = None
    trades: tuple[Trade, ...] = ()
    title: str = ""
    metrics: MetricsReport | None = None

    def __iter__(self):
        return iter(self.axes)

    def __len__(self) -> int:
        return len(self.axes)

    def __getitem__(self, item: int | slice) -> Any:
        return self.axes[item]


# Type alias for the extension callback.
OnAxesCallback = Callable[["PlotView"], None]


def plot_backtest(
    bars: BarSeries,
    result: SimResult,
    *,
    title: str = "tradesim backtest",
    max_bars: int = 0,
    relative_equity: bool = False,
    equity_mode: str = "realized",
    trade_style: str = "lines",
    trade_labels: str = "none",
    line_half_bars: int = _DEFAULT_LINE_HALF_BARS,
    metrics: MetricsReport | None = None,
    strategy_meta: dict[str, Any] | None = None,
    show: bool = True,
    show_metrics_window: bool = True,
    max_zone_trades: int = 0,
    extra_rows: int = 0,
    extra_row_heights: Sequence[float] | None = None,
    on_axes: OnAxesCallback | None = None,
    predictions: Mapping[int, float] | Any | None = None,
    prediction_name: str = "pred_mean",
    trade_annotations: Mapping[int, Mapping[str, Any] | float] | None = None,
    prediction_keys: Sequence[str] | None = None,
) -> PlotView:
    """Equity (top) + price/trades + optional extra panes + metrics window.

    ``extra_rows`` / ``extra_row_heights``
        Add empty panes below the price chart (shared X-axis). Heights are relative
        Finplot ``axis_height_factor`` weights (default ``0.45`` each). Draw into them
        from ``on_axes`` or after return when ``show=False``.

    ``on_axes``
        ``Callable[[PlotView], None]`` invoked after the standard equity/price/trade
        layers are drawn and before ``fplt.show()``. Use for indicators, volume,
        custom markers, etc.::

            def add_rsi(view):
                import finplot as fplt
                fplt.plot(rsi.index, rsi.values, ax=view.extra_axes[0], legend="RSI")

            plot_backtest(bars, result, extra_rows=1, on_axes=add_rsi)

        Or defer show and draw yourself::

            view = plot_backtest(bars, result, show=False, extra_rows=1)
            fplt.plot(..., ax=view.extra_axes[0])
            fplt.show()

    ``max_bars``:
      - ``0`` or negative (default): plot the **whole** bar series (full period).
      - positive: clip to at most that many bars around the trade window.

    ``equity_mode``:
      - ``"realized"`` (default): step curve — wallet moves only when a trade closes
      - ``"mtm"``: mark-to-market every bar (includes unrealized PnL)

    ``trade_style``:
      - ``"lines"`` / ``"spans"`` (default): one line per trade from
        (entry bar, entry price) → (exit bar, exit price); green if realized PnL > 0,
        red otherwise. Small markers at entry and exit on the exact bars.
      - ``"zones"`` / ``"boxes"``: same span line **plus** a translucent hold box
        (entry bar → exit bar). Red box means realized PnL < 0 (often ``max_hold``),
        not “stop hit”.
      - Optional dashed TP/SL % only when those % differ across trades (rare).

    ``trade_labels``:
      - ``"none"`` (default): no per-trade outcome tag pile — **click an entry candle**
        for side / hold / pnl details (cheap, tidy).
      - ``"on_chart"``: draw capped/piled outcome tags on the chart (legacy).

    ``max_zone_trades``:
      - ``0`` or negative (default): draw every visible trade
      - positive: only the last N visible trades

    ``predictions`` / ``prediction_name`` / ``trade_annotations``:
      Optional inspect overlays when ``Trade.meta`` was not filled by the engine.
      - ``predictions``: map (or Series) ``entry_ts_ms → float`` (or ``trade_id → float``).
        Default display key is ``pred_mean`` (LLM signed mean in about [-1, +1]).
      - ``trade_annotations``: ``entry_ts_ms`` or ``trade_id`` → dict of fields (or a float
        treated as the prediction).
      Prefer putting ``pred_mean`` (and friends) on ``Signal.meta`` so the engine freezes
      them onto each ``Trade`` automatically — the popup then needs no extra args.
    """
    try:
        import finplot as fplt
    except ImportError as exc:
        raise ImportError(
            "finplot is not installed. Install with: pip install tradesim[plot]"
        ) from exc

    _apply_dark_theme(fplt)

    df = _bars_frame(bars)
    if df[["Open", "High", "Low", "Close"]].isna().all().any() or len(df) == 0:
        raise ValueError(f"no plottable OHLC bars for {title!r}")
    if str(equity_mode).lower() in ("mtm", "mark", "mark_to_market", "unrealized"):
        eq = _equity_frame(result)
        eq_label = "MTM equity (every bar)"
    else:
        eq = _realized_equity_frame(result, df.index)
        eq_label = "Realized equity (closed trades only)"
    df, eq = _clip_window(df, eq, result.trades, bars.timeframe_ms, max_bars)
    visible_trades = _trades_in_window(result.trades, df.index)
    labels_mode = str(trade_labels or "none").lower().strip()
    draw_outcomes = labels_mode in ("on_chart", "chart", "tags", "pile", "yes", "true", "1")

    n_extra = max(0, int(extra_rows))
    if extra_row_heights is not None and len(extra_row_heights) != n_extra:
        raise ValueError(
            f"extra_row_heights length {len(extra_row_heights)} != extra_rows {n_extra}"
        )
    heights = {0: _EQUITY_HEIGHT, 1: _PRICE_HEIGHT}
    for i in range(n_extra):
        h = (
            float(extra_row_heights[i])
            if extra_row_heights is not None
            else _DEFAULT_EXTRA_HEIGHT
        )
        heights[2 + i] = h
    # Must be set BEFORE create_plot — finplot paints odd rows with odd_plot_background
    # and sizes rows from axis_height_factor.
    fplt.axis_height_factor = heights

    axes = fplt.create_plot(title, rows=2 + n_extra)
    if not isinstance(axes, (list, tuple)):
        axes = [axes]
    axes = list(axes)
    ax_eq, ax_px = axes[0], axes[1]
    extra_axes = axes[2:]
    _force_axes_dark(axes)

    _plot_equity(
        fplt, ax_eq, eq, relative_equity=relative_equity, curve_label=eq_label
    )
    # Candle shadows then bodies — force a non-zero width for dense histories.
    fplt.candlestick_ochl(
        df[["Open", "Close", "High", "Low"]],
        ax=ax_px,
        candle_width=0.7,
    )
    _force_axes_dark(axes)  # candlestick path can reset brushes on some finplot builds
    style = str(trade_style or "lines").lower().strip()
    if style in ("zones", "zone", "boxes", "box"):
        _plot_trades_zones(
            fplt,
            ax_px,
            df.index,
            visible_trades,
            max_zone_trades=max_zone_trades,
            draw_outcomes=draw_outcomes,
        )
    else:
        # lines / spans / default — entry→exit price paths
        _plot_trades_spans(
            fplt,
            ax_px,
            df.index,
            visible_trades,
            max_zone_trades=max_zone_trades,
            draw_outcomes=draw_outcomes,
            half_bars=int(line_half_bars),
        )
    # Price pane: no trade legend (equity pane keeps its own).

    view = PlotView(
        fplt=fplt,
        axes=axes,
        ax_equity=ax_eq,
        ax_price=ax_px,
        extra_axes=extra_axes,
        bars_df=df,
        equity_df=eq,
        trades=tuple(visible_trades),
        title=title,
        metrics=metrics,
    )
    if on_axes is not None:
        on_axes(view)
        _force_axes_dark(axes)

    metrics_text = _metrics_text(result, metrics, strategy_meta=strategy_meta)
    by_entry = _index_trades_by_entry_bar(visible_trades, df.index)
    bar_index = df.index

    def _on_click(x, _y, *_rest):
        # finplot set_mouse_callback passes (x, y); older docs mentioned a third arg.
        i = _click_x_to_bar_index(x, bar_index)
        rows = by_entry.get(i) if i is not None else None
        if rows:
            bar_ts = bar_index[i] if i is not None and 0 <= i < len(bar_index) else None
            detail = _trades_detail_text(
                rows,
                bar_ts=bar_ts,
                bar_i=i,
                predictions=predictions,
                prediction_name=prediction_name,
                trade_annotations=trade_annotations,
                prediction_keys=prediction_keys,
            )
            _open_info_window(
                detail,
                title=f"Trades @ bar {i} — {title}",
                key="trade_inspect",
                width=560,
                height=420,
            )
        else:
            _open_info_window(
                metrics_text,
                title=f"Metrics — {title}",
                key="metrics",
                width=720,
                height=640,
            )

    try:
        fplt.set_mouse_callback(_on_click, ax=ax_px, when="click")
    except Exception:
        try:
            fplt.set_time_inspector(_on_click, ax=ax_px, when="click")
        except Exception:
            pass

    if show:
        _ensure_qt_app()
        if show_metrics_window:
            _open_info_window(
                metrics_text, title=f"Metrics — {title}", key="metrics", width=720, height=640
            )
        fplt.show()
    elif show_metrics_window:
        _ensure_qt_app()
        _open_info_window(
            metrics_text, title=f"Metrics — {title}", key="metrics", width=720, height=640
        )
    return view


# --------------------------------------------------------------------------------------
# Theme / frames
# --------------------------------------------------------------------------------------


def _apply_dark_theme(fplt: Any) -> None:
    fplt.background = TV_BG
    # CRITICAL: finplot paints row 1,3,… with odd_plot_background (default #eaeaea = white).
    # That is why the price pane stayed white while the equity pane looked dark.
    fplt.odd_plot_background = TV_BG
    fplt.foreground = TV_FG
    # Filled bodies (default bull body is white → invisible on a light chart).
    fplt.candle_bull_color = TV_BULL
    fplt.candle_bull_body_color = TV_BULL
    fplt.candle_bear_color = TV_BEAR
    fplt.candle_bear_body_color = TV_BEAR
    fplt.cross_hair_color = "#758696"
    fplt.draw_line_color = TV_ENTRY
    fplt.legend_border_color = TV_GRID
    fplt.legend_fill_color = "#1e222d"
    fplt.legend_text_color = TV_FG
    fplt.volume_bull_color = TV_BULL
    fplt.volume_bear_color = TV_BEAR
    fplt.volume_bull_body_color = TV_BULL
    fplt.volume_neutral_color = "#787b86"
    fplt.band_color = TV_TP_ZONE
    fplt.draw_band_color = TV_TP_ZONE
    try:
        fplt.lod_candles = max(int(getattr(fplt, "lod_candles", 0) or 0), 25_000)
    except Exception:
        pass


def _force_axes_dark(axes: Sequence[Any]) -> None:
    """Paint every viewbox dark — do not trust create_plot's odd-row default."""
    for ax in axes:
        vb = getattr(ax, "vb", None)
        if vb is None:
            continue
        try:
            vb.setBackgroundColor(TV_BG)
        except Exception:
            pass
        try:
            vb.state["background"] = TV_BG
        except Exception:
            pass


def _bars_frame(bars: BarSeries) -> pd.DataFrame:
    idx = pd.to_datetime(np.asarray(bars.ts_ms, dtype=np.int64), unit="ms", utc=True)
    vol = bars.volume if bars.volume is not None else np.zeros(len(bars.ts_ms))
    return pd.DataFrame(
        {
            "Open": np.asarray(bars.open, dtype=float),
            "Close": np.asarray(bars.close, dtype=float),
            "High": np.asarray(bars.high, dtype=float),
            "Low": np.asarray(bars.low, dtype=float),
            "Volume": np.asarray(vol, dtype=float),
        },
        index=idx,
    )


def _equity_frame(result: SimResult) -> pd.DataFrame:
    eq = result.equity
    if eq is None or len(eq) == 0:
        return pd.DataFrame(columns=["equity"])
    out = eq.copy()
    if "ts_ms" in out.columns:
        out = out.set_index(
            pd.to_datetime(out["ts_ms"].to_numpy(dtype=np.int64), unit="ms", utc=True)
        )
    if "equity" not in out.columns:
        raise ValueError("SimResult.equity must contain an 'equity' column")
    return out[["equity"]].astype(float)


def _realized_equity_frame(
    result: SimResult, bar_index: pd.DatetimeIndex
) -> pd.DataFrame:
    """Step equity: flat while open, jumps only when a trade (or leg) realizes PnL.

    Built from closed-trade ``realized_pnl`` so the chart matches “wallet after exits”,
    not mark-to-market wiggles from open positions.
    """
    if bar_index is None or len(bar_index) == 0:
        return pd.DataFrame(columns=["equity"])
    start = float(result.starting_equity)
    # Event list: (timestamp, delta). One jump per closed trade at its exit time.
    events: list[tuple[pd.Timestamp, float]] = []
    for t in result.trades:
        ts = pd.Timestamp(int(t.exit_ts_ms), unit="ms", tz="UTC")
        if bar_index.tz is None:
            ts = ts.tz_localize(None)
        else:
            ts = ts.tz_convert(bar_index.tz)
        events.append((ts, float(t.realized_pnl)))
    events.sort(key=lambda x: x[0])

    # Walk bar timeline with forward-filled realized wallet.
    eq = np.empty(len(bar_index), dtype=float)
    wallet = start
    j = 0
    for i, t in enumerate(bar_index):
        while j < len(events) and events[j][0] <= t:
            wallet += events[j][1]
            j += 1
        eq[i] = wallet
    # Any exits after the last plotted bar still belong in the final level if we
    # ever extend the window; for the clipped view, stop at last bar.
    return pd.DataFrame({"equity": eq}, index=bar_index)


def _clip_window(
    df: pd.DataFrame,
    eq: pd.DataFrame,
    trades: Sequence[Trade],
    timeframe_ms: int,
    max_bars: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    # max_bars <= 0 → full period (no clip).
    if max_bars is None or int(max_bars) <= 0 or len(df) <= int(max_bars):
        return df, eq
    max_bars = int(max_bars)
    if trades:
        lo = min(t.entry_ts_ms for t in trades)
        hi = max(t.exit_ts_ms for t in trades)
        pad = int(timeframe_ms) * 50
        # pandas 3: Index.astype("int64") is not reliable ns→ms; use datetime64[ns]
        ts = (
            df.index.to_numpy(dtype="datetime64[ns]").astype("int64") // 1_000_000
        ).astype(np.int64)
        clipped = df.loc[(ts >= lo - pad) & (ts <= hi + pad)]
        df = clipped if len(clipped) else df.iloc[-max_bars:]
        if len(df) > max_bars:
            df = df.iloc[-max_bars:]
    else:
        df = df.iloc[-max_bars:]
    if len(eq):
        eq = eq.loc[df.index[0] : df.index[-1]]
    return df, eq


def _trades_in_window(
    trades: Sequence[Trade], index: pd.DatetimeIndex
) -> list[Trade]:
    """Keep only trades that intersect the plotted candle window."""
    if not len(index) or not trades:
        return list(trades)
    lo = int(pd.Timestamp(index[0]).value // 10**6)
    hi = int(pd.Timestamp(index[-1]).value // 10**6)
    return [
        t
        for t in trades
        if not (int(t.exit_ts_ms) < lo or int(t.entry_ts_ms) > hi)
    ]


def _snap(ts_ms: int, index: pd.DatetimeIndex) -> pd.Timestamp:
    """Snap a trade timestamp onto the nearest candle open (fixes floating markers)."""
    return index[_bar_i(ts_ms, index)]


def _bar_i(ts_ms: int, index: pd.DatetimeIndex) -> int:
    """Candle integer index for Finplot primitives.

    Finplot ``add_rect`` / ``add_line`` / ``add_text`` break on pandas Timestamps
    (``Series.astype('int64')`` is no longer nanoseconds), collapsing rectangles to
    ~0.01 width so take-profit / stop-loss zones look missing. Integer bar indices
    bypass that path (``_pdtime2index`` treats values ``< 1e7`` as already indexed).
    """
    t = pd.Timestamp(int(ts_ms), unit="ms", tz="UTC")
    if index.tz is None:
        t = t.tz_localize(None)
    else:
        t = t.tz_convert(index.tz)
    loc = int(index.get_indexer([t], method="nearest")[0])
    if loc < 0:
        return 0
    return loc


def _ensure_span_i(i0: int, i1: int, n: int) -> tuple[int, int]:
    """Guarantee a non-zero horizontal span so same-bar trades still draw a zone."""
    i0 = max(0, min(int(i0), n - 1))
    i1 = max(0, min(int(i1), n - 1))
    if i1 > i0:
        return i0, i1
    return i0, min(i0 + 1, n - 1)


def _index_trades_by_entry_bar(
    trades: Sequence[Trade],
    index: pd.DatetimeIndex,
) -> dict[int, list[Trade]]:
    """Map candle bar index → trades that **opened** on that bar (for click inspect)."""
    out: dict[int, list[Trade]] = {}
    if not trades or len(index) == 0:
        return out
    for t in trades:
        i = int(_bar_i(t.entry_ts_ms, index))
        out.setdefault(i, []).append(t)
    for lst in out.values():
        lst.sort(key=lambda t: int(t.trade_id))
    return out


def _click_x_to_bar_index(x: Any, index: pd.DatetimeIndex) -> int | None:
    """Snap a finplot click X (bar index or timestamp-ish) to a candle integer index."""
    if index is None or len(index) == 0:
        return None
    n = len(index)
    try:
        xf = float(x)
    except Exception:
        return None
    # Common case: finplot already gives the integer bar index.
    if 0 <= xf < n and abs(xf - round(xf)) < 0.51:
        return int(round(xf))
    # Large numbers are usually milliseconds (or ns) wall times.
    if xf > 1e11:
        ms = int(xf // 1_000_000) if xf > 1e14 else int(xf)
        return int(_bar_i(ms, index))
    # Clamp faint out-of-range drags.
    return max(0, min(n - 1, int(round(xf))))


# Prediction / signal-meta keys shown first in the trade inspect popup.
_PRIMARY_PRED_KEYS: tuple[str, ...] = (
    "pred_mean",
    "prediction",
    "p_hat",
    "score",
    "edge",
    "confidence_pct",
    "risk_pct",
    "actual_risk_pct",
)
# Secondary sizing/book context for LLM and similar packs.
_SECONDARY_PRED_KEYS: tuple[str, ...] = (
    "abs_mean",
    "size_mult",
    "strength_size_mult",
    "time_size_mult",
    "book_idx",
    "confidence_source",
)


def _meta_lookup(
    mapping: Mapping[int, Any] | Any | None,
    *keys: int,
) -> Any | None:
    """Look up by trade_id / entry_ts_ms on a dict, Series index, or similar."""
    if mapping is None:
        return None
    for key in keys:
        try:
            if hasattr(mapping, "index") and hasattr(mapping, "__getitem__"):
                # pandas Series
                try:
                    if key in mapping.index:
                        return mapping[key]
                except Exception:
                    pass
                try:
                    return mapping.loc[key]
                except Exception:
                    pass
            if isinstance(mapping, Mapping) and key in mapping:
                return mapping[key]
            # string keys in JSON-loaded maps
            sk = str(int(key))
            if isinstance(mapping, Mapping) and sk in mapping:
                return mapping[sk]
        except Exception:
            continue
    return None


def _merge_trade_display_meta(
    t: Trade,
    *,
    predictions: Mapping[int, float] | Any | None = None,
    prediction_name: str = "pred_mean",
    trade_annotations: Mapping[int, Mapping[str, Any] | float] | None = None,
) -> dict[str, Any]:
    """Trade.meta + optional plot overlays (annotations / predictions)."""
    meta: dict[str, Any] = dict(getattr(t, "meta", None) or {})
    if trade_annotations:
        extra = _meta_lookup(
            trade_annotations, int(t.trade_id), int(t.entry_ts_ms)
        )
        if extra is not None:
            if isinstance(extra, Mapping):
                meta.update(dict(extra))
            else:
                try:
                    meta[str(prediction_name or "pred_mean")] = float(extra)
                except (TypeError, ValueError):
                    meta[str(prediction_name or "pred_mean")] = extra
    if predictions is not None:
        p = _meta_lookup(predictions, int(t.entry_ts_ms), int(t.trade_id))
        if p is not None:
            try:
                meta[str(prediction_name or "pred_mean")] = float(p)
            except (TypeError, ValueError):
                meta[str(prediction_name or "pred_mean")] = p
    return meta


def _format_meta_value(key: str, value: Any) -> str | None:
    """One ``key=value`` fragment for the inspect line; None if unusable."""
    if value is None:
        return None
    k = str(key)
    if k == "book_idx":
        try:
            return f"book={int(value)}"
        except (TypeError, ValueError):
            return f"book={value}"
    try:
        f = float(value)
    except (TypeError, ValueError):
        s = str(value).strip()
        return f"{k}={s}" if s else None
    if not np.isfinite(f):
        return None
    if k in ("confidence_pct", "risk_pct", "actual_risk_pct") or k.endswith("_pct"):
        return f"{k}={f:.2f}%"
    if k in _PRIMARY_PRED_KEYS or k.endswith("_mean") or k in ("edge", "p_hat", "score"):
        return f"{k}={f:+.4f}"
    if abs(f) >= 1000 or (abs(f) > 0 and abs(f) < 1e-3):
        return f"{k}={f:.6g}"
    return f"{k}={f:.4g}"


def _prediction_detail_lines(
    meta: Mapping[str, Any],
    *,
    prediction_keys: Sequence[str] | None = None,
    prediction_name: str = "pred_mean",
) -> list[str]:
    """Lines appended under entry/exit for model score + size context."""
    if not meta:
        return []
    if prediction_keys is not None:
        keys = [str(k) for k in prediction_keys]
    else:
        # Prefer caller alias first so overlays land on the main line.
        name = str(prediction_name or "pred_mean")
        keys = []
        for k in (name, *_PRIMARY_PRED_KEYS, *_SECONDARY_PRED_KEYS):
            if k not in keys:
                keys.append(k)
        # Any remaining numeric/string meta not already listed is ignored here.
    shown: list[str] = []
    seen: set[str] = set()
    for k in keys:
        if k in seen or k not in meta:
            continue
        frag = _format_meta_value(k, meta[k])
        if frag is None:
            continue
        seen.add(k)
        shown.append(frag)
    if not shown:
        return []
    return [f"  {'  '.join(shown)}"]


def _format_trade_detail(
    t: Trade,
    *,
    n: int = 0,
    predictions: Mapping[int, float] | Any | None = None,
    prediction_name: str = "pred_mean",
    trade_annotations: Mapping[int, Mapping[str, Any] | float] | None = None,
    prediction_keys: Sequence[str] | None = None,
) -> str:
    """Multi-line block for one trade in the click-inspect panel."""
    side = "LONG" if int(t.side) > 0 else "SHORT"
    pnl = float(t.realized_pnl)
    qty = float(getattr(t, "qty", 0.0) or 0.0)
    notional = abs(qty * float(t.entry_price))
    pct = (pnl / notional * 100.0) if notional > 0 else 0.0
    reason = str(getattr(t, "exit_reason", "") or "") or "exit"
    hold = int(getattr(t, "hold_bars", 0) or 0)
    entry = float(t.entry_price)
    exit_px = float(t.exit_price)
    stop = float(t.stop_price)
    qty_s = f"{qty:.4g}" if qty else "?"
    lines = [
        f"#{n}  id={int(t.trade_id)}  {side}  {reason}",
        f"  hold={hold} bars  qty={qty_s}",
        f"  entry={entry:.6g}  exit={exit_px:.6g}  stop={stop:.6g}",
        f"  pnl={pnl:+.4f} USDT ({pct:+.3f}%)  "
        f"fees={float(t.fees):.4f}  funding={float(t.funding):.4f}",
    ]
    meta = _merge_trade_display_meta(
        t,
        predictions=predictions,
        prediction_name=prediction_name,
        trade_annotations=trade_annotations,
    )
    lines.extend(
        _prediction_detail_lines(
            meta,
            prediction_keys=prediction_keys,
            prediction_name=prediction_name,
        )
    )
    ladder = _tp_ladder(t)
    if ladder:
        bits = []
        for lab, px, _frac in ladder:
            bits.append(f"{lab or 'tp'}={float(px):.6g}")
        lines.append(f"  targets: {', '.join(bits)}")
    return "\n".join(lines)


def _trades_detail_text(
    trades: Sequence[Trade],
    *,
    bar_ts: Any = None,
    bar_i: int | None = None,
    predictions: Mapping[int, float] | Any | None = None,
    prediction_name: str = "pred_mean",
    trade_annotations: Mapping[int, Mapping[str, Any] | float] | None = None,
    prediction_keys: Sequence[str] | None = None,
) -> str:
    """Full body for the entry-bar trade inspect dialog."""
    header_bits = ["entry candle trade details"]
    if bar_i is not None:
        header_bits.append(f"bar_i={bar_i}")
    if bar_ts is not None:
        try:
            header_bits.append(str(pd.Timestamp(bar_ts)))
        except Exception:
            header_bits.append(str(bar_ts))
    header_bits.append(f"n={len(trades)}")
    chunks = ["  |  ".join(header_bits), "-" * 60]
    for k, t in enumerate(trades, start=1):
        chunks.append(
            _format_trade_detail(
                t,
                n=k,
                predictions=predictions,
                prediction_name=prediction_name,
                trade_annotations=trade_annotations,
                prediction_keys=prediction_keys,
            )
        )
        chunks.append("")
    chunks.append(
        "Click another entry candle to inspect. Empty / non-entry bars open full metrics."
    )
    return "\n".join(chunks).rstrip() + "\n"


# --------------------------------------------------------------------------------------
# Equity panel
# --------------------------------------------------------------------------------------


def _plot_equity(
    fplt: Any,
    ax: Any,
    eq: pd.DataFrame,
    *,
    relative_equity: bool,
    curve_label: str = "Equity",
) -> None:
    if eq is None or len(eq) == 0:
        fplt.add_legend("Equity: (no curve)", ax=ax)
        return

    series = eq["equity"].astype(float)
    start = float(series.iloc[0]) if float(series.iloc[0]) != 0 else 1.0
    plot_y = series / start if relative_equity else series
    ylabel = "Equity (x start)" if relative_equity else "Equity (USDT)"

    peak_curve = series.cummax()
    dd_frac = (peak_curve - series) / peak_curve.replace(0, np.nan)
    dd_frac = dd_frac.fillna(0.0)
    i_peak = int(series.values.argmax())
    i_final = len(series) - 1
    i_dd = int(dd_frac.values.argmax()) if len(dd_frac) else 0

    fplt.plot(
        plot_y.index, plot_y.values, ax=ax, color=COLOR_EQUITY, width=2, legend=curve_label
    )
    hw = peak_curve / start if relative_equity else peak_curve
    fplt.plot(
        hw.index, hw.values, ax=ax, color="#546e7a", width=1, style="-",
        legend="Peak (high-water)",
    )

    def _pt(i: int) -> tuple[pd.Timestamp, float]:
        return plot_y.index[i], float(plot_y.iloc[i])

    t_peak, y_peak = _pt(i_peak)
    t_final, y_final = _pt(i_final)
    t_dd, y_dd = _pt(i_dd)
    dd_pct = float(dd_frac.iloc[i_dd]) * 100.0

    fplt.plot(
        [t_peak], [y_peak], ax=ax, color=COLOR_PEAK, style="o", width=2,
        legend=f"Peak ({y_peak:,.2f})" if not relative_equity else f"Peak ({y_peak:.3f}x)",
    )
    fplt.plot(
        [t_final], [y_final], ax=ax, color=COLOR_FINAL, style="o", width=2,
        legend=(
            f"Final ({y_final:,.2f})" if not relative_equity else f"Final ({y_final:.3f}x)"
        ),
    )
    fplt.plot(
        [t_dd], [y_dd], ax=ax, color=COLOR_MAX_DD, style="o", width=2,
        legend=f"Max drawdown (-{dd_pct:.2f}%)",
    )
    fplt.add_legend(f"{ylabel}  |  start={start:,.2f}  |  {curve_label}", ax=ax)


# --------------------------------------------------------------------------------------
# TradingView-style trades
# --------------------------------------------------------------------------------------


def _tp_ladder(t: Trade) -> list[tuple[str, float, float | None]]:
    """Return ``(label, price, qty_fraction|None)`` for every take-profit level to draw.

    Prefers the planned ladder frozen on the trade at open (``tp_levels``). Falls back to
    ``target_price`` and any take-profit fill prices recorded in ``legs``.
    """
    out: list[tuple[str, float, float | None]] = []
    seen: set[float] = set()

    def _add(label: str, price: float, frac: float | None) -> None:
        key = round(float(price), 10)
        if key in seen or not np.isfinite(price) or price <= 0:
            return
        seen.add(key)
        out.append((str(label), float(price), frac))

    for item in getattr(t, "tp_levels", ()) or ():
        if len(item) >= 3:
            _add(str(item[0]), float(item[1]), float(item[2]))
        elif len(item) == 2:
            _add(str(item[0]), float(item[1]), None)

    if not out and t.target_price is not None:
        _add("tp", float(t.target_price), 1.0)

    for item in getattr(t, "legs", ()) or ():
        if len(item) < 4:
            continue
        label, _ts, _qty, price = item[0], item[1], item[2], item[3]
        if _looks_like_tp_label(str(label)):
            _add(str(label), float(price), None)

    # Sort near→far in the favourable direction.
    side = int(t.side)
    entry = float(t.entry_price)
    out.sort(key=lambda row: side * (row[1] - entry))
    return out


def _looks_like_tp_label(label: str) -> bool:
    s = label.lower()
    if "stop" in s or "liq" in s or "hold" in s or "timeout" in s or "trail" in s:
        return False
    return "tp" in s or "target" in s or s.startswith("take")


def _add_zone_rect(
    fplt: Any,
    p0: tuple[Any, float],
    p1: tuple[Any, float],
    color: tuple[int, int, int, int] | str,
    *,
    ax: Any,
) -> Any:
    """Translucent take-profit / stop-loss fill with **no** white ROI border."""
    rect = fplt.add_rect(p0, p1, color=color, ax=ax)
    try:
        import pyqtgraph as pg

        pen = pg.mkPen(None)
        rect.setPen(pen)
        rect.currentPen = pen
        rect.pen = pen
        # Hide RectROI scale handles if any.
        for h in list(getattr(rect, "handles", []) or []):
            try:
                h["item"].hide()
            except Exception:
                pass
    except Exception:
        pass
    return rect


def _trade_won(t: Trade) -> bool:
    return float(t.realized_pnl) > 0


def _trade_price_span(t: Trade) -> tuple[float, float]:
    """Min/max price touched by the trade annotation (entry, exit, stop, TPs)."""
    pts = [float(t.entry_price), float(t.exit_price), float(t.stop_price)]
    for _lab, px, _frac in _tp_ladder(t):
        pts.append(float(px))
    pts = [p for p in pts if np.isfinite(p) and p > 0]
    if not pts:
        p = float(t.entry_price) if np.isfinite(t.entry_price) else 0.0
        return p, p
    return float(min(pts)), float(max(pts))


def _trade_outcome_tag(t: Trade) -> str:
    """Readable summary for chart text (green/red via colour, not the word)."""
    side_txt = "LONG" if int(t.side) > 0 else "SHORT"
    reason = str(getattr(t, "exit_reason", "") or "") or "exit"
    hold = int(getattr(t, "hold_bars", 0) or 0)
    pnl = float(t.realized_pnl)
    qty = float(getattr(t, "qty", 0.0) or 0.0)
    notional = abs(qty * float(t.entry_price))
    pct = (pnl / notional * 100.0) if notional > 0 else 0.0
    qty_s = f"{qty:.4g}" if qty else "?"
    return (
        f" {side_txt} {reason}  hold={hold}  qty={qty_s}  "
        f"pnl={pnl:+.2f} USDT ({pct:+.2f}%)"
    )


def _trade_level_pcts(t: Trade) -> tuple[float, tuple[float, ...]]:
    """Signed stop-loss % and take-profit % ladder relative to entry (side-aware)."""
    entry = float(t.entry_price)
    side = float(int(t.side))
    if not np.isfinite(entry) or entry <= 0 or side == 0:
        return 0.0, ()
    r = int(_LEVEL_PCT_ROUND)
    sl = round((float(t.stop_price) / entry - 1.0) * side * 100.0, r)
    tps: list[float] = []
    for _lab, px, _frac in _tp_ladder(t):
        tps.append(round((float(px) / entry - 1.0) * side * 100.0, r))
    return sl, tuple(tps)


def _chart_levels_policy(
    trades: Sequence[Trade],
) -> tuple[bool, str]:
    """Whether take-profit / stop-loss % tags belong on the chart.

    Returns ``(show_level_pct_text, metrics_line)``.
    When every trade uses the same percentages (within rounding), hide those tags
    on the chart and document them once in the metrics window only.
    """
    if not trades:
        return False, "levels: (no trades)"
    sigs = {_trade_level_pcts(t) for t in trades}
    if len(sigs) == 1:
        sl, tps = next(iter(sigs))
        bits = [f"SL {sl:+.2f}%"]
        if tps:
            bits.extend(f"TP{i} {p:+.2f}%" for i, p in enumerate(tps, start=1))
        else:
            bits.append("TP (none)")
        return False, "levels (constant — chart tags omitted): " + "  |  ".join(bits)
    return True, "levels: mixed across trades (TP/SL % shown once per unique level)"


def _level_label_side(kind: str, side: int) -> bool:
    """Whether a level label draws *above* its price line (True) or below (False).

    Long: take-profit above, stop-loss below. Short: take-profit below, stop-loss above.
    """
    long = int(side) > 0
    k = str(kind or "").strip().lower()
    if k in ("tp", "target", "take_profit"):
        return long
    if k in ("sl", "stop", "stop_loss"):
        return not long
    if k in ("entry", "side", "long", "short"):
        return long
    return long


def _text_anchor_above(above: bool) -> tuple[float, float]:
    """PyQtGraph: anchor is the text corner sitting on the point.

    * ``(0, 1)`` bottom-left → text grows upward (above the line).
    * ``(0, 0)`` top-left → text grows downward (below the line).
    """
    return (0.0, 1.0) if above else (0.0, 0.0)


def _qpointf(x: float, y: float) -> Any:
    try:
        from PyQt6.QtCore import QPointF  # type: ignore
    except ImportError:
        try:
            from PyQt5.QtCore import QPointF  # type: ignore
        except ImportError:
            from PySide6.QtCore import QPointF  # type: ignore
    return QPointF(float(x), float(y))


def _item_set_price(
    ax: Any,
    item: Any,
    x: float,
    price_y: float,
) -> None:
    """Place text at bar ``x`` and **price** ``price_y`` (same path as finplot.add_text)."""
    y = float(price_y)
    vb = getattr(ax, "vb", None)
    yscale = getattr(vb, "yscale", None) if vb is not None else None
    if yscale is not None and hasattr(yscale, "invxform"):
        try:
            y = float(yscale.invxform(float(price_y)))
        except Exception:
            y = float(price_y)
    try:
        item.setPos(float(x), float(y))
    except Exception:
        pass


def _select_outcome_trades(
    trades: Sequence[Trade],
    *,
    max_n: int = _LABEL_MAX_OUTCOMES,
) -> list[Trade]:
    """Cap how many outcome tags we create (prefer most recent closes)."""
    if not trades:
        return []
    if int(max_n) <= 0 or len(trades) <= int(max_n):
        return list(trades)
    ordered = sorted(trades, key=lambda t: (int(t.exit_ts_ms), int(t.trade_id)))
    return list(ordered[-int(max_n) :])


@dataclass
class _OutcomeAnno:
    """One chart outcome line: a full trade tag or a collapse summary."""

    text: str
    color: str
    above: bool
    entry_i: int
    price: float
    order: int


def _build_outcome_annotations(
    trades: Sequence[Trade],
    index: pd.DatetimeIndex,
    *,
    max_full: int = _LABEL_CLUSTER_MAX_FULL,
) -> list[_OutcomeAnno]:
    """Cluster nearby entry bars; pile tags; collapse long clusters to +N more."""
    if not trades or len(index) == 0:
        return []
    ordered = sorted(trades, key=lambda t: (int(t.entry_ts_ms), int(t.trade_id)))
    nearby = max(1, int(np.ceil(float(_LABEL_NEARBY_BARS))))
    clusters: list[list[Trade]] = []
    for t in ordered:
        i = int(_bar_i(t.entry_ts_ms, index))
        if clusters:
            prev_i = int(_bar_i(clusters[-1][-1].entry_ts_ms, index))
            if abs(i - prev_i) <= nearby:
                clusters[-1].append(t)
                continue
        clusters.append([t])

    annos: list[_OutcomeAnno] = []
    for cl in clusters:
        full = cl[: max(1, int(max_full))]
        rest = cl[len(full) :]
        for t in full:
            won = _trade_won(t)
            i = int(_bar_i(t.entry_ts_ms, index))
            entry = float(t.entry_price)
            annos.append(
                _OutcomeAnno(
                    text=_trade_outcome_tag(t),
                    color=COLOR_WIN if won else COLOR_LOSS,
                    above=bool(won),
                    entry_i=i,
                    price=entry,
                    order=int(t.trade_id),
                )
            )
        if rest:
            n_more = len(rest)
            last = rest[-1]
            i = int(_bar_i(last.entry_ts_ms, index))
            n_win = sum(1 for t in rest if _trade_won(t))
            above = n_win >= (n_more - n_win)
            color = COLOR_WIN if above else COLOR_LOSS
            entry = float(np.mean([float(t.entry_price) for t in rest]))
            annos.append(
                _OutcomeAnno(
                    text=f" +{n_more} more entries",
                    color=color,
                    above=above,
                    entry_i=i,
                    price=entry,
                    order=int(last.trade_id) + 10_000,
                )
            )
    return annos


@dataclass
class _PackLabel:
    """One finplot/pyqtgraph text item tracked for zoom-adaptive packing."""

    item: Any
    x: float
    y_ref: float  # price units (not invxform)
    above: bool
    kind: str  # "outcome" | "level"
    order: int
    width_chars: int = 12


class AdaptiveLabelBoard:
    """Pile outcome tags at entry bars with a non-zero floor step; pack level tags.

    step_y is derived from the view when possible, but never collapses to ~0 so
    consecutive entries stay on distinct rows. Deferred + range-change relayout.
    """

    def __init__(self, ax: Any) -> None:
        self.ax = ax
        self.labels: list[_PackLabel] = []
        self._hooked = False
        self._busy = False
        self._deferred = False

    def add(
        self,
        item: Any,
        *,
        above: bool,
        kind: str = "level",
        order: int = 0,
        text: str = "",
        price_y: float | None = None,
    ) -> None:
        if item is None:
            return
        try:
            p = item.pos()
            x = float(p.x())
            # Prefer explicit price; item.pos().y is already invxform'd.
            if price_y is not None and np.isfinite(price_y):
                y_ref = float(price_y)
            else:
                y_ref = float(p.y())
        except Exception:
            return
        self.labels.append(
            _PackLabel(
                item=item,
                x=x,
                y_ref=y_ref,
                above=bool(above),
                kind=str(kind or "level"),
                order=int(order),
                width_chars=max(4, len(str(text) or "")),
            )
        )
        self._ensure_hook()

    def _ensure_hook(self) -> None:
        if self._hooked:
            return
        vb = getattr(self.ax, "vb", None)
        if vb is not None and hasattr(vb, "sigRangeChanged"):
            try:
                vb.sigRangeChanged.connect(self.relayout)
                self._hooked = True
            except Exception:
                pass
        # First paint often has zero-height viewbox; schedule a post-event layout.
        if not self._deferred:
            self._deferred = True
            try:
                from pyqtgraph.Qt import QtCore

                QtCore.QTimer.singleShot(0, self.relayout)
                QtCore.QTimer.singleShot(50, self.relayout)
            except Exception:
                pass

    def _step_y_price(self) -> float:
        """Row spacing in **price** units, floored so stacking is always visible."""
        y_span = 0.0
        px_h = 0.0
        ref = 1.0
        vb = getattr(self.ax, "vb", None)
        if vb is not None:
            try:
                if hasattr(vb, "viewRange"):
                    yr = vb.viewRange()[1]
                    y_span = abs(float(yr[1]) - float(yr[0]))
                    ref = max(abs(float(yr[0])), abs(float(yr[1])), 1.0)
            except Exception:
                pass
            try:
                if hasattr(vb, "height"):
                    px_h = float(vb.height())
            except Exception:
                pass
            if px_h > 1.0 and y_span > 0:
                step = y_span / px_h * float(_LABEL_LINE_PX + _LABEL_GAP_PX)
            elif hasattr(vb, "mapToView"):
                try:
                    p0 = vb.mapToView(_qpointf(0.0, 0.0))
                    p1 = vb.mapToView(
                        _qpointf(0.0, float(_LABEL_LINE_PX + _LABEL_GAP_PX))
                    )
                    step = abs(float(p1.y()) - float(p0.y()))
                except Exception:
                    step = 0.0
            else:
                step = 0.0
        else:
            # Headless tests: ~0.12 price units per row if price≈100.
            step = float(_LABEL_LINE_PX + _LABEL_GAP_PX) * 0.12

        if self.labels:
            ref = max(ref, max(abs(L.y_ref) for L in self.labels), 1.0)
        floor = max(
            ref * float(_LABEL_STEP_PRICE_FRAC),
            y_span * float(_LABEL_STEP_YSPAN_FRAC) if y_span > 0 else 0.0,
            1e-6,
        )
        return max(float(step), float(floor))

    def _nearby_x(self) -> float:
        vb = getattr(self.ax, "vb", None)
        if vb is not None and hasattr(vb, "mapToView"):
            try:
                p0 = vb.mapToView(_qpointf(0.0, 0.0))
                p1 = vb.mapToView(_qpointf(float(_LABEL_CLUSTER_X_PX), 0.0))
                return max(abs(float(p1.x()) - float(p0.x())), float(_LABEL_NEARBY_BARS))
            except Exception:
                pass
        return float(_LABEL_NEARBY_BARS)

    def relayout(self, *_args: Any, **_kwargs: Any) -> None:
        if self._busy or not self.labels:
            return
        self._busy = True
        try:
            step_y = self._step_y_price()
            nearby_x = self._nearby_x()
            outcomes = [L for L in self.labels if L.kind == "outcome"]
            levels = [L for L in self.labels if L.kind != "outcome"]

            for above in (True, False):
                group = [L for L in outcomes if L.above is above]
                group.sort(key=lambda L: (float(L.x), int(L.order)))
                clusters: list[list[_PackLabel]] = []
                for L in group:
                    if (
                        clusters
                        and abs(float(L.x) - float(clusters[-1][-1].x)) <= nearby_x
                    ):
                        clusters[-1].append(L)
                    else:
                        clusters.append([L])
                for cl in clusters:
                    if above:
                        base = max(float(L.y_ref) for L in cl)
                        for i, L in enumerate(cl):
                            y_price = base + float(i) * step_y
                            _item_set_price(self.ax, L.item, L.x, y_price)
                    else:
                        base = min(float(L.y_ref) for L in cl)
                        for i, L in enumerate(cl):
                            y_price = base - float(i) * step_y
                            _item_set_price(self.ax, L.item, L.x, y_price)

            if not levels:
                return
            half_h = step_y * 0.55
            ordered = sorted(
                levels, key=lambda L: (float(L.x), int(L.order), float(L.y_ref))
            )
            placed: list[tuple[float, float, float]] = []  # x, y_price, half_w
            for L in ordered:
                half_w = max(float(L.width_chars) * 0.35, 3.0)
                y = float(L.y_ref)
                direction = 1.0 if L.above else -1.0
                for _ in range(int(_LABEL_MAX_STACK)):
                    collides = False
                    for cx, cy, hw in placed:
                        if abs(float(L.x) - cx) > (half_w + hw):
                            continue
                        if abs(y - cy) > half_h * 2.0:
                            continue
                        collides = True
                        break
                    if not collides:
                        break
                    y = y + direction * step_y
                _item_set_price(self.ax, L.item, L.x, y)
                placed.append((float(L.x), float(y), half_w))
        finally:
            self._busy = False


def _stack_outcome_ys(
    trades: Sequence[Trade],
    index: pd.DatetimeIndex,
    *,
    step_frac: float = 0.014,
    pad_frac: float = 0.0,
) -> dict[int, float]:
    """Deterministic outcome Y bases (offline tests). Live charts use AdaptiveLabelBoard."""
    if not trades or len(index) == 0:
        return {}
    ordered = sorted(trades, key=lambda t: (int(t.entry_ts_ms), int(t.trade_id)))
    out: dict[int, float] = {}
    last_i_win = -10**9
    last_i_loss = -10**9
    last_y_win: float | None = None
    last_y_loss: float | None = None
    nearby = 1
    for t in ordered:
        won = _trade_won(t)
        i_entry = int(_bar_i(t.entry_ts_ms, index))
        entry = float(t.entry_price) if np.isfinite(t.entry_price) else 0.0
        base_px = max(abs(entry), 1e-9)
        pad = base_px * float(pad_frac)
        step = base_px * float(step_frac)
        tid = int(t.trade_id)
        if won:
            y_base = float(entry + pad)
            if last_y_win is not None and abs(i_entry - last_i_win) <= nearby:
                y = max(y_base, float(last_y_win) + step)
            else:
                y = y_base
            last_i_win = i_entry
            last_y_win = y
            out[tid] = y
        else:
            y_base = float(entry - pad)
            if last_y_loss is not None and abs(i_entry - last_i_loss) <= nearby:
                y = min(y_base, float(last_y_loss) - step)
            else:
                y = y_base
            last_i_loss = i_entry
            last_y_loss = y
            out[tid] = y
    return out


def _add_chart_text(
    fplt: Any,
    board: AdaptiveLabelBoard | None,
    pos: tuple[float | int, float],
    text: str,
    *,
    color: str,
    above: bool,
    ax: Any,
    kind: str = "level",
    order: int = 0,
) -> Any:
    price_y = float(pos[1])
    item = fplt.add_text(
        pos,
        text,
        color=color,
        anchor=_text_anchor_above(above),
        ax=ax,
    )
    if board is not None:
        board.add(
            item,
            above=above,
            kind=kind,
            order=order,
            text=text,
            price_y=price_y,
        )
    return item


def _plot_outcomes(
    fplt: Any,
    board: AdaptiveLabelBoard,
    ax: Any,
    index: pd.DatetimeIndex,
    trades: Sequence[Trade],
) -> None:
    selected = _select_outcome_trades(trades)
    for anno in _build_outcome_annotations(selected, index):
        _add_chart_text(
            fplt,
            board,
            (anno.entry_i, anno.price),
            anno.text,
            color=anno.color,
            above=anno.above,
            ax=ax,
            kind="outcome",
            order=anno.order,
        )


def _selected_trades(
    trades: Sequence[Trade],
    *,
    max_zone_trades: int = 0,
) -> list[Trade]:
    if int(max_zone_trades) <= 0:
        return list(trades)
    return list(trades)[-int(max_zone_trades) :]


def _draw_entry_exit_span(
    fplt: Any,
    ax: Any,
    index: pd.DatetimeIndex,
    t: Trade,
    *,
    width: int = 2,
) -> None:
    """One green/red line: exact entry bar@price → exact exit bar@price."""
    n = len(index)
    if n == 0:
        return
    i0 = int(_bar_i(t.entry_ts_ms, index))
    i1 = int(_bar_i(t.exit_ts_ms, index))
    # Same-bar round-trip still needs a non-zero X so the segment is visible.
    i0, i1 = _ensure_span_i(i0, i1, n)
    entry = float(t.entry_price)
    exit_px = float(t.exit_price)
    if not np.isfinite(entry) or entry <= 0:
        return
    if not np.isfinite(exit_px) or exit_px <= 0:
        exit_px = entry
    color = COLOR_WIN if _trade_won(t) else COLOR_LOSS
    fplt.add_line(
        (i0, entry),
        (i1, exit_px),
        color=color,
        width=int(width),
        style="-",
        ax=ax,
    )
    # Exact bar markers: circle at entry, cross at exit.
    fplt.plot(
        [index[i0]],
        [entry],
        ax=ax,
        color=color,
        style="o",
        width=2,
        legend=None,
    )
    fplt.plot(
        [index[i1]],
        [exit_px],
        ax=ax,
        color=color,
        style="x",
        width=2,
        legend=None,
    )


def _plot_trades_spans(
    fplt: Any,
    ax: Any,
    index: pd.DatetimeIndex,
    trades: Sequence[Trade],
    *,
    max_zone_trades: int = 0,
    draw_outcomes: bool = False,
    half_bars: int = _DEFAULT_LINE_HALF_BARS,
    show_level_pct: bool | None = None,
) -> None:
    """Default overlay: green/red entry→exit price lines on exact bars.

    Optional: outcome text piles (``draw_outcomes``) and unique TP/SL % tags when
    levels are mixed across the sample.
    """
    if not trades or len(index) == 0:
        return
    selected = _selected_trades(trades, max_zone_trades=max_zone_trades)
    board = AdaptiveLabelBoard(ax)
    if show_level_pct is None:
        show_level_pct, _ = _chart_levels_policy(selected)

    for t in selected:
        _draw_entry_exit_span(fplt, ax, index, t, width=2)

    if draw_outcomes:
        _plot_outcomes(fplt, board, ax, index, selected)

    # Only mixed-level % tags (once per unique level); not on every trade.
    if show_level_pct:
        n = len(index)
        half = max(1, int(half_bars))
        seen_levels: set[tuple[int, str, float]] = set()
        for t in selected:
            won = _trade_won(t)
            color = COLOR_WIN if won else COLOR_LOSS
            side = int(t.side)
            i_entry = _bar_i(t.entry_ts_ms, index)
            entry = float(t.entry_price)
            sl_label: str | None = None
            try:
                sl_pct = round(
                    (float(t.stop_price) / entry - 1.0) * 100.0 * float(side),
                    int(_LEVEL_PCT_ROUND),
                )
                key = (side, "sl", sl_pct)
                if key not in seen_levels:
                    seen_levels.add(key)
                    sl_label = f"SL {sl_pct:+.2f}%"
            except Exception:
                sl_label = "SL"
            if sl_label:
                _level_line_cross(
                    fplt,
                    board,
                    ax,
                    index,
                    i_center=i_entry,
                    price=float(t.stop_price),
                    label=sl_label,
                    color=color,
                    half=half,
                    n=n,
                    kind="sl",
                    side=side,
                    show_text=True,
                    order=int(t.trade_id),
                )
            for k, (lab, tp_px, _frac) in enumerate(_tp_ladder(t), start=1):
                raw = str(lab or "").strip()
                if raw.lower().startswith("tp") and raw[2:].isdigit():
                    name = f"TP{raw[2:]}"
                else:
                    name = f"TP{k}"
                tp_label: str | None = None
                try:
                    pct = round(
                        (float(tp_px) / entry - 1.0) * 100.0 * float(side),
                        int(_LEVEL_PCT_ROUND),
                    )
                    key = (side, f"tp{k}", pct)
                    if key not in seen_levels:
                        seen_levels.add(key)
                        tp_label = f"{name} {pct:+.2f}%"
                except Exception:
                    tp_label = name
                if tp_label:
                    _level_line_cross(
                        fplt,
                        board,
                        ax,
                        index,
                        i_center=i_entry,
                        price=float(tp_px),
                        label=tp_label,
                        color=color,
                        half=half,
                        n=n,
                        kind="tp",
                        side=side,
                        show_text=True,
                        order=int(t.trade_id) * 10 + k,
                    )
    if board.labels:
        board.relayout()


def _plot_trades_lines(
    fplt: Any,
    ax: Any,
    index: pd.DatetimeIndex,
    trades: Sequence[Trade],
    *,
    max_zone_trades: int = 0,
    half_bars: int = _DEFAULT_LINE_HALF_BARS,
    show_level_pct: bool | None = None,
    draw_outcomes: bool = False,
) -> None:
    """Alias for entry→exit spans (kept for older call sites)."""
    _plot_trades_spans(
        fplt,
        ax,
        index,
        trades,
        max_zone_trades=max_zone_trades,
        half_bars=half_bars,
        show_level_pct=show_level_pct,
        draw_outcomes=draw_outcomes,
    )


def _level_line_cross(
    fplt: Any,
    board: AdaptiveLabelBoard | None,
    ax: Any,
    index: pd.DatetimeIndex,
    *,
    i_center: int,
    price: float,
    label: str | None,
    color: str,
    half: int,
    n: int,
    kind: str,
    side: int,
    show_text: bool = True,
    order: int = 0,
) -> None:
    """Horizontal segment of ``2*half+1`` bars with a cross at ``i_center``."""
    if not np.isfinite(price) or price <= 0:
        return
    i_center = max(0, min(int(i_center), n - 1))
    i0 = max(0, i_center - half)
    i1 = min(n - 1, i_center + half)
    if i1 <= i0:
        i1 = min(i0 + 1, n - 1)
    fplt.add_line((i0, price), (i1, price), color=color, width=1, style="-", ax=ax)
    fplt.plot(
        [index[i_center]],
        [price],
        ax=ax,
        color=color,
        style="x",
        width=2,
        legend=None,
    )
    if not show_text or not label:
        return
    above = _level_label_side(kind, side)
    _add_chart_text(
        fplt,
        board,
        (i_center, float(price)),
        f" {label}",
        color=color,
        above=above,
        ax=ax,
        kind="level",
        order=order,
    )


def _plot_trades_zones(
    fplt: Any,
    ax: Any,
    index: pd.DatetimeIndex,
    trades: Sequence[Trade],
    *,
    max_zone_trades: int = 0,
    show_level_pct: bool | None = None,
    draw_outcomes: bool = False,
) -> None:
    """Hold box + entry→exit price span (green/red) on exact bars.

    Outcome text piles only when ``draw_outcomes`` is True. Click entry candle
    for trade details.
    """
    if not trades or len(index) == 0:
        return

    selected = _selected_trades(trades, max_zone_trades=max_zone_trades)
    zone_ids = {t.trade_id for t in selected}
    board = AdaptiveLabelBoard(ax)
    if show_level_pct is None:
        show_level_pct, _ = _chart_levels_policy(selected)

    n = len(index)
    seen_levels: set[tuple[int, str, float]] = set()
    for t in trades:
        if t.trade_id not in zone_ids:
            continue
        i0, i1 = _ensure_span_i(
            _bar_i(t.entry_ts_ms, index), _bar_i(t.exit_ts_ms, index), n
        )
        entry = float(t.entry_price)
        exit_px = float(t.exit_price)
        stop = float(t.stop_price)
        ladder = _tp_ladder(t)
        won = _trade_won(t)
        side = int(t.side)
        color = COLOR_WIN if won else COLOR_LOSS
        zone = TV_WIN_ZONE if won else TV_LOSS_ZONE

        y0 = min(entry, exit_px)
        y1 = max(entry, exit_px)
        if abs(y1 - y0) < max(abs(entry) * 1e-4, 1e-9):
            pad = abs(entry) * 0.0015
            y0, y1 = entry - pad, entry + pad
        _add_zone_rect(fplt, (i0, y0), (i1, y1), zone, ax=ax)

        # Same path as lines style: exact entry→exit on price.
        _draw_entry_exit_span(fplt, ax, index, t, width=2)

        if show_level_pct:
            try:
                sl_pct = round(
                    (stop / entry - 1.0) * 100.0 * float(side), int(_LEVEL_PCT_ROUND)
                )
                key = (side, "sl", sl_pct)
                if key not in seen_levels:
                    seen_levels.add(key)
                    fplt.add_line(
                        (i0, stop), (i1, stop), color="#ffffff", width=1, style="--", ax=ax
                    )
                    _add_chart_text(
                        fplt,
                        board,
                        (i0, float(stop)),
                        f" SL {sl_pct:+.2f}%",
                        color=color,
                        above=_level_label_side("sl", side),
                        ax=ax,
                        kind="level",
                        order=int(t.trade_id),
                    )
            except Exception:
                pass
            for k, (label, tp_px, _frac) in enumerate(ladder, start=1):
                name = (
                    label
                    if label and str(label).lower() not in {"tp", "target"}
                    else f"TP{k}"
                )
                try:
                    pct = round(
                        (float(tp_px) / entry - 1.0) * 100.0 * float(side),
                        int(_LEVEL_PCT_ROUND),
                    )
                    key = (side, f"tp{k}", pct)
                    if key not in seen_levels:
                        seen_levels.add(key)
                        fplt.add_line(
                            (i0, float(tp_px)),
                            (i1, float(tp_px)),
                            color="#90caf9",
                            width=1,
                            style="--",
                            ax=ax,
                        )
                        _add_chart_text(
                            fplt,
                            board,
                            (i0, float(tp_px)),
                            f" {name} {pct:+.2f}%",
                            color=color,
                            above=_level_label_side("tp", side),
                            ax=ax,
                            kind="level",
                            order=int(t.trade_id) * 10 + k,
                        )
                except Exception:
                    pass

    if draw_outcomes:
        _plot_outcomes(fplt, board, ax, index, selected)
    if board.labels:
        board.relayout()


# --------------------------------------------------------------------------------------
# Metrics window
# --------------------------------------------------------------------------------------


def _metrics_text(
    result: SimResult,
    metrics: MetricsReport | None,
    *,
    strategy_meta: dict[str, Any] | None = None,
) -> str:
    chunks: list[str] = []
    # Always surface constant take-profit / stop-loss so the chart can omit repeats.
    _, levels_line = _chart_levels_policy(result.trades or ())
    if levels_line:
        chunks.append(levels_line)
        chunks.append("")
    if strategy_meta:
        # Surface live account / botsgeneral bots PnL first when present.
        acct = strategy_meta.get("account") or strategy_meta.get("account_ref")
        bots = strategy_meta.get("bots")
        live_pnl = strategy_meta.get("bots_pnl") or strategy_meta.get("live_pnl")
        if acct or bots or live_pnl:
            chunks.append("bots / account:")
            if acct:
                chunks.append(f"  account: {acct}")
            if bots is not None:
                if isinstance(bots, (list, tuple)):
                    chunks.append(f"  bots: {', '.join(str(b) for b in bots) or '-'}")
                else:
                    chunks.append(f"  bots: {bots}")
            if isinstance(live_pnl, dict):
                for k in (
                    "total_equity",
                    "total_wallet_balance",
                    "total_perp_upl",
                    "error",
                ):
                    if k in live_pnl and live_pnl[k] is not None:
                        chunks.append(f"  {k}: {live_pnl[k]}")
                for p in live_pnl.get("positions") or []:
                    chunks.append(
                        f"  pos {p.get('symbol')} {p.get('side')} "
                        f"size={p.get('size')} upl={p.get('unrealisedPnl')}"
                    )
            elif live_pnl is not None:
                chunks.append(f"  bots_pnl: {live_pnl}")
            chunks.append("")
        try:
            from .report import strategy_details_text

            detail = strategy_details_text(strategy_meta)
            if detail:
                chunks.append(detail)
                chunks.append("")
        except Exception:
            chunks.append("strategy details:")
            for k, v in strategy_meta.items():
                if k in {"bots_pnl", "live_pnl", "bots", "account", "account_ref"}:
                    continue
                chunks.append(f"  {k}: {v}")
            chunks.append("")
    if metrics is not None:
        chunks.append(headline_table(metrics).rstrip())
        chunks.append("")
        chunks.append("backtesting.py-compatible stats:")
        for k, v in metrics.as_backtesting_stats().items():
            chunks.append(f"  {k}: {v}")
        return "\n".join(chunks)
    chunks.append(
        f"run_id={result.run_id}\n"
        f"trades={len(result.trades)}  "
        f"start={result.starting_equity:.2f}  end={result.ending_equity:.2f}\n"
        "(pass metrics=compute_metrics(result) for the full table)"
    )
    return "\n".join(chunks)


def _ensure_qt_app() -> Any:
    try:
        from pyqtgraph.Qt import QtWidgets
    except Exception:
        return None
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _open_info_window(
    text: str,
    *,
    title: str,
    key: str = "metrics",
    width: int = 720,
    height: int = 640,
) -> None:
    """Non-blocking Qt text dialog; same ``key`` replaces content instead of spawning.

    Keys used: ``metrics`` (full report), ``trade_inspect`` (entry-candle click).
    Falls back to print when Qt is unavailable.
    """
    try:
        from pyqtgraph.Qt import QtCore, QtWidgets
    except Exception:
        print(text)
        return

    app = _ensure_qt_app()
    if app is None:
        print(text)
        return

    if not hasattr(_open_info_window, "_by_key"):
        _open_info_window._by_key = {}  # type: ignore[attr-defined]
    by_key: dict[str, Any] = _open_info_window._by_key  # type: ignore[attr-defined]

    # Drop dead refs.
    dead = [k for k, d in by_key.items() if not d.isVisible()]
    for k in dead:
        by_key.pop(k, None)

    existing = by_key.get(key)
    if existing is not None and existing.isVisible():
        box = getattr(existing, "_body", None)
        if box is not None:
            try:
                box.setPlainText(text)
                existing.setWindowTitle(title)
                existing.raise_()
                existing.activateWindow()
                return
            except Exception:
                pass

    if not hasattr(_open_info_window, "_alive"):
        _open_info_window._alive = []  # type: ignore[attr-defined]
    alive: list[Any] = _open_info_window._alive  # type: ignore[attr-defined]
    alive[:] = [d for d in alive if d.isVisible()]
    n = len(alive)

    dlg = QtWidgets.QDialog()
    dlg.setWindowTitle(title)
    dlg.resize(int(width), int(height))
    dlg.move(40 + 36 * n, 40 + 36 * n)
    layout = QtWidgets.QVBoxLayout(dlg)
    box = QtWidgets.QPlainTextEdit()
    box.setReadOnly(True)
    box.setPlainText(text)
    box.setStyleSheet(
        "QPlainTextEdit { background:#131722; color:#d1d4dc; "
        "font-family: Consolas, monospace; }"
    )
    dlg._body = box  # type: ignore[attr-defined]
    layout.addWidget(box)
    btn = QtWidgets.QPushButton("Close")
    btn.clicked.connect(dlg.close)
    layout.addWidget(btn)
    try:
        dlg.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    except Exception:
        pass
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    alive.append(dlg)
    by_key[key] = dlg


def _open_metrics_window(text: str, *, title: str) -> None:
    """Back-compat wrapper around :func:`_open_info_window` for the metrics key."""
    _open_info_window(text, title=title, key="metrics", width=720, height=640)
