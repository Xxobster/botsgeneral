#!/bin/bash
set +e
H=$(hostname)
echo "HOST=$H"

echo "=== CRYPTHOR ==="
if [ -f /etc/crypthor/bybit.env ]; then
  grep -E 'ACCOUNT|Xxobster|xxobster|account' /etc/crypthor/bybit.env | grep -viE 'key|secret|password|token' || true
  # show non-secret var names only
  cut -d= -f1 /etc/crypthor/bybit.env 2>/dev/null
fi
systemctl is-active crypthor-btc.service crypthor-eth.service 2>/dev/null
ps -eo args | grep run_live_bot | grep crypthor | grep -v grep

echo "=== DIVERGENCES ==="
[ -f /opt/divergences/config/live.env ] && grep -vE 'KEY|SECRET|PASSWORD|TOKEN' /opt/divergences/config/live.env
echo "alt env files:"; ls /opt/divergences/config/live.env* 2>/dev/null
# screens may be under other users
for u in root $(ls /home 2>/dev/null); do
  echo "screens user=$u"
  sudo -u "$u" screen -ls 2>/dev/null | head -n 40
done
ps -eo user,args | grep -i diverg | grep -v grep | head
systemctl status divergences-screens.service --no-pager 2>/dev/null | head -n 25

echo "=== NEWS ==="
systemctl is-active crypto_alpha_btcusdt_live.service crypto_alpha_ethusdt_live.service crypto_alpha_solusdt_live.service 2>/dev/null
ps -eo args | grep -i crypto_alpha | grep -v grep | head
grep -h 'bybit_account\|live_account' /home/crypto_alpha/config/default.yaml /home/crypto_alpha/config/strategies/*.json 2>/dev/null | sort -u

echo "=== KARMAA ==="
systemctl is-active karmaa-mp-live.service 2>/dev/null
ps -eo args | grep -i karmaa | grep -v grep | head
grep -RIn -E 'Xxobster[0-9]+|account' /root/karmaa_mp/config /root/karmaa_mp/deploy 2>/dev/null | grep -viE 'key|secret' | head -n 30

echo "=== XGB runtime account ==="
# inspect env of a live process
pid=$(pgrep -f 'vps_run_asset_live.py btcusdt' | head -n1)
echo "btc_pid=$pid"
if [ -n "$pid" ]; then
  tr '\0' '\n' < /proc/$pid/environ 2>/dev/null | grep -E 'ACCOUNT|Xxobster|xxobster|BYBIT|BINANCE' | grep -viE 'KEY|SECRET' || true
  # cmdline already known; check nearby config
fi
# find account default in script/config without dumping secrets
python3 - <<'PY'
import os,re,json,glob
roots=["/home/xgb","/home/xgb_match"]
for root in roots:
  if not os.path.isdir(root):
    continue
  print("ROOT", root)
  for path in glob.glob(root+"/**/*.{py,yaml,yml,json,env}", recursive=True):
    if any(x in path for x in ["pnl_export","__pycache__","venv",".git"]):
      continue
    try:
      txt=open(path,encoding="utf-8",errors="ignore").read()
    except Exception:
      continue
    if not re.search(r"xxobster|ACCOUNT", txt, re.I):
      continue
    # only print matching lines without secrets
    for i,line in enumerate(txt.splitlines(),1):
      if re.search(r"xxobster\d*|account\s*[:=]|BYBIT_ACCOUNT|ACCOUNT_NAME", line, re.I):
        if re.search(r"api_key|api_secret|secret|password", line, re.I):
          continue
        if len(line.strip())>180: continue
        print(f"  {path}:{i}:{line.strip()}")
PY

echo "=== TSM ==="
ps -eo args | grep tsm-vpa | grep -v grep
systemctl list-units 'tsm-vpa@*' --all --no-pager 2>/dev/null

echo "=== LD ==="
systemctl list-units 'ld-live*' --all --no-pager 2>/dev/null | head -n 50
ps -eo args | grep -E 'run_ld_live|ld-live' | grep -v grep | head -n 50
# find account args
ps -eo args | grep run_ld_live | grep -v grep | sed 's/api[^ ]*/*/g' | head -n 50
ls /home/ld 2>/dev/null | head
grep -RIn -E 'Xxobster[0-9]+|--account|account' /home/ld /etc/systemd/system 2>/dev/null | grep -viE 'key|secret' | grep -E 'ld|Xxobster' | head -n 60

echo "=== SM / ORDERBOOK STYLE ==="
ps -eo args | head -n 5
ps -eo args | grep -Ei 'orderbook|bot|live|bybit|binance' | grep -v grep | head -n 40
ls /home /opt /root 2>/dev/null | head -n 80
