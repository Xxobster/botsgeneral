#!/bin/bash
set +e
echo "=== XGB account selection ==="
python3 - <<'PY'
import re,os,glob
p="/home/xgb/scripts/vps_run_asset_live.py"
print("exists", os.path.exists(p))
if os.path.exists(p):
    txt=open(p,encoding="utf-8",errors="ignore").read().splitlines()
    for i,l in enumerate(txt,1):
        if re.search(r"account|xxobster|BYBIT|keys", l, re.I) and not re.search(r"api_key|api_secret|secret\s*=", l, re.I):
            print(f"{i}:{l.strip()[:200]}")
# asset configs
for path in sorted(glob.glob("/home/xgb/config/**/*btc*", recursive=True)+glob.glob("/home/xgb/config/**/*sol*", recursive=True)+glob.glob("/home/xgb/**/live*.json", recursive=True))[:30]:
    if "pnl" in path or "venv" in path: continue
    try:
        t=open(path,encoding="utf-8",errors="ignore").read()
    except Exception:
        continue
    if re.search(r"xxobster|account", t, re.I):
        print("FILE", path)
        for i,l in enumerate(t.splitlines(),1):
            if re.search(r"xxobster|account", l, re.I) and not re.search(r"secret|api_key", l, re.I):
                print(f"  {i}:{l.strip()[:160]}")
PY
echo "=== per-process cmdline account ==="
ps -eo args | grep vps_run_asset_live | grep -v grep
echo "=== screen names imply accounts ==="
screen -ls | sed -n '2,30p'
# Try to read account from each asset state/log header without secrets
for s in btcusdt ethusdt solusdt bnbusdt; do
  f=$(ls -1 /home/xgb/log/$s/*.log 2>/dev/null | tail -n1)
  if [ -n "$f" ]; then
    echo "-- $s from $f --"
    grep -iE 'account|xxobster|using keys|trading as' "$f" 2>/dev/null | grep -viE 'secret|api_key' | tail -n 5
  fi
done

echo "=== CRYPTHOR key fingerprint match (prefix only) ==="
python3 - <<'PY'
import re,os
env={}
for line in open('/etc/crypthor/bybit.env',encoding='utf-8',errors='ignore'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    env[k.strip()]=v.strip().strip('"').strip("'")
ck=env.get('BYBIT_API_KEY','')
print('crypthor_key_prefix', ck[:6]+'...'+ck[-4:] if len(ck)>10 else 'missing')
# parse bybit_keys.txt accounts and compare prefixes
path='/etc/botsgeneral/bybit_keys.txt'
text=open(path,encoding='utf-8',errors='ignore').read()
# flexible parse
accounts={}
cur=None
for line in text.splitlines():
    m=re.match(r'^\[(.+)\]\s*$', line.strip())
    if m:
        cur=m.group(1).strip(); accounts.setdefault(cur,{}); continue
    m=re.match(r'^([A-Za-z][A-Za-z0-9_]*)\s*$', line.strip())
    if m and 'key' not in m.group(1).lower():
        cur=m.group(1); accounts.setdefault(cur,{}); continue
    if cur:
        m=re.search(r'api[_ ]?key\s*[:=]\s*(\S+)', line, re.I)
        if m: accounts[cur]['api_key']=m.group(1).strip().strip('"').strip("'")
        m=re.search(r'api[_ ]?secret\s*[:=]\s*(\S+)', line, re.I)
        if m: accounts[cur]['api_secret']=m.group(1).strip().strip('"').strip("'")
matches=[]
for name,creds in accounts.items():
    k=creds.get('api_key','')
    if k and ck and k==ck:
        matches.append(name)
    if k:
        print('stored', name, k[:6]+'...'+k[-4:])
print('CRYPTHOR_MATCHES', matches or 'NONE')
PY

echo "=== DIVERGENCES screens now ==="
screen -ls
ps -eo pid,args | grep -iE 'diverg|run_live' | grep -v grep | head
# which live.env used by launcher
grep -RInE 'live.env|BYBIT_ACCOUNT|Xxobster' /opt/divergences/deploy /opt/divergences/scripts /etc/systemd/system/divergences-screens.service 2>/dev/null | grep -vi secret | head -n 40
