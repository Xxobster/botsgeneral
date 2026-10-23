#!/bin/bash
python3 - <<'PY'
import re
text=open("/etc/botsgeneral/bybit_keys.txt",encoding="utf-8",errors="ignore").read()
env={}
for line in open("/etc/crypthor/bybit.env",encoding="utf-8",errors="ignore"):
    if "=" in line and not line.strip().startswith("#"):
        k,v=line.split("=",1)
        env[k.strip()]=v.strip().strip("\"'")
ck=env.get("BYBIT_API_KEY","")
print("crypthor", (ck[:4]+"..."+ck[-4:]) if len(ck)>8 else "missing")
cur=None
for line in text.splitlines():
    s=line.strip()
    m=re.match(r"(?i)^ACCOUNT:\s*(.+)$", s)
    if m:
        cur=m.group(1).strip()
        continue
    m=re.match(r"(?i)^API KEY:\s*(.+)$", s)
    if m and cur:
        k=m.group(1).strip()
        print(cur, k[:4]+"..."+k[-4:], "MATCH" if k==ck else "")
PY
