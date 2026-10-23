#!/bin/bash
set +e
echo "HOST=$(hostname)"
echo "IP=$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "VPS_ID=$(cat /etc/botsgeneral/vps_id 2>/dev/null || echo none)"
echo

echo "=== RUNNING TRADING PROCS ==="
ps -eo pid,args --no-headers 2>/dev/null \
  | grep -Ei 'vps_run_asset|run_ld_live|run_live|crypthor|karmaa|diverg|tsm-vpa|crypto_alpha|llm2|structure|xgb|bybit' \
  | grep -vE 'grep|bash -lc|SCREEN ' || true

echo
echo "=== SCREENS ==="
screen -ls 2>/dev/null | head -n 60 || true

echo
echo "=== SYSTEMD RUNNING BOT-LIKE ==="
systemctl list-units --type=service --state=running --no-pager 2>/dev/null \
  | grep -Ei 'tsm|xgb|ld-live|crypthor|karmaa|diverg|crypto_alpha|llm|structure|botsgeneral|collector|orderbook|tradeshistory' \
  || true

echo
echo "=== LLM2 / STRUCTURE DIRS ==="
ls -d /home/llm* /opt/llm* /root/llm* /home/*structure* /opt/*structure* /home/*llm2* /opt/*llm2* 2>/dev/null
find /home /opt /root -maxdepth 3 -type d -iname '*llm*' 2>/dev/null | head -n 40
find /home /opt /root -maxdepth 3 -type d -iname '*structure*' 2>/dev/null | head -n 40

echo
echo "=== SYSTEMD UNITS MATCHING LLM/STRUCTURE ==="
systemctl list-unit-files --no-pager 2>/dev/null | grep -Ei 'llm|structure|xgb|tsm|ld-live|crypthor|karmaa|diverg|crypto_alpha' | head -n 80

echo
echo "=== KEY ACCOUNTS PRESENT ==="
if [ -f /etc/botsgeneral/bybit_keys.txt ]; then
  grep -iE '^ACCOUNT:' /etc/botsgeneral/bybit_keys.txt
fi
for f in /home/xgb/config/api_keys.json /home/ld/config/api_keys.json /home/*/config/api_keys.json /opt/*/config/api_keys.json; do
  [ -f "$f" ] || continue
  echo "-- $f --"
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print('\n'.join(sorted(str(k) for k in d if not str(k).endswith('_local'))))" "$f" 2>/dev/null
done

echo
echo "=== REPORT.YAML BOT MAP ==="
cat /etc/botsgeneral/report.yaml 2>/dev/null | head -n 200

echo
echo "=== END ==="
