# Trading Project Profile — template

Complete this file for each repository. Do not copy values from another bot without verification. Unknown fields stay `UNRESOLVED`; Cursor must not guess them.

This profile contains project choices and user preferences. It cannot weaken the non-negotiable causality, accounting, evidence, authorization or live-safety rules in `TRADING_BOT_RESEARCH_STANDARD_V2.md`.

## 1. Project identity

```yaml
project_name: UNRESOLVED
repository_root: UNRESOLVED
project_memory_directory: docs/project_memory
research_core_version: UNRESOLVED
live_strategy_module: UNRESOLVED
backtest_entrypoint: UNRESOLVED
walk_forward_entrypoint: UNRESOLVED
live_entrypoint: UNRESOLVED
research_database: data/audit/research_registry.sqlite
market_database: data/market/market_data.sqlite
live_database: data/live/live_audit.sqlite
plotting_tool: finplot
```

## 2. Target product contract

```yaml
target_venue: UNRESOLVED
product_type: UNRESOLVED       # spot | linear_perpetual | inverse_perpetual | futures | forex | equity | other
symbols: []
primary_research_symbols: [BTCUSDT, ETHUSDT]
expansion_symbol_queue: [SOLUSDT, VETUSDT, BNBUSDT, XRPUSDT, TRXUSDT, DOGEUSDT, XLMUSDT, ADAUSDT]
future_market_queue: [EURUSD, EURCHF, major_forex_pairs, major_commodities]
settlement_currency: UNRESOLVED
signal_market: UNRESOLVED      # may differ only when explicitly designed and separately stored
execution_market: UNRESOLVED
signal_price_source: UNRESOLVED
entry_price_source: UNRESOLVED
tp_trigger_source: UNRESOLVED  # LastPrice | MarkPrice | IndexPrice
sl_trigger_source: UNRESOLVED
liquidation_source: UNRESOLVED
strategy_timeframes: []
execution_replay_timeframe: UNRESOLVED
timezone: UTC
session_definition: 24x7
```

## 3. Account and order contract

```yaml
account_or_subaccount: UNRESOLVED
position_mode: UNRESOLVED      # one_way | hedge
margin_mode: UNRESOLVED        # isolated | cross | portfolio/UTA
sizing_mode: UNRESOLVED        # fixed_base_qty | fixed_notional | fixed_fractional_risk
wallet_allocation_usdt: UNRESOLVED
risk_per_trade: UNRESOLVED
max_portfolio_exposure: UNRESOLVED
max_concurrent_positions: UNRESOLVED
max_margin_utilization: 0.60
baseline_max_drawdown_budget: 0.20
moderate_stress_max_drawdown_budget: 0.25
max_daily_loss: UNRESOLVED
max_weekly_loss: UNRESOLVED
max_risk_of_ruin_or_loss_limit_breach: 0.01
leverage_policy: lowest_operational_leverage_meeting_frozen_capital_and_liquidation_constraints
entry_order_type: UNRESOLVED
entry_time_in_force: UNRESOLVED
maker_timeout_ms: UNRESOLVED
maker_reprice_policy: UNRESOLVED
exit_order_types: UNRESOLVED
max_hold_policy: UNRESOLVED
one_position_rules: UNRESOLVED
```

Instrument rules such as minimum quantity, quantity step, minimum notional, tick size, leverage limits, funding interval and risk tiers must be fetched and timestamped. Do not hard-code examples such as `BTC minimum quantity = 0.001` as timeless facts.

## 4. Costs and execution assumptions

```yaml
fee_source: UNRESOLVED
maker_fee: UNRESOLVED
taker_fee: UNRESOLVED
baseline_spread_model: UNRESOLVED
baseline_slippage_model: UNRESOLVED
latency_model: UNRESOLVED
historical_funding_source: UNRESOLVED
maker_fill_evidence: UNRESOLVED
moderate_cost_stress: UNRESOLVED
severe_cost_stress: UNRESOLVED
```

The moderate deployment stress must be frozen before outer OOS is opened. Include all-taker execution when maker evidence is not strong enough.

## 5. Research design and preferences

```yaml
economic_hypothesis: UNRESOLVED
candidate_budget: UNRESOLVED
root_random_seed: UNRESOLVED
outer_fold_count: 5
outer_scheme: expanding
inner_scheme: expanding
purge_rule: UNRESOLVED
embargo_rule: UNRESOLVED
minimum_oos_evidence: see_frozen_gate_profile
gate_profile: trading_bot_v2_1_frozen
min_complete_outer_folds: 5
min_resolved_trades_per_gating_fold: 10
min_pooled_resolved_oos_trades: 50
preferred_pooled_resolved_oos_trades: 100
annualized_daily_sharpe_gate: 1.0
hac_annualized_sharpe_gate: 0.75
pooled_profit_factor_gate: 1.20
moderate_stress_profit_factor_gate: 1.05
positive_fold_fraction_gate: 0.80
bootstrap_positive_expectancy_probability_gate: 0.90
bootstrap_min_resamples: 10000
bootstrap_method_and_block_rule: UNRESOLVED
hac_lag_or_bandwidth_rule: UNRESOLVED
dsr_probability_gate: 0.95
pbo_gate_when_valid: 0.20
pbo_unavailable_blocks_shadow_if_nested_dsr_bootstrap_pass: false
best_year_positive_pnl_share_max: 0.40
pnl_excluding_best_trade_must_be_positive: true
pnl_excluding_best_year_must_be_positive: true
target_win_rate_preference: 0.60
win_rate_is_hard_gate: false
target_trades_per_month_preference: UNRESOLVED
minimum_frequency_preference: 1_to_2_trades_per_month
aspirational_frequency_preference: 1_to_2_trades_per_day
aspirational_win_rate: 0.80
aspirational_annualized_sharpe: 4.0
reporting_priority: [evidence_class, post_cost_pnl, expectancy, drawdown, sharpe, profit_factor, trade_count, win_rate]
target_sides: [long, short]
side_specific_strategies_allowed: true
```

The performance values above distinguish gates from aspirations. Aspirational WR, Sharpe and trade frequency guide what the user would like to find; they are not evidence and are never used to relax causality, costs, sample sufficiency or risk. Change hard gates only before viewing the relevant OOS/forward evidence, record the reason, then freeze and hash them.

The expansion queues are TODO preferences, not permission to mine every market after observing OOS. Each expansion is a registered experiment with exact venue/product data, a fixed budget and shared-wallet validation.

## 6. Data and secret references

```yaml
primary_market_data_source: UNRESOLVED
proxy_market_data_sources: []
credential_reference: UNRESOLVED   # reference/path only; never store or print secret values
vpn_note: UNRESOLVED
download_checkpoint_directory: data/download_checkpoints
```

Before suggesting a VPN, distinguish authentication, permissions, DNS, rate-limit, service outage, endpoint, symbol and data-coverage errors. Public market-data endpoints should not receive private credentials unless the API actually requires them.

## 7. Local and VPS operations

```yaml
research_execution_location: local
vps_role: live_and_shadow_only
vps_host_alias: UNRESOLVED
process_supervisor: UNRESOLVED      # systemd | docker | screen+watchdog | other
process_names: []
automatic_restart_enabled: UNRESOLVED
startup_reconciliation_required: true
singleton_lock_required: true
websocket_primary_stream: true
rest_reconciliation_required: true
```

Automatic restart is allowed only after an explicitly authorized deployment has installed the service. Every restarted process must reconcile exchange positions, open orders, protective orders, last processed events and duplicate-instance state before opening new risk.

### 7.1 Live decision cadence

```yaml
live_decision_cadence: bar_close     # bar_close | event_driven | fixed_poll (fixed_poll needs a recorded reason)
bar_anchor: utc_epoch                # utc_epoch | venue_session; weekly bars follow the venue week start
schedule_overrides: {}               # e.g. {"4h": {"lead_sec": 60, "close_poll_sec": 5}}; empty = standard 22.1 defaults
startup_catchup_decision: true
one_decision_per_bar_enforced: true
late_bar_action: stale_event_no_action
multi_symbol_close_stagger: UNRESOLVED
intrabar_event_logic: none           # none | list the stream-driven behaviours and their separate cadence
```

Section 22.1 of the detailed standard holds the per-timeframe defaults (1m–1d) and the required invariants. Record any override here before it is used; scheduling parameters are execution configuration and must never be tuned on OOS performance.

## 8. Repository-specific reading list

Replace these examples with real files. Remove entries that do not exist; do not invent them.

```yaml
required_read_before_changes:
  - docs/project_memory/CURRENT_STATE.md
  - docs/project_memory/DECISIONS.md
  - docs/project_memory/STRATEGIES.md
  - docs/project_memory/BACKTEST_VS_LIVE.md
  - docs/project_memory/TESTING.md
  - path/to/research_core.py
  - path/to/strategy.py
  - path/to/live_runner.py
```

## 9. Shadow and forward evidence

```yaml
shadow_start_rule: UNRESOLVED
shadow_min_calendar_duration_days: 90
shadow_min_signal_count: 30
shadow_min_fill_observations: 20
shadow_unexplained_action_mismatches_max: 0
shadow_safety_critical_failures_max: 0
micro_live_min_calendar_duration_days: 180
micro_live_min_trade_count: 50
micro_live_preferred_trade_count: 100
micro_live_pf_gate_for_scale: 1.10
scale_schedule: UNRESOLVED
```

Calendar duration and observation count must both be defined before a forward stage begins. Sparse strategies require longer time, not weaker evidence.

## 10. Approval record

```yaml
research_authorized: false
shadow_authorized: false
micro_live_authorized: false
deployment_authorized: false
restart_authorized: false
leverage_change_authorized: false
size_increase_authorized: false
approval_scope: none
approval_timestamp_utc: null
approval_expiry_utc: null
```

Cursor must never set these values to true based only on a research result. Authorization must come from the user for the exact action and scope.
