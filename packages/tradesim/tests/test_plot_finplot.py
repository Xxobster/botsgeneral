"""Unit tests for Finplot layout helpers (no GUI)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradesim import BarSeries, InstrumentSpec, Side, Signal, simulate
from tradesim.metrics import compute_metrics
from tradesim.research.defaults import (
    research_costs,
    research_margin,
    research_sim,
    research_sizing,
)
from tradesim.research import plot as plot_mod


class _FakeFplt:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.axes: list[object] = []
        self.axis_height_factor: dict = {}
        self.background = "#fff"
        self.foreground = "#000"
        self.candle_bull_color = ""
        self.candle_bull_body_color = ""
        self.candle_bear_color = ""
        self.candle_bear_body_color = ""
        self.cross_hair_color = ""
        self.draw_line_color = ""
        self.legend_border_color = ""
        self.legend_fill_color = ""
        self.legend_text_color = ""
        self.volume_bull_color = ""
        self.volume_bear_color = ""
        self.volume_bull_body_color = ""
        self.volume_neutral_color = ""
        self.odd_plot_background = ""
        self.band_color = None
        self.draw_band_color = None
        self.lod_candles = 0

    def create_plot(self, title, rows=1, **kw):
        self.calls.append(("create_plot", title, rows))
        self.axes = [object() for _ in range(int(rows))]
        return self.axes

    def candlestick_ochl(self, df, ax=None, candle_width=0.6, **kw):
        self.calls.append(("candlestick", len(df), ax, candle_width))

    def plot(self, *args, **kwargs):
        self.calls.append(("plot", kwargs.get("legend"), kwargs.get("style"), kwargs.get("color")))

    def add_legend(self, text, ax=None):
        self.calls.append(("add_legend", text, ax))

    def add_rect(self, p0, p1, color=None, ax=None, interactive=False):
        self.calls.append(("add_rect", p0, p1, color))

    def add_line(self, p0, p1, color=None, width=1, style=None, ax=None, interactive=False):
        self.calls.append(("add_line", p0, p1, color, style))

    def add_text(self, pos, s, color=None, anchor=(0, 0), ax=None):
        self.calls.append(("add_text", pos, s, color))

    def set_time_inspector(self, callback, ax=None, when="click"):
        self.calls.append(("set_time_inspector", when))

    def show(self):
        self.calls.append(("show",))


def _tiny_result():
    n = 40
    tf = 3_600_000
    t0 = 1_700_000_000_000
    ts = np.arange(n, dtype=np.int64) * tf + t0
    o = np.linspace(100, 105, n)
    bars = BarSeries(
        ts_ms=ts, open=o, high=o + 1, low=o - 1, close=o + 0.2,
        timeframe_ms=tf, symbol="TEST",
    )
    sig = [
        Signal(
            ts_ms=int(ts[5]), side=Side.LONG,
            stop_offset=0.05, target_offset=0.05, qty=1.0,
        )
    ]
    inst = InstrumentSpec(
        symbol="TEST", tick_size=0.01, qty_step=0.001,
        min_qty=0.001, min_notional=1.0,
    )
    result = simulate(
        bars=bars, signals=sig, instrument=inst,
        costs=research_costs(), margin=research_margin(),
        sizing=research_sizing(), sim=research_sim(),
        run_id="plot-unit",
    )
    return bars, result


def test_plot_backtest_tv_zones_and_dark_theme(monkeypatch):
    fake = _FakeFplt()
    monkeypatch.setitem(__import__("sys").modules, "finplot", fake)
    monkeypatch.setattr(plot_mod, "_open_metrics_window", lambda *a, **k: None)

    bars, result = _tiny_result()
    metrics = compute_metrics(result)
    view = plot_mod.plot_backtest(
        bars,
        result,
        title="unit",
        show=False,
        metrics=metrics,
        show_metrics_window=True,
        trade_style="zones",
    )
    assert isinstance(view, plot_mod.PlotView)
    assert list(view) == fake.axes
    assert view.ax_equity is fake.axes[0]
    assert view.ax_price is fake.axes[1]
    assert view.extra_axes == []
    assert fake.background == plot_mod.TV_BG
    assert fake.axis_height_factor == {0: plot_mod._EQUITY_HEIGHT, 1: plot_mod._PRICE_HEIGHT}
    kinds = [c[0] for c in fake.calls]
    assert fake.calls[0][2] == 2
    assert "candlestick" in kinds
    assert "add_rect" in kinds
    assert "add_line" in kinds
    assert "add_text" in kinds
    assert "set_time_inspector" in kinds
    texts = " ".join(c[2] for c in fake.calls if c[0] == "add_text")
    assert "TP1 +" in texts or "TP +" in texts
    assert "SL -" in texts
    assert "%" in texts
    assert "LONG" in texts or "SHORT" in texts
    assert "show" not in kinds


def test_plot_backtest_extra_rows_and_on_axes(monkeypatch):
    fake = _FakeFplt()
    monkeypatch.setitem(__import__("sys").modules, "finplot", fake)
    monkeypatch.setattr(plot_mod, "_open_metrics_window", lambda *a, **k: None)

    seen: list[plot_mod.PlotView] = []

    def on_axes(view: plot_mod.PlotView) -> None:
        seen.append(view)
        fake.plot([0, 1], [1, 2], ax=view.extra_axes[0], legend="RSI")

    bars, result = _tiny_result()
    view = plot_mod.plot_backtest(
        bars,
        result,
        title="extra",
        show=False,
        show_metrics_window=False,
        extra_rows=1,
        extra_row_heights=(0.5,),
        on_axes=on_axes,
    )
    assert len(seen) == 1
    assert seen[0] is view
    assert len(view.axes) == 3
    assert len(view.extra_axes) == 1
    assert view.bars_df is not None and len(view.bars_df) > 0
    assert fake.axis_height_factor == {
        0: plot_mod._EQUITY_HEIGHT,
        1: plot_mod._PRICE_HEIGHT,
        2: 0.5,
    }
    assert ("create_plot", "extra", 3) in fake.calls
    assert any(c[0] == "plot" and c[1] == "RSI" for c in fake.calls)


def test_plot_backtest_default_line_style(monkeypatch):
    fake = _FakeFplt()
    monkeypatch.setitem(__import__("sys").modules, "finplot", fake)
    monkeypatch.setattr(plot_mod, "_open_metrics_window", lambda *a, **k: None)

    bars, result = _tiny_result()
    plot_mod.plot_backtest(
        bars, result, title="lines", show=False, show_metrics_window=False
    )
    kinds = [c[0] for c in fake.calls]
    assert "add_line" in kinds
    assert "add_rect" not in kinds


def test_snap_onto_candle_index():
    idx = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
    # 20 minutes after a bar open → snap back to that bar
    ts_ms = int(idx[2].value // 10**6) + 20 * 60_000
    snapped = plot_mod._snap(ts_ms, idx)
    assert snapped == idx[2]


def test_equity_frame_from_result():
    bars, result = _tiny_result()
    eq = plot_mod._equity_frame(result)
    assert "equity" in eq.columns
    assert len(eq) > 0
