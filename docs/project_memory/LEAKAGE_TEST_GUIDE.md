# Leakage Test Guide — shared `leakage` engine

**Source of truth:** `C:\projects\botsgeneral\packages\leakage`  
**CLI:** `leakage-check` / `python -m leakage`  
**Research Standard:** V2 §7 (causality and look-ahead protection)

## Why this exists

Separate train/test SQLite files are **hardening only**. They do **not** prove causality.

A confirmed real-world failure: Extreme Gradient Boosting (XGBoost) packs used
`dpo_20` (Detrended Price Oscillator) built with `pandas_ta.dpo` default
`centered=True`, which injects about **11 hours of future close** into the current
1h bar. Source greps missed it because the leak was a **library default**, not an
explicit `.shift(-N)` in project code. Out-of-sample Sharpe collapsed from ~14 to
base-rate once the column was removed or fixed.

The check that catches this is **prefix-invariance**: a causal feature at bar `t`
may only depend on bars `≤ t`, so recomputing on a series truncated at `t` must
reproduce the full-series values through that cutoff.

## Mandatory rule for every coding agent (LLM session)

Before **any** train, hunt, freeze, or test that consumes project-built indicators
or feature matrices:

1. Install / pin the botsgeneral package (see below).
2. Run the shared leakage audit against the **same** `build_features` path used for
   research and live.
3. If the audit hard-fails: **stop**. Do not train. Mark affected columns
   `LEAKAGE_POTENTIAL` in the registry (the engine writes this automatically).
4. Fix the feature builder, rebuild indicator / feature stores, re-run the audit
   until `PASS`, then drop or quarantine any still-marked columns from the feature set.
5. Only then train / test. Invalidate contaminated packs and readiness hashes.

Physical train/test split remains required as hardening, but is never a substitute
for this audit.

## Install

```powershell
pip install -e C:\projects\botsgeneral\packages\leakage[dev]
```

Or force the botsgeneral tree before import:

```python
from leakage.ensure_source import prefer_botsgeneral_leakage
prefer_botsgeneral_leakage()  # C:\projects\botsgeneral\packages\leakage\src
```

Refuse to run if `leakage.__file__` does not contain `botsgeneral`.

## Library API

```python
from leakage.ensure_source import prefer_botsgeneral_leakage
prefer_botsgeneral_leakage()

from leakage import run_leakage_audit, require_clean_audit, assert_no_leakage_potential

def build_features(ohlcv, *, interval="1h"):
    # MUST be the production / research feature path (or a thin guard adapter)
    ...

report = run_leakage_audit(
    ohlcv=ohlcv,                    # Open-High-Low-Close-Volume frame, DatetimeIndex
    build_features=build_features,
    interval="1h",
    registry_path="database/leakage_registry.json",
    symbol="BTCUSDT",
    train_path="database/ind/btcusdt_train_1h_indicators.db",  # optional hardening
    test_path="database/ind/btcusdt_test_1h_indicators.db",
    min_gap_ms=12 * 3600 * 1000,    # optional label-horizon gap
)
require_clean_audit(report)
assert_no_leakage_potential(report.registry_path, feature_columns_used)
```

Exit / `report.ok` is false on any **HARD** finding.

## CLI

```powershell
# Causal checks via project builder (decisive)
leakage-check `
  --symbol BTCUSDT --timeframe 1h `
  --builder utils.calc_indicators:build_features_for_guard `
  --registry database/leakage_registry.json

# Optional: also check train/test file geometry
leakage-check `
  --builder utils.calc_indicators:build_features_for_guard `
  --train-db database/ind/btcusdt_train_1h_indicators.db `
  --test-db database/ind/btcusdt_test_1h_indicators.db `
  --min-gap-ms 43200000
```

`--builder` must be `module.path:callable` accepting
`(ohlcv: DataFrame, *, interval: str) -> DataFrame`.

## What the engine checks

| Check | Severity | Meaning |
|---|---|---|
| `PREFIX_INVARIANCE` | HARD | Truncated recompute differs from full series (or NaN-only-in-prefix) |
| `FUTURE_MUTATION` | HARD | Shocking bars after a cutoff changes earlier feature values |
| `NAME_SCAN` | HARD / ADVISORY | Label/outcome tokens in feature names (`net_return`, `is_win`, …); future-ish names advisory |
| `FORWARD_CORR` | HARD if \|corr\|≥0.50; else ADVISORY if ≥0.20 | Mechanical-leak signature vs forward close returns |
| `TRAIN_TEST_SPLIT` | HARD on overlap / order / gap fail | File geometry only — not causality proof |

Hard failures block train/test. Advisory findings still mark the column
`LEAKAGE_POTENTIAL` in the registry and must be investigated before use.

## LEAKAGE_POTENTIAL registry

Default path: `database/leakage_registry.json` (per project).

```json
{
  "updated_at_utc": "2026-08-01T05:00:00Z",
  "columns": {
    "dpo_20": {
      "status": "LEAKAGE_POTENTIAL",
      "reasons": ["PREFIX_INVARIANCE: ..."],
      "first_seen_utc": "...",
      "last_seen_utc": "..."
    }
  }
}
```

Rules:

- Never train or select a column while it is `LEAKAGE_POTENTIAL`.
- After a fix: rebuild stores, re-run audit to `PASS`, remove the column from the
  active feature list (or clear the registry entry only after a documented clean audit).
- Contaminated model packs / Profit Factor / Sharpe claims are
  `RESEARCH_ONLY_CONTAMINATED` until rebuilt on clean features.

## Required project adapter

Each strategy repository must expose a single guard entrypoint, for example:

```python
# utils/calc_indicators.py (or ld/indicators.py)
def build_features_for_guard(ohlcv, *, interval="1h"):
    """Same columns as production research — no alternate 'clean' path."""
    return build_all_indicators(ohlcv, interval=interval)
```

Do **not** give the guard a simplified builder that omits the leaky pack.

## Stop-before-optimize

If leakage is found:

1. Stop optimization / hunting.
2. Invalidate affected results and readiness.
3. Fix the canonical feature engine (not only the report).
4. Add a regression (prefer calling `leakage` from project tests).
5. Rebuild stores; re-run every affected experiment.
6. Report maximum earned status (usually `LIVE_STOP / RESEARCH_ONLY`).

## What this does **not** replace

- Nested walk-forward purge / embargo for overlapping labels.
- Train-only scaler / imputer / calibrator fitting.
- Selection discipline (no ranking on outer out-of-sample).
- Live versus backtest feature parity.
- Trade Simulator (tradesim) execution conformance.

Those remain mandatory under Research Standard V2. This package proves
**point-in-time feature causality** for the indicator / feature matrix.
