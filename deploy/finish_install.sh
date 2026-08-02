#!/usr/bin/env bash
# Finish install on a VPS when code is already under /opt/botsgeneral
# Usage: bash deploy/finish_install.sh <VPS_IP>
set -euo pipefail
VPS_IP="${1:?VPS IP required}"
cd /opt/botsgeneral
sed -i 's/\r$//' deploy/*.sh deploy/*.service deploy/bots 2>/dev/null || true
python3 -m venv venv
./venv/bin/pip install -U pip
./venv/bin/pip install -r requirements.txt
./venv/bin/pip install -e . || true
mkdir -p /var/lib/botsgeneral /etc/botsgeneral
cp deploy/botsgeneral-collector@.service /etc/systemd/system/
if ! grep -q PYTHONPATH /etc/systemd/system/botsgeneral-collector@.service; then
  sed -i '/Environment=BOTSGENERAL_KEYS/a Environment=PYTHONPATH=/opt/botsgeneral' \
    /etc/systemd/system/botsgeneral-collector@.service
fi
# Phone-friendly command from /root
install -m 755 deploy/bots /usr/local/bin/bots
ln -sfn /usr/local/bin/bots /root/bots
# Report settings (do not overwrite existing since_date edits)
if [[ ! -f /etc/botsgeneral/report.yaml ]]; then
  cp config/report.yaml /etc/botsgeneral/report.yaml
fi
systemctl daemon-reload
systemctl enable --now "botsgeneral-collector@${VPS_IP}"
# Pin interactive `bots` / sitrep to this host (path-hit fallback is ambiguous across fleets)
mkdir -p /etc/botsgeneral
echo "${VPS_IP}" >/etc/botsgeneral/vps_id
sleep 3
systemctl --no-pager status "botsgeneral-collector@${VPS_IP}" || true
PYTHONPATH=/opt/botsgeneral ./venv/bin/python -m botsgeneral --vps "${VPS_IP}" discover
echo "Keys: /etc/botsgeneral/bybit_keys.txt"
echo "VPS pin: /etc/botsgeneral/vps_id"
echo "Report since date: /etc/botsgeneral/report.yaml"
echo "From /root just run:  bots"
echo "Drilldown:            bots trades Xxobster4 BTCUSDT"
