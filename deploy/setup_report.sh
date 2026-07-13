#!/usr/bin/env bash
set -euo pipefail
VPS_IP="${1:?vps ip}"
cd /opt/botsgeneral
python3 -m venv --clear venv
./venv/bin/pip install -U pip setuptools wheel -q
./venv/bin/pip install -r requirements.txt -q
PYTHONPATH=/opt/botsgeneral ./venv/bin/python -c 'import botsgeneral,numpy; print("ok", numpy.__version__)'
sed -i 's/\r$//' deploy/bots deploy/*.sh
install -m 755 deploy/bots /usr/local/bin/bots
ln -sfn /usr/local/bin/bots /root/bots
mkdir -p /etc/botsgeneral
if [ ! -f /etc/botsgeneral/report.yaml ]; then
  cp config/report.yaml /etc/botsgeneral/report.yaml
fi
systemctl restart "botsgeneral-collector@${VPS_IP}"
sleep 5
systemctl is-active "botsgeneral-collector@${VPS_IP}"
echo "=== bots report (head) ==="
bots | head -70
echo "=== journal (backfill) ==="
journalctl -u "botsgeneral-collector@${VPS_IP}" -n 15 --no-pager
