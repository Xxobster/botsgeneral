# Frozen Default Trading-Strategy Gates V2.1

Status: `FROZEN_DEFAULT_POLICY`  
Frozen: 2026-07-16  
Applies to: new research generations using Trading-Bot Standard V2.1  
Purpose: maximize the probability that a historical winner represents a real, executable post-cost edge while avoiding arbitrary rejection of legitimate low-frequency strategies.

## 1. What “frozen” means

These are the default gates Cursor installs into a new project profile.

- A project MAY make them stricter at any time.
- A project MAY use a different value only before the affected outer-OOS/forward evidence is viewed, with an explicit economic/statistical reason and user approval.
- A gate MUST NOT be relaxed for a research generation after results are seen.
- A failed preferred strategy does not justify changing the gate.
- Any later V2 default change requires a new rule version and hash.

The thresholds are risk/research policy, not laws of finance or guarantees of live profitability.

## 2. Gate A — engine and evidence validity

Every relevant item is mandatory before performance is scored:

- exact target venue/product and point-in-time data;
- complete data QA and feature coverage;
- causality/future-mutation tests;
- live/backtest signal and management parity;
- next-executable entry timing;
- realistic order, fee, spread, slippage and intrabar model;
- signed discrete historical funding for perpetuals;
- executable tick, quantity, minimum-notional and partial-exit handling;
- exact margin mode, maintenance tiers and Mark-based liquidation;
- chronological MTM wallet reconciliation;
- shared-wallet simulation for jointly deployed strategies;
- deterministic rerun and append-only trial registry;
- no critical UNKNOWN.

Failure outcome: `ENGINE_INVALID`, `DATA_PARITY_FAIL` or another precise blocker. Profitability is not considered.

## 3. Gate B — nested historical edge

All values use stitched nested outer-OOS evidence, never full-history winners or means of fold ratios.

| Test | Frozen default |
| --- | ---: |
| Complete non-overlapping outer folds | >= 5 |
| Resolved trades per gating fold | >= 10 |
| Pooled resolved outer-OOS trades | >= 50; >=100 preferred |
| Net PnL after baseline costs | > 0 |
| Pooled net expectancy | > 0 |
| Pooled baseline PF | >= 1.20 |
| Annualized daily MTM Sharpe | >= 1.00 |
| HAC/dependence-adjusted annualized Sharpe | >= 0.75 |
| Eligible folds with PnL > 0 and PF > 1 | >= 80% |
| Dependence-aware bootstrap resamples with expectancy > 0 | >= 90% |
| DSR probability | >= 0.95 |
| PBO, only with a valid complete aligned matrix | <= 0.20 |

Additional requirements:

- 50–99 pooled trades are labelled `SPARSE_EVIDENCE` and require passing PSR/MinTRL/power, DSR and bootstrap safeguards plus longer forward observation.
- Fewer than 50 pooled trades cannot earn `SHADOW_READY` under this default profile. Before any OOS is viewed, a legitimately sparse strategy may preregister longer folds and an alternative sample requirement supported by PSR/MinTRL/power; it may not change the requirement after failure.
- Incomplete and ineligible folds are reported separately; they are not inserted as zero and cannot be hidden to improve fold coverage.
- DSR uses consistent nonannualized units, complete relevant research history and a preregistered defensible trial-count method. Raw/effective trial sensitivity is always reported.
- PBO is never computed from fold summaries or winners. `PBO_UNAVAILABLE_INSUFFICIENT_MATRIX` does not automatically block `SHADOW_READY` if genuine nested OOS, complete trial registration, DSR and bootstrap gates pass, but no PBO PASS may be claimed.
- Win rate is always reported with uncertainty but is not a universal hard gate.
- The HAC lag/bandwidth rule and block-bootstrap method/block length are chosen from training-only information or frozen before outer OOS. Use a deterministic seed and at least 10,000 bootstrap resamples. Do not tune the dependence correction until the candidate passes.

## 4. Gate C — cost robustness

The exact product-specific scenario is frozen before outer OOS.

### Baseline

- actual/conservative account fees per fill;
- directional spread/slippage;
- actual signed historical funding;
- actual live order type/fill assumptions;
- realistic latency, gaps and rejects.

### Moderate stress — pass gate

- all-taker fees unless maker fills have independent evidence;
- at least `2 x` baseline directional slippage/spread, or observed forward-shadow p95 when available, whichever frozen scenario is worse;
- actual historical funding plus the preregistered adverse-funding sensitivity;
- frozen latency and gap stress;
- simulation rerun chronologically without retuning.

Required result:

- net PnL > 0;
- pooled PF >= 1.05;
- no liquidation/ruin;
- stress MDD within limit.

### Severe stress — mandatory report, not automatic pass gate

- at least `3 x` baseline slippage;
- adverse funding;
- delayed entry;
- adverse stop gaps;
- maker missed/partial fills where relevant.

The severe result identifies fragility. It is not silently omitted and is not automatically required to remain profitable unless the project freezes it as a stricter gate.

## 5. Gate D — concentration and stability

Required:

- PnL excluding the best trade > 0;
- PnL excluding the best year > 0;
- best year <= 40% of total positive PnL;
- no isolated parameter spike;
- preregistered neighboring parameters preserve the sign of expectancy and remain operationally viable;
- acceptable inner-selection turnover;
- no single outer fold breaches the frozen risk budget;
- the latest complete fold may be negative, but it must remain within the preregistered prediction/risk envelope and have no mechanical failure.

The latest fold is not forced positive: that would overreact to one arbitrary window and encourage fold manipulation.

## 6. Gate E — wallet, risk and portfolio

These percentages use explicit allocated strategy capital, never inflated toy cash.

| Test | Frozen default |
| --- | ---: |
| Baseline MTM MDD | <= 20% |
| Moderate-stress MTM MDD | <= 25% |
| Maximum margin utilization | <= 60% |
| Estimated probability of ruin/breaching frozen loss limit | < 1% |
| Confirmed liquidations | 0 |
| Hidden recapitalizations | 0 |

Also required:

- every intended order and TP/SL leg is executable;
- exchange minimum quantity never overrides the risk cap;
- shared-wallet portfolio gates pass;
- standalone passes cannot rescue a failing portfolio;
- the project defines risk per trade, daily/weekly loss limits, exposure and capital allocation before live readiness.

## 7. Gate F — readiness escalation

### Historical -> `SHADOW_READY`

- Gates A–E pass;
- immutable code/config/data/risk/evidence freeze exists;
- nothing is deployed automatically.

### Shadow -> `MICRO_LIVE_CANDIDATE`

Default minimum forward requirement:

- >= 90 calendar days;
- >= 30 actionable signal decisions;
- >= 20 executable hypothetical fill observations where entries occur;
- no retuning;
- zero unexplained action-level signal/order mismatches;
- zero safety-critical operational failures;
- observed p95 spread/slippage within the frozen stress envelope;
- all restart, duplicate-order, stale-data, reconciliation and protective-order tests pass.

Explicit user authorization is still required for micro-live activation.

### Micro-live -> `SCALE_CANDIDATE`

Default minimum:

- >= 180 calendar days;
- >= 50 resolved live trades; 100 preferred;
- more if PSR/MinTRL/power requires it;
- positive live net expectancy;
- live PF >= 1.10;
- realized MDD inside the frozen risk/prediction envelope;
- actual costs, funding and fills reconcile with research/shadow assumptions;
- zero unresolved safety-critical failures;
- shared-wallet portfolio review passes;
- predefined gradual scaling schedule.

Every material risk increase requires separate explicit user approval.

## 8. Machine-readable default profile

```yaml
gate_profile: trading_bot_v2_1_frozen

mechanical:
  require_all_relevant: true
  critical_unknown_allowed: false

historical_oos:
  min_complete_outer_folds: 5
  min_resolved_trades_per_gating_fold: 10
  min_pooled_resolved_trades: 50
  preferred_pooled_resolved_trades: 100
  sparse_evidence_below_trades: 100
  net_pnl_min_exclusive: 0.0
  net_expectancy_min_exclusive: 0.0
  pooled_pf_min: 1.20
  annualized_daily_mtm_sharpe_min: 1.00
  hac_annualized_sharpe_min: 0.75
  positive_eligible_fold_fraction_min: 0.80
  bootstrap_positive_expectancy_probability_min: 0.90
  bootstrap_min_resamples: 10000
  dsr_probability_min: 0.95
  pbo_max_when_valid: 0.20
  win_rate_hard_gate: false

cost_stress:
  moderate_slippage_multiplier_min: 2.0
  moderate_all_taker_unless_maker_proven: true
  moderate_net_pnl_min_exclusive: 0.0
  moderate_pooled_pf_min: 1.05
  severe_slippage_multiplier_min: 3.0
  severe_is_report_only: true

concentration:
  pnl_excluding_best_trade_positive: true
  pnl_excluding_best_year_positive: true
  best_year_positive_pnl_share_max: 0.40
  parameter_spike_allowed: false

risk:
  baseline_mtm_mdd_max: 0.20
  moderate_stress_mtm_mdd_max: 0.25
  margin_utilization_max: 0.60
  ruin_or_loss_limit_breach_probability_max_exclusive: 0.01
  confirmed_liquidations_max: 0
  hidden_recapitalizations_max: 0

shadow_to_micro_candidate:
  min_calendar_days: 90
  min_actionable_signals: 30
  min_hypothetical_fill_observations: 20
  unexplained_action_mismatches_max: 0
  safety_critical_failures_max: 0

micro_to_scale_candidate:
  min_calendar_days: 180
  min_resolved_live_trades: 50
  preferred_resolved_live_trades: 100
  live_net_expectancy_min_exclusive: 0.0
  live_pf_min: 1.10
  safety_critical_failures_max: 0
```

## 9. Why these four headline gates remain

- **Sharpe 1.0:** a useful quality floor, but only on daily MTM wallet returns and accompanied by dependence-aware inference. A point estimate alone is insufficient.
- **PF 1.20:** provides a modest baseline cushion above break-even; the stress PF 1.05 prevents a favorable baseline from hiding cost fragility.
- **80% positive folds:** demands broad chronological consistency, but only after fold eligibility is defined. It is not computed from one-trade or incomplete folds.
- **DSR 0.95:** directly addresses multiple testing and non-normality, provided the complete research history and correct units are used.

PBO is not added as an unconditional fifth gate because it is mathematically invalid without the required complete aligned matrix. Fabricating PBO is worse than reporting it unavailable.

## 10. Methodological references

- Bailey & López de Prado, [The Deflated Sharpe Ratio](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551).
- Bailey, Borwein, López de Prado & Zhu, [The Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253).
- Bailey & López de Prado, [The Sharpe Ratio Efficient Frontier](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1821643).
- Lo, [The Statistics of Sharpe Ratios](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=377260).
- López de Prado, Lipton & Zoonekynd, [Sharpe Ratio Inference: A New Standard for Decision-Making and Reporting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5520741).
