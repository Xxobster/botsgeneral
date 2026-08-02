"""Optional Finplot review of a tradesim backtest.

TradingView-inspired layout:

* **top panel** (~20% height) — **realized** equity (steps when trades close; use
  ``equity_mode="mtm"`` for mark-to-market every bar)
* **bottom panel** (~80%) — dark ``#131722`` candlesticks; trades as short horizontal
  lines (±3 bars) with a cross at entry / stop-loss / each take-profit, labelled
  LONG/SHORT, SL, TP1… Colors = green win / red loss. No filled zones; no price legend.
* **metrics window** — full strategy metrics; also reopened by clicking the price chart

Requires: ``pip install tradesim[plot]``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

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
# Legacy filled zones (trade_style="zones" only)
TV_TP_ZONE = (38, 166, 154, 64)
TV_SL_ZONE = (239, 83, 80, 64)

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
    line_half_bars: int = _DEFAULT_LINE_HALF_BARS,
    metrics: MetricsReport | None = None,
    strategy_meta: dict[str, Any] | None = None,
    show: bool = True,
    show_metrics_window: bool = True,
    max_zone_trades: int = 0,
    extra_rows: int = 0,
    extra_row_heights: Sequence[float] | None = None,
    on_axes: OnAxesCallback | None = None,
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
      - ``"lines"`` (default): short horizontal level (±``line_half_bars``) with a
        cross at entry / stop-loss / each take-profit; labels LONG|SHORT, SL, TP1…
        Color is green for winning trades and red for losing trades.
      - ``"zones"``: legacy translucent take-profit / stop-loss rectangles.

    ``max_zone_trades``:
      - ``0`` or negative (default): draw every visible trade
      - positive: only the last N visible trades
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
        )
    else:
        _plot_trades_lines(
            fplt,
            ax_px,
            df.index,
            visible_trades,
            max_zone_trades=max_zone_trades,
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

    def _on_click(_x, _y, _z):
        _open_metrics_window(metrics_text, title=f"Metrics — {title}")

    try:
        fplt.set_time_inspector(_on_click, ax=ax_px, when="click")
    except Exception:
        pass

    if show:
        _ensure_qt_app()
        if show_metrics_window:
            _open_metrics_window(metrics_text, title=f"Metrics — {title}")
        fplt.show()
    elif show_metrics_window:
        _ensure_qt_app()
        _open_metrics_window(metrics_text, title=f"Metrics — {title}")
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


def _plot_trades_lines(
    fplt: Any,
    ax: Any,
    index: pd.DatetimeIndex,
    trades: Sequence[Trade],
    *,
    max_zone_trades: int = 0,
    half_bars: int = _DEFAULT_LINE_HALF_BARS,
) -> None:
    """Short horizontal levels (±half_bars) + cross; green=win, red=loss."""
    if not trades or len(index) == 0:
        return
    if int(max_zone_trades) <= 0:
        selected = list(trades)
    else:
        selected = list(trades)[-int(max_zone_trades) :]

    n = len(index)
    half = max(1, int(half_bars))
    for t in selected:
        color = COLOR_WIN if float(t.realized_pnl) > 0 else COLOR_LOSS
        i_entry = _bar_i(t.entry_ts_ms, index)
        side_txt = "LONG" if int(t.side) > 0 else "SHORT"
        _level_line_cross(
            fplt,
            ax,
            index,
            i_center=i_entry,
            price=float(t.entry_price),
            label=side_txt,
            color=color,
            half=half,
            n=n,
        )
        _level_line_cross(
            fplt,
            ax,
            index,
            i_center=i_entry,
            price=float(t.stop_price),
            label="SL",
            color=color,
            half=half,
            n=n,
        )
        for k, (lab, tp_px, _frac) in enumerate(_tp_ladder(t), start=1):
            raw = str(lab or "").strip()
            if raw.lower().startswith("tp") and raw[2:].isdigit():
                name = f"TP{raw[2:]}"
            else:
                name = f"TP{k}"
            _level_line_cross(
                fplt,
                ax,
                index,
                i_center=i_entry,
                price=float(tp_px),
                label=name,
                color=color,
                half=half,
                n=n,
            )


def _level_line_cross(
    fplt: Any,
    ax: Any,
    index: pd.DatetimeIndex,
    *,
    i_center: int,
    price: float,
    label: str,
    color: str,
    half: int,
    n: int,
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
    # Cross at the exact event bar (finplot scatter; timestamps map correctly).
    fplt.plot(
        [index[i_center]],
        [price],
        ax=ax,
        color=color,
        style="x",
        width=2,
        legend=None,
    )
    fplt.add_text(
        (i_center, price),
        f" {label}",
        color=color,
        anchor=(0, 0.5),
        ax=ax,
    )


def _plot_trades_zones(
    fplt: Any,
    ax: Any,
    index: pd.DatetimeIndex,
    trades: Sequence[Trade],
    *,
    max_zone_trades: int = 0,
) -> None:
    """Legacy translucent take-profit / stop-loss rectangles."""
    if not trades or len(index) == 0:
        return

    if int(max_zone_trades) <= 0:
        zone_ids = {t.trade_id for t in trades}
    else:
        zone_ids = {t.trade_id for t in list(trades)[-int(max_zone_trades) :]}

    n = len(index)
    for t in trades:
        if t.trade_id not in zone_ids:
            continue
        i0, i1 = _ensure_span_i(
            _bar_i(t.entry_ts_ms, index), _bar_i(t.exit_ts_ms, index), n
        )
        entry = float(t.entry_price)
        stop = float(t.stop_price)
        side = int(t.side)
        ladder = _tp_ladder(t)
        sl_pct = ((stop - entry) / entry) * 100.0
        color = COLOR_WIN if float(t.realized_pnl) > 0 else COLOR_LOSS

        if ladder:
            far_tp = ladder[-1][1]
            _add_zone_rect(fplt, (i0, entry), (i1, far_tp), TV_TP_ZONE, ax=ax)
        _add_zone_rect(fplt, (i0, entry), (i1, stop), TV_SL_ZONE, ax=ax)
        fplt.add_line((i0, stop), (i1, stop), color=color, width=1, style="--", ax=ax)
        fplt.add_text(
            (i1, stop),
            f" SL -{abs(sl_pct):.2f}%",
            color=color,
            anchor=(0, 0.5),
            ax=ax,
        )
        for k, (label, tp_px, frac) in enumerate(ladder, start=1):
            if side > 0:
                tp_pct = ((tp_px - entry) / entry) * 100.0
            else:
                tp_pct = ((entry - tp_px) / entry) * 100.0
            fplt.add_line(
                (i0, tp_px), (i1, tp_px), color=color, width=1, style="--", ax=ax
            )
            frac_txt = f" {100.0 * frac:.0f}%" if frac is not None else ""
            name = label if label and label.lower() not in {"tp", "target"} else f"TP{k}"
            fplt.add_text(
                (i1, tp_px),
                f" {name} +{abs(tp_pct):.2f}%{frac_txt}",
                color=color,
                anchor=(0, 0.5),
                ax=ax,
            )
        side_txt = "LONG" if side > 0 else "SHORT"
        fplt.add_text(
            (i0, entry),
            f" {side_txt}",
            color=color,
            anchor=(0, 0.5),
            ax=ax,
        )


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
    if strategy_meta:
        try:
            from .report import strategy_details_text

            detail = strategy_details_text(strategy_meta)
            if detail:
                chunks.append(detail)
                chunks.append("")
        except Exception:
            chunks.append("strategy details:")
            for k, v in strategy_meta.items():
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


def _open_metrics_window(text: str, *, title: str) -> None:
    """Non-blocking Qt dialog with the full metrics report (one per chart)."""
    try:
        from pyqtgraph.Qt import QtCore, QtWidgets
    except Exception:
        print(text)
        return

    app = _ensure_qt_app()
    if app is None:
        print(text)
        return

    if not hasattr(_open_metrics_window, "_alive"):
        _open_metrics_window._alive = []  # type: ignore[attr-defined]
    alive: list[Any] = _open_metrics_window._alive  # type: ignore[attr-defined]
    # Drop closed dialogs so the cascade index stays meaningful.
    alive[:] = [d for d in alive if d.isVisible()]
    n = len(alive)

    dlg = QtWidgets.QDialog()
    dlg.setWindowTitle(title)
    dlg.resize(720, 640)
    # Cascade so multiple charts do not hide each other's metrics under one window.
    dlg.move(40 + 36 * n, 40 + 36 * n)
    layout = QtWidgets.QVBoxLayout(dlg)
    box = QtWidgets.QPlainTextEdit()
    box.setReadOnly(True)
    box.setPlainText(text)
    box.setStyleSheet(
        "QPlainTextEdit { background:#131722; color:#d1d4dc; "
        "font-family: Consolas, monospace; }"
    )
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
