#!/bin/bash
set +e
case "$1" in
  ln1)
    for s in xrpusdt dogeusdt adausdt trxusdt xlmusdt vetusdt; do
      f=/home/xgb/log/$s/trading.log
      echo "== $s =="
      grep -i "Live trading started" "$f" 2>/dev/null | tail -n1
    done
    echo "== tsm =="
    ps -eo args | grep tsm-vpa | grep -v grep
    echo "== xgb_match =="
    pgrep -af vps_run_asset_live_match || echo none
    ;;
  ln2)
    python3 - <<'PY'
import re
text=open("/etc/botsgeneral/bybit_keys.txt",encoding="utf-8",errors="ignore").read()
print("FILE_LEN", len(text))
for i,l in enumerate(text.splitlines()[:40],1):
    l2=re.sub(r"(?i)(key|secret)\s*[:=]\s*\S+","\\1=<redacted>",l)
    print(f"{i}:{l2[:140]}")
env={}
for line in open("/etc/crypthor/bybit.env",encoding="utf-8",errors="ignore"):
    if "=" in line and not line.strip().startswith("#"):
        k,v=line.split("=",1)
        env[k.strip()]=v.strip().strip("\"'")
ck=env.get("BYBIT_API_KEY","")
print("crypthor_prefix", (ck[:4]+"..."+ck[-4:]) if len(ck)>8 else "missing")
cur=None
for line in text.splitlines():
    s=line.strip()
    if not s or s.startswith("#"):
        continue
    if s.startswith("[") and s.endswith("]"):
        cur=s[1:-1]
        continue
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", s) and "key" not in s.lower() and "secret" not in s.lower():
        cur=s
        continue
    mk=re.search(r"(?i)api[_-]?key\s*[:=]\s*([A-Za-z0-9]+)", s)
    if mk and cur:
        k=mk.group(1)
        flag=" MATCH" if k==ck else ""
        print("acct", cur, "prefix", k[:4]+"..."+k[-4:]+flag)
PY
    echo "--- crypthor refs ---"
    grep -RInE "Xxobster|account" /opt/crypthor/deploy /etc/systemd/system/crypthor*.service 2>/dev/null | grep -viE "secret|api_key" | head -n 30
    echo "--- divergences ---"
    ls /run/screen/S-root 2>/dev/null || echo no_screen_dir
    ps -eo pid,args | grep -E "diverg|bybit_" | grep -v grep || echo no_diverg_procs
    ;;
  sm)
    grep -RInE "Xxobster|account|BYBIT|BINANCE" /opt/orderbook /opt/tradeshistory /etc/systemd/system/orderbook* /etc/systemd/system/tradeshistory* 2>/dev/null \
      | grep -viE "secret|api_key|apiKey|password|token" | head -n 50
    systemctl cat orderbook-recorder.service 2>/dev/null | head -n 35
    systemctl cat tradeshistory-vault-monitor.service 2>/dev/null | head -n 35
    ;;
esac
