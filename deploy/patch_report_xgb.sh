#!/usr/bin/env bash
set -euo pipefail
cd /opt/botsgeneral
# refresh code already scp'd; install wrapper + ensure xgb keys readable
sed -i 's/\r$//' deploy/bots
install -m 755 deploy/bots /usr/local/bin/bots
ln -sfn /usr/local/bin/bots /root/bots
if [ -f /home/xgb/config/api_keys.json ]; then
  cp -f /home/xgb/config/api_keys.json /etc/botsgeneral/xgb_api_keys.json
  chmod 600 /etc/botsgeneral/xgb_api_keys.json
fi
PYTHONPATH=/opt/botsgeneral /opt/botsgeneral/venv/bin/python -c 'from botsgeneral.keys import resolve_accounts; a=resolve_accounts(); print("keys", sorted(a)); print("has2", "Xxobster2" in a, "has13", "Xxobster13" in a)'
echo "=== help ==="
bots --help
echo "=== report head ==="
bots | head -80
