# Build prompt — `tradesim` shared execution engine + conformance pack

Paste the block below into a fresh Cursor chat opened on `C:\projects\botsgeneral`.
Do Phase 1 and Phase 2 in one session; Phase 3 (per-repository migration) is a separate
session per repository.

---

## PROMPT — copy from here

You are building `tradesim`, the shared, conformance-tested trade-execution engine that every
trading repository in this family will depend on instead of hand-writing its own simulator.

**Why this exists.** In `d:\projects\TSM-VPA` a hand-rolled backtest engine opened the position
at the entry bar's open but only began checking Stop Loss / Take Profit / liquidation on the
**next** bar. Every trade got one free bar of immunity, on exactly the bar where a stop placed
just beyond a recent extreme is most likely to be hit. 47.6% of 1278 trades would have been
stopped out on their entry bar. Fixing that one missing branch moved the stitched out-of-sample
Profit Factor from 1.50 to 0.90 and the annualized Sharpe from +1.32 to −0.31 — the project's
entire apparent edge was that defect. The repository had a fully green test suite at the time.
That is the point: a green suite is not evidence, and prose rules did not prevent it.

Authority: read and obey `.cursor/rules/trading-bot-core.mdc` and
`docs/project_memory/TRADING_BOT_RESEARCH_STANDARD_V2.md` (v2.2), in particular **Section 4.4**
(shared engine / re-implementation ban), **Section 9.6** (first-bar exit resolution) and
**Section 24.0** (conformance identifiers, golden fixtures, result stamping). Default status is
`LIVE_STOP / RESEARCH_ONLY`. Do not deploy anything, do not touch any live bot, do not commit
unless I explicitly ask.

### Non-negotiable design rules

1. **One shared exit-resolution function.** Exactly one function decides what a bar does to an
   open position, and it is called for the entry bar and for every later bar. There must be no
   separate entry-bar code path. Any structure where the entry is created after the exit check
   inside a bar loop must re-run the exit check on that bar before continuing.
2. **Deterministic and offline.** Pure function of its inputs. No network, no clock, no globals,
   no imports from the `botsgeneral` collector runtime. Dependencies limited to `numpy` and
   `pandas`.
3. **Fail closed, never silently.** An infeasible order (below minimum quantity or notional,
   rounds to zero, exceeds margin) is either raised or recorded as a skip with an explicit
   reason code. Never silently resized, never silently dropped, never rounded to zero.
4. **Extract, do not invent.** Two sibling repositories already have engines that handle the
   entry bar correctly and have regression tests for it. Read them first and merge their
   capabilities rather than writing a new loop from scratch:
   - `C:\projects\xgb\utils\audit_v4\execution_sim.py` (`ThresholdExecutionSim`) — in-loop
     liquidation, venue rounding via `utils/audit_v4/venue.py`, historical funding, lower
     timeframe ambiguity resolution, adverse same-bar default, fee ledger.
     Its tests: `C:\projects\xgb\tests\test_audit_v4_execution.py`.
   - `D:\projects\LLM1\src\llm1\backtest\path_exit_simulator.py` (`simulate_path_exits`) —
     decision timeframe versus touch timeframe via `searchsorted`, stop-market gap fills using
     `touch_open`, take-profit limit fills with no favorable exit slippage, fee-versus-slippage
     separation, plus `mtm_equity.py` (signed funding over `[entry_ms, exit_ms)`) and
     `daily_mtm_metrics.py`.
     Its tests: `D:\projects\LLM1\tests\test_path_exit_simulator.py`, `test_mtm_equity.py`.
   Write down, in `docs/project_memory/DECISIONS.md`, which behaviour you took from which
   engine and every place the two disagreed, with the resolution and its justification.

### Phase 1 — conformance pack first (this is the higher-value half; do it before the engine)

Build the pack so it can grade **any** engine, including the three existing ones, through a thin
adapter. This gives immediate protection even before migration.

`packages/tradesim/src/tradesim/conformance/`:

- `registry.py` — the identifier registry from Section 24.0 of the standard: `EXEC-001` …
  `EXEC-017` plus the `DATA`, `CAUS`, `FUND`, `QTY`, `METR`, `VALD`, `PORT`, `LIVE` areas that
  apply to a bracketed perpetual simulator. Each entry carries the identifier, one-sentence
  behaviour statement, whether it is mandatory for a given contract, and the standard section
  reference. Identifiers are permanent: never renumber, never reuse; retired ones are marked
  retired.
- `fixtures/` — the golden fixture pack. One JSON file per identifier where the correct answer
  is exactly computable. Each fixture holds deterministic inputs (bars, optional lower-timeframe
  bars, signals, instrument specification, fee/slippage/funding configuration) and the exact
  expected outputs (exit reason, exit price, per-fill fees, funding charged, quantity, realized
  profit and loss, equity path). Keep every fixture small enough to verify by hand — a handful of
  bars, round numbers. Content-hash the whole pack and expose `fixture_pack_hash()`.
- `adapter.py` — a minimal protocol an engine must satisfy to be graded, plus a `tradesim`
  implementation. It must be possible to write a 30-line adapter for a foreign engine.
- `checker.py` + a `tradesim-conformance` console script — reads the required identifier set for
  a declared contract, discovers test bindings in a target test suite (identifier in a pytest
  marker, decorator, test name or docstring), runs them, replays the fixture pack against the
  declared engine, and **exits non-zero when any required identifier has no binding, when a bound
  test is skipped, or when a bound test or fixture fails.** A missing test must fail exactly like
  a failing test — this is the mechanism that would have caught the original defect. Print a
  table of identifier, bound test, status.
- `stamp.py` — `build_stamp()` returning engine name, version, commit (or `UNKNOWN_DIRTY` when
  the working tree is dirty), fixture-pack hash, checker timestamp, pass/fail state, and counts
  of required versus satisfied identifiers. Provide `assert_quotable(stamp)` which raises unless
  the stamp is green, for report writers to call.

These seven entry-bar fixtures and tests are mandatory and must be written first, before the
engine, so that the engine is developed against them:

| Identifier | Case |
| --- | --- |
| `EXEC-010` | Entry bar's own range takes out the stop: trade closes on its entry bar, `exit_ts == entry_ts`, both fills' fees charged, reason distinguishable (e.g. `stop_entry_bar`). |
| `EXEC-011` | Same for the take profit. |
| `EXEC-012` | Entry bar contains both stop and target: the adverse one is taken (or lower-timeframe resolved when that data is supplied) and the trade is labelled ambiguous. |
| `EXEC-013` | Entry bar reaches the liquidation price: liquidation resolves on the entry bar, in the correct order relative to the stop for the actual margin model. |
| `EXEC-014` | **Negative control:** a quiet entry bar that touches nothing does NOT close the position, and a later bar still resolves it correctly. Without this an engine passes `EXEC-010` by closing everything immediately. |
| `EXEC-015` | A position opened and closed on the same bar is still charged the funding settlements inside its holding window. |
| `EXEC-016` | A trade closed on its entry bar reports a hold of zero, and maximum-hold arithmetic is identical to the live runner's. |

Then, as the first real use of the pack, grade the three existing engines and write the results
to `docs/project_memory/ENGINE_CONFORMANCE_BASELINE.md`: `tradesim` (once Phase 2 lands),
xgb's `ThresholdExecutionSim`, LLM1's `simulate_path_exits`, and TSM-VPA's `src/vpa/engine.py`.
Report per-identifier pass/fail per engine. Do not fix the foreign engines in this session —
just record the truth.

### Phase 2 — the engine

`packages/tradesim/` as its own installable distribution (`pyproject.toml`, name `tradesim`,
`requires-python >=3.10`, dependencies `numpy` and `pandas` only) so a research repository can
install it without pulling in the collector's `requests`/`PyYAML`/`websocket-client`. Do not
add it to the existing `botsgeneral` distribution's dependencies.

Modules under `src/tradesim/`:

- `contracts.py` — frozen dataclasses: `InstrumentSpec` (tick, quantity step, minimum quantity,
  minimum notional, maximum leverage, maintenance tiers, funding interval, launch timestamp),
  `CostConfig` (maker and taker rates, entry and exit slippage, spread), `MarginConfig` (margin
  mode, maintenance rate or tier table, mark and maintenance buffers), `SizingConfig` (fixed
  quantity, fixed notional, or risk fraction), `SimConfig` (decision timeframe, touch timeframe,
  entry reference `next_open` or `close`, exit set, maximum hold, same-bar policy).
- `exits.py` — **the** shared resolution function. Signature roughly
  `resolve_bar_exit(side, stop, target, liq, bar, *, touch_bars=None, policy) -> ExitEvent | None`.
  Applied identically to the entry bar and every later bar.
- `engine.py` — `simulate(...) -> SimResult`. Chronological event loop (path-dependent state
  genuinely needs a loop; vectorize the feature/indicator work outside it). Order within each
  bar: apply funding settlements due, fill any pending entry, **resolve exits on this bar
  including a just-filled entry**, then mark to market. Returns trades, per-bar equity including
  unrealized profit and loss, a fee ledger, a funding ledger, skip reasons with counts, and a
  liquidation status that is `MODELLED` / `SIMPLIFIED` / `UNKNOWN` — never a silent pass.
- `fees.py` — fee per fill on executed notional at that fill's maker or taker rate. Slippage
  moves the fill price and is never folded into the rate.
- `funding.py` — signed historical rates applied at each settlement inside the holding window,
  affecting wallet, margin and equity chronologically.
- `margin.py` — leverage from stop distance, initial margin, maintenance tiers, Mark-based
  liquidation price, and an invariant check that the stop is inside the liquidation buffer.
- `sizing.py` — tick and step rounding, minimum quantity and notional enforcement with a
  configurable safety buffer, and explicit skip reasons.
- `metrics.py` — the one authoritative implementation: Sharpe on chronological daily
  mark-to-market wallet returns (raw and annualized reported separately), Heteroskedasticity and
  Autocorrelation Consistent adjustment, pooled uncapped Profit Factor, pooled win rate and
  expectancy, drawdown including unrealized profit and loss, exposure, fee/slippage/funding
  totals, and the ambiguous-intrabar and entry-bar-exit counts.

Capabilities to support because the three repositories need them: two timeframes (decision plus
touch resolution); entry at next open or at close; bracket stop and target, timeout, trailing,
break-even, and multi-leg take profit; quantity accounting with a fixed-notional mode that also
reports return units; isolated and cross margin; shared-wallet portfolio simulation across
symbols from one event stream.

Add `parity.py`: given two engines and one common configuration, run both and emit a
trade-by-trade diff (entry and exit timestamp, price, reason, fee, funding, profit and loss) with
a tolerance, for use during migration.

Every public entry point must accept and propagate a run identifier and return the conformance
stamp inside `SimResult`, so a caller physically cannot write a result artifact without it.

### Phase 3 — migration, one repository per session, not now

For each of `xgb`, `LLM1`, `TSM-VPA`: write the adapter, run the conformance pack, run
`parity.py` against the incumbent engine on a real configuration, explain every difference in
writing, then switch the repository to `tradesim` and rerun the affected experiments. Numbers
produced by the old engine stay unquotable until rerun. Delete or clearly quarantine legacy
simulators — `C:\projects\xgb\utils\simulate_trades.py` already has the same entry-bar defect and
is still importable, and LLM1's legacy label-proxy scorer is still wired into older generation
objectives.

### Definition of done for this session

- `pip install -e packages/tradesim` works in a clean virtual environment.
- `tradesim-conformance --engine tradesim --tests packages/tradesim/tests` exits zero and prints
  the full identifier table.
- Deliberately reintroducing the original defect (skip exit resolution on the entry bar) makes
  `EXEC-010`, `EXEC-012`, `EXEC-013` fail — demonstrate this, then revert it. Deliberately
  deleting the `EXEC-014` test makes the checker fail for a missing binding — demonstrate that
  too, then restore it. If neither demonstration fails, the pack is not doing its job.
- `docs/project_memory/ENGINE_CONFORMANCE_BASELINE.md` records how all four engines score.
- `docs/project_memory/DECISIONS.md` records the xgb-versus-LLM1 behaviour choices and their
  justification.
- Report `git diff --stat` and confirm no live system was touched and nothing was committed.

Work through all of this without stopping after a plan. Ask only if a genuine design decision
needs my authority or an action would touch a live system.

## PROMPT — copy to here
