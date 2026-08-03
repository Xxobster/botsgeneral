#!/usr/bin/env bash
set -euo pipefail
cd /opt/botsgeneral
PY=/opt/botsgeneral/venv/bin/python
if [[ ! -x "$PY" ]]; then
  echo "missing venv python" >&2
  exit 1
fi

# If git checkout, pull; else assume files already synced
if [[ -d .git ]]; then
  git fetch origin main
  git reset --hard origin/main
  echo "git HEAD=$(git rev-parse --short HEAD)"
fi

"$PY" -m pip install -e packages/live_candles -e packages/market_data -e . -q
"$PY" - <<'PY'
import botsgeneral
import live_candles
from botsgeneral.reader import load_ohlcv
print("import_ok", live_candles.__file__)
PY

UNIT="${1:?collector unit name required}"
systemctl restart "$UNIT"
sleep 2
systemctl is-active "$UNIT"
journalctl -u "$UNIT" -n 20 --no-pager
