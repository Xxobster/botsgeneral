#!/usr/bin/env bash
# Remove fleet HMI hub / nginx public site leftovers from sm (212.73.150.149).
# Keep botsgeneral-hmi-agent (ln1 hub still fans out here).
set -euo pipefail
systemctl disable --now botsgeneral-hmi-hub.service 2>/dev/null || true
rm -f /etc/systemd/system/botsgeneral-hmi-hub.service
systemctl daemon-reload || true
# Drop public nginx HMI vhosts / snippets
rm -f /etc/nginx/sites-enabled/bots-ip \
      /etc/nginx/sites-enabled/cirlapp-duckdns \
      /etc/nginx/sites-enabled/cirl-duckdns \
      /etc/nginx/sites-enabled/bots94-duckdns \
      /etc/nginx/sites-available/bots-ip \
      /etc/nginx/sites-available/cirlapp-duckdns \
      /etc/nginx/sites-available/cirl-duckdns \
      /etc/nginx/sites-available/bots94-duckdns \
      /etc/nginx/snippets/bots-hmi.conf
# Strip leftover include from CIRL IP vhost if present
if [[ -f /etc/nginx/sites-available/cirl-ip ]]; then
  sed -i '/bots-hmi.conf/d' /etc/nginx/sites-available/cirl-ip
fi
# If nginx only served HMI, leave default; otherwise reload if present
if command -v nginx >/dev/null 2>&1; then
  if nginx -t 2>/dev/null; then
    systemctl reload nginx 2>/dev/null || true
  fi
fi
# Ensure agent stays up for fleet aggregation
if [[ -f /etc/systemd/system/botsgeneral-hmi-agent.service ]]; then
  systemctl enable --now botsgeneral-hmi-agent.service
  systemctl restart botsgeneral-hmi-agent.service
  systemctl is-active botsgeneral-hmi-agent.service
fi
echo "sm: hub/nginx HMI public site removed; agent kept"
