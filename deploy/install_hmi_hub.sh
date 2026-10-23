#!/usr/bin/env bash
# Install the Human-Machine Interface (HMI) hub on 94.156.189.76 (ln1).
# Serves https://bots94.duckdns.org/ and http://94.156.189.76/ (site root).
set -euo pipefail
ROOT=/opt/botsgeneral
cd "$ROOT"
sed -i 's/\r$//' deploy/bots deploy/*.sh deploy/*.service deploy/*.conf 2>/dev/null || true
if [[ ! -x "$ROOT/venv/bin/python" ]]; then
  python3 -m venv "$ROOT/venv"
  "$ROOT/venv/bin/pip" install -U pip setuptools wheel
  "$ROOT/venv/bin/pip" install "PyYAML>=6.0" "requests>=2.31.0" "numpy>=1.24.0"
fi
install -m 755 deploy/bots /usr/local/bin/bots
ln -sfn /usr/local/bin/bots /root/bots
mkdir -p /etc/botsgeneral /var/lib/botsgeneral /root/.ssh /etc/nginx/snippets
if [[ ! -f /etc/botsgeneral/hmi_token ]]; then
  echo "ERROR: /etc/botsgeneral/hmi_token missing (copy from a trading VPS)" >&2
  exit 2
fi
if [[ ! -f /root/.ssh/hmi_hub ]]; then
  ssh-keygen -t ed25519 -N "" -f /root/.ssh/hmi_hub -C "hmi-hub-ln1"
  echo "NEW hub public key:"
  cat /root/.ssh/hmi_hub.pub
fi
echo "94.156.189.76" >/etc/botsgeneral/vps_id
install -m 644 deploy/botsgeneral-hmi-hub.service /etc/systemd/system/botsgeneral-hmi-hub.service
install -m 644 deploy/botsgeneral-hmi-agent.service /etc/systemd/system/botsgeneral-hmi-agent.service
sed -i 's/BOTSGENERAL_VPS=.*/BOTSGENERAL_VPS=94.156.189.76/' /etc/systemd/system/botsgeneral-hmi-hub.service
install -m 644 deploy/nginx-bots-hmi.conf /etc/nginx/snippets/bots-hmi.conf
if [[ ! -f /etc/botsgeneral/hmi_htpasswd ]]; then
  if command -v htpasswd >/dev/null 2>&1; then
    htpasswd -cbm /etc/botsgeneral/hmi_htpasswd admin 000000
  else
    HASH="$(openssl passwd -apr1 000000)"
    printf 'admin:%s\n' "$HASH" >/etc/botsgeneral/hmi_htpasswd
  fi
  chmod 644 /etc/botsgeneral/hmi_htpasswd
  printf '000000\n' >/root/hmi_web_password
  chmod 600 /root/hmi_web_password
  echo "web user admin"
fi
cat >/etc/botsgeneral/hmi.yaml <<'YAML'
agents:
  - id: ln1
    url: http://127.0.0.1:8788
  - id: ln2
    host: 212.73.150.178
    ssh: root@212.73.150.178
YAML
# Default IP vhost — HMI at /
cat >/etc/nginx/sites-available/bots-ip <<'NGX'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name 94.156.189.76 _;
    include /etc/nginx/snippets/bots-hmi.conf;
}
NGX
ln -sfn /etc/nginx/sites-available/bots-ip /etc/nginx/sites-enabled/bots-ip
# bots94.duckdns.org
install -m 644 deploy/nginx-bots94-duckdns.conf /etc/nginx/sites-available/bots94-duckdns
ln -sfn /etc/nginx/sites-available/bots94-duckdns /etc/nginx/sites-enabled/bots94-duckdns
# Drop legacy cirlapp vhost if present (domain moved away from this use)
rm -f /etc/nginx/sites-enabled/cirlapp-duckdns /etc/nginx/sites-enabled/cirl-duckdns
systemctl daemon-reload
systemctl enable --now botsgeneral-hmi-agent.service
systemctl enable --now botsgeneral-hmi-hub.service
systemctl restart botsgeneral-hmi-agent.service
systemctl restart botsgeneral-hmi-hub.service
nginx -t
systemctl enable --now nginx
systemctl reload nginx
sleep 1
systemctl is-active botsgeneral-hmi-hub.service
systemctl is-active botsgeneral-hmi-agent.service
echo "HMI: https://bots94.duckdns.org/"
echo "Also: http://94.156.189.76/"
echo "HTTP basic user: admin"
echo "Password file: /root/hmi_web_password"
echo "Then: certbot --nginx -d bots94.duckdns.org (snap certbot preferred)"
