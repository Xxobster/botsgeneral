# leakage — shared look-ahead / data-leakage test engine

Source of truth: `C:\projects\botsgeneral\packages\leakage`

Separate train/test SQLite files are **hardening**, not proof of causality. A feature
computed at bar `t` may only depend on bars `≤ t`. Recomputing on a series truncated at
`t` must reproduce the full-series values through that cutoff. This catches leaks that
source greps miss — including leaky library defaults such as `pandas_ta.dpo(centered=True)`.

## Install

```powershell
pip install -e C:\projects\botsgeneral\packages\leakage[dev]
```

Or before import:

```python
from leakage.ensure_source import prefer_botsgeneral_leakage
prefer_botsgeneral_leakage()
```

## Quick use

```python
from leakage import run_leakage_audit

def build_features(ohlcv, *, interval="1h"):
    # project-specific causal indicator builder
    ...

report = run_leakage_audit(
    ohlcv=ohlcv,
    build_features=build_features,
    interval="1h",
    registry_path="database/leakage_registry.json",
)
assert report.ok, report.summary()
```

Hard-fail checks: prefix-invariance, future-mutation, label-column name scan.
Advisory: forward-return correlation (still marks `LEAKAGE_POTENTIAL` when elevated).

Exit code / `report.ok` is false if any hard-fail finding exists. Training and testing
must not proceed until leaks are fixed and the registry is cleared or the column is
explicitly dropped from the feature set.

Operator guide in the rules package: `LEAKAGE_TEST_GUIDE.md`.
