"""Unit tests for Finplot layout helpers (no GUI)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradesim import BarSeries, InstrumentSpec, Side, Signal, Trade, simulate
from tradesim.metrics import compute_metrics
from tradesim.research.defaults import (
    research_costs,
    research_margin,
    research_sim,
    research_sizing,
)
from tradesim.research import plot as plot_mod


class _FakePos:
    def __init__(self, x: float, y: float) -> None:
        self._x = float(x)
        self._y = float(y)

    def x(self) -> float:
        return self._x

    def y(self) -> float:
        return self._y


class _FakeText:
    def __init__(self, pos, s: str, anchor) -> None:
        self._x = float(pos[0])
        self._y = float(pos[1])
        self.s = s
        self.anchor = anchor

    def pos(self) -> _FakePos:
        return _FakePos(self._x, self._y)

    def setPos(self, x, y) -> None:
        self._x = float(x)
        self._y = float(y)


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
        self.texts: list[_FakeText] = []

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
        self.calls.append(("add_text", pos, s, color, anchor))
        item = _FakeText(pos, s, anchor)
        self.texts.append(item)
        return item

    def set_time_inspector(self, callback, ax=None, when="click"):
        self.calls.append(("set_time_inspector", when))

    def set_mouse_callback(self, callback, ax=None, when="click"):
        self.calls.append(("set_mouse_callback", when))

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
    monkeypatch.setattr(plot_mod, "_open_info_window", lambda *a, **k: None)

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
        trade_labels="none",
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
    assert "set_time_inspector" in kinds or "set_mouse_callback" in kinds
    # Default: no outcome tags on chart (tidy).
    texts = " ".join(c[2] for c in fake.calls if c[0] == "add_text")
    assert "hold=" not in texts
    assert "show" not in kinds
    metrics_txt = plot_mod._metrics_text(result, metrics)
    assert "constant" in metrics_txt.lower() or "SL" in metrics_txt


def test_plot_backtest_on_chart_labels(monkeypatch):
    fake = _FakeFplt()
    monkeypatch.setitem(__import__("sys").modules, "finplot", fake)
    monkeypatch.setattr(plot_mod, "_open_info_window", lambda *a, **k: None)

    bars, result = _tiny_result()
    plot_mod.plot_backtest(
        bars,
        result,
        title="labels",
        show=False,
        show_metrics_window=False,
        trade_style="zones",
        trade_labels="on_chart",
    )
    texts = " ".join(c[2] for c in fake.calls if c[0] == "add_text")
    assert "hold=" in texts
    assert "pnl=" in texts
    assert "LONG" in texts or "SHORT" in texts


def test_plot_backtest_extra_rows_and_on_axes(monkeypatch):
    fake = _FakeFplt()
    monkeypatch.setitem(__import__("sys").modules, "finplot", fake)
    monkeypatch.setattr(plot_mod, "_open_info_window", lambda *a, **k: None)

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
    monkeypatch.setattr(plot_mod, "_open_info_window", lambda *a, **k: None)

    bars, result = _tiny_result()
    view = plot_mod.plot_backtest(
        bars, result, title="lines", show=False, show_metrics_window=False
    )
    kinds = [c[0] for c in fake.calls]
    assert "add_line" in kinds
    assert "add_rect" not in kinds
    # Entry→exit price spans (exact bars); green win / red loss.
    span_lines = [c for c in fake.calls if c[0] == "add_line" and c[4] in (None, "-")]
    assert span_lines, "expected solid entry→exit span lines"
    trades = list(view.trades) if view.trades else list(result.trades)
    assert trades
    for t in trades:
        i0 = plot_mod._bar_i(t.entry_ts_ms, view.bars_df.index)
        i1 = plot_mod._bar_i(t.exit_ts_ms, view.bars_df.index)
        i0, i1 = plot_mod._ensure_span_i(i0, i1, len(view.bars_df.index))
        color = plot_mod.COLOR_WIN if t.realized_pnl > 0 else plot_mod.COLOR_LOSS
        match = any(
            c[1] == (i0, float(t.entry_price))
            and c[2] == (i1, float(t.exit_price))
            and c[3] == color
            for c in span_lines
        )
        assert match, f"missing span for trade {t.trade_id}"
    # Markers at entry (o) and exit (x)
    styles = {c[2] for c in fake.calls if c[0] == "plot"}
    assert "o" in styles
    assert "x" in styles


def test_draw_entry_exit_span_same_bar():
    """Same-bar round-trip still draws a visible span to next index."""
    idx = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
    t = Trade(
        trade_id=1,
        symbol="T",
        side=1,
        entry_ts_ms=int(idx[2].value // 10**6),
        entry_price=100.0,
        entry_ref_price=100.0,
        qty=1.0,
        stop_price=95.0,
        target_price=105.0,
        liquidation_price=None,
        leverage=1.0,
        initial_margin=10.0,
        exit_ts_ms=int(idx[2].value // 10**6),
        exit_price=99.0,
        exit_reason="stop_entry_bar",
        hold_bars=0,
        fees=0.1,
        funding=0.0,
        slippage_cost=0.0,
        gross_pnl=-1.0,
        realized_pnl=-1.1,
        return_units=-0.011,
        mae=0.0,
        mfe=0.0,
        ambiguous_intrabar=False,
        resolved_by_touch=False,
        entry_bar_exit=True,
    )
    fake = _FakeFplt()
    plot_mod._draw_entry_exit_span(fake, object(), idx, t)
    lines = [c for c in fake.calls if c[0] == "add_line"]
    assert len(lines) == 1
    assert lines[0][1] == (2, 100.0)
    assert lines[0][2] == (3, 99.0)  # bumped by _ensure_span_i
    assert lines[0][3] == plot_mod.COLOR_LOSS


def test_stack_outcome_ys_wins_above_losses_below():
    """Wins annotate above entry; losses below; consecutive stack."""
    idx = pd.date_range("2024-01-01", periods=20, freq="h", tz="UTC")

    def trade(tid, side, entry, exit_p, stop, pnl, entry_i, exit_i):
        return Trade(
            trade_id=tid,
            symbol="T",
            side=side,
            entry_ts_ms=int(idx[entry_i].value // 10**6),
            entry_price=entry,
            entry_ref_price=entry,
            qty=1.0,
            stop_price=stop,
            target_price=exit_p,
            liquidation_price=None,
            leverage=1.0,
            initial_margin=10.0,
            exit_ts_ms=int(idx[exit_i].value // 10**6),
            exit_price=exit_p,
            exit_reason="target" if pnl > 0 else "stop",
            hold_bars=exit_i - entry_i,
            fees=0.0,
            funding=0.0,
            slippage_cost=0.0,
            gross_pnl=pnl,
            realized_pnl=pnl,
            return_units=pnl / entry,
            mae=0.0,
            mfe=0.0,
            ambiguous_intrabar=False,
            resolved_by_touch=False,
            entry_bar_exit=False,
        )

    win1 = trade(1, 1, 100.0, 110.0, 95.0, 10.0, 2, 5)
    win2 = trade(2, 1, 100.0, 105.0, 95.0, 5.0, 3, 4)  # adjacent entry → stack
    loss1 = trade(3, 1, 100.0, 95.0, 95.0, -5.0, 10, 12)
    ys = plot_mod._stack_outcome_ys([win1, win2, loss1], idx)
    assert ys[1] >= 100.0
    assert ys[2] > ys[1]
    assert ys[3] <= 100.0
    tag = plot_mod._trade_outcome_tag(win1)
    assert "hold=" in tag and "pnl=" in tag and "LONG" in tag


def test_level_label_side_tp_sl_long_short():
    """TP long above; TP short below; SL long below; SL short above."""
    assert plot_mod._level_label_side("tp", 1) is True
    assert plot_mod._level_label_side("sl", 1) is False
    assert plot_mod._level_label_side("tp", -1) is False
    assert plot_mod._level_label_side("sl", -1) is True
    assert plot_mod._text_anchor_above(True) == (0.0, 1.0)
    assert plot_mod._text_anchor_above(False) == (0.0, 0.0)


def test_constant_levels_policy_hides_chart_tags():
    idx = pd.date_range("2024-01-01", periods=10, freq="h", tz="UTC")

    def mk(tid, entry, stop, target):
        return Trade(
            trade_id=tid,
            symbol="T",
            side=1,
            entry_ts_ms=int(idx[tid].value // 10**6),
            entry_price=entry,
            entry_ref_price=entry,
            qty=1.0,
            stop_price=stop,
            target_price=target,
            liquidation_price=None,
            leverage=1.0,
            initial_margin=10.0,
            exit_ts_ms=int(idx[tid + 1].value // 10**6),
            exit_price=target,
            exit_reason="target",
            hold_bars=1,
            fees=0.0,
            funding=0.0,
            slippage_cost=0.0,
            gross_pnl=1.0,
            realized_pnl=1.0,
            return_units=0.01,
            mae=0.0,
            mfe=0.0,
            ambiguous_intrabar=False,
            resolved_by_touch=False,
            entry_bar_exit=False,
        )

    same = [mk(1, 100.0, 98.0, 101.0), mk(2, 200.0, 196.0, 202.0)]  # same ±%
    show, line = plot_mod._chart_levels_policy(same)
    assert show is False
    assert "constant" in line and "SL" in line and "TP1" in line

    mixed = [mk(1, 100.0, 98.0, 101.0), mk(2, 200.0, 190.0, 210.0)]
    show2, line2 = plot_mod._chart_levels_policy(mixed)
    assert show2 is True
    assert "mixed" in line2


def test_adaptive_board_piles_outcomes_at_entry():
    """Nearby entry outcomes stack upward with distinct Y, same X ordering."""
    ax = object()
    board = plot_mod.AdaptiveLabelBoard(ax)
    a = _FakeText((10, 100.0), " LONG A", (0.0, 1.0))
    b = _FakeText((11, 100.0), " LONG B", (0.0, 1.0))
    c = _FakeText((12, 100.0), " LONG C", (0.0, 1.0))
    board.add(a, above=True, kind="outcome", order=1, text=a.s, price_y=100.0)
    board.add(b, above=True, kind="outcome", order=2, text=b.s, price_y=100.0)
    board.add(c, above=True, kind="outcome", order=3, text=c.s, price_y=100.0)
    board.relayout()
    ya, yb, yc = a.pos().y(), b.pos().y(), c.pos().y()
    assert ya < yb < yc  # piled up with non-zero floor step
    assert (yb - ya) >= 0.1
    assert a.pos().x() == 10 and b.pos().x() == 11 and c.pos().x() == 12


def test_outcome_cluster_collapses_to_plus_n():
    idx = pd.date_range("2024-01-01", periods=40, freq="h", tz="UTC")

    def trade(tid, entry_i, pnl=1.0):
        return Trade(
            trade_id=tid,
            symbol="T",
            side=1,
            entry_ts_ms=int(idx[entry_i].value // 10**6),
            entry_price=100.0,
            entry_ref_price=100.0,
            qty=1.0,
            stop_price=95.0,
            target_price=101.0,
            liquidation_price=None,
            leverage=1.0,
            initial_margin=10.0,
            exit_ts_ms=int(idx[entry_i + 1].value // 10**6),
            exit_price=101.0,
            exit_reason="target",
            hold_bars=1,
            fees=0.0,
            funding=0.0,
            slippage_cost=0.0,
            gross_pnl=pnl,
            realized_pnl=pnl,
            return_units=0.01,
            mae=0.0,
            mfe=0.0,
            ambiguous_intrabar=False,
            resolved_by_touch=False,
            entry_bar_exit=False,
        )

    # 8 consecutive entry bars → 5 full + "+3 more"
    trades = [trade(i, i) for i in range(1, 9)]
    annos = plot_mod._build_outcome_annotations(trades, idx, max_full=5)
    full = [a for a in annos if "more entries" not in a.text]
    more = [a for a in annos if "more entries" in a.text]
    assert len(full) == 5
    assert len(more) == 1 and "+3 more" in more[0].text


def test_zones_constant_levels_no_tpsl_text(monkeypatch):
    fake = _FakeFplt()
    monkeypatch.setitem(__import__("sys").modules, "finplot", fake)
    monkeypatch.setattr(plot_mod, "_open_info_window", lambda *a, **k: None)

    bars, result = _tiny_result()
    plot_mod.plot_backtest(
        bars,
        result,
        title="levels",
        show=False,
        show_metrics_window=False,
        trade_style="zones",
        trade_labels="on_chart",
    )
    # No TP/SL % on chart when constant; still have outcome tags with on_chart.
    texts = [t.s for t in fake.texts]
    assert any("hold=" in s for s in texts)
    assert not any("TP" in s for s in texts)
    assert not any(s.strip().startswith("SL") for s in texts)


def test_index_trades_by_entry_bar_and_detail_text():
    idx = pd.date_range("2024-01-01", periods=10, freq="h", tz="UTC")

    def mk(tid, entry_i, side=1):
        return Trade(
            trade_id=tid,
            symbol="T",
            side=side,
            entry_ts_ms=int(idx[entry_i].value // 10**6),
            entry_price=100.0 + tid,
            entry_ref_price=100.0,
            qty=0.5,
            stop_price=95.0,
            target_price=105.0,
            liquidation_price=None,
            leverage=1.0,
            initial_margin=10.0,
            exit_ts_ms=int(idx[entry_i + 1].value // 10**6),
            exit_price=105.0,
            exit_reason="target",
            hold_bars=1,
            fees=0.01,
            funding=0.0,
            slippage_cost=0.0,
            gross_pnl=2.5,
            realized_pnl=2.4,
            return_units=0.024,
            mae=0.0,
            mfe=0.0,
            ambiguous_intrabar=False,
            resolved_by_touch=False,
            entry_bar_exit=False,
        )

    a = mk(1, 3)
    b = mk(2, 3)
    c = mk(3, 5, side=-1)
    by = plot_mod._index_trades_by_entry_bar([a, b, c], idx)
    assert len(by[3]) == 2
    assert {t.trade_id for t in by[3]} == {1, 2}
    assert len(by[5]) == 1 and by[5][0].trade_id == 3
    detail = plot_mod._trades_detail_text(by[3], bar_ts=idx[3], bar_i=3)
    assert "LONG" in detail
    assert "hold=1" in detail
    assert "pnl=" in detail
    assert "entry=" in detail
    assert plot_mod._click_x_to_bar_index(3.1, idx) == 3
    assert plot_mod._click_x_to_bar_index(float(idx[5].value // 10**6), idx) == 5


def test_trade_detail_shows_pred_mean_from_meta_and_overlay():
    idx = pd.date_range("2024-01-01", periods=8, freq="h", tz="UTC")
    entry_ts = int(idx[2].value // 10**6)
    t = Trade(
        trade_id=9,
        symbol="ETHUSDT",
        side=1,
        entry_ts_ms=entry_ts,
        entry_price=2000.0,
        entry_ref_price=2000.0,
        qty=0.03,
        stop_price=1960.0,
        target_price=2040.0,
        liquidation_price=None,
        leverage=1.0,
        initial_margin=60.0,
        exit_ts_ms=int(idx[3].value // 10**6),
        exit_price=2040.0,
        exit_reason="target",
        hold_bars=1,
        fees=0.05,
        funding=0.0,
        slippage_cost=0.0,
        gross_pnl=1.2,
        realized_pnl=1.15,
        return_units=0.019,
        mae=0.0,
        mfe=0.02,
        ambiguous_intrabar=False,
        resolved_by_touch=False,
        entry_bar_exit=False,
        meta={
            "pred_mean": 0.456,
            "size_mult": 1.5,
            "book_idx": 2,
            "confidence_pct": 45.6,
            "risk_pct": 3.28,
            "actual_risk_pct": 3.21,
        },
    )
    detail = plot_mod._format_trade_detail(t, n=1)
    assert "pred_mean=+0.4560" in detail
    assert "size_mult=1.5" in detail or "size_mult=1.500" in detail
    assert "book=2" in detail
    assert "confidence_pct=45.60%" in detail
    assert "risk_pct=3.28%" in detail
    assert "actual_risk_pct=3.21%" in detail

    # Overlay map by entry_ts overrides / supplies when meta empty
    t2 = Trade(
        trade_id=10,
        symbol="ETHUSDT",
        side=-1,
        entry_ts_ms=entry_ts,
        entry_price=2100.0,
        entry_ref_price=2100.0,
        qty=0.02,
        stop_price=2140.0,
        target_price=2050.0,
        liquidation_price=None,
        leverage=1.0,
        initial_margin=42.0,
        exit_ts_ms=int(idx[4].value // 10**6),
        exit_price=2050.0,
        exit_reason="target",
        hold_bars=2,
        fees=0.04,
        funding=0.0,
        slippage_cost=0.0,
        gross_pnl=1.0,
        realized_pnl=0.96,
        return_units=0.023,
        mae=0.0,
        mfe=0.02,
        ambiguous_intrabar=False,
        resolved_by_touch=False,
        entry_bar_exit=False,
    )
    detail2 = plot_mod._format_trade_detail(
        t2, n=1, predictions={entry_ts: -0.2605}
    )
    assert "pred_mean=-0.2605" in detail2


def test_engine_copies_signal_meta_onto_trade():
    bars, _ = _tiny_result()
    # rebuild with meta on the signal
    n = 40
    tf = 3_600_000
    t0 = 1_700_000_000_000
    ts = np.arange(n, dtype=np.int64) * tf + t0
    o = np.linspace(100, 105, n)
    bars2 = BarSeries(
        ts_ms=ts, open=o, high=o + 1, low=o - 1, close=o + 0.2,
        timeframe_ms=tf, symbol="TEST",
    )
    sig = [
        Signal(
            ts_ms=int(ts[5]),
            side=Side.LONG,
            stop_offset=0.05,
            target_offset=0.05,
            qty=1.0,
            meta={"pred_mean": 0.42, "size_mult": 1.25},
        )
    ]
    inst = InstrumentSpec(
        symbol="TEST", tick_size=0.01, qty_step=0.001,
        min_qty=0.001, min_notional=1.0,
    )
    result = simulate(
        bars=bars2, signals=sig, instrument=inst,
        costs=research_costs(), margin=research_margin(),
        sizing=research_sizing(), sim=research_sim(),
        run_id="meta-unit",
    )
    assert result.trades
    assert result.trades[0].meta.get("pred_mean") == 0.42
    assert result.trades[0].meta.get("size_mult") == 1.25
    detail = plot_mod._format_trade_detail(result.trades[0])
    assert "pred_mean=+0.4200" in detail


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
