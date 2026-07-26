# tradesim versus TRADING_BOT_CURSOR_RULES_V2 — discrepancy report

Reviewed 2026-07-25 against the three authority documents extracted from
`C:\projects\BASE CURSOR\TRADING_BOT_CURSOR_RULES_V2.zip` and installed here:

- `.cursor/rules/trading-bot-core.mdc`
- `docs/project_memory/TRADING_BOT_RESEARCH_STANDARD_V2.md`
- `docs/project_memory/FROZEN_DEFAULT_GATES_V2_1.md`

plus the standing stack rules in `docs/project_memory/RULES.md`.

Findings are grouped by whether they need action. Nothing below is hypothetical: each item
names the rule text and what tradesim actually does.

---

## A. Conflicts that were found and fixed in this session

### A1. Gate A's "no critical UNKNOWN" was written down but not enforced

**Rule:** Gate A lists "no critical UNKNOWN" as mandatory before performance is scored, and
`trading-bot-core.mdc` repeats it for `MICRO_LIVE_CANDIDATE`.

**Was:** `assert_quotable` checked only the conformance stamp. A green engine handed a run
with `liquidation_status == "UNKNOWN"` — which happens whenever margin is unconfigured —
would have passed the check and the number would have been quotable.

**Now:** `assert_quotable(stamp, result=result)` raises `NotQuotableError` when the result
carries a critical UNKNOWN, independently of the engine's grade. Bound to VALD-001 with a
test, so it cannot be removed silently.

### A2. Bybit fee defaults

**Rule:** non-VIP baseline taker 0.055%, maker 0.02%, `Fee = Qty × ExecutedPrice × Rate`
per fill, slippage moves the price and is never folded into the rate.

**Status: compliant.** `CostConfig` defaults are `taker_rate=0.00055`,
`maker_rate=0.0002`, fees are charged per fill on the executed price, and slippage moves
the price. The golden fixtures deliberately use round synthetic rates (0.1% / 0.04%)
because their expected values are hand-computed and round numbers make the arithmetic
auditable; that is the fixture instrument, not the default.

---

## B. Deliberate deviations, with reasons

### B1. EXEC-009 and EXEC-017 are registered but not required for a backtest

**Rule:** "`EXEC-001` … `EXEC-017` … each must be bound to a discoverable test."

**tradesim:** both identifiers exist in the registry, but they are scoped to the
`live_runner` contract rather than `perp_bracket_portfolio`. EXEC-009 is reduce-only and
position-mode semantics; EXEC-017 is retry idempotency. A pure bar-replay backtest has no
order router, cannot issue a duplicate order, and cannot exhibit either behaviour. Marking
them required for the backtest contract would force a fake test that asserts nothing, which
is the exact failure mode the pack exists to prevent.

**Consequence:** when a live runner is built on tradesim, it is graded against the
`live_runner` contract and both become mandatory then. The registry already carries the
contract split, so nothing needs to be invented at that point.

### B2. LIVE-001 to LIVE-004 are registered but not yet required

Same reasoning. They are visible in every checker run with `NO_BINDING`, marked not
required, so the gap is on the report rather than hidden. They become required the moment a
bot runs on tradesim, which is tracked in `TODO.md`.

### B3. The engine loop is not vectorised, and cannot be

**Rule:** `RULES.md` — "Vectorized calculations; avoid Python loops; optimize for speed."
This is also a standing user instruction.

**tradesim:** the per-bar loop in `engine.py` is a genuine Python loop and stays one.

This is the one place I have deliberately not followed the standing rule, so it deserves a
straight explanation rather than a footnote. Vectorising an execution simulator requires
computing all bars' outcomes independently, and the following are all path-dependent in a
way that forbids it:

- funding moves the wallet, the wallet moves the liquidation price, and the liquidation
  price decides whether the *next* bar closes the position;
- a shared wallet means whether symbol B can open at bar *i* depends on what symbol A did
  at bar *i − 1*;
- a trailing stop's level at bar *i* is a function of the extremes of bars up to *i − 1*;
- a partially filled multi-leg take-profit changes the quantity that the remaining legs and
  the liquidation calculation apply to.

Every vectorised execution simulator I have read solves this by computing "first bar where
the stop was touched" and "first bar where the target was touched" with `argmax` over a
boolean matrix and comparing the two indices. **That construction is precisely how the
original defect arises**: the natural slice starts at `entry_index + 1`, the entry bar drops
out, and every trade gets a free bar of immunity. The measured cost of that in this codebase
family was out-of-sample profit factor 1.50 falling to 0.90 and Sharpe +1.32 falling to
−0.31. Speed is not worth that.

What *is* vectorised, and is: bar-series construction and validation, funding-settlement
lookup (`searchsorted`), touch-window slicing, mark-price lookup, the equity curve, daily
resampling, and every metric in `metrics.py`.

**Measured cost of the decision** (Python 3.14, this machine, single symbol, one-minute
bars, brackets plus liquidation, no touch timeframe):

| workload | result |
|---|---|
| 200,000 bars, 999 signals, 999 trades | 13.3 s, about 15,000 bars/second |
| projected 3.4 M bars (the full BTC 1m history in the warehouse) | about 3.8 minutes |

A single full-history backtest in under four minutes is fine. A parameter sweep of ten
thousand combinations over that history is not, and that is the real constraint to plan
around. The intended answer is to parallelise across parameter combinations with separate
processes rather than to vectorise the loop, because that keeps the exact live-aligned
semantics and scales with cores. If a sweep ever needs to be an order of magnitude faster,
the correct move is to compile this same loop — the arithmetic is simple and typed — not to
rewrite it as array operations with different behaviour.

---

## C. Real gaps: what the rules require that tradesim does not do

These are not defects in what was built. They are boundaries of what an execution engine
is, and each one is somebody's job later. The important consequence is stated first.

**tradesim can tell you a strategy's simulation is trustworthy. It cannot on its own tell
you a strategy is `SHADOW_READY`.** Gate A is now largely mechanised by the conformance
pack; Gates B, C, D and F are not, and most of what is missing lives above the engine, in
the research harness that runs it many times.

### C1. Gate B statistics are absent

`metrics.py` implements Sharpe (raw, annualised, and HAC-adjusted), Sortino, pooled profit
factor, drawdown with duration, win rate with a Wilson interval, exposure, turnover, and
cost totals. It does **not** implement:

- **Deflated Sharpe Ratio** (Gate B requires >= 0.95) — needs the complete trial record, so
  it belongs to the research registry, not to one simulation;
- **Probability of Backtest Overfitting** (<= 0.20 when a valid matrix exists) — needs a
  complete candidate-by-time return matrix across folds;
- **dependence-aware block bootstrap** (>= 90% of resamples with positive expectancy, >=
  10,000 resamples with a deterministic seed);
- **PSR / MinTRL / power** for the `SPARSE_EVIDENCE` path.

All four are functions of many runs, not of one. They should live in a small
`tradesim.evidence` module or in each research repository's harness, taking a list of
stitched outer-OOS results. Until they exist, no strategy can legitimately be called
`SHADOW_READY`, and the gate profile in `FROZEN_DEFAULT_GATES_V2_1.md` cannot be evaluated
mechanically.

### C2. Gate D concentration statistics are absent

"PnL excluding the best trade > 0", "PnL excluding the best year > 0", and "best year <= 40%
of total positive PnL" are cheap to compute from a trade list and are not in `metrics.py`.
This is the smallest of the gaps and the easiest to close.

### C3. Gate C stress scenarios are expressible but not first-class

The moderate scenario (all-taker fees, at least 2× baseline slippage) and the severe
scenario (3× slippage, adverse funding, delayed entry, adverse stop gaps) can all be
expressed by constructing a different `CostConfig` and re-running. There is no frozen
scenario runner that takes a baseline configuration and emits the baseline, moderate and
severe results as one artefact, which is what the gate actually asks to see. Worth adding as
`tradesim.stress` when the first strategy reaches that gate.

### C4. Microstructure the rules name and the engine does not model

`trading-bot-core.mdc` asks for "actual live order type, time-in-force, latency, spread,
slippage, queue/non-fill behavior, partial fills, rejections, retries, gaps and
price/quantity rounding". tradesim models order type, spread, slippage, gaps and rounding.
It does **not** model:

- **latency** — a signal fills at the next bar's open with no delay. At one-minute bars this
  is a small effect; at tick or second resolution it would not be.
- **queue position and non-fill for resting limit orders** — a limit take-profit that is
  touched always fills. Live, a touch is not a fill if you are behind the queue. The rules
  allow this only when maker fills have independent evidence, so the mitigation today is to
  run the maker scenario as an upside case and the all-taker scenario as the gate, which the
  cost configuration supports.
- **rejections and retries** — infeasible orders are recorded as typed skips, which covers
  the sizing and margin causes, but not a venue-side reject.
- **partial entry fills** — an entry fills completely or is skipped. Partial *exits* are
  modelled properly through multi-leg take-profits.

None of these silently flatters a result today, because the engine's conservative defaults
(taker on exits, no favourable slip on a limit touch, adverse resolution of ambiguity) point
the other way. They should be written into each project profile's known-limitations section
rather than forgotten.

### C5. Persistence and the trial registry

The rules require SQLite storage for data and evidence, an append-only trial registry that
survives across scripts and sessions, and deterministic per-fold seeds derived from one
recorded root seed. tradesim persists nothing: it takes arrays in and returns a result
object. This is correct for a library — it keeps the engine deterministic and offline — but
it means the registry is still to be built, and it is a Gate A item ("deterministic rerun
and append-only trial registry"). What tradesim contributes towards it is the
`config_digest` on every result, which hashes the full configuration, and the run identifier
threaded through every entry point.

### C6. Probability gating helpers

The standard's decision-theoretic gate — trade only when calibrated `p_hat >= pi* =
(mu_minus + lambda) / (mu_plus + mu_minus)`, with `mu_plus` and `mu_minus` computed from the
exact per-fill fees of each branch — is not in tradesim. It belongs next to the engine
because it needs the same fee model, and putting it anywhere else is how research and live
end up on different cost assumptions, which the rules explicitly forbid. Recommended as
`tradesim.decision`, sharing `fees.py` so the two cannot drift.

---

## D. Where tradesim goes further than the rules require

Noted so these are not mistaken for scope creep.

- **Ambiguity is recorded, not just resolved.** The rules say to use the adverse feasible
  sequence and report sensitivity. tradesim additionally flags the individual trade, counts
  the flagged trades, and refuses to claim a touch-resolved exit when the touch data does
  not fully cover the decision bar.
- **Liquidation fidelity is labelled.** Every result carries `MODELLED`, `SIMPLIFIED` or
  `UNKNOWN`, so a reader can tell an approximation from tier-based evidence without reading
  the configuration.
- **Skips are typed and counted.** The rules say to skip an order whose minimum exceeds the
  risk cap. tradesim distinguishes five reasons and reports them, so a run that quietly
  dropped half its signals is visible.
- **A missing test binding fails the build.** The rules require it; the pack demonstrates
  it. Deleting the EXEC-014 tests leaves all 50 fixtures passing and still fails the run.

---

## E. Recommended order of work

1. **Gate D concentration statistics** into `metrics.py`. An hour's work, closes a real gate.
2. **`tradesim.stress`** — baseline, moderate and severe as one artefact, frozen before
   outer out-of-sample.
3. **`tradesim.evidence`** — DSR, block bootstrap, PSR/MinTRL, and PBO when the matrix is
   valid. This is what unblocks `SHADOW_READY`.
4. **The trial registry**, in SQLite, append-only, shared across the strategy repositories.
5. **`tradesim.decision`** — the break-even probability gate on the shared fee model.
6. **Known-limitations block** in each project profile naming latency, queue position and
   partial entry fills.

Items 1 to 3 are the ones standing between a green engine and a defensible readiness
decision.
