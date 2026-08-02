"""The one authoritative metric implementation.

Section 17 of the standard exists because every simulator author reinvents these and
each reinvention is favourable in a slightly different way. The rules that are easy to
break and expensive to break:

* the return series is chronological periodic mark-to-market WALLET equity, including
  unrealised profit and loss, flat days, fees, slippage and funding. Never closed-trade
  returns;
* raw periodic and annualised Sharpe are different numbers and are reported separately,
  with the calendar factor stated. Square-root annualisation is a display convention, not
  an inferential claim, so a dependence-aware value is reported next to it;
* profit factor is POOLED gross profit over absolute pooled gross loss. Never capped at a
  sentinel, never the mean of fold values. Zero gross loss is infinity with a sample
  warning, not an automatic pass;
* drawdown uses mark-to-market equity. Realised-only drawdown understates every strategy
  that holds through adverse excursions.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .contracts import REASON_LIQUIDATION, SimResult, Trade

DEFAULT_ANNUALISATION_DAYS = 365.0


@dataclass(frozen=True)
class SharpeReport:
    raw_periodic: float
    annualised: float
    annualisation_factor: float
    n_periods: int
    mean_return: float
    std_return: float
    hac_raw: float
    hac_annualised: float
    hac_lag: int
    risk_free: float = 0.0
    available: bool = True
    reason: str = ""


@dataclass(frozen=True)
class MetricsReport:
    # period and coverage
    n_trades: int
    n_longs: int
    n_shorts: int
    start_ts_ms: int
    end_ts_ms: int
    span_days: float
    trades_per_month: float
    # wallet
    starting_equity: float
    ending_equity: float
    equity_peak: float
    net_pnl: float
    total_return: float
    invested_notional: float
    return_on_invested: float
    cagr: float
    buy_hold_return: float
    volatility_annualised: float
    wallet_blown: bool
    ruined_at_ts_ms: int | None
    # distribution
    profit_factor: float
    profit_factor_note: str
    win_rate: float
    win_rate_ci_low: float
    win_rate_ci_high: float
    expectancy: float
    expectancy_return_units: float
    avg_win: float
    avg_loss: float
    median_win: float
    median_loss: float
    payoff_ratio: float
    worst_trade: float
    best_trade: float
    best_trade_pct: float
    worst_trade_pct: float
    avg_trade_pct: float
    cvar_5: float
    # duration (backtesting.py-style + bars)
    avg_hold_bars: float
    min_hold_bars: float
    max_hold_bars: float
    avg_hold_hours: float
    min_hold_hours: float
    max_hold_hours: float
    # side split
    long_pnl: float
    short_pnl: float
    long_win_rate: float
    short_win_rate: float
    # streaks / quality
    max_consecutive_wins: int
    max_consecutive_losses: int
    sqn: float
    kelly_fraction: float
    recovery_factor: float
    # risk
    sharpe: SharpeReport
    sortino_annualised: float
    max_drawdown: float
    max_drawdown_pct: float
    max_drawdown_duration_days: float
    avg_drawdown_pct: float
    avg_drawdown_duration_days: float
    calmar: float
    # execution honesty
    exposure: float
    turnover: float
    total_fees: float
    total_slippage: float
    total_funding: float
    n_liquidations: int
    n_skips: int
    skip_counts: Mapping[str, int]
    entry_bar_exits: int
    entry_bar_exit_rate: float
    ambiguous_intrabar: int
    ambiguous_rate: float
    liquidation_status: str
    warnings: tuple[str, ...] = ()
    stamp: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["sharpe"] = asdict(self.sharpe)
        return out

    def as_backtesting_stats(self) -> dict[str, Any]:
        """Keys aligned with kernc/backtesting.py ``._stats.compute_stats`` where possible.

        Extra tradesim-only fields (longs/shorts, fees, funding, HAC Sharpe, …) are included
        under the same dict so a strategy report can show everything in one place.
        """
        sh = self.sharpe
        return {
            "Start": self.start_ts_ms,
            "End": self.end_ts_ms,
            "Duration": self.span_days,
            "Exposure Time [%]": self.exposure * 100.0,
            "Equity Final [$]": self.ending_equity,
            "Equity Peak [$]": self.equity_peak,
            "Commissions [$]": self.total_fees,
            "Return [%]": self.total_return * 100.0,
            "Return on Invested [%]": self.return_on_invested * 100.0,
            "Invested Notional [$]": self.invested_notional,
            "Net PnL [$]": self.net_pnl,
            "Buy & Hold Return [%]": self.buy_hold_return * 100.0,
            "Return (Ann.) [%]": self.cagr * 100.0 if math.isfinite(self.cagr) else math.nan,
            "Volatility (Ann.) [%]": self.volatility_annualised * 100.0,
            "CAGR [%]": self.cagr * 100.0 if math.isfinite(self.cagr) else math.nan,
            "Sharpe Ratio": sh.annualised,
            "Sortino Ratio": self.sortino_annualised,
            "Calmar Ratio": self.calmar,
            "Max. Drawdown [%]": self.max_drawdown_pct * 100.0,
            "Avg. Drawdown [%]": self.avg_drawdown_pct * 100.0,
            "Max. Drawdown Duration": self.max_drawdown_duration_days,
            "Avg. Drawdown Duration": self.avg_drawdown_duration_days,
            "# Trades": self.n_trades,
            "# Longs": self.n_longs,
            "# Shorts": self.n_shorts,
            "Win Rate [%]": self.win_rate * 100.0 if math.isfinite(self.win_rate) else math.nan,
            "Best Trade [%]": self.best_trade_pct * 100.0,
            "Worst Trade [%]": self.worst_trade_pct * 100.0,
            "Avg. Trade [%]": self.avg_trade_pct * 100.0,
            "Max. Trade Duration": self.max_hold_hours,
            "Avg. Trade Duration": self.avg_hold_hours,
            "Min. Trade Duration": self.min_hold_hours,
            "Profit Factor": self.profit_factor,
            "Expectancy [%]": self.expectancy_return_units * 100.0,
            "SQN": self.sqn,
            "Kelly Criterion": self.kelly_fraction,
            # tradesim extras (not in backtesting.py)
            "Sharpe HAC (ann.)": sh.hac_annualised,
            "Funding [$]": self.total_funding,
            "Slippage [$]": self.total_slippage,
            "Long PnL [$]": self.long_pnl,
            "Short PnL [$]": self.short_pnl,
            "Recovery Factor": self.recovery_factor,
            "Max Consecutive Wins": self.max_consecutive_wins,
            "Max Consecutive Losses": self.max_consecutive_losses,
            "Entry-bar exit rate [%]": self.entry_bar_exit_rate * 100.0,
        }


# --------------------------------------------------------------------------------------
# Sharpe
# --------------------------------------------------------------------------------------


def hac_lag(n_returns: int) -> int:
    """Newey-West truncation lag, frozen as ``max(1, floor(4*(n/100)^(2/9)))``."""
    if n_returns <= 1:
        return 1
    return max(1, int(math.floor(4.0 * (n_returns / 100.0) ** (2.0 / 9.0))))


def sharpe(
    returns: Sequence[float] | np.ndarray,
    *,
    annualisation_days: float = DEFAULT_ANNUALISATION_DAYS,
    risk_free_per_period: float = 0.0,
) -> SharpeReport:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    factor = math.sqrt(annualisation_days)
    n = int(r.size)
    if n < 2:
        return SharpeReport(
            math.nan, math.nan, factor, n, math.nan, math.nan, math.nan, math.nan, 1,
            risk_free_per_period, False,
            "fewer than two periodic returns; Sharpe is undefined rather than zero",
        )
    excess = r - float(risk_free_per_period)
    mean = float(np.mean(excess))
    std = float(np.std(excess, ddof=1))
    if std <= 0:
        return SharpeReport(
            math.nan, math.nan, factor, n, mean, std, math.nan, math.nan, 1,
            risk_free_per_period, False,
            "zero return dispersion; Sharpe is undefined rather than infinite",
        )
    raw = mean / std

    # Bartlett-kernel long-run variance: the IID Sharpe overstates confidence when daily
    # returns are serially dependent, which they are whenever positions span days.
    lag = hac_lag(n)
    x = excess - mean
    gamma0 = float(np.dot(x, x) / n)
    lrv = gamma0
    for k in range(1, min(lag, n - 1) + 1):
        weight = 1.0 - k / (lag + 1.0)
        gamma_k = float(np.dot(x[k:], x[:-k]) / n)
        lrv += 2.0 * weight * gamma_k
    if lrv <= 0:
        hac_raw = math.nan
    else:
        hac_raw = mean / math.sqrt(lrv)

    return SharpeReport(
        raw_periodic=raw,
        annualised=raw * factor,
        annualisation_factor=factor,
        n_periods=n,
        mean_return=mean,
        std_return=std,
        hac_raw=hac_raw,
        hac_annualised=hac_raw * factor if math.isfinite(hac_raw) else math.nan,
        hac_lag=lag,
        risk_free=float(risk_free_per_period),
    )


def sortino(
    returns: Sequence[float] | np.ndarray,
    *,
    annualisation_days: float = DEFAULT_ANNUALISATION_DAYS,
) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return math.nan
    downside = r[r < 0]
    if downside.size == 0:
        return math.inf
    dd = float(np.sqrt(np.mean(downside**2)))
    if dd <= 0:
        return math.nan
    return float(np.mean(r) / dd) * math.sqrt(annualisation_days)


# --------------------------------------------------------------------------------------
# Trade distribution
# --------------------------------------------------------------------------------------


def profit_factor(pnls: Sequence[float] | np.ndarray) -> tuple[float, str]:
    """Pooled, uncapped. Returns ``(value, note)``."""
    p = np.asarray(pnls, dtype=float)
    p = p[np.isfinite(p)]
    if p.size == 0:
        return math.nan, "no resolved trades"
    gross_profit = float(p[p > 0].sum())
    gross_loss = float(-p[p < 0].sum())
    if gross_loss == 0.0:
        if gross_profit == 0.0:
            return math.nan, "no profit and no loss"
        return math.inf, (
            f"zero gross loss over {p.size} trades: profit factor is undefined/infinite, "
            "which is an insufficient-sample warning and not an automatic pass"
        )
    return gross_profit / gross_loss, ""


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Win-rate uncertainty. A win rate without one is a number, not evidence."""
    if n <= 0:
        return math.nan, math.nan
    phat = wins / n
    denom = 1.0 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return max(0.0, centre - margin), min(1.0, centre + margin)


# --------------------------------------------------------------------------------------
# Drawdown
# --------------------------------------------------------------------------------------


def max_drawdown(equity: Sequence[float] | np.ndarray) -> tuple[float, float, int]:
    """Return ``(magnitude, fraction_of_peak, duration_in_periods)`` on MTM equity."""
    e = np.asarray(equity, dtype=float)
    e = e[np.isfinite(e)]
    if e.size == 0:
        return 0.0, 0.0, 0
    peak = np.maximum.accumulate(e)
    drop = peak - e
    frac = np.where(peak > 0, drop / peak, 0.0)
    i = int(np.argmax(drop))
    magnitude = float(drop[i])
    fraction = float(np.max(frac))

    duration = 0
    current = 0
    for k in range(e.size):
        if e[k] < peak[k] - 1e-12:
            current += 1
            duration = max(duration, current)
        else:
            current = 0
    return magnitude, fraction, duration


def avg_drawdown_stats(
    equity: Sequence[float] | np.ndarray,
) -> tuple[float, float]:
    """Mean drawdown fraction and mean drawdown episode length (in periods)."""
    e = np.asarray(equity, dtype=float)
    e = e[np.isfinite(e)]
    if e.size == 0:
        return 0.0, 0.0
    peak = np.maximum.accumulate(e)
    frac = np.where(peak > 0, (peak - e) / peak, 0.0)
    underwater = frac > 1e-12
    avg_frac = float(frac[underwater].mean()) if underwater.any() else 0.0
    lengths: list[int] = []
    cur = 0
    for flag in underwater:
        if flag:
            cur += 1
        elif cur:
            lengths.append(cur)
            cur = 0
    if cur:
        lengths.append(cur)
    avg_len = float(np.mean(lengths)) if lengths else 0.0
    return avg_frac, avg_len


def _streak_extremes(pnls: np.ndarray) -> tuple[int, int]:
    max_w = max_l = cur_w = cur_l = 0
    for p in pnls:
        if p > 0:
            cur_w += 1
            cur_l = 0
            max_w = max(max_w, cur_w)
        elif p < 0:
            cur_l += 1
            cur_w = 0
            max_l = max(max_l, cur_l)
        else:
            cur_w = cur_l = 0
    return max_w, max_l


def _sqn(pnls: np.ndarray) -> float:
    """Van Tharp System Quality Number: ``sqrt(n) * mean / std`` of trade PnL."""
    if pnls.size < 2:
        return math.nan
    std = float(np.std(pnls, ddof=1))
    if std <= 0:
        return math.nan
    return float(math.sqrt(pnls.size) * np.mean(pnls) / std)


def _kelly(win_rate: float, payoff: float) -> float:
    """Classical Kelly fraction ``p - (1-p)/b`` with ``b`` = avg_win/|avg_loss|."""
    if not math.isfinite(win_rate) or not math.isfinite(payoff) or payoff <= 0:
        return math.nan
    return float(win_rate - (1.0 - win_rate) / payoff)


# --------------------------------------------------------------------------------------
# Top level
# --------------------------------------------------------------------------------------


def daily_returns(daily_equity: pd.DataFrame) -> np.ndarray:
    if daily_equity is None or len(daily_equity) < 2:
        return np.empty(0, dtype=float)
    e = daily_equity["equity"].to_numpy(dtype=float)
    prev = e[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(prev != 0, e[1:] / prev - 1.0, np.nan)
    return r[np.isfinite(r)]


def compute_metrics(
    result: SimResult,
    *,
    annualisation_days: float = DEFAULT_ANNUALISATION_DAYS,
    risk_free_per_period: float = 0.0,
    bars: Any | None = None,
) -> MetricsReport:
    trades: tuple[Trade, ...] = result.trades
    pnls = np.asarray([t.realized_pnl for t in trades], dtype=float)
    rets = np.asarray([t.return_units for t in trades], dtype=float)
    holds = np.asarray([t.hold_bars for t in trades], dtype=float)
    hold_hours = np.asarray(
        [(t.exit_ts_ms - t.entry_ts_ms) / 3_600_000.0 for t in trades], dtype=float
    )
    n = len(trades)

    equity_df = result.equity
    if equity_df is not None and len(equity_df):
        start_ts = int(equity_df["ts_ms"].iloc[0])
        end_ts = int(equity_df["ts_ms"].iloc[-1])
        mtm = equity_df["equity"].to_numpy(dtype=float)
    else:
        start_ts = end_ts = 0
        mtm = np.asarray([result.starting_equity, result.ending_equity], dtype=float)
    span_days = max((end_ts - start_ts) / 86_400_000.0, 0.0)

    r = daily_returns(result.daily_equity)
    sh = sharpe(
        r, annualisation_days=annualisation_days, risk_free_per_period=risk_free_per_period
    )
    so = sortino(r, annualisation_days=annualisation_days)
    vol_ann = (
        float(np.std(r, ddof=1) * math.sqrt(annualisation_days))
        if r.size >= 2
        else math.nan
    )

    pf, pf_note = profit_factor(pnls)
    wins = int((pnls > 0).sum())
    losses = pnls[pnls < 0]
    winners = pnls[pnls > 0]
    wr = wins / n if n else math.nan
    lo, hi = wilson_interval(wins, n)

    dd_mag, dd_frac, dd_periods = max_drawdown(mtm)
    avg_dd_frac, avg_dd_len = avg_drawdown_stats(mtm)
    period_days = (span_days / max(1, len(mtm) - 1)) if len(mtm) > 1 else 1.0

    net = result.ending_equity - result.starting_equity
    total_return = net / result.starting_equity if result.starting_equity else math.nan
    invested_notional = float(sum(abs(float(t.qty) * float(t.entry_price)) for t in trades))
    return_on_invested = (
        net / invested_notional if invested_notional > 0 else math.nan
    )
    years = span_days / 365.0
    cagr = (
        ((result.ending_equity / result.starting_equity) ** (1.0 / years) - 1.0)
        if years > 0 and result.starting_equity > 0 and result.ending_equity > 0
        else math.nan
    )

    buy_hold = math.nan
    if bars is not None and len(bars) >= 2:
        c0 = float(bars.close[0])
        c1 = float(bars.close[-1])
        if c0 > 0:
            buy_hold = c1 / c0 - 1.0

    exposure = _exposure(equity_df)
    turnover = sum(abs(f.notional) for f in result.fills) / (
        result.starting_equity if result.starting_equity else 1.0
    )

    summary = dict(result.meta.get("summary", {}))
    sorted_pnls = np.sort(pnls) if n else np.empty(0)
    tail = max(1, int(math.ceil(0.05 * n))) if n else 0

    longs = [t for t in trades if int(t.side) > 0]
    shorts = [t for t in trades if int(t.side) < 0]
    long_pnls = np.asarray([t.realized_pnl for t in longs], dtype=float)
    short_pnls = np.asarray([t.realized_pnl for t in shorts], dtype=float)
    payoff = (
        float(winners.mean() / abs(losses.mean()))
        if winners.size and losses.size and losses.mean() != 0
        else math.nan
    )
    max_w, max_l = _streak_extremes(pnls)
    equity_peak = float(np.max(mtm)) if mtm.size else result.ending_equity

    return MetricsReport(
        n_trades=n,
        n_longs=int(summary.get("n_longs", len(longs))),
        n_shorts=int(summary.get("n_shorts", len(shorts))),
        start_ts_ms=start_ts,
        end_ts_ms=end_ts,
        span_days=span_days,
        trades_per_month=(n / (span_days / 30.4375)) if span_days > 0 else math.nan,
        starting_equity=result.starting_equity,
        ending_equity=result.ending_equity,
        equity_peak=equity_peak,
        net_pnl=net,
        total_return=total_return,
        invested_notional=invested_notional,
        return_on_invested=return_on_invested,
        cagr=cagr,
        buy_hold_return=buy_hold,
        volatility_annualised=vol_ann,
        wallet_blown=bool(summary.get("wallet_blown", False)) or result.ending_equity <= 0,
        ruined_at_ts_ms=(
            int(summary["ruined_at_ts_ms"])
            if summary.get("ruined_at_ts_ms") is not None
            else None
        ),
        profit_factor=pf,
        profit_factor_note=pf_note,
        win_rate=wr,
        win_rate_ci_low=lo,
        win_rate_ci_high=hi,
        expectancy=float(pnls.mean()) if n else math.nan,
        expectancy_return_units=float(rets.mean()) if n else math.nan,
        avg_win=float(winners.mean()) if winners.size else math.nan,
        avg_loss=float(losses.mean()) if losses.size else math.nan,
        median_win=float(np.median(winners)) if winners.size else math.nan,
        median_loss=float(np.median(losses)) if losses.size else math.nan,
        payoff_ratio=payoff,
        worst_trade=float(pnls.min()) if n else math.nan,
        best_trade=float(pnls.max()) if n else math.nan,
        best_trade_pct=float(rets.max()) if n else math.nan,
        worst_trade_pct=float(rets.min()) if n else math.nan,
        avg_trade_pct=float(rets.mean()) if n else math.nan,
        cvar_5=float(sorted_pnls[:tail].mean()) if tail else math.nan,
        avg_hold_bars=float(holds.mean()) if n else math.nan,
        min_hold_bars=float(holds.min()) if n else math.nan,
        max_hold_bars=float(holds.max()) if n else math.nan,
        avg_hold_hours=float(hold_hours.mean()) if n else math.nan,
        min_hold_hours=float(hold_hours.min()) if n else math.nan,
        max_hold_hours=float(hold_hours.max()) if n else math.nan,
        long_pnl=float(long_pnls.sum()) if long_pnls.size else 0.0,
        short_pnl=float(short_pnls.sum()) if short_pnls.size else 0.0,
        long_win_rate=(
            float((long_pnls > 0).mean()) if long_pnls.size else math.nan
        ),
        short_win_rate=(
            float((short_pnls > 0).mean()) if short_pnls.size else math.nan
        ),
        max_consecutive_wins=max_w,
        max_consecutive_losses=max_l,
        sqn=_sqn(pnls),
        kelly_fraction=_kelly(wr, payoff),
        recovery_factor=(
            net / dd_mag if dd_mag > 0 and math.isfinite(net) else math.nan
        ),
        sharpe=sh,
        sortino_annualised=so,
        max_drawdown=dd_mag,
        max_drawdown_pct=dd_frac,
        max_drawdown_duration_days=dd_periods * period_days,
        avg_drawdown_pct=avg_dd_frac,
        avg_drawdown_duration_days=avg_dd_len * period_days,
        calmar=(cagr / dd_frac) if dd_frac > 0 and math.isfinite(cagr) else math.nan,
        exposure=exposure,
        turnover=turnover,
        total_fees=float(summary.get("total_fees", sum(t.fees for t in trades))),
        total_slippage=float(
            summary.get("total_slippage", sum(t.slippage_cost for t in trades))
        ),
        total_funding=float(summary.get("total_funding", sum(t.funding for t in trades))),
        n_liquidations=int(
            summary.get(
                "n_liquidations",
                sum(1 for t in trades if t.exit_reason.startswith(REASON_LIQUIDATION)),
            )
        ),
        n_skips=len(result.skips),
        skip_counts=dict(result.skip_counts),
        entry_bar_exits=int(summary.get("entry_bar_exits", 0)),
        entry_bar_exit_rate=float(summary.get("entry_bar_exit_rate", 0.0)),
        ambiguous_intrabar=int(summary.get("ambiguous_intrabar", 0)),
        ambiguous_rate=float(summary.get("ambiguous_rate", 0.0)),
        liquidation_status=result.liquidation_status,
        warnings=result.warnings,
        stamp=result.stamp,
    )


def _exposure(equity_df: pd.DataFrame | None) -> float:
    """Fraction of observations with at least one position open."""
    if equity_df is None or not len(equity_df):
        return 0.0
    return float((equity_df["open_positions"] > 0).mean())


def headline_table(report: MetricsReport) -> str:
    """The required headline table (standard section 17.8), stamp first."""
    sh = report.sharpe
    lines = [
        "",
        "=" * 78,
        "HEADLINE",
        "=" * 78,
    ]
    if report.stamp:
        state = "GREEN" if report.stamp.get("passed") else "NOT GREEN"
        lines.append(
            f"conformance stamp  : {report.stamp.get('engine_name')} "
            f"{report.stamp.get('engine_version')} @ {report.stamp.get('engine_commit')} "
            f"| fixtures {str(report.stamp.get('fixture_pack_hash', ''))[:12]} "
            f"| {report.stamp.get('satisfied_count')}/{report.stamp.get('required_count')} "
            f"| {state}"
        )
        if state != "GREEN":
            lines.append(
                "  *** NOT QUOTABLE EVIDENCE: the engine that produced these numbers has "
                "no green conformance stamp."
            )
    else:
        lines.append("conformance stamp  : ABSENT — these numbers are not quotable evidence")
    lines += [
        "-" * 78,
        f"period             : {report.span_days:.1f} days  "
        f"({_fmt_ts(report.start_ts_ms)} -> {_fmt_ts(report.end_ts_ms)})",
        f"trades             : {report.n_trades}  "
        f"(longs {report.n_longs} / shorts {report.n_shorts})  "
        f"{report.trades_per_month:.2f}/month",
        f"hold bars          : avg {report.avg_hold_bars:.2f}  "
        f"min {report.min_hold_bars:.0f}  max {report.max_hold_bars:.0f}",
        f"hold hours         : avg {report.avg_hold_hours:.2f}  "
        f"min {report.min_hold_hours:.2f}  max {report.max_hold_hours:.2f}",
        f"wallet             : {report.starting_equity:,.2f} -> {report.ending_equity:,.2f}"
        f"  peak {report.equity_peak:,.2f}"
        + ("  *** WALLET BLOWN ***" if report.wallet_blown else ""),
        f"net PnL            : {report.net_pnl:,.2f} USDT   "
        f"on invested {report.invested_notional:,.2f}  "
        f"({report.return_on_invested:.2%} ROI on investment)  "
        f"[headline money % — not wallet %]",
        f"wallet return      : {report.total_return:.2%} of starting equity  "
        f"buy&hold {report.buy_hold_return:.2%}  "
        f"[secondary — wallet is oversized so margin never binds]",
        f"long/short PnL     : {report.long_pnl:,.2f} / {report.short_pnl:,.2f}  "
        f"WR {report.long_win_rate:.2%} / {report.short_win_rate:.2%}",
        f"expectancy         : {report.expectancy:,.4f} USDT/trade  "
        f"({report.expectancy_return_units:.4%} per unit invested)",        f"profit factor      : {report.profit_factor:.4f} {report.profit_factor_note}",
        f"win rate           : {report.win_rate:.2%}  "
        f"[{report.win_rate_ci_low:.2%}, {report.win_rate_ci_high:.2%}] Wilson 95%",
        f"payoff             : {report.payoff_ratio:.3f}   "
        f"avg win {report.avg_win:,.2f} / avg loss {report.avg_loss:,.2f}",
        f"SQN / Kelly        : {report.sqn:.3f} / {report.kelly_fraction:.3f}",
        f"streaks (W/L)      : {report.max_consecutive_wins} / "
        f"{report.max_consecutive_losses}",
        f"Sharpe daily raw   : {sh.raw_periodic:.4f}   (n={sh.n_periods})",
        f"Sharpe annualised  : {sh.annualised:.4f}   "
        f"(factor sqrt({sh.annualisation_factor ** 2:.0f}))",
        f"Sharpe HAC raw/ann : {sh.hac_raw:.4f} / {sh.hac_annualised:.4f}   "
        f"(Bartlett lag {sh.hac_lag})",
        f"Sortino annualised : {report.sortino_annualised:.4f}",
        f"volatility (ann.)  : {report.volatility_annualised:.2%}",
        f"max drawdown (MTM) : {report.max_drawdown:,.2f}  ({report.max_drawdown_pct:.2%}) "
        f"over {report.max_drawdown_duration_days:.1f} days",
        f"avg drawdown       : {report.avg_drawdown_pct:.2%}  "
        f"over {report.avg_drawdown_duration_days:.1f} days",
        f"Calmar / recovery  : {report.calmar:.4f} / {report.recovery_factor:.4f}",
        f"exposure / turnover: {report.exposure:.2%} / {report.turnover:.2f}x",
        f"fees / slip / fund : {report.total_fees:,.2f} / {report.total_slippage:,.2f} / "
        f"{report.total_funding:,.2f}",
        f"entry-bar exits    : {report.entry_bar_exits} ({report.entry_bar_exit_rate:.1%})",
        f"ambiguous intrabar : {report.ambiguous_intrabar} ({report.ambiguous_rate:.1%})",
        f"liquidations       : {report.n_liquidations}   status {report.liquidation_status}",
        f"skips              : {report.n_skips} {dict(report.skip_counts) or ''}",
        "=" * 78,
    ]
    if report.wallet_blown:
        lines.insert(
            5,
            f"*** WALLET BLOWN at ts_ms={report.ruined_at_ts_ms} — "
            "subsequent signals were not traded ***",
        )
    for w in report.warnings:
        lines.append(f"WARNING: {w}")
    return "\n".join(lines) + "\n"


def _fmt_ts(ts_ms: int) -> str:
    if not ts_ms:
        return "?"
    return pd.Timestamp(ts_ms, unit="ms", tz="UTC").strftime("%Y-%m-%d")
