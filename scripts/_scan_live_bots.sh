#!/bin/bash
set +e
echo "HOST=$(hostname)"
echo "VPS_ID=$(cat /etc/botsgeneral/vps_id 2>/dev/null || echo none)"
echo

echo "=== RUNNING BOT PROCESSES ==="
ps -eo pid,args --no-headers 2>/dev/null | grep -Ei \
  'vps_run_asset|run_ld_live|run_live_bot|crypthor|karmaa|diverg|tsm-vpa|crypto_alpha|run_live' \
  | grep -v grep | grep -v 'bash -lc' | grep -v SCREEN || true

echo
echo "=== SCREENS ==="
screen -ls 2>/dev/null | head -n 40 || true

echo
echo "=== SYSTEMD ACTIVE BOT-LIKE ==="
systemctl list-units --type=service --state=running --no-pager 2>/dev/null \
  | grep -Ei 'tsm|xgb|ld-live|crypthor|karmaa|diverg|crypto_alpha|botsgeneral|collector|orderbook|tradeshistory' \
  || true

echo
echo "=== XGB LOG ACCOUNT (last start per asset) ==="
for s in btcusdt ethusdt solusdt bnbusdt xrpusdt dogeusdt adausdt trxusdt xlmusdt vetusdt; do
  f=/home/xgb/log/$s/trading.log
  if [ -f "$f" ] && pgrep -f "vps_run_asset_live.py $s" >/dev/null 2>&1; then
    line=$(grep -i "Live trading started" "$f" 2>/dev/null | tail -n1)
    echo "$s: $line"
  fi
done

echo
echo "=== XGB_MATCH ==="
pgrep -af vps_run_asset_live_match || echo none

echo
echo "=== TSM CMDLINE ==="
ps -eo args | grep -E 'tsm-vpa|run_live_bot.py --symbol' | grep -v grep || true

echo
echo "=== CRYPTHOR ACCOUNT MATCH ==="
if [ -f /etc/crypthor/bybit.env ] && [ -f /etc/botsgeneral/bybit_keys.txt ]; then
python3 - <<'PY'
import re
env={}
for line in open("/etc/crypthor/bybit.env",encoding="utf-8",errors="ignore"):
    if "=" in line and not line.strip().startswith("#"):
        k,v=line.split("=",1); env[k.strip()]=v.strip().strip("\"'")
ck=env.get("BYBIT_API_KEY","")
cur=None
for line in open("/etc/botsgeneral/bybit_keys.txt",encoding="utf-8",errors="ignore"):
    s=line.strip()
    m=re.match(r"(?i)^ACCOUNT:\s*(.+)$", s)
    if m: cur=m.group(1).strip(); continue
    m=re.match(r"(?i)^API KEY:\s*(.+)$", s)
    if m and cur and m.group(1).strip()==ck:
        print("crypthor_account", cur)
PY
fi
ps -eo args | grep crypthor | grep -v grep || true

echo
echo "=== DIVERGENCES ==="
ps -eo args | grep -iE 'diverg|bybit_' | grep -v grep || echo none
grep -h '^BYBIT_ACCOUNT=' /opt/divergences/config/live.env 2>/dev/null || true

echo
echo "=== NEWS/CRYPTO_ALPHA ==="
ps -eo args | grep -i crypto_alpha | grep -v grep || echo none
systemctl is-active crypto_alpha_btcusdt_live.service crypto_alpha_ethusdt_live.service crypto_alpha_solusdt_live.service 2>/dev/null || true

echo
echo "=== KARMAA ==="
ps -eo args | grep -i karmaa | grep -v grep || echo none
systemctl is-active karmaa-mp-live.service 2>/dev/null || true

echo
echo "=== LD ==="
systemctl list-units 'ld-live*' --state=running --no-pager 2>/dev/null || true
ps -eo args | grep run_ld_live | grep -v grep || true
for u in /etc/systemd/system/ld-live*.service /etc/systemd/system/ld-live@*.service; do
  [ -f "$u" ] || continue
  echo "FILE $u"
  grep -E 'Description=|LD_BYBIT_ACCOUNT=' "$u" 2>/dev/null
done
# instantiated units
systemctl show 'ld-live@btcusdt.service' -p Environment -p ActiveState 2>/dev/null | head -n 5
systemctl show 'ld-live-crosspair.service' -p Environment -p ActiveState 2>/dev/null | head -n 5

echo
echo "=== SM RESEARCH SERVICES ==="
systemctl is-active orderbook-recorder.service tradeshistory-vault-monitor.service 2>/dev/null || true
ps -eo args | grep -Ei 'orderbook|tradeshistory|record-ws|vault' | grep -v grep | head -n 10 || true

echo
echo "=== END ==="
