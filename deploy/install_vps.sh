#!/usr/bin/env bash
# Deploy botsgeneral collector onto this VPS.
# Usage: bash deploy/install_vps.sh <VPS_IP>
set -euo pipefail
VPS_IP="${1:?VPS IP required e.g. 94.156.189.76}"
ROOT=/opt/botsgeneral
DATA=/var/lib/botsgeneral
ETC=/etc/botsgeneral

mkdir -p "$ROOT" "$DATA" "$ETC"
rsync -a --delete \
  --exclude '.git' --exclude 'venv' --exclude 'data' --exclude '__pycache__' \
  ./ "$ROOT/"

python3 -m venv "$ROOT/venv"
"$ROOT/venv/bin/pip" install -U pip
"$ROOT/venv/bin/pip" install -e "$ROOT"

cp "$ROOT/deploy/botsgeneral-collector@.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now "botsgeneral-collector@${VPS_IP}"
systemctl --no-pager status "botsgeneral-collector@${VPS_IP}" || true
echo "DB: $DATA/shared_candles.db"
echo "Keys: place Bybit keys at $ETC/bybit_keys.txt"
echo "Test: $ROOT/venv/bin/python -m botsgeneral --vps ${VPS_IP} discover"
echo "      $ROOT/venv/bin/python -m botsgeneral --vps ${VPS_IP} sitrep"
