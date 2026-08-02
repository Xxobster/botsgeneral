"""METR-001 .. METR-008 — one implementation, and no flattering shortcuts in it.

Each of these has a well-known favourable variant: profit factor averaged across folds,
drawdown measured on realised profit and loss only, an annualised Sharpe quoted without
its raw counterpart or its serial-dependence caveat, a win rate presented without an
interval. The variants are not disagreements about taste, they are all biased the same
way, and the bias is always towards deploying.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from conftest import QUIET_BAR_1, SIGNAL_BAR, TF, long_signal, run
from tradesim import MarginConfig, compute_metrics, headline_table
from tradesim.metrics import (
    hac_lag,
    max_drawdown,
    profit_factor,
    sharpe,
    wilson_interval,
)


@pytest.mark.conformance("METR-001")
def test_metr_001_profit_factor_is_pooled_and_uncapped():
    """METR-001: pool the trades, then divide. Never average the folds' ratios.

    Fold A is +10.00 against -5.00 (a ratio of 2.00) and fold B is +1.00 against -10.00
    (a ratio of 0.10). The mean of the two ratios is 1.05, which reads as profitable.
    Pooled, the strategy made 11.00 and lost 15.00: a profit factor of 0.733. Averaging
    lets a small, lucky fold outvote a large, losing one.
    """
    fold_a = [10.0, -5.0]
    fold_b = [1.0, -10.0]

    pf_a, _ = profit_factor(fold_a)
    pf_b, _ = profit_factor(fold_b)
    pooled, note = profit_factor(fold_a + fold_b)

    assert pf_a == pytest.approx(2.0)
    assert pf_b == pytest.approx(0.1)
    assert (pf_a + pf_b) / 2 == pytest.approx(1.05), "the flattering variant"
    assert pooled == pytest.approx(11.0 / 15.0)
    assert note == ""


@pytest.mark.conformance("METR-001")
def test_metr_001_profit_factor_is_not_capped_at_a_sentinel():
    """METR-001: a large ratio is reported as it is, not clipped to a tidy ceiling."""
    value, _ = profit_factor([1000.0, -0.01])
    assert value == pytest.approx(100_000.0)


@pytest.mark.conformance("METR-002")
def test_metr_002_zero_gross_loss_is_infinity_with_a_warning():
    """METR-002: three winners and no losers is a sample-size warning, not a pass.

    A strategy with no losing trade in its record has not proven it cannot lose; it has
    proven the record is short.
    """
    value, note = profit_factor([1.0, 2.0, 3.0])
    assert math.isinf(value)
    assert "insufficient-sample warning" in note
    assert "not an automatic pass" in note

    empty, empty_note = profit_factor([])
    assert math.isnan(empty)
    assert empty_note == "no resolved trades"


@pytest.mark.conformance("METR-003")
def test_metr_003_drawdown_uses_mark_to_market_equity(
    instrument, costs, sizing, sim
):
    """METR-003: one winning trade that spent a bar 10.00 underwater still has drawdown.

    Realised-only drawdown for this run is exactly zero: there is one trade and it made
    money. The account, meanwhile, was down 10.10 at bar 2 and would have been margin
    called on a bigger position. Reporting zero here understates the risk of every
    strategy that holds through adverse excursions, which is most of them.
    """
    result = run(
        [
            SIGNAL_BAR,
            QUIET_BAR_1,
            [2 * TF, 100.0, 100.5, 89.0, 90.0],
            [3 * TF, 90.0, 111.0, 89.0, 110.0],
        ],
        [long_signal(stop=80.0)],
        instrument=instrument,
        costs=costs,
        margin=MarginConfig(leverage=2.0),
        sizing=sizing,
        sim=sim,
    )
    report = compute_metrics(result)

    assert all(t.realized_pnl > 0 for t in result.trades)
    assert report.max_drawdown == pytest.approx(10.10)
    assert report.max_drawdown_pct == pytest.approx(10.10 / 10_000.0)


@pytest.mark.conformance("METR-003")
def test_metr_003_max_drawdown_reports_magnitude_fraction_and_duration():
    """METR-003: the peak-to-trough is measured on the curve, not on the trade list."""
    magnitude, fraction, periods = max_drawdown([100.0, 120.0, 90.0, 95.0, 130.0])
    assert magnitude == pytest.approx(30.0)
    assert fraction == pytest.approx(0.25)
    assert periods == 2


@pytest.mark.conformance("METR-004")
def test_metr_004_raw_and_annualised_sharpe_are_separate_numbers():
    """METR-004: the annualisation factor is stated, and both values are reported.

    Multiplying by the square root of 365 is a display convention. Quoting only the
    annualised number invites it to be read as an out-of-sample expectation.
    """
    returns = [0.01, -0.005, 0.02, 0.0, -0.01, 0.015, 0.005, -0.002]
    report = sharpe(returns, annualisation_days=365.0)

    mean = float(np.mean(returns))
    std = float(np.std(returns, ddof=1))
    assert report.raw_periodic == pytest.approx(mean / std)
    assert report.annualisation_factor == pytest.approx(math.sqrt(365.0))
    assert report.annualised == pytest.approx(report.raw_periodic * math.sqrt(365.0))
    assert report.n_periods == len(returns)
    assert report.available is True


@pytest.mark.conformance("METR-004")
def test_metr_004_sharpe_is_undefined_rather_than_zero_on_thin_samples():
    """METR-004: one return, or a flat curve, produces NaN and a reason. Not 0.0."""
    one = sharpe([0.01])
    assert math.isnan(one.raw_periodic) and not one.available
    assert "fewer than two" in one.reason

    flat = sharpe([0.01, 0.01, 0.01])
    assert math.isnan(flat.raw_periodic) and not flat.available
    assert "zero return dispersion" in flat.reason


@pytest.mark.conformance("METR-005")
def test_metr_005_hac_sharpe_is_reported_next_to_the_iid_value():
    """METR-005: on positively autocorrelated returns the HAC value must be lower.

    The IID Sharpe assumes each period is fresh evidence. When a position spans days the
    returns are serially dependent, the effective sample is smaller than the count of
    periods, and the IID number overstates confidence. Reporting both makes the size of
    that overstatement visible instead of arguable.
    """
    rng = np.random.default_rng(0)
    noise = rng.normal(0.0, 0.01, 400)
    series = np.zeros(400)
    series[0] = noise[0]
    for i in range(1, 400):  # AR(1), phi = 0.6: deliberately dependent
        series[i] = 0.6 * series[i - 1] + noise[i]
    series = series + 0.004

    report = sharpe(series)
    assert report.hac_lag == hac_lag(400) == 5
    assert math.isfinite(report.hac_raw)
    assert report.hac_raw < report.raw_periodic
    assert report.hac_annualised == pytest.approx(report.hac_raw * math.sqrt(365.0))


@pytest.mark.conformance("METR-006")
def test_metr_006_execution_costs_and_coverage_are_reported(
    instrument, costs, margin, sizing, sim
):
    """METR-006: exposure, turnover and the three cost lines are in the report.

    A strategy that is flat 95% of the time and one that is always in the market can show
    the same Sharpe and are not the same strategy. Fees, slippage and funding are
    reported separately because they respond to different fixes.
    """
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
        funding=[(2 * TF, 0.001)],
    )
    report = compute_metrics(result)

    assert report.total_fees == pytest.approx(0.21)
    # The settlement lands on bar 2's open of 100.50: 1 * 100.50 * 0.001, paid by the long.
    assert report.total_funding == pytest.approx(-0.1005)
    assert report.total_slippage == pytest.approx(0.0)
    # Two fills of 100.00 and 110.00 against a 10000.00 wallet.
    assert report.turnover == pytest.approx(210.0 / 10_000.0)
    # One of three observations had a position open: bars 0 and 2 are flat.
    assert report.exposure == pytest.approx(1 / 3)
    assert report.n_skips == 0


@pytest.mark.conformance("METR-007")
def test_metr_007_entry_bar_exit_frequency_is_counted_and_warned_about(
    instrument, costs, margin, sizing, sim
):
    """METR-007: three trades, three entry-bar exits, one prominent warning.

    Above roughly a quarter, the stop is inside ordinary single-bar noise. The strategy
    is paying two sets of costs to be shaken out, and this is the number that revealed
    the original defect once it was finally measured: 47.6% of 1278 trades.
    """
    result = run(
        [
            SIGNAL_BAR,
            [TF, 100.0, 101.0, 94.0, 99.0],
            [2 * TF, 99.0, 100.0, 98.0, 100.0],
            [3 * TF, 100.0, 101.0, 94.0, 99.0],
            [4 * TF, 99.0, 100.0, 98.0, 100.0],
            [5 * TF, 100.0, 101.0, 94.0, 99.0],
            [6 * TF, 99.0, 100.0, 98.0, 99.0],
        ],
        [
            long_signal(stop=None, target=None, stop_offset=0.05, target_offset=0.10),
            long_signal(ts_ms=2 * TF, stop=None, target=None, stop_offset=0.05, target_offset=0.10),
            long_signal(ts_ms=4 * TF, stop=None, target=None, stop_offset=0.05, target_offset=0.10),
        ],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )
    report = compute_metrics(result)

    assert report.n_trades == 3
    assert report.entry_bar_exits == 3
    assert report.entry_bar_exit_rate == pytest.approx(1.0)
    assert any("exited on their entry bar" in w for w in report.warnings)
    assert "entry-bar exits    : 3 (100.0%)" in headline_table(report)


@pytest.mark.conformance("METR-007")
def test_metr_007_ambiguous_intrabar_count_is_reported(
    instrument, costs, margin, sizing, sim
):
    """METR-007: the count of bars decided by convention rather than by data."""
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 94.0, 100.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )
    report = compute_metrics(result)

    assert report.ambiguous_intrabar == 1
    assert report.ambiguous_rate == pytest.approx(1.0)


@pytest.mark.conformance("METR-008")
def test_metr_008_win_rate_carries_an_uncertainty_interval():
    """METR-008: 6 wins in 10 is 60% [31.3%, 83.2%]. The width is the finding.

    A 60% win rate over ten trades and a 60% win rate over a thousand are different
    claims, and only the interval says which one is being made.
    """
    low, high = wilson_interval(6, 10)
    assert (low, high) == (pytest.approx(0.31267, abs=1e-5), pytest.approx(0.83182, abs=1e-5))
    assert high - low > 0.5, "ten trades prove very little"

    tight_low, tight_high = wilson_interval(600, 1000)
    assert tight_high - tight_low < 0.07


@pytest.mark.conformance("METR-008")
def test_metr_008_the_report_never_shows_a_bare_win_rate(
    instrument, costs, margin, sizing, sim
):
    """METR-008: the headline table prints the interval on the same line as the rate."""
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )
    report = compute_metrics(result)
    table = headline_table(report)

    assert report.win_rate == 1.0
    assert report.win_rate_ci_low < 1.0, "one winning trade does not prove 100%"
    assert "Wilson 95%" in table
    assert "win rate           : 100.00%  [" in table


def test_backtesting_py_compatible_stats_include_durations_and_sides(
    instrument, costs, margin, sizing, sim
):
    """Familiar kernc/backtesting.py keys plus longs/shorts and hold durations."""
    result = run(
        [SIGNAL_BAR, QUIET_BAR_1, [2 * TF, 100.5, 111.0, 100.0, 110.0]],
        [long_signal()],
        instrument=instrument,
        costs=costs,
        margin=margin,
        sizing=sizing,
        sim=sim,
    )
    report = compute_metrics(result)
    stats = report.as_backtesting_stats()
    assert stats["# Trades"] == 1
    assert stats["# Longs"] == 1
    assert stats["# Shorts"] == 0
    assert "Sortino Ratio" in stats
    assert "SQN" in stats
    assert "Kelly Criterion" in stats
    assert "Avg. Trade Duration" in stats
    assert "Max. Trade Duration" in stats
    assert "Min. Trade Duration" in stats
    assert "hold bars" in headline_table(report)
