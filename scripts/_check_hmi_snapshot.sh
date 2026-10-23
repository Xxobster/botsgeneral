#!/usr/bin/env bash
set -euo pipefail
systemctl restart botsgeneral-hmi-hub.service botsgeneral-hmi-agent.service
sleep 3
systemctl is-active botsgeneral-hmi-hub botsgeneral-hmi-agent
TOKEN=$(tr -d '\n' </etc/botsgeneral/hmi_token 2>/dev/null || true)
if [[ -n "$TOKEN" ]]; then
  curl -sS -o /tmp/bots_snap.json -w "http=%{http_code}\n" \
    -H "Authorization: Bearer ${TOKEN}" \
    http://127.0.0.1:8787/bots/api/snapshot || true
else
  curl -sS -o /tmp/bots_snap.json -w "http=%{http_code}\n" \
    http://127.0.0.1:8787/bots/api/snapshot || true
fi
python3 - <<'PY'
import json
d=json.load(open("/tmp/bots_snap.json"))
bots=[]
def walk(o):
  if isinstance(o, dict):
    if "bot" in o:
      bots.append(str(o.get("bot")))
    if "label" in o:
      bots.append(str(o.get("label")))
    for k in ("bots","bot_ids"):
      v=o.get(k)
      if isinstance(v, list):
        for x in v:
          if isinstance(x, str):
            bots.append(x)
          elif isinstance(x, dict) and "bot" in x:
            bots.append(str(x.get("bot")))
            if x.get("label"):
              bots.append(str(x.get("label")))
    for v in o.values():
      walk(v)
  elif isinstance(o, list):
    for i in o:
      walk(i)
walk(d)
uniq=sorted(set(bots))
banned={"divergences","crypthor2","karmaa_mp","news","xgb_match","mp_oos"}
hits=sorted(b for b in uniq if b.lower() in banned or b in banned)
print("all_botish", uniq)
print("banned_hits", hits)
PY
