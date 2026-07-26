# Engine conformance baseline

Measured, not asserted. Every number below came out of `tradesim-conformance`, and the
commands that produced it are at the bottom so anyone can reproduce the table.

- Date of run: 2026-07-25
- Fixture pack hash: `c11352baf1cc` (50 fixtures)
- Registry: 62 required identifiers, contract `perp_bracket_portfolio`
- Environment: clean virtual environment, `pip install -e packages/tradesim[conformance]`,
  Python 3.14, numpy 2.5.1, pandas 3.0.5

## What is being graded

Two independent questions, kept separate on purpose.

**Fixtures** ask whether the engine produces the right numbers on inputs whose expected
outputs were computed by hand. **Bindings** ask whether the engine's own repository has a
test that claims each identifier. An engine can pass every fixture and still be ungradable,
because nothing in its repository will notice when someone breaks it tomorrow. That is why
the last column of the totals table exists.

`UNSUPPORTED` means the adapter declined the fixture because the engine has no concept the
fixture requires — a shared wallet, a partial take-profit, a maintenance-margin tier. It is
reported separately and never counts as a pass. It is a capability gap, which is a milder
finding than a wrong answer but is still a reason a number cannot be quoted.

## Totals

| engine | fixtures passed | failed | unsupported | errored | identifiers with a test binding |
|---|---|---|---|---|---|
| tradesim | 50 | 0 | 0 | 0 | 62 of 62 |
| xgb (`audit_v4.ThresholdExecutionSim`) | 15 | 16 | 18 | 1 | 0 of 62 |
| LLM1 (`simulate_path_exits`) | 9 | 20 | 21 | 0 | 0 of 62 |
| TSM-VPA (`vpa.engine.run_backtest`) | 11 | 22 | 17 | 0 | 0 of 62 |

None of the three legacy engines binds a single identifier. Their test suites test them,
but nothing in them declares *which* shared execution behaviour is under test, so the
checker cannot tell a green suite from an absent one. Under the standing rule that a
missing binding is a hard failure, no number any of the three produces is quotable evidence
today, independently of how many fixtures they pass.

## The seven entry-bar identifiers

These seven are jointly non-negotiable: an engine that misses any one of them may not claim
execution parity. This is the family that the original defect lived in.

| identifier | behaviour | tradesim | xgb | LLM1 | TSM-VPA |
|---|---|---|---|---|---|
| EXEC-010 | stop touched on the entry bar closes the trade there | PASS | PASS | PASS | PASS |
| EXEC-011 | target touched on the entry bar closes the trade there | PASS | PASS | PASS | PASS |
| EXEC-012 | both levels on the entry bar resolves adversely and is flagged ambiguous | PASS | FAIL | FAIL | FAIL |
| EXEC-013 | liquidation reachable on the entry bar is taken | PASS | FAIL | FAIL | FAIL |
| EXEC-014 | a quiet entry bar does **not** close the trade (negative control) | PASS | PASS | PASS | PASS |
| EXEC-015 | a same-bar round trip is still charged its funding settlement | PASS | FAIL | UNSUPPORTED | FAIL |
| EXEC-016 | an entry-bar exit has a hold of zero bars, not one | PASS | PASS | FAIL | FAIL |

All three legacy engines have since been fixed for the plain cases, EXEC-010 and EXEC-011.
The failures are in the harder half of the same family, and they are the ones nobody
noticed because nobody had written the case down:

- **EXEC-012** — all three resolve adversely, which is right, but none of them *records*
  that the bar was ambiguous. The trade looks like a clean stop. A strategy whose results
  depend heavily on ambiguous bars is indistinguishable from one that does not, which is
  exactly the situation in which a backtest quietly stops predicting anything.
- **EXEC-013** — xgb checks liquidation only after the stop and never on the entry bar's
  own range; LLM1 does not model liquidation at all and says so; TSM-VPA's entry-bar
  resolver uses an approximate liquidation level that misses the fixture's price.
- **EXEC-015** — a funding settlement that falls inside a same-bar round trip is dropped by
  xgb and TSM-VPA. LLM1 has no funding in the path simulator at all.
- **EXEC-016** — LLM1 and TSM-VPA report a hold of one bar for a trade that opened and
  closed inside a single bar. Every per-bar statistic built on that number is off by one.

## Fixture outcome by family

| family | what it covers | tradesim | xgb | LLM1 | TSM-VPA |
|---|---|---|---|---|---|
| DATA | input validation | 2/2 pass | 0/2 pass | 0/2 pass | 0/2 pass |
| CAUS | no lookahead | 3/3 pass | 1/3 pass, 1 unsupported | 1/3 pass, 1 unsupported | 1/3 pass, 2 unsupported |
| EXEC | fills, exits, entry bar | 18/18 pass | 8/18 pass, 3 unsupported | 6/18 pass, 4 unsupported | 5/18 pass, 3 unsupported |
| FUND | funding cashflows | 6/6 pass | 5/6 pass | 0/6 pass, 6 unsupported | 2/6 pass |
| QTY | sizing, rounding, margin, liquidation | 7/7 pass | 0/7 pass, 3 unsupported, 1 error | 0/7 pass, 1 unsupported | 0/7 pass, 1 unsupported |
| METR | metric arithmetic | 6/6 pass | 0/6 pass, 6 unsupported | 0/6 pass, 6 unsupported | 0/6 pass, 6 unsupported |
| PORT | shared wallet across symbols | 3/3 pass | 0/3 pass, 3 unsupported | 0/3 pass, 3 unsupported | 0/3 pass, 3 unsupported |
| VALD | stamping and self-validation | graded by tests only | - | - | - |

Three findings are worth pulling out of that grid.

**Nobody validates their inputs.** All three legacy engines happily simulated a bar series
with a duplicated timestamp, an out-of-order timestamp, a negative price, and a high below
its low, and returned a trade with a straight face. Every one of those inputs is something
a candle downloader can produce on a bad day. This is the quietest and most dangerous class
of failure in the table, because it produces a plausible number from impossible data.

**Nobody rounds to the exchange's grid.** The entire QTY family is failed or declined by
all three. LLM1 works in return units and has no notion of quantity at all; xgb and TSM-VPA
have partial rounding but no consistent treatment of an order that rounds to zero, breaches
a minimum notional, or exceeds the margin available. In live trading each of those is a
rejected order; in these backtests each is a trade that silently happened.

**Nobody owns the metrics.** No legacy engine ships an authoritative Sharpe, profit factor
or drawdown implementation to grade, so each caller computes its own. That is how two
reports of the same run disagree.

## Notable per-engine failures beyond the entry bar

**xgb** — the strongest of the three, and the only one with real funding support (5 of 6
FUND fixtures pass; the failure is the same-bar settlement of EXEC-015). It fails EXEC-003
because it charges one commission rate on every fill and has no maker/taker distinction, so
a limit take-profit is billed at the taker rate. It fails EXEC-005 because a market
take-profit does not slip. It does not report a liquidation price on the trade even though
it computes one internally, so EXEC-007 and QTY-007 cannot be satisfied.

**LLM1** — the cleanest causally, and the only one whose module documentation states its
own limits honestly ("liquidation is NOT modelled"). It works in return units against a
notional of one, which is why the whole QTY family is out of reach, and its horizon is
expressed in hours, which is why EXEC-008 lands on the wrong bar for minute data. It
carries no funding in the path simulator; funding lives in a separate module that the
simulator does not call, so a research number and a live result can diverge by the entire
funding bill.

**TSM-VPA** — resolves the entry bar explicitly and labels it (`stop_entry_bar`), which is
good, and its `_resolve_bar_exit` is a genuine single shared resolver. It fails EXEC-004
because a bar that gaps straight through the stop still fills *at* the stop rather than at
the gap, which flatters every violent move against the position. It derives leverage from
the stop distance rather than taking the configured leverage, so the margin and liquidation
fixtures do not line up. It has no touch timeframe, so intrabar ambiguity can never be
resolved by data.

## Reproducing this table

The three foreign adapters live in `packages/tradesim/adapters/`. They are graders, not
products, and are deliberately outside the installed distribution: tradesim does not depend
on any of the three repositories.

```powershell
# from C:\projects\botsgeneral, in a clean venv with tradesim[conformance] installed
$env:PYTHONPATH = "C:\projects\botsgeneral\packages\tradesim\adapters"

tradesim-conformance --engine tradesim --tests packages/tradesim/tests --json base_tradesim.json
tradesim-conformance --engine xgb_adapter:build      --json base_xgb_adapter.json
tradesim-conformance --engine llm1_adapter:build     --json base_llm1_adapter.json
tradesim-conformance --engine tsmvpa_adapter:build   --json base_tsmvpa_adapter.json

python packages/tradesim/tools/baseline_table.py `
  tradesim=base_tradesim.json xgb=base_xgb_adapter.json `
  LLM1=base_llm1_adapter.json TSM-VPA=base_tsmvpa_adapter.json
```

The adapters give each engine its best case: where an engine wants a percentage bracket and
the fixture states an absolute price, the adapter derives the percentage that lands exactly
on the fixture's level at the fill the engine will take; where an engine wants an entry in
its own instrument table, the adapter registers the fixture's instrument. A failure in this
table is the engine's behaviour, not a translation artefact. Where an adapter could not
express a fixture at all it declined, and the result is `UNSUPPORTED` rather than a
sympathetic pass.

## What this baseline is for

It is the before picture. Phase 3 migrates each repository onto tradesim one at a time, and
the acceptance criterion for each migration is a trade-by-trade parity diff whose remaining
differences are explained by exactly these rows. When a migration is complete, that engine's
row becomes 62 of 62, and every difference between the old backtest and the new one has a
named identifier attached to it.
