#!/usr/bin/env bash
set -euo pipefail
ROOT=/opt/botsgeneral
tar -xzf /tmp/botsgeneral-bake.tar.gz -C "$ROOT"
"$ROOT/venv/bin/pip" install -e "$ROOT" -q
UNIT=$(systemctl list-units --type=service --state=running --no-legend 'botsgeneral-collector@*' | awk '{print $1}' | head -1)
VPS_IP=${UNIT#botsgeneral-collector@}
VPS_IP=${VPS_IP%.service}
echo "HOST_UNIT=$UNIT"
echo "===== DRY-RUN ====="
"$ROOT/venv/bin/python" -m botsgeneral --vps "$VPS_IP" purge-unused-candles --dry-run
echo "===== DISCOVER ====="
"$ROOT/venv/bin/python" -m botsgeneral --vps "$VPS_IP" discover
echo "===== PURGE ====="
systemctl stop "$UNIT"
"$ROOT/venv/bin/python" -m botsgeneral --vps "$VPS_IP" purge-unused-candles
systemctl start "$UNIT"
sleep 3
echo "ACTIVE=$(systemctl is-active "$UNIT")"
"$ROOT/venv/bin/python" /tmp/print_shared_history_coverage.py
echo "===== DISCOVER AFTER ====="
"$ROOT/venv/bin/python" -m botsgeneral --vps "$VPS_IP" discover
