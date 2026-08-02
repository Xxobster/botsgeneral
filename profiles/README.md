# Python profiles

Two pinned environments. Shared packages (`tradesim`, `leakage`, `market_data`,
`live_candles`) must import and test cleanly on **both**.

| Profile | Python | Who uses it | Notes |
|---------|--------|-------------|-------|
| `research-311` | 3.11 | `xgb`, `LD` | tensorflow 2.19 + numpy 1.26.4 |
| `general-312` | 3.12 | everyone else | numpy ≥ 2; no tensorflow |

## Create / refresh

```powershell
cd C:\projects\botsgeneral
uv venv .venv-research-311 --python 3.11
uv pip install --python .venv-research-311 -r profiles\research-311\requirements.txt
uv pip install --python .venv-research-311 -e . -e packages\tradesim[conformance,plot] -e packages\leakage[dev] -e packages\market_data -e packages\live_candles

uv venv .venv-general-312 --python 3.12
uv pip install --python .venv-general-312 -r profiles\general-312\requirements.txt
uv pip install --python .venv-general-312 -e . -e packages\tradesim[conformance,plot] -e packages\leakage[dev] -e packages\market_data -e packages\live_candles
```

LD continues to borrow the xgb interpreter (`C:\projects\xgb\.venv`) for tensorflow
work; that venv should track `research-311` pins.
