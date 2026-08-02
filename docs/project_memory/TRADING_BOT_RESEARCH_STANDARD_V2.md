# Trading-Bot Research, Validation and Live-Deployment Standard

Version: 2.1  
Date: 2026-07-16  
Intended use: Cursor rule/reference for automated trading projects  
Default status of every new or materially changed strategy: `LIVE_STOP / RESEARCH_ONLY`

Frozen default gate profile: `FROZEN_DEFAULT_GATES_V2_1.md`

## 0. Purpose, language and precedence

The objective is to determine whether the exact strategy that can be executed live has a reproducible, statistically defensible, post-cost edge with survivable risk.

The objective is not to make a backtest look profitable. A negative result, an invalidated historical winner, or a decision to abandon a strategy family is a valid successful research outcome. A profitable result obtained through invalid data, look-ahead, favorable fills, incorrect accounting, incomplete costs, OOS selection or hidden trial mining is a failure.

### 0.1 Normative words

- **MUST / MUST NOT**: non-negotiable requirement.
- **SHOULD / SHOULD NOT**: strong default; deviations require a written, testable reason.
- **MAY**: optional.
- **UNKNOWN**: evidence is missing or cannot be verified. UNKNOWN is never converted to PASS.
- **proxy**: useful exploratory evidence that does not establish live parity.

### 0.2 Three kinds of rule

Do not confuse them:

1. **Truth constraints** prevent invalid inference: causality, point-in-time data, honest selection, correct accounting and executable fills. These are not relaxed to obtain a winner.
2. **Risk policy** defines allowed wallet loss, exposure, leverage, margin use, drawdown and live escalation. These require explicit user choices.
3. **Research gates** are conservative decision thresholds. They must be declared before the corresponding OOS/forward evidence is viewed, then timestamped and hashed. They are not universal laws of finance.

### 0.3 Precedence

Apply rules in this order:

1. safety, authorization, causality and evidence-integrity requirements in this standard;
2. stricter repository safety rules;
3. the frozen project profile and experiment registry;
4. the current task instructions.

A lower level may make a rule stricter. It may not silently weaken a higher-level truth or authorization constraint. If two instructions still conflict, stop the affected action, identify the exact conflict and ask only if the choice materially changes risk or methodology.

### 0.4 Evidence hierarchy

Label every result with its strongest valid evidence class:

1. `EXPLORATORY_IN_SAMPLE`
2. `INNER_VALIDATION`
3. `NESTED_OUTER_OOS`
4. `RETROSPECTIVE_REUSED_HISTORY`
5. `FORWARD_SHADOW`
6. `MICRO_LIVE`
7. `LIVE_SCALED`

Never compare or describe these as interchangeable. Lead reports with the strongest uncontaminated evidence, not the best number.

## 1. Installation and repository startup

For each repository, keep:

- a short always-on rule at `.cursor/rules/trading-bot-core.mdc`;
- this detailed standard at `docs/project_memory/TRADING_BOT_RESEARCH_STANDARD_V2.md`;
- the frozen default policy at `docs/project_memory/FROZEN_DEFAULT_GATES_V2_1.md`;
- a completed project profile at `docs/project_memory/TRADING_PROJECT_PROFILE.md`;
- concise current-state, decisions, testing, experiment-log and live/backtest-parity documentation adapted to the repository.

Reference the standard from `AGENTS.md` or the repository’s equivalent instruction index. Do not paste several competing constitutions into always-on context.

At the start of a trading task, inspect as applicable:

- repository instructions and relevant project memory;
- `git status --short`;
- data schemas and current databases;
- canonical research/backtest engine;
- strategy and feature code;
- live runner and order-management code;
- tests;
- deployment scripts and service definitions;
- current frozen/candidate/live configurations;
- evidence hashes and readiness state.

Preserve unrelated dirty-worktree changes. Do not remove functions or strategy features unless explicitly requested. Corrected implementations may be introduced alongside legacy behavior for comparison, but there must be one clearly identified canonical path after validation.

Version and hash this standard. Each research run records the standard version/hash. A stronger existing rule is retained; do not overwrite it with weaker language.

## 2. Authorization and change control

### 2.1 Actions requiring exact explicit user authorization

Never automatically:

- deploy or sync code to a live host;
- restart, stop, enable or disable a live process;
- place, amend or cancel live or testnet orders;
- modify a live configuration;
- overwrite frozen parameters;
- change live quantity, risk, leverage, margin mode or position mode;
- remove or replace protective orders on an existing position;
- close an existing position;
- transfer funds;
- install or change a live supervisor/service;
- delete databases, logs, strategies, features or audit evidence;
- commit, push or open a pull request.

The authorization must identify the action and scope. Research, audit, optimization, “fix it,” “make it ready,” backtest and shadow authorization do not imply live authorization.

No readiness label grants permission. Store readiness and human authorization as separate fields.

### 2.2 Live-change preflight

Before requesting deployment approval, present:

- exact files and configuration diff;
- current code/config/evidence hashes;
- maximum earned readiness and unresolved blockers;
- current exchange positions, orders and protective orders if authorized and available;
- expected state migration;
- rollback plan;
- service/restart plan;
- risk delta;
- explicit statement of the action requiring approval.

Never remove protective orders during deployment. If state is uncertain, fail closed and prevent new entries.

### 2.3 Material-change invalidation

Any material change creates a new version and invalidates inherited readiness for the affected evidence:

- signal or feature logic;
- side, symbol or timeframe;
- entry, exit, TP/SL, trailing, break-even or max hold;
- quantity, sizing, leverage, margin or wallet allocation;
- order type, fill model, fee, slippage or funding model;
- data venue, product, source or timestamp semantics;
- portfolio membership or priority;
- metric or validation correction;
- research-core behavior;
- deployment/safety behavior.

Flags such as `validated=true`, `nested_wf_validated=true` or `live_ready=true` are computed outputs tied to hashes. They are never inherited booleans.

## 3. Project contract before results

Complete and freeze a machine-readable project/deployment profile before interpreting profitability.

### 3.1 Target product

Record:

- venue;
- exact product/category and contract type;
- symbol and settlement currency;
- launch/delivery dates;
- signal market and execution market;
- candle and session definitions;
- timezone and UTC resampling anchors;
- signal, entry, TP, SL and liquidation price sources;
- strategy and execution/replay timeframes.

If the signal market differs from the execution market, state the economic reason, store both point-in-time datasets and simulate execution on the execution market. Never substitute signal-market OHLC for execution-market fills.

### 3.2 Account and risk contract

Record:

- account/subaccount topology;
- one-way or hedge mode;
- isolated, cross or portfolio/UTA margin;
- starting and allocated wallet equity;
- sizing mode and risk per trade;
- leverage policy;
- maximum concurrent positions;
- maximum gross/net exposure;
- maximum margin utilization;
- maximum acceptable drawdown;
- daily/weekly loss limits;
- maximum acceptable ruin probability;
- capital/signal priority when orders compete.

Do not assume isolated margin universally. Use the exact live mode. If the user has not chosen a risk budget, deployment readiness is blocked; Cursor must not invent one.

### 3.3 Order contract

Record:

- entry order type and time-in-force;
- PostOnly/IOC/FOK behavior;
- signal timestamp, submit timestamp and earliest executable timestamp;
- timeout, cancellation and repricing rules;
- partial-fill policy;
- TP/SL order types and trigger sources;
- reduce-only/close-on-trigger behavior;
- max-hold, time exit, flip exit and re-entry/cooldown rules;
- multi-TP leg percentages and residual handling;
- restart/reconciliation behavior.

Unknown behavior is a named blocker, not a favorable assumption.

## 4. Architecture and separation of concerns

### 4.1 One versioned research core

Do not create a favorable simulator, metric function or walk-forward implementation for each strategy. Use one versioned and tested research core with separable modules for:

- market-data access and point-in-time joins;
- causal feature/signal generation;
- position sizing;
- instrument-rule normalization;
- execution/order state;
- fees, spread and slippage;
- funding;
- margin and liquidation;
- wallet and portfolio accounting;
- daily/periodic equity;
- metrics and uncertainty;
- nested validation and selection;
- trial registry and evidence persistence;
- reports and readiness gates.

Strategy modules should produce causal intents and position-management decisions. They must not implement private favorable fills, costs or metrics.

Third-party packages such as Backtesting.py may be used for quick exploratory diagnostics only if their quantity, timing, cost and execution semantics are understood. Deployment-grade evidence comes from the canonical parity-tested core. An adapter must reproduce canonical golden cases before its output is trusted.

### 4.2 Live/backtest shared logic

Use the same versioned strategy logic for:

- indicators;
- filters;
- signals;
- side;
- threshold logic;
- TP/SL and max-hold construction;
- sizing intent;
- re-entry/cooldown;
- position-management decisions.

If Pine, research Python and live Python must differ, create deterministic fixtures spanning normal, boundary and adversarial cases and compare all actionable outputs within declared numerical tolerance. A tiny smoke sample is not proof.

### 4.3 Configuration separation

Maintain distinct, immutable identities for:

- exploratory research config;
- inner-selection config;
- outer-OOS freeze;
- shadow freeze;
- micro-live config;
- live config;
- deployment state.

An optimizer MUST NOT write directly to live configuration. Candidate output uses a new file/record. Promotion requires gate calculation plus separate human authorization.

### 4.4 Shared canonical execution engine and the re-implementation ban

Section 4.1 requires one core per repository. That is not sufficient: across repositories, every hand-written trade simulator is an independent chance to omit one of roughly forty subtle behaviours, and a green project test suite is not evidence that the omission is absent. Evidence from three sibling repositories: two had correct entry-bar resolution with an explicit regression test, the third hand-rolled its own engine, had a fully green test suite, and was silently wrong for its entire history.

Therefore:

1. A repository MUST NOT write a new trade-execution simulator when a shared conformant engine covers its product/order contract. Use the shared engine as a library dependency, pinned by version.
2. If a repository genuinely needs different execution semantics (different product, order type, or accounting unit), it MUST extend the shared engine rather than fork it. If a separate implementation is unavoidable, it MUST (a) pass the complete shared golden fixture pack of Section 24.0, and (b) produce a trade-by-trade parity diff against the shared engine on at least one common configuration, with every difference explained in writing before any result is quoted.
3. The shared engine MUST be deterministic, offline, and free of dependencies on any data-collection or live-trading runtime. Research must be reproducible from stored inputs alone.
4. Every result artifact MUST record the engine name, version, commit and fixture-pack hash. A result whose engine version cannot be resolved is not quotable evidence.
5. Upgrading the shared engine is a material change under Section 2.3: it invalidates inherited readiness for affected results, and affected experiments MUST be rerun before their numbers are quoted again.

**Xxobster / botsgeneral concrete binding (mandatory on this stack):**

- The shared engine is **`tradesim`** at `C:\projects\botsgeneral\packages\tradesim`. Every strategy program (xgb, TSM-VPA, LLM1, crypthor, …) MUST import this tree — not a vendored copy, not an old wheel under `site-packages`, not GitHub `backtesting.py`.
- Force the latest source before other tradesim imports: `from tradesim.ensure_source import prefer_botsgeneral_tradesim; prefer_botsgeneral_tradesim()`. Refuse to run if `tradesim.__file__` does not contain `botsgeneral`.
- Preferred research entrypoint: `run_backtest(..., strategy_meta={…})`. Persist by default to `D:\projectsdata\backtests\tradesim_runs.sqlite` (embedded bars) and write `D:\projectsdata\backtests\reports\{run_id}\` (REPORT.md, strategy.json with name/batch/model path/TP/SL, metrics, trades.csv). Reopen with `tradesim-research open --run-id …` — do **not** re-simulate to redraw charts or reprint metrics.
- Operator guide: `TRADESIM_BACKTEST_ENGINE_GUIDE.md`. Conformance must be GREEN before quoting numbers.

## 5. SQLite evidence and reproducibility

SQLite is the authoritative store unless the user explicitly chooses an equally auditable alternative. CSV, JSON, Parquet and Markdown may be mirrors/exports; they are not the sole evidence source.

### 5.1 Minimum evidence domains

Store, as applicable:

- standard and project-profile versions;
- source manifests and instrument snapshots;
- raw LTP/mark/index/premium candles;
- public trades/order-book samples used for fills;
- funding and auxiliary features;
- data-quality findings and download checkpoints;
- hypotheses and candidate registries;
- all trials and statuses;
- fold definitions and inner selections;
- orders, fills, trades and exit legs;
- funding, fees, margin and liquidation events;
- wallet/equity curves;
- metric inputs and outputs;
- stress, stability, DSR and PBO results;
- portfolio results;
- parity and live reconciliation;
- readiness verdicts and approval records.

### 5.2 Run identity

Every run records:

- deterministic run/trial ID;
- UTC start/end;
- Git commit plus dirty-worktree/content hash;
- research-core and strategy hashes;
- config and project-profile hashes;
- data manifest/hash;
- standard hash;
- root and derived seeds;
- runtime/package versions;
- command/entrypoint;
- completion/interruption status and reason.

Do not reset the registry between sessions, scripts or strategy names. Exact duplicate trials may share a deduplication identity, but the attempts and their influence on research decisions remain recorded.

### 5.3 Reproducibility and resilience

- Same data, code, config and seed MUST produce the same orders, trades and metrics.
- Derive candidate/fold seeds deterministically from one root seed; never vary an unrecorded seed until a desirable result appears.
- Long downloads/searches checkpoint to SQLite and resume.
- Retries are bounded, idempotent, rate-limit aware and use backoff/jitter.
- After retry exhaustion, preserve the checkpoint and report the exact blocker. Do not loop forever.

Physical train/test databases may be used as hardening, but database separation alone does not prove causality. Immutable manifests, access boundaries, point-in-time features, selection discipline and tests are authoritative.

## 6. Market-data truth and point-in-time integrity

### 6.1 Exact venue/product parity

Primary deployment evidence MUST use the target venue and exact product from its actual launch onward when those data exist.

Not equivalent unless explicitly designed and separately tested:

- Binance spot and Bybit linear perpetual;
- spot and perpetual;
- inverse and linear perpetual;
- index, Mark and Last Price candles;
- CFD/index/Yahoo proxy and exchange futures;
- signal venue and execution venue;
- current instrument rules and historical rules.

Proxy data are labelled `RESEARCH_PROXY`. They may test broad economic behavior but cannot unlock live parity. Never silently fall back to another venue.

“Longest possible history” means the longest valid point-in-time history for the declared evidence class. It does not authorize pre-launch bars, cross-venue splicing or relabelling contaminated data.

### 6.2 Instrument specification snapshots

Query and persist timestamped official instrument rules as applicable:

- symbol/status/contract type;
- launch and delivery time;
- quote/settlement;
- price tick and limits;
- minimum/maximum quantity;
- quantity step;
- minimum notional;
- leverage limits/steps;
- funding interval/caps;
- risk/maintenance tiers;
- order-type limits.

Instrument rules change. The live runner refreshes them at startup and on an appropriate schedule, and stores the effective snapshot. Examples from documentation are not timeless constants.

If required rules or maintenance tiers are unavailable, return a named UNKNOWN/blocker. Do not claim exchange feasibility or liquidation parity.

### 6.3 Raw-series requirements

Every stored series identifies:

- venue, product, symbol and interval;
- price/feature type;
- timestamp meaning and UTC timezone;
- publication/availability time when different from event time;
- retrieval time;
- original endpoint/source;
- checksum/version;
- first/last timestamp and row count;
- final/incomplete status.

Use timezone-aware UTC or integer UTC milliseconds internally. Never mix naive and aware timestamps.

### 6.4 Quality checks

Validate and persist findings for:

- duplicates and non-monotonic order;
- missing intervals and outages;
- stale tail data and incomplete final candles;
- bars before launch or after delivery;
- invalid OHLC and nonpositive prices;
- NaN/inf;
- unexpected interval length;
- source/contract discontinuities;
- wrong session/resampling boundaries;
- LTP/Mark/Index alignment;
- funding interval and coverage;
- auxiliary-feature availability by fold.

OHLC invariants include:

- `high >= max(open, close)`;
- `low <= min(open, close)`;
- `high >= low`.

Do not forward-fill/backfill OHLC through a gap. Do not silently treat missing OI, funding, news, volume, CVD or sentiment as zero, neutral or confirmation. A required feature below its preregistered coverage fails that candidate/fold or is explicitly removed in a new research generation.

### 6.5 Resampling and sessions

Define `closed`, `label`, `origin`, timezone and session semantics explicitly. For continuous UTC crypto, typical anchors are 2h at 00/02/04, 4h at 00/04/08 and so forth, but the project contract is authoritative.

A parent candle is complete only when every required child interval is present and final. Research and live resampling from identical inputs MUST yield identical timestamps/OHLC.

Test DST/session boundaries for non-24/7 markets, UTC-aware daily keys, incomplete parents, missing child bars and higher-timeframe joins. A timezone join producing unexpected NaN fails loudly.

### 6.6 Point-in-time auxiliary data

For news, macroeconomic releases, OI, sentiment, fundamentals and revised data, store separately:

- event/observation time;
- publication time;
- earliest actual availability time;
- revision/vintage time;
- ingestion time.

Use a value only after its earliest genuine availability. Do not leak revised history backward.

**Shared warehouse (Xxobster stack):** Cross-asset / LLM training features that are not the traded venue’s native OHLCV MUST come from `D:\projectsdata\candles\market_ohlcv.sqlite` (`botsgeneral.research_candles`), not ad-hoc per-project downloads. Include when in the candidate space: FRED yields (US02Y/US10Y/T10Y2Y), VIX/SPX/NDX, crypto mcap/dominance, stablecoin mcap/flows, Fear & Greed, plus Dukascopy FX/DXY/metals/oil. Refresh is incremental — skip series whose latest bar is still fresh. A live pack must refresh every symbol its feature list names.

## 7. Causality and look-ahead protection

### 7.1 Information, decision and execution timestamps

Record three distinct times:

1. information becomes available;
2. strategy decision is finalized;
3. order can first execute after compute/network/exchange latency.

A signal using candle T’s close exists only after T is final. Default causal sequence:

`T closes -> calculate -> send -> first executable event after T`

Do not fill at T’s historical close unless the strategy had a real executable order resting before that close and the backtest models it.

### 7.2 Forbidden leakage

Forbidden unless delayed to genuine confirmation and tested:

- negative shifts;
- centered rolling windows;
- backward fill from future values;
- full-history scaling, quantiles or thresholds;
- feature selection outside the training region;
- higher-timeframe values before their candle completes;
- current-day/week/month final levels used inside that same unfinished period;
- future funding, future revisions or future publication values;
- pivots timestamped at the pivot rather than confirmation;
- labels/positions crossing validation boundaries without purge/embargo;
- final OOS used to choose features, family, direction, symbol or parameters.

A normal chronological EMA/rolling calculation is not automatically leakage. Prove causality with tests rather than rewriting valid calculations blindly.

### 7.3 Learned transforms and ML

For each inner/outer split:

- fit scalers, encoders, imputers, feature selectors, thresholds and models on training data only;
- transform later data without refitting;
- generate labels causally and purge/embargo overlap;
- keep hyperparameter, feature and architecture selection inside inner validation;
- never tune on final outer OOS or forward lockbox;
- **calibrate class probabilities** (isotonic when the calibration slice is large, else Platt/sigmoid) on a held-out slice inside the training window, apply to later data without refitting, and persist the calibrators with the model. A decision rule that consumes probabilities REQUIRES calibrated probabilities; report ECE/Brier;
- log model, feature schema, fit interval and preprocessing hashes.

Chronological separation is mandatory. Random train/test shuffling is inappropriate for path-dependent time-series deployment evidence unless the exact task is not temporal and the exception is justified.

### 7.4 Mandatory causality tests

For representative cutoffs across regimes:

1. **Truncation invariance:** full-series and truncated calculations agree for every actionable time through the cutoff after warmup.
2. **Future mutation:** modifying/appending extreme future data cannot alter earlier indicators, signals, orders or trades.
3. **Streaming/batch parity:** incremental live-style calculation matches batch research within declared tolerance.
4. **Higher-timeframe completion:** every child bar receives only the correct completed HTF value.
5. **Off-by-one:** changing candle i cannot create an order before the first executable time after i becomes known.
6. **Pivot confirmation:** a pivot with right-hand bars becomes actionable only at confirmation.

Any relevant failure makes affected results `ENGINE_INVALID`.

### 7.5 Shared `leakage` package (mandatory before train/test)

On the Xxobster / botsgeneral stack, truncation invariance and future mutation for
**indicator / feature matrices** are executed through the shared package
`C:\projects\botsgeneral\packages\leakage` (CLI `leakage-check`). Operator guide:
`LEAKAGE_TEST_GUIDE.md`.

Every coding agent must run this audit against the production feature builder
**before** training, hunting, freezing or testing models. Hard failures mark each
affected column `LEAKAGE_POTENTIAL` in the project registry
(`database/leakage_registry.json` by default). Columns marked `LEAKAGE_POTENTIAL`
must not enter a feature set until the builder is fixed, stores are rebuilt, and
a clean audit passes.

Physical train/test database separation remains useful hardening but **never**
substitutes for prefix-invariance. Source-text greps for `.shift(-N)` /
`center=True` are insufficient alone because leaky **library defaults** (for
example `pandas_ta.dpo(centered=True)`) leave no literal in project code.

## 8. Signal and live/backtest parity

Parity covers more than entry direction. Compare for identical completed inputs and state:

- candle/resample hashes;
- feature values/hashes;
- signal and edge-trigger behavior;
- side and threshold;
- intended submit time;
- sizing intent and normalized quantity;
- leverage/margin mode;
- TP, SL, trailing and break-even state;
- max hold/time exit;
- cooldown, flip and re-entry;
- one-position and portfolio-priority decisions.

Test multiple regimes and boundary cases, not only a short sample. Store every mismatch. No unexplained mismatch may be omitted from the rate.

If live differs intentionally, the project profile must define the difference and the backtest must reproduce it. Otherwise, parity fails.

## 9. Exchange-realistic orders and fills

### 9.1 Conservative executable baseline

Implement a conservative `taker_next_executable` scenario that:

- submits only after signal confirmation;
- uses the execution market;
- includes latency and directional spread/slippage;
- charges taker fees per fill;
- permits partial fills, rejection and insufficient liquidity/margin;
- handles gaps and price-protection limits.

This is the minimum executable benchmark. A strategy intended to use maker orders should also be evaluated with its actual maker policy, but maker assumptions cannot hide a negative taker baseline unless forward/order-book evidence independently establishes reliable maker execution.

### 9.2 Maker/PostOnly modelling

A touched OHLC limit is not a guaranteed maker fill. Model or bound:

- whether the order would cross and be cancelled;
- queue position/priority;
- trade-through evidence;
- partial fill;
- timeout/cancel/reprice;
- adverse selection after fill;
- missed trades;
- maker/taker classification per fill.

If historical order-book/trade evidence is inadequate, label maker results `FORWARD_EXECUTION_EXPERIMENT`. Do not assume zero slippage merely because an order is a limit.

### 9.3 Order semantics

Model the live behavior of market, limit, IOC, FOK, PostOnly, conditional, stop-market, stop-limit, TP and reduce-only orders. Include:

- bid/ask;
- submit/ack/fill latency;
- price and quantity limits;
- price/quantity rounding;
- margin reservation;
- conditional-order margin check;
- partial fills;
- cancellation/rejection;
- retry and idempotency;
- stop gaps;
- TP-limit non-fill;
- max-hold force close;
- reduce-only and position-mode conflicts.

Use unique deterministic client order IDs. A retry must not create a duplicate order.

### 9.4 Entry-relative risk levels

TP, SL, break-even, trailing levels and wallet risk MUST use the actual simulated/live weighted-average fill, unless the strategy explicitly defines another causal reference. Signal price may be retained as a diagnostic only.

### 9.5 Fee-aware probabilistic decisioning (expected value)

Converting a probability into an order MUST use the decision-theoretic net expected value, not a flat cost blob subtracted from a raw score:

- Compute per-branch **net-of-fee** outcome magnitudes in return space. For a bracket: `mu_plus = tp - entry_slip - entry_fee - tp_exit_fee*(1+tp)`; `mu_minus = sl + entry_slip + entry_fee + sl_exit_fee*(1-sl)`; and, when applicable, a no-touch/max-hold branch `mu_nt` using the market exit fee and slip. Fees are `rate * executed_notional` per fill; slippage moves the fill price and is NOT added to the rate.
- The expected value is `EV = p_up*mu_plus - p_down*mu_minus (+ p_nt*mu_nt)`; the minimum probability to act is the break-even `pi* = (mu_minus + lambda)/(mu_plus + mu_minus)` with risk margin `lambda`. Enter only when the CALIBRATED probability clears `pi*` (equivalently `EV > lambda`).
- A single favorable outcome that is actually profitable in practice (e.g. a small TP that gets hit) MUST yield `mu_plus > 0`. If the cost model makes such a win non-positive, the cost model is wrong.
- The research gate and the live gate MUST be the same code on the same fee assumptions. If a live pack lacks its fee/cost configuration, fail loud; never substitute a cheaper or default cost.
- Reward:risk geometry dominates `pi*`; do not blame fees for an over-strict gate that is really caused by an unfavorable TP:SL ratio.

### 9.6 First-bar exit resolution (non-negotiable)

A position is exposed from the instant it fills. Therefore the bar on which the entry fills MUST be resolved for every protective and terminal condition, in the same simulation step that opens the position:

- stop loss;
- take profit (all legs);
- liquidation;
- trailing/break-even activation, where the strategy defines it as active from the fill;
- any maximum-adverse-excursion or intrabar risk accounting.

The single most damaging and most frequently repeated simulator defect is to open the position at a bar's open (or close) and then begin exit checking on the **following** bar. This grants every trade one free bar of immunity, on precisely the bar where a stop placed just beyond a recent extreme is most likely to be taken out. Measured example: on a daily Volume Spread Analysis strategy whose stop sat just beyond the signal bar's extreme, **47.6% of 1278 trades would have been stopped out on the entry bar**, and removing that immunity turned a stitched out-of-sample Profit Factor of 1.50 into 0.90 and an annualized Sharpe of +1.32 into −0.31. The entire apparent edge of the project was that one missing branch.

Requirements:

1. Exit resolution MUST be a single shared function applied identically to the entry bar and to every later bar. Do not write a separate entry-bar code path; do not place the entry after the exit check inside a bar loop without then re-running the exit check on that bar.
2. If the entry fills at the bar open, the whole bar range is post-entry and MUST be used. If the entry fills intrabar (stop/limit trigger), only the portion of the path after the fill may be used, and that requires lower-timeframe data; without it, use the adverse feasible sequence per Section 10.
3. When a bar closes the position on its entry bar, the round trip MUST still charge both fills' fees, the entry-day/entry-interval funding settlements that fall inside the holding window, and any applicable slippage. A same-bar round trip is not a free round trip.
4. A trade closed on its entry bar MUST be labelled distinguishably (for example `stop_entry_bar`) so that its frequency is reportable. If that frequency exceeds 25% of trades, the report MUST state it prominently, because it means the stop is inside ordinary single-bar noise and the strategy is paying costs to be shaken out.
5. Maximum-hold counting MUST be measured from the entry bar index, so that a same-bar exit has a hold of zero and the hold used live matches the hold used in research.

This requirement is verified by conformance identifiers `EXEC-010` through `EXEC-016` in Section 24.0 and cannot be satisfied by inspection or by assertion in a report.

### 9.7 Mandatory execution stresses

Freeze the stress scenarios before OOS. At minimum report, without retuning:

- account-realistic baseline;
- all-taker;
- moderate and severe slippage/spread;
- entry delay;
- adverse stop gap;
- missed/partial maker fills;
- adverse funding;
- combined stress.

Each scenario reruns the chronological simulation. Do not merely subtract a total cost afterward when changed fills, margin or trade paths could result.

## 10. Intrabar chronology

A strategy-timeframe OHLC candle does not reveal whether its high or low occurred first. Whenever one candle can contain more than one relevant event, replay chronological lower-timeframe target-venue data:

- entry and exit;
- TP and SL;
- TP1 and break-even activation;
- trailing update and stop;
- stop and liquidation;
- funding settlement and exit;
- max-hold exit and another trigger;
- gap and order acknowledgement.

Use the finest reliable data required by the strategy: typically 1m for hourly/four-hour strategies, and trades/ticks where 1m remains ambiguous.

If still unresolved:

1. enumerate feasible sequences;
2. use the adverse feasible sequence for the primary result;
3. label the trade `AMBIGUOUS_INTRABAR`;
4. store the data resolution and selected sequence;
5. report ambiguity count and total PnL/equity sensitivity.

“SL first” is a conservative fallback, not proof of historical order. Do not count an unresolved path as execution-verified.

Multi-TP, break-even and trailing strategies cannot earn execution parity without chronological tests. Never activate break-even before the fill that triggers it, or let a trailing stop use a future high/low from the same candle.

## 11. Fees, spread, slippage and funding

### 11.0 Bybit USDT perpetual — canonical fee math (do not invent)

**Primary sources (check before changing BT cost code):**

- [Perpetual Futures Contract Fees Explained](https://www.bybit.com/en/help-center/article/Perpetual-Futures-Contract-Fees-Explained)
- [Bybit Fees You Need to Know](https://www.bybit.com/en/help-center/article/Bybit-Fees-You-Need-to-Know)
- [Types of Orders](https://www.bybit.com/en/help-center/article/Types-of-Orders-Available-on-Bybit/)
- [Post-Only Order](https://www.bybit.com/en/help-center/article/Post-Only-Order)
- [Maker vs Taker](https://www.bybit.com/en/help-center/article/Comparison-Between-Maker-Orders-and-Taker-Orders/)

**Official USDT/linear formula:**

```text
Trading Fee = Order Value × Fee Rate
Order Value  = Quantity × Executed Price
```

Non-VIP baseline (verify on account fee page): **taker 0.055%**, **maker 0.02%**.

Rules agents must follow:

1. Charge **per fill**, at **that fill’s executed price**. Open and close are two separate fees. Do not invent a single blended “0.225% round-trip” as if it were Bybit’s formula.
2. **Slippage is not a fee.** Slippage changes the executable price; the fee is then `qty × (actual fill price) × rate`. Never add a slip percent into the fee rate.
3. **Limit ≠ always maker.** A limit that rests on the book is maker; a limit that crosses and fills immediately is **taker**. Only **Post-Only** guarantees maker-or-cancel.
4. **Conservative BT default:** if live TP/SL are plain trading-stop / limit exits without proven Post-Only maker fills, charge **taker fee on exits** too. Still fill TP/SL at the **limit price when touched** — do **not** apply market exit slippage to those limit prices unless modelling a stop-market.
5. Market / IOC opens: taker fee + directional entry slippage on price.
6. Store per fill: role (entry/exit/liq), maker|taker, rate, qty, exec price, notional, fee amount.
7. Never assume; re-check Bybit Help Center / account fee page when rates or product rules may have changed.

### 11.1 Fees

Use dated account-specific rates when available; otherwise use a documented conservative official schedule.


Charge fees from each actual fill notional:

- entry fills;
- every TP/partial exit;
- stop/forced exit;
- liquidation/close charges;
- maker rebate only when the fill is actually maker.

Do not apply one round-trip fee regardless of leg count. Store fee role, rate, notional and amount separately.

### 11.2 Slippage and spread

Slippage is directional and order-specific. Model:

- spread at submit/fill;
- size/liquidity impact where material;
- market and stop-market slippage;
- latency;
- gap through stop;
- limit non-fill/partial fill/adverse selection.

After forward fills exist, calculate median, 90th/95th percentile and adverse-event slippage. Review whether the frozen stress envelope contains observed costs. Never replace a predeclared test with the most favorable observed statistic.

Fixed 5/10/20 bp sensitivities are useful diagnostics but not universally realistic. The project profile defines baseline/moderate/severe scenarios before OOS, including a cost severe enough to reveal fragility without pretending every strategy trades the same market or horizon.

### 11.3 Historical funding

For perpetuals, the primary simulation uses signed historical funding at actual settlement timestamps and historical intervals.

For a linear position, an auditable convention is:

`funding_cashflow = -side * position_value_at_mark * funding_rate`

where `side = +1` for long and `-1` for short, subject to the venue’s exact product convention.

Apply funding:

- only while the position is open at settlement;
- exactly once per settlement;
- using the correct historical rate and Mark/position value;
- with the correct side/sign;
- chronologically to cash, equity, available margin, drawdown and liquidation risk.

Do not use `abs(rate)`, always-pay funding, continuous prorating of a discrete settlement or a final post-simulation overlay as live-parity evidence.

A constant rate may be an explicitly labelled sensitivity only. Missing required historical funding/Mark data makes perpetual funding parity UNKNOWN/FAIL.

Test positions opening/closing at settlement boundaries, positive and negative rates, partial positions, flat state and interval changes.

## 12. Quantity, price and order feasibility

### 12.1 Explicit units

Never rely on ambiguous backtest-library units. Distinguish:

- base-asset quantity;
- contract quantity;
- quote notional;
- percentage of equity;
- fixed fractional risk;
- margin allocated.

For every order store desired quantity/notional/risk, normalized values, submitted/fill values, effective notional/risk and rejection/skip reason.

### 12.2 Exchange normalization

Use the instrument snapshot effective at the event. Conceptually:

`minimum_executable_qty = ceil_to_step(max(min_qty, min_notional / executable_price), qty_step)`

Then validate:

- desired quantity;
- rounding direction;
- risk-limited maximum;
- price tick/limit;
- minimum/maximum quantity and notional;
- available margin;
- entry/closing fees;
- funding and safety buffer.

Never use `price_scale`, synthetic fractional orders or an oversized fake wallet to make an unsupported quantity appear executable.

If minimum executable quantity breaches the frozen risk cap, skip with a reason such as `SKIP_MIN_QTY_RISK_CAP`. Do not silently round upward and over-risk.

### 12.3 Partial exits

Every multi-TP/partial exit must:

- satisfy quantity step and minimum quantity/notional;
- use the live rounding method;
- sum to the filled position after accounting for prior partial fills;
- leave no unintended dust;
- allow the residual to close;
- handle partial entry/exit fills;
- match live order behavior.

If any required leg rounds to zero or becomes invalid, reject the configuration as `NON_DEPLOYABLE_ORDER_GRANULARITY`. Do not silently convert it into single TP or different percentages.

For minimum-sized accounts, explicitly test a full-position single-exit alternative as a new preregistered candidate—not as an undocumented live substitution.

## 13. Sizing, leverage, margin and liquidation

### 13.1 Separate edge, size and leverage

Research these in order:

1. Does the signal/exit policy have post-cost expectancy at a normalized risk/notional?
2. What position size satisfies the frozen risk budget and exchange constraints?
3. What leverage/margin allocation can support that size safely?

Leverage does not multiply raw PnL when quantity is fixed. It changes required margin, margin utilization and liquidation distance. Never use leverage to manufacture profitability.

### 13.2 Capital-efficient leverage policy

If the goal is to minimize capital committed, solve it as a constrained risk problem. Choose the **lowest operational leverage** that:

- supports the frozen position quantity and wallet allocation;
- reserves entry/exit fees and funding;
- keeps margin utilization below its limit;
- keeps liquidation beyond the stop under conservative Mark-price/gap/funding stress;
- respects venue tiers and leverage limits;
- leaves the required operational buffer.

Do not simply choose maximum leverage or `1 / stop_distance`. If no leverage satisfies all constraints, the trade/configuration is infeasible. Reducing funded capital is never allowed to increase risk beyond the frozen policy.

### 13.3 Margin and liquidation model

Model the exact live system:

- isolated/cross/portfolio margin;
- one-way/hedge positions;
- initial and maintenance margin;
- risk/maintenance tier changes;
- fee-to-close and funding deductions;
- wallet/available balance;
- other open orders/positions;
- Mark versus Last/Index behavior;
- bankruptcy/liquidation rules;
- gaps, latency and protective-order failure.

Liquidation triggers must use the target venue/product’s actual trigger—commonly Mark Price for perpetuals—not a Last-price candle or leverage-distance heuristic.

If a higher-timeframe candle contains both stop and liquidation, resolve with lower-timeframe Last and Mark paths. A simplistic “liquidation first” or “stop first” rule is not evidence. If exact data/rules remain unavailable, report bounded sensitivity and keep liquidation parity UNKNOWN.

For each simulated liquidation, store a reconstruction: entry/fills, quantity/notional, leverage, margin mode, wallet, initial/maintenance margin, tier, stop, liquidation/bankruptcy price, Mark path, fees, funding and resulting equity.

### 13.4 Required invariants

Tests must prove:

- lowering leverage changes margin/liquidation but not pre-financing fixed-quantity price PnL;
- worsening fees/funding cannot improve wallet results because of a sign bug;
- Mark divergence can liquidate before a Last-triggered stop where the venue allows it;
- on a continuous path, a shallower valid stop is reached before a deeper liquidation threshold unless gaps/trigger sources/state change the order;
- insufficient margin rejects rather than silently funds an order.

## 14. Wallet and portfolio accounting

### 14.1 Authoritative ledger

The canonical result comes from a chronological wallet ledger. At every relevant event/bar track:

- cash/free balance;
- reserved/used margin;
- position quantity/value;
- realized and unrealized PnL;
- fees and funding;
- equity and peak equity;
- maintenance margin and margin utilization;
- accepted, rejected and skipped orders;
- liquidation/ruin state.

Reconcile within strict tolerance:

`starting equity + deposits - withdrawals + gross trading PnL - fees +/- funding + other cashflows = ending equity`

Deposits/recapitalization are not silently injected. If the wallet is ruined, trading stops unless a separately documented deposit policy is part of the experiment.

Never present sum of trade percentage returns, average trade return or closed-only equity as wallet return. Drawdown uses marked-to-market equity including unrealized PnL.

### 14.2 Position-size scenarios

At minimum distinguish and label:

- fixed base quantity/notional without compounding;
- fixed fractional risk with explicit equity and compounding.

Do not compare return percentages from artificial cash with fixed-quantity live PnL without showing the mapping. Report dollar PnL, expectancy and the required wallet/margin alongside return metrics.

### 14.3 Shared-wallet simulation

If bots/symbols share account equity, margin, positions or API state, standalone backtests are insufficient. Simulate a single chronological portfolio with:

- simultaneous signals and deterministic priority;
- shared available margin;
- unrealized PnL and correlated losses;
- position netting/hedge mode;
- symbol and aggregate exposure;
- order rejection/skips;
- funding and tier changes;
- TP/SL ownership and conflicts;
- liquidation dependencies;
- restarts and reconciliation state.

Do not add independent equity curves after the fact or reuse the full wallet for every bot.

Report both standalone diagnostic results and the actual shared-wallet result. Reconcile the portfolio engine to component trades/cashflows and hand-calculated scenarios; a simulated -100% result caused by an accounting bug is not genuine ruin.

When multiple bots trade the same symbol, prove one cannot amend, cancel or close another bot’s position/order unintentionally. Use deterministic unique order/strategy ownership identifiers.

## 15. Hypothesis registration and bounded research

### 15.1 Register before search

Before evaluating outer OOS, create and hash an immutable research-generation registry containing:

- economic/behavioral rationale;
- exact signal/entry/exit logic;
- strategy families;
- symbols, sides and timeframes;
- feature/indicator candidates;
- parameter ranges and constraints;
- sizing and execution policies;
- cost/funding scenarios;
- data and coverage requirements;
- inner/outer folds, warmup, purge and embargo;
- objective and tie-breaker;
- complete candidate/search budget;
- root seed;
- statistical/risk gates;
- handling of current partial periods and fold-boundary positions.

Once outer evaluation starts, do not add candidates, remove losers, change ranking/tie-breaking, modify folds/costs/gates, drop bad years/symbols or add a filter suggested by outer losses.

Any new idea after viewing validation results is a new generation. The viewed history is labelled reused/contaminated for the new decision.

### 15.2 Diagnose raw edge before complex exits

Before broad TP/SL or feature optimization, run a causal event study on the unchanged hypothesis:

- post-cost forward returns by horizon;
- MFE and MAE;
- direction and signal subtype;
- holding-time distribution;
- regime and liquidity;
- turnover and cost break-even.

If broad post-cost directional expectancy is absent, stop or propose a genuinely new economic hypothesis. Exit optimization cannot reliably manufacture a durable signal edge from noise.

### 15.3 Research discipline

Prefer:

- small, interpretable, economically motivated candidate sets;
- dimensionless/volatility-normalized parameters where appropriate;
- shared or hierarchical parameters across symbols;
- parameter plateaus rather than peaks;
- lower complexity/turnover when performance is comparable;
- explicit ablations showing each feature’s incremental value.

Reject:

- unrestricted grids/random search until something passes;
- indicator soup;
- adding a filter after every historical loss;
- optimizing primarily for WR;
- isolated maximum Sharpe;
- symbol-specific winners chosen from OOS;
- complex ML on inadequate observations;
- selecting fleet membership on standalone outer results.

Timeframes, sides, symbols, indicator families, multi-TP/BE choices and per-symbol parameters are all trials. Record them.

Long and short should be evaluated separately because their economics and market regimes may differ. A one-sided strategy is acceptable if the side was selected within the registered validation design and has a clear rationale. Do not require symmetry or select the winning side post hoc without counting that choice.

### 15.4 Expansion sequence

Do not automatically optimize every altcoin/forex/commodity after a BTC/ETH result. Expansion is a new registered experiment:

1. verify exact venue/product data and executable rules;
2. test the frozen transferable hypothesis/parameters first;
3. evaluate cross-symbol robustness;
4. allow symbol-specific tuning only inside inner validation with adequate evidence;
5. validate the combined shared-wallet portfolio;
6. retain all tested symbols, including failures, in the trial history.

## 16. True nested walk-forward and lockboxes

### 16.1 Outer and inner roles

Use chronological rolling or expanding nested walk-forward.

For each outer fold:

1. define `outer_train` ending before `outer_test`;
2. create chronological inner folds entirely inside `outer_train`;
3. perform every choice inside inner validation: family, features, parameters, symbol, side, timeframe, exits, execution policy and portfolio membership;
4. apply the preregistered objective/tie-breaker;
5. select exactly one complete candidate/portfolio;
6. freeze it before `outer_test`;
7. evaluate it once on `outer_test`;
8. never expose outer metrics to the selector for that generation.

The outer loop evaluates the complete selection procedure, not an outer leaderboard of candidates.

### 16.2 Boundary handling

- Use half-open intervals `[start, end)`.
- Warmup data may precede the scored interval but cannot leak targets/selection.
- Purge trades/labels crossing boundaries when required.
- Embargo reflects maximum information overlap/hold duration when required.
- Explicitly define whether folds start flat or inherit a causally simulated position/state.
- Do not duplicate trades or cashflows at boundaries.
- Incomplete current folds are diagnostic, not zero-valued completed folds.

### 16.3 Required outer outputs

Produce:

1. stitched chronological outer-OOS wallet/equity for the adaptive inner-selection algorithm;
2. fixed-candidate outer slice results where the complete preregistered candidate matrix exists, for diagnostics/PBO;
3. per-fold selections and metrics;
4. one consolidated trade/fill/cashflow ledger.

Headline metrics come from the stitched outer-OOS wallet/trades. Do not average fold Sharpes, PFs, WRs or drawdowns into headline values. Fold results diagnose stability and worst cases.

If a global winner/fleet is chosen after comparing outer results, those results have become selection/validation data. Label them `OOS_USED_FOR_SELECTION`; do not call the selected result untouched OOS.

### 16.4 Final historical holdout and forward lockbox

A historical holdout may be opened once for one fully locked decision. Comparing several candidates or changing anything after seeing it contaminates it.

Previously viewed history cannot become untouched again through a new script or reconstructed folds. Only data arriving after the final code/config/gate freeze can be a pristine forward lockbox.

Before a forward stage, register:

- start time and access log;
- code/config/data-spec/risk hashes;
- minimum calendar duration;
- minimum signals/trades/fill observations;
- reconciliation and performance gates;
- rules for missing/partial data;
- no-retuning commitment.

Do not repeatedly inspect and tune against partial lockbox performance. Calendar time and sample count are both necessary; sparse strategies wait longer rather than lowering the evidence requirement.

## 17. Metrics: one authoritative implementation

### 17.1 Canonical return series

The primary performance series is chronological periodic marked-to-market wallet/equity returns. For continuously traded crypto, daily UTC is the default reporting interval unless the project preregisters another economically justified interval.

Include:

- realized and unrealized PnL;
- fees, spread/slippage and funding;
- idle/flat days;
- rejected/skipped orders through their effect on the actual path;
- deposits/withdrawals separately;
- liquidation and ruin.

Do not use closed-trade returns as the portfolio-return series.

### 17.2 Sharpe and uncertainty

Report explicit names and units:

- `sharpe_daily_raw` or the raw periodic equivalent;
- `sharpe_annualized` with calendar factor;
- risk-free assumption;
- observation count and missing/flat-day treatment;
- confidence/PSR diagnostics;
- autocorrelation/HAC-adjusted or block-bootstrap sensitivity where applicable.

For 24/7 crypto under an IID display convention:

`SR_annualized = SR_daily * sqrt(365)`

But do not assume square-root annualization is inferentially exact under serial dependence. Report a dependence-aware diagnostic.

Never:

- use trade-return Sharpe as the deployment headline;
- average fold Sharpes as the headline;
- feed annualized Sharpe into a PSR/DSR formula expecting per-period Sharpe and per-period sample size;
- hide undefined/unstable Sharpe from sparse or flat returns.

### 17.3 Profit factor, win rate and expectancy

Canonical pooled profit factor:

`PF = total gross winning net-trade PnL / abs(total gross losing net-trade PnL)`

Use one declared treatment for fees/funding and apply it consistently. Prefer fully net trade/cashflow economics for the headline.

Rules:

- never cap PF at 99 or another sentinel;
- never average fold PF for the headline;
- zero gross loss is infinity/undefined with a warning and sample count, not an automatic pass;
- one/few-trade PF cannot pass an evidence gate;
- fold PF is diagnostic only.

Report pooled WR as wins / eligible resolved trades, along with Wilson or equivalent uncertainty and exact treatment of breakeven/partial outcomes.

WR is descriptive, not proof of edge. A strategy can be profitable with WR below 50% when average wins exceed losses, and unprofitable with high WR when rare losses dominate. A WR target becomes a hard gate only when preregistered for a specific operational/economic reason.

Report:

- average and median win/loss;
- payoff ratio;
- expectancy per trade;
- expectancy in R and per notional where meaningful;
- tail loss/CVaR diagnostic;
- MAE/MFE and duration.

### 17.4 Drawdown and return

Use chronological MTM equity for:

- net PnL and total return;
- CAGR/annualized return where meaningful;
- maximum drawdown magnitude;
- drawdown duration and time under water;
- Calmar;
- exposure and turnover;
- maximum concurrent exposure/margin use.

Do not use realized-only drawdown or average fold drawdown as the headline.

### 17.5 Fold and pooled reporting

Headline metrics come from stitched OOS. Also report each complete fold with:

- dates and evidence class;
- selected candidate;
- trade count and coverage;
- PnL, expectancy, PF, WR, Sharpe and MDD;
- costs and rejects;
- completion status.

Incomplete folds remain `PARTIAL_DIAGNOSTIC`. Insufficient-trade folds remain `INSUFFICIENT_EVIDENCE`. Do not insert Sharpe/PF/WR = 0 to make them averageable, and do not let their exclusion hide poor coverage.

### 17.6 PSR, DSR and MinTRL

Probabilistic/Deflated Sharpe calculations MUST use consistent units and documented formulas.

Store/report:

- observed per-period Sharpe;
- benchmark in the same units;
- observation count;
- skewness and declared kurtosis convention;
- raw and effective trial count assumptions;
- distribution of trial Sharpes/expected maximum Sharpe as required;
- PSR/DSR probability;
- Minimum Track Record Length or equivalent power/sample diagnostic;
- sensitivity to effective trials such as 10, 50, 100, 500 and 1,000 when uncertainty is material.

The trial count includes reconstructable searches, discarded variants, manual alternatives, timeframes, sides, symbols, exits and previous rounds that influenced the choice. Do not reset it because the file or optimizer name changed.

More relevant trials must not mechanically make a conservative DSR more favorable because of an implementation/sign error. Add reference tests.

### 17.7 PBO/CSCV

Deployment-grade PBO is valid only from a complete aligned candidate-by-time-block return matrix for the declared candidate universe.

Do not compute PBO from:

- fold summary metrics;
- winner-only returns;
- only saved candidates;
- an incomplete matrix;
- unrelated candidate histories with inconsistent blocks.

Report candidate count, block count, combinations, metric, degradation distribution and uncertainty. If requirements are not met, report `PBO_UNAVAILABLE_INSUFFICIENT_MATRIX`. Unavailable is not zero and not PASS.

PBO only covers the included universe; it does not erase earlier research selection. If PBO is methodologically inapplicable, preregister an alternative multiple-testing/overfitting diagnostic and retain the limitation.

### 17.8 Required headline table

For each serious candidate/portfolio report at least:

- evidence class and exact period;
- target venue/product and data coverage;
- trades and trades/month;
- net PnL and return;
- expectancy;
- pooled PF and WR with uncertainty;
- daily/raw and annualized Sharpe;
- dependence-aware Sharpe/uncertainty;
- Sortino and Calmar;
- MTM MDD and duration;
- exposure and turnover;
- average win/loss and payoff;
- worst trade/fold/quarter/year;
- fees, slippage, funding;
- rejects/skips/missed fills;
- liquidation/ruin count;
- DSR and PBO status;
- parameter/regime concentration;
- shared-wallet result when relevant.

## 18. Robustness, concentration and falsification

Robustness analysis is performed on a preregistered neighborhood without choosing a new OOS winner.

Test as applicable:

- neighboring parameter values/heatmaps;
- selection turnover across inner/outer folds;
- leave-one-year-out and leave-one-fold-out;
- result excluding best trade/year/regime;
- bull, bear, sideways, high/low-volatility regimes;
- positive/negative funding;
- liquidity/spread stress;
- cross-venue proxy sensitivity, clearly labelled;
- cost, latency and gap stress;
- block-bootstrap confidence intervals;
- risk-of-ruin simulation;
- feature ablation;
- long/short and symbol contribution.

Reject or flag:

- an isolated parameter spike;
- performance dominated by one trade/year/regime;
- severe selection turnover;
- a cost-fragile result;
- a result whose effective order sizes violate risk;
- a portfolio result dominated by correlated exposure.

Default concentration diagnostics, unless the project freezes stricter/different values:

- best year no more than 40% of total positive PnL;
- PnL excluding best year remains positive;
- no single trade/fold explains the entire edge.

These are policy defaults, not theorems. Never change them after seeing the final evidence merely to obtain PASS.

## 19. Frozen research gates

The default gate profile is frozen in `FROZEN_DEFAULT_GATES_V2_1.md`. Copy its values into the project profile before a new research generation begins. Write, timestamp and hash the project’s exact gates before outer OOS. Do not relax them for the current research generation. A failure may motivate a new hypothesis/generation, but previously viewed periods are recorded as reused.

### 19.1 Mechanical gates — all relevant items mandatory

- target venue/product data parity;
- data quality and coverage;
- signal causality;
- live/backtest signal/decision parity;
- executable quantity/price/exit legs;
- entry/exit timing and intrabar chronology;
- fee/spread/slippage model;
- signed historical funding for perps;
- wallet/accounting reconciliation;
- margin/liquidation validity;
- shared-wallet validity for jointly deployed bots;
- deterministic reproducibility;
- no critical UNKNOWN.

Any mechanical failure blocks historical readiness regardless of profit.

### 19.2 Default statistical gates

Unless the completed project profile freezes a stricter or explicitly justified alternative before OOS, every item below is required for historical `SHADOW_READY`:

- at least five non-overlapping complete outer folds;
- every gating fold contains at least the preregistered minimum evidence, default 10 resolved trades; redesign longer folds before OOS for a legitimately sparse strategy rather than scoring tiny folds;
- at least 50 pooled resolved outer-OOS trades; 100 or more is preferred;
- 50–99 pooled trades are labelled `SPARSE_EVIDENCE` and require PSR/MinTRL, DSR, bootstrap and forward-evidence safeguards; fewer than 50 cannot earn `SHADOW_READY` under the default profile;
- stitched nested outer-OOS net PnL > 0 after all baseline costs;
- pooled outer-OOS net expectancy > 0;
- pooled outer-OOS PF >= 1.20;
- annualized Sharpe from daily MTM wallet returns >= 1.0;
- dependence/HAC-adjusted annualized Sharpe >= 0.75 using a frozen documented estimator;
- positive net PnL and PF > 1 in at least 80% of eligible complete outer folds;
- at least 90% of the preregistered dependence-aware block-bootstrap resamples have pooled net expectancy > 0;
- the HAC lag/bandwidth rule and block-bootstrap method/block length are selected from training-only information or frozen before outer OOS; use a deterministic seed and at least 10,000 bootstrap resamples;
- no catastrophic fold under the frozen risk budget;
- DSR probability >= 0.95 using consistent nonannualized units, the complete relevant trial history and a preregistered defensible trial-count method;
- raw/effective-trial DSR inputs and sensitivity are reported even when only the preregistered conservative DSR is gated;
- PBO <= 0.20 when a valid complete aligned candidate matrix exists;
- when PBO is methodologically unavailable, report `PBO_UNAVAILABLE_INSUFFICIENT_MATRIX`; it does not by itself block `SHADOW_READY` if genuine nested OOS, complete trial registration, DSR and bootstrap gates all pass, but no PBO PASS may be claimed;
- sufficient track record/observations under preregistered PSR/MinTRL/power criteria;
- parameter neighborhood and selection stability;
- PnL excluding the best trade and best year remains positive;
- best year contributes no more than 40% of total positive PnL;
- no confirmed liquidation or wallet ruin.

Do not use mean fold Sharpe/PF/WR for these pooled gates.

There is no universal WR gate. Always report WR and the user’s preferred target. If WR is a hard strategy requirement, freeze the threshold and whether the point estimate or confidence-bound must pass before OOS.

### 19.3 Cost, drawdown and portfolio gates

- baseline and the preregistered moderate combined stress remain net positive;
- moderate-stress pooled PF >= 1.05;
- the moderate stress reruns the simulation and includes all-taker execution unless maker fills are independently supported, at least 2x baseline directional slippage/spread or the observed shadow 95th percentile when available, actual historical funding and the frozen latency/gap assumptions;
- a severe scenario using at least 3x baseline slippage plus adverse funding, delay and gap assumptions is reported but is not automatically a pass gate;
- baseline actual-wallet MDD <= 20% of explicitly allocated strategy capital unless a stricter profile limit exists;
- moderate-stress MDD <= 25% unless a stricter profile limit exists;
- maximum margin utilization <= 60% unless a stricter profile limit exists;
- estimated probability of ruin or breaching the frozen loss limit under the preregistered dependence-aware stress model < 1%;
- no hidden recapitalization;
- rejected orders are within policy and never omitted;
- shared-wallet result passes even if standalone bots pass.

The profile must define the capital base so MDD and margin percentages are not calculated on artificial cash. Product-specific stress bps may be stricter than the multipliers above and must be frozen before OOS. If the user has not defined the necessary capital/risk limits, historical research may continue, but live readiness is blocked.

### 19.4 Insufficient evidence

Low trade count does not become a pass because Sharpe/PF is large. It receives `INSUFFICIENT_EVIDENCE` and remains research-only until enough independent evidence accumulates.

Do not universally reject a legitimately low-frequency strategy solely because it cannot reach an arbitrary trade count. Predefine a sample/power requirement appropriate to its frequency and report sensitivity at practical counts. Sparse strategies need more calendar time and forward observation, not weaker statistics.

Under the frozen default profile, changing the 50-trade minimum or 10-trade fold eligibility is permitted only before outer OOS, with explicit justification from PSR/MinTRL/power calculations and a longer forward requirement. It is not permitted merely because a preferred candidate failed.

## 20. Readiness, failure and authorization are separate

Store three fields:

1. **Readiness level** — highest stage earned by evidence.
2. **Failure/blocker codes** — exact reasons a higher stage was not earned.
3. **Human authorization** — exact live action approved or not approved.

### 20.1 Readiness levels

`RESEARCH_ONLY`

- default;
- exploratory/contaminated/incomplete evidence or unresolved critical assumptions;
- no live orders.

`SHADOW_READY`

- canonical engine and mechanical gates pass;
- target-venue nested historical gates pass;
- frozen code/config/risk/evidence hashes exist;
- live ingestion can run without orders;
- no deployment permission implied.

`MICRO_LIVE_CANDIDATE`

- SHADOW_READY remains valid;
- preregistered forward shadow/reconciliation requirement completed; default minimum is both 90 calendar days and 30 actionable signal decisions, with at least 20 executable hypothetical fill observations where the strategy generates entries;
- observed spread/slippage/fill/rejection behavior fits tested bounds;
- protective orders, quantity, restart and fail-closed behavior pass;
- zero unexplained action-level signal/order mismatches and zero safety-critical operational failures;
- no strategy retuning during the shadow window;
- risk is deliberately minimal and capped;
- explicit user approval is still required.

`SCALE_CANDIDATE`

- sufficient micro-live calendar/sample evidence; default minimum is both 180 calendar days and 50 resolved live trades, with 100 preferred; PSR/MinTRL/power analysis may require more, and sparse strategies require longer calendar observation rather than weaker gates;
- actual fills/costs/funding/behavior reconcile with the freeze;
- live net expectancy remains positive, live PF >= 1.10 and realized drawdown remains inside the frozen prediction/risk envelope;
- no unresolved operational failure;
- shared-wallet/portfolio gates pass;
- a gradual predefined scale schedule exists;
- each material risk increase still requires explicit approval.

### 20.2 Failure/blocker codes

Use precise codes such as:

- `ENGINE_INVALID`
- `DATA_PARITY_FAIL`
- `DATA_GAP_FAIL`
- `CAUSALITY_FAIL`
- `LIVE_BT_PARITY_FAIL`
- `EXECUTION_UNKNOWN`
- `FUNDING_PARITY_FAIL`
- `ORDER_GRANULARITY_FAIL`
- `LIQUIDATION_VALIDATION_FAIL`
- `PORTFOLIO_VALIDATION_FAIL`
- `RESEARCH_FAIL`
- `INSUFFICIENT_EVIDENCE`
- `SHADOW_FAIL`
- `MICRO_FAIL`
- `RISK_POLICY_UNDEFINED`
- `AUTHORIZATION_NOT_GRANTED`

A profitable-looking result never suppresses a blocker. The most conservative valid readiness wins when evidence conflicts.

### 20.3 Deployment certificate/interlock

A live runner SHOULD require a time-limited deployment certificate containing:

- strategy/research-core/live code hashes;
- config/project-profile hashes;
- evidence/audit hash and readiness;
- approved symbols/account/margin mode;
- quantities, leverage and risk limits;
- approval scope, timestamp and expiry.

Startup refuses new risk if hashes/state differ, the certificate is absent/expired, a blocker is unresolved or authorization does not cover the action.

## 21. Shadow, forward and live reconciliation

Freeze before shadow/micro-live:

- strategy/core/live code hashes;
- config/profile/risk hashes;
- data schema/source specification;
- expected signal/order behavior;
- symbols, sides, quantities, leverage and margin;
- TP/SL/max hold;
- order and retry policy;
- fees/slippage/funding envelope;
- portfolio limits.

For every decision/event, store:

- source candle hash and timestamps;
- indicator/signal decision;
- desired normalized order;
- API acknowledgement/rejection;
- order updates and fills;
- maker/taker state and fees;
- expected versus actual entry;
- TP/SL/protective-order state;
- funding;
- position/balance/margin state;
- expected versus actual exit/PnL;
- discrepancy type and resolution.

Required reconciliation metrics include:

- signal match rate;
- order acceptance and fill rate;
- missed/duplicate order rate;
- entry latency;
- median and tail slippage;
- fee/funding difference;
- exit/protective-order match;
- PnL difference;
- unexplained discrepancy count.

Do not silently exclude mismatches. A safety-critical discrepancy fails the stage until understood, corrected, tested and re-observed.

Historical robustness and operational shadow answer different questions. Shadow can validate live data, timing and execution assumptions; a short shadow period does not prove economic alpha.

## 22. Live operational safety

Before any live candidate, implement and test:

- unique idempotent client order IDs;
- duplicate-order/process prevention and singleton lock;
- server/exchange clock-skew checks;
- stale/incomplete candle protection;
- WebSocket disconnect/reconnect and sequence-gap handling;
- REST snapshot reconciliation at startup, reconnect and intervals;
- partial-fill and cancellation handling;
- reduce-only exits and protective-stop confirmation;
- orphan-order detection/cleanup policy;
- exchange versus local position/order reconciliation;
- restart recovery from authoritative exchange state;
- position mismatch shutdown;
- maximum position/notional/exposure/margin limits;
- daily/weekly loss and drawdown kill switches;
- fee/funding/margin buffers;
- API error/rate-limit/backoff behavior;
- structured redacted audit logs and heartbeat;
- manual emergency stop;
- inability of one strategy to control another’s orders unintentionally.

Fail closed: uncertain state prevents new exposure. Existing risk is reconciled and protected according to the frozen incident policy.

Use WebSocket for timely streaming where supported, but do not treat it as the sole truth. A running process or named `screen` is not proof of health. Confirm fresh data, authenticated state, order/fill updates, protection, positions, balance, heartbeat, database freshness and singleton state.

Automatic restart is permitted only for an already authorized deployed service. After restart, no new entry is allowed until full reconciliation succeeds. Process supervision (`systemd`, Docker, named `screen` plus a watchdog, etc.) is a project profile choice; reliability and safe state recovery are the requirements.

### 22.1 Decision cadence and polling policy

A close-based strategy decides on candle closes, so the live loop schedule must be driven by the bar boundary, not by an arbitrary wall-clock poll. Recomputing features and signals many times inside one forming bar cannot produce an earlier valid decision; it only consumes rate limit, CPU and log volume, and it invites acting on an incomplete candle.

Every live/shadow loop for a close-based signal MUST implement the four-phase cycle:

1. **Idle** until `lead_sec` before the next close, performing only cheap heartbeats.
2. **Close window**: from the close onward, poll every `close_poll_sec` using the cheapest available freshness check (incremental closed-candle fetch or stream event), not a full recomputation.
3. **Decide once** when the newly closed bar is observed: features, signal, entry/exit, protective orders, bar-based exits.
4. **Idle again** until the next close.

A bare `sleep(timeframe)` is NOT acceptable: clock skew, restart offsets and late venue publication silently shift or skip decisions. The pre-close wake-up and the post-close confirmation window are both required.

Default per-timeframe values. A project MAY freeze different values in its profile; it MUST record them.

| Timeframe | `lead_sec` | `close_poll_sec` | `confirm_timeout_sec` | `heartbeat_sec` |
|-----------|-----------|------------------|-----------------------|-----------------|
| 1m  | 5   | 1  | 30  | 60   |
| 3m  | 5   | 1  | 45  | 60   |
| 5m  | 10  | 2  | 60  | 120  |
| 15m | 15  | 3  | 90  | 300  |
| 30m | 20  | 3  | 120 | 300  |
| 1h  | 30  | 5  | 180 | 600  |
| 2h  | 45  | 5  | 240 | 900  |
| 4h  | 60  | 5  | 300 | 900  |
| 6h  | 60  | 5  | 300 | 1800 |
| 12h | 90  | 10 | 600 | 1800 |
| 1d  | 120 | 10 | 900 | 3600 |

Unlisted timeframes use bounded fractions of the bar length: `lead_sec = clip(0.01*bar_sec, 5, 120)`, `close_poll_sec = clip(bar_sec/720, 1, 10)`, `confirm_timeout_sec = clip(0.05*bar_sec, 30, 900)`, `heartbeat_sec = clip(0.05*bar_sec, 60, 3600)`.

Required invariants:

- decide only on closed bars, verified by timestamp (`bar_open + bar_ms <= now`), never on a forming candle;
- align bars to the venue anchor (UTC epoch for intraday/daily; the venue's week start for weekly) and record the anchor;
- exactly one decision per bar, enforced by a persisted `last_processed_bar_ts`, so reconnects, duplicate wake-ups and restarts cannot double-process or double-order;
- on startup, run one immediate catch-up decision when the last processed bar is older than the last closed bar, then re-align; a restart must not silently skip a closed bar;
- if the bar does not arrive within `confirm_timeout_sec`, log a distinct stale-data event, take no action on stale data, and wait for the next close;
- if more than one bar was missed, log a distinct gap event and reconcile before new risk;
- heartbeats reconcile exchange position, protective orders and stream freshness only; they never compute signals or open risk;
- protective orders live on the exchange so that idling between closes cannot leave a position unprotected; a position without confirmed protection is a heartbeat alarm;
- bar-based exits (`max_hold`, signal-flip) are evaluated at the same close as entries, matching backtest semantics;
- intrabar-triggered logic (stops, trailing, liquidation-avoidance) is event-driven from the stream and is explicitly out of scope for the bar-close cycle; if a strategy needs it, register it, model it in the backtest and document the separate cadence;
- stagger or jitter multi-symbol fleets so simultaneous closes do not create a rate-limit burst.

Scheduling parameters are execution configuration, not strategy parameters: they must not be tuned on OOS performance. Changing the decision cadence changes live/backtest parity and requires a parity re-check.

## 23. Engineering rules

- Run feature calculation, model training, backtest, walk-forward and optimization locally by default. VPS is live/shadow only unless explicitly changed.
- Use vectorized NumPy/pandas/SQL for bulk feature, signal and metric calculations where causal and correct.
- Avoid `iterrows()`, row-wise `apply` and repeated full scans when vectorization/caching is clear.
- Use sequential chronological event loops for path-dependent fills, positions, funding, margin and portfolio state. Correct event order matters more than eliminating every loop.
- Cache identical indicators/features by data/config hash; do not recompute them per candidate.
- Parallelize independent candidates/folds only when registry writes, seeds and resources remain deterministic and safe.
- Prefer pure deterministic functions and focused interfaces.
- Integrate fixes into the canonical pipeline; one-off repair scripts may diagnose but should not become permanent parallel truth.
- Test after changes. If live code changes, readiness is invalidated; do not restart/deploy without explicit authorization.
- Update project memory after meaningful changes, including current state, decisions, tests, experiment log, blockers and TODO.
- Use visual trade plots (for example finplot) when requested or when plots materially help diagnose event order/fill discrepancies. Plots are diagnostics, not evidence by themselves.

## 24. Mandatory automated tests

Relevant tests are blocking; skipped relevant tests prevent PASS.

### 24.0 Conformance identifier registry, golden fixtures and result stamping

A prose checklist does not prevent defects. A reader who has just written a simulator will read "same-bar entry/exit" and believe it is covered, and a green test suite will appear to confirm it. Enforcement must be mechanical.

**Identifiers.** Every mandatory behaviour in this section carries a stable identifier of the form `AREA-NNN` (`DATA`, `CAUS`, `EXEC`, `FUND`, `QTY`, `METR`, `VALD`, `PORT`, `LIVE`). Identifiers are permanent: they are never renumbered or reused, and retired ones are marked retired.

**Test binding.** Each identifier MUST be bound to at least one automated test, and the binding MUST be discoverable from the test source without human interpretation — for example a marker, a decorator, or the identifier in the test name or docstring. A test that exercises a behaviour without declaring its identifier does not satisfy it.

**Coverage checker.** The repository MUST provide an automated conformance checker that:

1. reads the identifier registry required for its declared contract;
2. scans the test suite for declared bindings;
3. runs those tests;
4. **fails the build when any required identifier has no binding, when a bound test is skipped, or when a bound test fails.**

A missing test MUST be a hard failure, exactly like a failing test. This is the specific mechanism that would have caught the entry-bar defect: the repository had a green suite, but no test declared `EXEC-010`, and nothing objected to its absence.

**Golden fixture pack.** Behaviours whose correct answer is exactly computable MUST be verified against a shared, versioned fixture pack rather than project-local assertions. Each fixture specifies deterministic inputs — bars, signals, instrument specification, fee/slippage/funding configuration — and the exact expected outputs: exit reason, exit price, fees per fill, funding charged, quantity, realized profit and loss, and equity path. The pack is content-hashed. Identical fixtures are applied to every engine in every repository, so engines are graded against one arbiter instead of each against its own author's understanding.

**Result stamping.** Every result artifact (JSON report, database run row, summary document) MUST embed a conformance stamp: engine name and version, engine commit, fixture-pack hash, checker run timestamp, and the pass/fail state with the count of required and satisfied identifiers. Required report tables MUST print it. **A number produced without a green conformance stamp is not quotable evidence, in any report, at any readiness level.** This closes the loop where a defect is found, fixed and documented, while the old numbers keep circulating in summaries.

**Minimum required execution identifiers.** For any repository that simulates bracketed orders on a perpetual or futures product:

| Identifier | Behaviour that MUST be locked by a test |
| --- | --- |
| `EXEC-001` | Signal computed from a bar's close cannot fill at that close; it fills at the next executable price. |
| `EXEC-002` | Entry fill price includes directional slippage; slippage moves the price and is never folded into the fee rate. |
| `EXEC-003` | Fee charged per fill, on executed notional, at the correct maker/taker rate for that fill's order type. |
| `EXEC-004` | Gap through the stop fills worse than the stop, not at the stop. |
| `EXEC-005` | Take-profit limit touch fills at the limit price with no favorable exit slippage; a market-triggered take profit does incur slippage. |
| `EXEC-006` | Both stop and target inside one bar resolves adversely, or by lower-timeframe replay, and is labelled ambiguous. |
| `EXEC-007` | Stop and liquidation inside one bar resolves in the correct order for the actual margin model. |
| `EXEC-008` | Maximum hold exits at the correct bar and price, counted from the entry bar index. |
| `EXEC-009` | Reduce-only and position-mode semantics match the live venue. |
| `EXEC-010` | **Entry bar stop:** entry fills at a bar and that same bar's range takes out the stop — the trade MUST close on its entry bar, with `exit_ts == entry_ts` and both fees charged. |
| `EXEC-011` | **Entry bar target:** same, for the take profit. |
| `EXEC-012` | **Entry bar both:** entry bar contains stop and target — the adverse one is taken. |
| `EXEC-013` | **Entry bar liquidation:** entry bar reaches the liquidation price — liquidation is resolved on the entry bar. |
| `EXEC-014` | **Quiet entry bar:** an entry bar that touches nothing does NOT close, and a later bar still resolves it correctly. This is the paired negative control; without it an engine can pass `EXEC-010` by closing everything immediately. |
| `EXEC-015` | **Entry bar funding:** a position opened and closed on the same bar is still charged the funding settlements falling inside its holding window. |
| `EXEC-016` | **Same-bar hold count:** a trade closed on its entry bar reports a hold of zero, and maximum-hold arithmetic is identical in research and live. |
| `EXEC-017` | Retry is idempotent; a retried order never becomes two positions. |

`EXEC-010` through `EXEC-016` are jointly non-negotiable and no repository may declare execution parity without all seven bound, run and passing. `EXEC-014` MUST be present alongside `EXEC-010`; a suite containing only positive cases is not conformance.

### Data and time

- duplicate/gap/incomplete candle detection;
- OHLC invariants and nonpositive price rejection;
- launch/delivery boundaries;
- UTC and session/resampling anchors;
- missing child bars invalidate parents;
- aware/naive join prevention;
- point-in-time auxiliary feature availability;
- missing feature cannot soft-pass;
- coverage computation.

### Causality and parity

- truncation and future-mutation invariance;
- pivot confirmation timestamp;
- HTF completion/lag;
- no retroactive signal-close fill;
- batch/streaming parity;
- live/backtest golden signal/level hashes;
- fold-fitted scaler/threshold;
- re-entry/cooldown/max-hold parity.

### Execution

- next-executable timing and latency (`EXEC-001`);
- PostOnly cancellation/missed/partial fill;
- market IOC/price-protection rejection where applicable;
- fee per execution leg and maker/taker classification (`EXEC-003`);
- directional spread/slippage (`EXEC-002`);
- gap-through-stop (`EXEC-004`);
- TP-limit fill semantics (`EXEC-005`);
- TP/SL dual touch (`EXEC-006`);
- stop versus liquidation ordering within one bar (`EXEC-007`);
- **entry-bar exit resolution: stop, target, both, liquidation, quiet control, funding, hold count (`EXEC-010` … `EXEC-016`) — all seven mandatory, see Section 9.6**;
- maximum-hold bar and price (`EXEC-008`);
- break-even/trailing event order;
- TP-limit non-fill;
- reduce-only/position-mode behavior (`EXEC-009`);
- idempotent retry/no duplicate order (`EXEC-017`).

### Funding

- positive funding: long pays/short receives under the product convention;
- negative funding reverses cashflow;
- no charge while flat;
- exactly one settlement charge;
- correct boundary/open/close behavior;
- funding changes cash/equity/margin chronologically.

### Quantity, margin and wallet

- tick/step rounding and minimum notional;
- risk-cap skip instead of oversize;
- every multi-TP leg/residual;
- no zero-quantity exit;
- margin rejection;
- leverage invariant for fixed-quantity price PnL;
- maintenance tier and Mark liquidation;
- continuous stop versus liquidation ordering and gap exceptions;
- cashflow/equity reconciliation;
- no trading after ruin without declared deposit.

### Metrics and validation

- pooled/uncapped PF and no-loss edge case;
- pooled WR/PnL versus fold means;
- MTM versus realized-only drawdown;
- daily/raw versus annualized Sharpe;
- serial-dependence diagnostic;
- PSR/DSR unit/reference calculations and trial-count monotonicity;
- PBO refuses incomplete matrices and passes synthetic reference cases;
- incomplete/one-trade fold cannot pass;
- half-open fold boundaries/no duplicate trades;
- purge/embargo and crossing positions;
- selector cannot read outer test;
- exactly one outer selection per fold;
- full trial registration, including failures;
- holdout/lockbox access logged;
- config change invalidates freeze.

### Portfolio and live safety

- simultaneous signals and deterministic priority;
- shared margin and order rejection;
- one-way/hedge and same-symbol strategy conflicts;
- component versus portfolio ledger reconciliation;
- duplicate process and stale data fail closed;
- WebSocket gap plus REST recovery;
- restart state reconciliation;
- bar-close scheduling: exactly one decision per closed bar, no decision on a forming bar, correct bar anchoring, restart catch-up without skipping or repeating a bar, and a late/absent bar producing a stale-data event instead of an action;
- missing/failed protective order blocks new risk;
- deployment certificate invalidates after hash/config expiry/change;
- no credentials in artifacts.

## 25. Required workflows

### 25.1 Audit an existing bot

1. Inspect repository instructions, dirty state, project profile, evidence, databases, canonical backtest and live code.
2. Reconstruct the exact current live contract and account topology without printing secrets.
3. Audit in this order: data -> causality -> signal parity -> execution -> costs/funding -> quantity -> margin/liquidation -> wallet/portfolio -> metrics -> selection/validation -> live operations.
4. Run baseline tests and preserve old results as legacy evidence.
5. On a defect, mark affected results invalid, add a regression test, fix the canonical engine and rerun.
6. Compare old versus corrected results with evidence classes.
7. Do not invent alpha, enable multi-TP, increase size/leverage or expand symbols until the corrected engine and validation pass.
8. Update SQLite evidence and project memory.
9. State explicitly that nothing was deployed unless separately authorized.

### 25.2 Research a new strategy family

1. Complete the project contract and risk-policy blockers needed for the stage.
2. Validate target-product data and the research core.
3. Register the economic hypothesis, candidate budget, folds, objective, costs and gates.
4. Run a causal event study/unchanged baseline.
5. If the premise survives, run bounded inner selection and nested outer evaluation.
6. Record all trials, failures and interruptions.
7. Calculate stitched OOS metrics, uncertainty, stress, concentration and shared-wallet result.
8. Stop at the registered budget. If no candidate passes, preserve evidence and abandon/reformulate rather than expanding opportunistically.
9. A passing historical result may only be proposed for a separately authorized shadow stage.

### 25.3 Optimize TP/SL, multi-TP, break-even or leverage

Treat each design as a new candidate dimension. First prove:

- engine/live parity;
- executable child quantities;
- chronological intrabar event order;
- fees per leg;
- post-fill TP/SL calculation;
- exact margin/liquidation behavior.

Select only inside inner validation. Leverage is optimized for operational capital/risk constraints after edge and quantity are frozen, never for PnL appearance.

### 25.4 Add new symbols or markets

Create a new generation with exact product data, metadata, costs and sessions. Test transfer of frozen parameters before symbol-specific tuning. Record every symbol; do not hide losers. Revalidate the shared wallet and portfolio priority.

### 25.5 `sitrep`

When the user says `sitrep`, provide a concise complete situation report appropriate to the project:

- current readiness/evidence stage;
- live/shadow health and current positions/orders only if authorized/available;
- latest completed run and timestamp;
- active job, checkpoint, resource/data status and ETA only when defensible;
- data coverage/gaps;
- trials/folds completed versus registered budget;
- stitched OOS result only if legitimately available;
- live metrics and backtest comparison when live evidence exists;
- discrepancies and blockers;
- files/DB records changed;
- next bounded action.

Do not present partial folds or best in-sample trials as final. Do not expose secrets.

## 26. Required final report

Every material audit/research generation ends with:

1. maximum earned readiness, evidence class and confidence;
2. one-line live action: `STOP`, `RESEARCH_ONLY`, `BEGIN/CONTINUE_SHADOW_CANDIDATE`, `MICRO_LIVE_CANDIDATE` or `SCALE_CANDIDATE`—authorization remains separate;
3. exact target venue/product, periods and data coverage;
4. what was and was not tested;
5. code/config/data/profile/standard hashes;
6. data, causality and live/backtest parity verdicts;
7. fill, fee, slippage, funding and intrabar models;
8. desired versus effective quantities and order feasibility;
9. margin/liquidation and wallet reconciliation;
10. nested fold design, selection procedure and complete trial count;
11. stitched outer-OOS headline table plus worst folds;
12. daily/raw and annualized Sharpe with uncertainty;
13. pooled uncapped PF, expectancy and WR uncertainty;
14. DSR inputs/result and PBO matrix/status;
15. base, moderate and severe stress;
16. parameter/regime/best-year/trade concentration;
17. shared-wallet results;
18. forward/shadow/live reconciliation if any;
19. every PASS/FAIL/UNKNOWN gate and exact blockers;
20. tests/commands and pass/fail/skip counts;
21. files changed, SQLite/report paths and `git diff --stat`;
22. pre-existing versus current-task changes;
23. explicit confirmation that no deployment/live mutation occurred unless authorized;
24. what not to do next;
25. the next bounded research/operational decision.

Lead with strict stitched OOS/forward evidence. Do not lead with the best full-history backtest. Do not hide failed candidates, missing data, weak folds or negative results.

Every claimed PASS cites a test, artifact, database query or code location. Avoid vague terms such as “robust,” “safe,” “deployable,” “strict pass” or “near live-ready” unless the corresponding frozen definition demonstrably passed.

## 27. Stop conditions

Stop the current research generation when:

- the preregistered candidate budget is exhausted;
- raw signal expectancy is absent after costs;
- no candidate passes frozen nested gates;
- realistic costs remove the edge;
- results depend on one year/regime/trade or an isolated parameter spike;
- selection turnover/DSR/PBO shows unacceptable overfitting;
- exchange minimum size violates risk;
- shared-wallet result fails;
- evidence is insufficient and requires future data;
- repeated sealed generations of the same economic idea fail.

Do not respond by expanding the grid, adding unmotivated indicators or relaxing gates. Report one of:

- `ABANDON_CURRENT_STRATEGY_FAMILY`;
- `REQUIRES_NEW_ECONOMIC_HYPOTHESIS`;
- `INSUFFICIENT_EVIDENCE_WAIT_FOR_DATA`;
- exact infrastructure/data blocker.

A new campaign needs a distinct documented hypothesis, new bounded budget/generation ID and honest acknowledgement that previously inspected history is reused.

## 28. Forbidden failure patterns

These invalidate affected evidence and require a regression test plus rerun:

- Binance/spot/proxy data presented as target-perpetual parity;
- data before target contract launch treated as native history;
- silent venue/product fallback or splicing;
- signal-close fill after using that close;
- **entry bar exempt from its own stop/target/liquidation — exit checking beginning on the bar after the fill, granting every trade one free bar of immunity;**
- **a separate entry-bar code path instead of one shared exit-resolution function applied to every bar including the entry bar;**
- **a same-bar round trip escaping either fill's fee or the funding inside its holding window;**
- **a green project test suite presented as execution parity when no test declares the mandatory conformance identifiers;**
- **a result quoted from a report that carries no green conformance stamp, or whose engine version cannot be resolved;**
- hidden extra shift between live and backtest;
- percentage-equity quantity mistaken for coin/contracts;
- price scaling or synthetic cash used to fake fractional quantity;
- TP/SL based on signal price when live uses actual fill;
- maker fill assumed from candle touch or at signal close;
- limit-order slippage/non-fill ignored;
- fees charged once per round trip instead of each fill;
- constant/absolute always-pay funding;
- funding applied as a final overlay;
- zero-quantity or non-executable multi-TP leg;
- silent collapse/change of multi-TP behavior;
- leverage selected to improve return or described safe because a stop exists;
- liquidation proxy presented as exchange-accurate;
- Last Price used for a Mark-triggered liquidation;
- realized-only drawdown;
- fake wallet return from summed trade percentages;
- independent equity curves added as a shared wallet;
- portfolio ruin accepted without ledger reconciliation;
- mean fold PF/Sharpe/WR used as headline;
- PF capped at 99;
- trade Sharpe substituted for daily MTM Sharpe;
- annualized Sharpe passed to a daily PSR/DSR formula;
- DSR omitting relevant trials;
- PBO from fold summaries/winners/incomplete matrix;
- OOS used to select/persist a winner, side, symbol or fleet;
- repeated `validate_frozen` runs ranked on the same OOS;
- legacy validation inherited after material change;
- incomplete folds inserted as zero;
- missing features treated as confirmation;
- UTC-aware data joined to naive period keys;
- NaN silently interpreted as pass/fail/no-signal;
- random seed changes not recorded;
- optimizer continuing until something passes;
- user preference such as high WR presented as proof of edge;
- maximum leverage/minimum quantity presented as minimum risk;
- live process restarted/deployed because historical research passed;
- automatic restart opening new risk before reconciliation;
- running process/screen treated as proof of bot health;
- infinite retry loop or non-idempotent order retry;
- full-history winner presented before strict OOS/forward evidence.

When detected:

1. stop optimization/deployment work;
2. mark affected evidence invalid;
3. fix the canonical implementation;
4. add regression coverage;
5. rerun affected experiments;
6. revoke inherited readiness.

## 29. Sources and rationale

The following sources support specific methodological or exchange-mechanics requirements. Numerical gates in Section 19 remain declared research/risk policy, not conclusions guaranteed by these sources.

- Bailey & López de Prado, [The Deflated Sharpe Ratio](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551): selection bias, non-normality, trial history and DSR/MinTRL rationale.
- Bailey, Borwein, López de Prado & Zhu, [The Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253): CSCV/PBO and the need for an appropriate candidate-performance matrix.
- Bailey & López de Prado, [The Sharpe Ratio Efficient Frontier](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1821643): PSR and minimum track-record reasoning.
- Andrew W. Lo, [The Statistics of Sharpe Ratios](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=377260): sampling uncertainty and the limits of naive square-root annualization under serial dependence.
- López de Prado, Lipton & Zoonekynd, [Sharpe Ratio Inference: A New Standard for Decision-Making and Reporting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5520741): inference, power, minimum sample length and multiple-testing-aware reporting.
- López de Prado, [Confidence and Power of the Sharpe Ratio under Multiple Testing](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3193697): type-I/type-II error and power considerations under multiple testing.
- Bybit V5 API, [Get Instruments Info](https://bybit-exchange.github.io/docs/v5/market/instrument): product metadata including launch time, tick/quantity/notional rules, leverage limits and funding interval; the documentation also warns that some limits change.
- Bybit V5 API, [Get Funding Rate History](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate): signed historical rates, settlement timestamps and symbol-specific funding intervals.
- Bybit V5 API, [Get Mark Price Kline](https://bybit-exchange.github.io/docs/v5/market/mark-kline): separate historical Mark Price series.
- Bybit V5 API, [Place Order](https://bybit-exchange.github.io/docs/v5/order/create-order): market-order IOC protection, PostOnly cancellation, trigger sources, position modes, reduce-only and TP/SL order semantics.
- Bybit Help Center, [USDT perpetual/futures FAQ](https://www.bybit.com/en/help-center/article/FAQ-USDT-Perpetual-and-Expiry-Contracts): liquidation is triggered from Mark Price and behavior differs by margin mode.
- Bybit Help Center, [Funding Fee Calculation](https://www.bybit.com/en/help-center/article/Funding-fee-calculation): funding can reduce available/position margin and affect liquidation risk.

Design judgments introduced by this standard include the layered rule architecture, the exact default thresholds, sample minima, stress multipliers, readiness taxonomy, capital-efficient leverage policy and reporting workflow. They are intended to make evidence conservative, reproducible and operationally actionable; they are frozen policy for V2.1, not universal empirical facts or guarantees of profitability.
