#!/usr/bin/env bash
set -euo pipefail
VPS=185.203.119.52
cd /opt/botsgeneral
# files already scp'd into place by deploy step
sed -i 's/\r$//' botsgeneral/*.py botsgeneral/discover/*.py config/bots_registry.yaml deploy/bots 2>/dev/null || true
install -m 755 deploy/bots /usr/local/bin/bots
ln -sfn /usr/local/bin/bots /root/bots
echo "$VPS" >/etc/botsgeneral/vps_id
cp deploy/botsgeneral-collector@.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now "botsgeneral-collector@${VPS}.service"
sleep 4
systemctl is-active "botsgeneral-collector@${VPS}.service"
echo "=== discover ==="
BOTSGENERAL_VPS="$VPS" ./venv/bin/python -m botsgeneral --vps "$VPS" discover
echo "=== sitrep ==="
bots sitrep
echo "=== reader smoke ==="
PYTHONPATH=/opt/botsgeneral ./venv/bin/python - <<'PY'
from botsgeneral.reader import load_ohlcv, newest_ts_ms, is_fresh
for sym in ("BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT"):
    n = newest_ts_ms("binance", sym, "1h")
    df = load_ohlcv("binance", sym, "1h", limit=5)
    print(sym, "newest", n, "tail_rows", len(df), "fresh", is_fresh("binance", sym, "1h"))
    if len(df):
        print(" ", df.tail(1).to_dict("records")[0])
PY
journalctl -u "botsgeneral-collector@${VPS}" -n 25 --no-pager
