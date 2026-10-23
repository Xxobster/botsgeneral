#!/usr/bin/env bash
# Install / refresh the Human-Machine Interface (HMI) agent on a trading VPS.
set -euo pipefail
ROOT=/opt/botsgeneral
cd "$ROOT"
sed -i 's/\r$//' deploy/bots deploy/*.sh deploy/*.service deploy/*.conf 2>/dev/null || true
install -m 755 deploy/bots /usr/local/bin/bots
ln -sfn /usr/local/bin/bots /root/bots
mkdir -p /etc/botsgeneral /var/lib/botsgeneral
if [[ ! -f /etc/botsgeneral/hmi_token ]]; then
  python3 - <<'PY'
import secrets
from pathlib import Path
p = Path("/etc/botsgeneral/hmi_token")
p.write_text(secrets.token_hex(24) + "\n", encoding="utf-8")
p.chmod(0o600)
print("wrote", p)
PY
fi
install -m 644 deploy/botsgeneral-hmi-agent.service /etc/systemd/system/botsgeneral-hmi-agent.service
systemctl daemon-reload
systemctl enable --now botsgeneral-hmi-agent.service
systemctl restart botsgeneral-hmi-agent.service
sleep 1
systemctl is-active botsgeneral-hmi-agent.service
echo "agent: 127.0.0.1:8788"
