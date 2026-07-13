#!/usr/bin/env bash
# Finish install on a VPS when code is already under /opt/botsgeneral
# Usage: bash deploy/finish_install.sh <VPS_IP>
set -euo pipefail
VPS_IP="${1:?VPS IP required}"
cd /opt/botsgeneral
sed -i 's/\r$//' deploy/*.sh deploy/*.service 2>/dev/null || true
python3 -m venv venv
./venv/bin/pip install -U pip
./venv/bin/pip install -r requirements.txt
# Prefer editable; fall back to PYTHONPATH if build is slow
./venv/bin/pip install -e . || true
mkdir -p /var/lib/botsgeneral /etc/botsgeneral
cp deploy/botsgeneral-collector@.service /etc/systemd/system/
# Ensure PYTHONPATH so package imports work without editable install
if ! grep -q PYTHONPATH /etc/systemd/system/botsgeneral-collector@.service; then
  sed -i '/Environment=BOTSGENERAL_KEYS/a Environment=PYTHONPATH=/opt/botsgeneral' \
    /etc/systemd/system/botsgeneral-collector@.service
fi
systemctl daemon-reload
systemctl enable --now "botsgeneral-collector@${VPS_IP}"
sleep 3
systemctl --no-pager status "botsgeneral-collector@${VPS_IP}" || true
PYTHONPATH=/opt/botsgeneral ./venv/bin/python -m botsgeneral --vps "${VPS_IP}" discover
PYTHONPATH=/opt/botsgeneral ./venv/bin/python -m botsgeneral --vps "${VPS_IP}" sitrep
echo "Keys: /etc/botsgeneral/bybit_keys.txt"
