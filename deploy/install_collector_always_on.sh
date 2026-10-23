#!/usr/bin/env bash
# Install always-on collector + keep-alive timer on this VPS.
# Usage: bash deploy/install_collector_always_on.sh [VPS_IP]
set -euo pipefail
ROOT=/opt/botsgeneral
VPS_IP="${1:-}"
if [[ -z "$VPS_IP" ]]; then
  for ip in 94.156.189.76 212.73.150.178 185.203.119.52; do
    if hostname -I 2>/dev/null | grep -qw "$ip"; then
      VPS_IP=$ip
      break
    fi
  done
fi
VPS_IP="${VPS_IP:?cannot detect VPS IP; pass e.g. 94.156.189.76}"

install -m 644 "$ROOT/deploy/botsgeneral-collector@.service" /etc/systemd/system/botsgeneral-collector@.service
install -m 755 "$ROOT/deploy/botsgeneral-collector-ensure" /usr/local/bin/botsgeneral-collector-ensure
install -m 644 "$ROOT/deploy/botsgeneral-collector-ensure.service" /etc/systemd/system/botsgeneral-collector-ensure.service
install -m 644 "$ROOT/deploy/botsgeneral-collector-ensure.timer" /etc/systemd/system/botsgeneral-collector-ensure.timer

systemctl daemon-reload
systemctl enable --now "botsgeneral-collector@${VPS_IP}.service"
systemctl enable --now botsgeneral-collector-ensure.timer
systemctl start botsgeneral-collector-ensure.service || true

echo "collector: $(systemctl is-enabled botsgeneral-collector@${VPS_IP}) / $(systemctl is-active botsgeneral-collector@${VPS_IP})"
echo "ensure.timer: $(systemctl is-enabled botsgeneral-collector-ensure.timer) / $(systemctl is-active botsgeneral-collector-ensure.timer)"
systemctl list-timers botsgeneral-collector-ensure.timer --no-pager || true
