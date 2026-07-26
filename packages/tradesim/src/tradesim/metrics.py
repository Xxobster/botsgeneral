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
    start_ts_ms: int
    end_ts_ms: int
    span_days: float
    trades_per_month: float
    # wallet
    starting_equity: float
    ending_equity: float
    net_pnl: float
    total_return: float
    cagr: float
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
    cvar_5: float
    # risk
    sharpe: SharpeReport
    sortino_annualised: float
    max_drawdown: float
    max_drawdown_pct: float
    max_drawdown_duration_days: float
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
) -> MetricsReport:
    trades: tuple[Trade, ...] = result.trades
    pnls = np.asarray([t.realized_pnl for t in trades], dtype=float)
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

    pf, pf_note = profit_factor(pnls)
    wins = int((pnls > 0).sum())
    losses = pnls[pnls < 0]
    winners = pnls[pnls > 0]
    wr = wins / n if n else math.nan
    lo, hi = wilson_interval(wins, n)

    dd_mag, dd_frac, dd_periods = max_drawdown(mtm)
    period_days = (span_days / max(1, len(mtm) - 1)) if len(mtm) > 1 else 1.0

    net = result.ending_equity - result.starting_equity
    total_return = net / result.starting_equity if result.starting_equity else math.nan
    years = span_days / 365.0
    cagr = (
        ((result.ending_equity / result.starting_equity) ** (1.0 / years) - 1.0)
        if years > 0 and result.starting_equity > 0 and result.ending_equity > 0
        else math.nan
    )

    exposure = _exposure(equity_df)
    turnover = sum(abs(f.notional) for f in result.fills) / (
        result.starting_equity if result.starting_equity else 1.0
    )

    summary = dict(result.meta.get("summary", {}))
    sorted_pnls = np.sort(pnls) if n else np.empty(0)
    tail = max(1, int(math.ceil(0.05 * n))) if n else 0

    return MetricsReport(
        n_trades=n,
        start_ts_ms=start_ts,
        end_ts_ms=end_ts,
        span_days=span_days,
        trades_per_month=(n / (span_days / 30.4375)) if span_days > 0 else math.nan,
        starting_equity=result.starting_equity,
        ending_equity=result.ending_equity,
        net_pnl=net,
        total_return=total_return,
        cagr=cagr,
        profit_factor=pf,
        profit_factor_note=pf_note,
        win_rate=wr,
        win_rate_ci_low=lo,
        win_rate_ci_high=hi,
        expectancy=float(pnls.mean()) if n else math.nan,
        expectancy_return_units=(
            float(np.mean([t.return_units for t in trades])) if n else math.nan
        ),
        avg_win=float(winners.mean()) if winners.size else math.nan,
        avg_loss=float(losses.mean()) if losses.size else math.nan,
        median_win=float(np.median(winners)) if winners.size else math.nan,
        median_loss=float(np.median(losses)) if losses.size else math.nan,
        payoff_ratio=(
            float(winners.mean() / abs(losses.mean()))
            if winners.size and losses.size and losses.mean() != 0
            else math.nan
        ),
        worst_trade=float(pnls.min()) if n else math.nan,
        best_trade=float(pnls.max()) if n else math.nan,
        cvar_5=float(sorted_pnls[:tail].mean()) if tail else math.nan,
        sharpe=sh,
        sortino_annualised=so,
        max_drawdown=dd_mag,
        max_drawdown_pct=dd_frac,
        max_drawdown_duration_days=dd_periods * period_days,
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
        f"trades             : {report.n_trades}  ({report.trades_per_month:.2f}/month over {report.span_days:.1f} days)",
        f"net PnL            : {report.net_pnl:,.2f}  ({report.total_return:.2%})",
        f"expectancy         : {report.expectancy:,.4f} per trade",
        f"profit factor      : {report.profit_factor:.4f} {report.profit_factor_note}",
        f"win rate           : {report.win_rate:.2%}  [{report.win_rate_ci_low:.2%}, {report.win_rate_ci_high:.2%}] Wilson 95%",
        f"payoff             : {report.payoff_ratio:.3f}   avg win {report.avg_win:,.2f} / avg loss {report.avg_loss:,.2f}",
        f"Sharpe daily raw   : {sh.raw_periodic:.4f}   (n={sh.n_periods})",
        f"Sharpe annualised  : {sh.annualised:.4f}   (factor sqrt({sh.annualisation_factor ** 2:.0f}))",
        f"Sharpe HAC raw/ann : {sh.hac_raw:.4f} / {sh.hac_annualised:.4f}   (Bartlett lag {sh.hac_lag})",
        f"Sortino annualised : {report.sortino_annualised:.4f}",
        f"max drawdown (MTM) : {report.max_drawdown:,.2f}  ({report.max_drawdown_pct:.2%}) over {report.max_drawdown_duration_days:.1f} days",
        f"Calmar             : {report.calmar:.4f}",
        f"exposure / turnover: {report.exposure:.2%} / {report.turnover:.2f}x",
        f"fees / slip / fund : {report.total_fees:,.2f} / {report.total_slippage:,.2f} / {report.total_funding:,.2f}",
        f"entry-bar exits    : {report.entry_bar_exits} ({report.entry_bar_exit_rate:.1%})",
        f"ambiguous intrabar : {report.ambiguous_intrabar} ({report.ambiguous_rate:.1%})",
        f"liquidations       : {report.n_liquidations}   status {report.liquidation_status}",
        f"skips              : {report.n_skips} {dict(report.skip_counts) or ''}",
        "=" * 78,
    ]
    for w in report.warnings:
        lines.append(f"WARNING: {w}")
    return "\n".join(lines) + "\n"
