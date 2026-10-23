#!/bin/bash
set +e
echo "HOST=$(hostname)"
echo "VPS_ID=$(cat /etc/botsgeneral/vps_id 2>/dev/null || echo none)"
echo
echo "=== SCREENS ==="
screen -ls 2>/dev/null | head -n 100 || true
echo
echo "=== SYSTEMD (bot-like) ==="
systemctl list-units --type=service --all --no-pager 2>/dev/null \
  | grep -Ei 'tsm|xgb|ld-live|crypthor|karmaa|diverg|crypto_alpha|botsgeneral|collector|news' \
  | head -n 100 || true
echo
echo "=== PROCESSES ==="
ps -eo pid,cmd --no-headers 2>/dev/null \
  | grep -Ei 'vps_run_asset|run_ld_live|run_live|crypthor|karmaa|diverg|tsm-vpa|crypto_alpha|botsgeneral.collect' \
  | grep -v grep | head -n 100 || true
echo
echo "=== KEY ACCOUNT NAMES (headers only, no secrets) ==="
list_txt_accounts() {
  local f="$1"
  [ -f "$f" ] || return 0
  echo "-- $f --"
  # Section headers like [Xxobster5] or bare account lines before key=
  awk '
    /^[[:space:]]*\[.*\]/ { gsub(/[\[\]]/,""); print $0; next }
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    /^[A-Za-z][A-Za-z0-9_]*[[:space:]]*$/ { print $1; next }
    /[Xx]xobster[0-9]+/ && !/(api_key|api_secret|API_KEY|API_SECRET|secret)/ {
      if (match($0, /[Xx]xobster[0-9]+/)) print substr($0, RSTART, RLENGTH)
    }
  ' "$f" | sort -u
}
list_json_accounts() {
  local f="$1"
  [ -f "$f" ] || return 0
  echo "-- $f --"
  python3 - "$f" <<'PY'
import json,sys
p=sys.argv[1]
try:
    d=json.load(open(p))
except Exception as e:
    print("parse_error",e); sys.exit(0)
for k in sorted(d):
    if str(k).endswith("_local"):
        continue
    print(k)
PY
}
for f in \
  /etc/botsgeneral/bybit_keys.txt \
  /etc/botsgeneral/keys.txt \
  /etc/botsgeneral/binance_keys.txt \
  /home/xgb/api_keys.json \
  /home/xgb/config/api_keys.json \
  /home/xgb_match/api_keys.json \
  /home/xgb_match/config/api_keys.json \
  /home/ld/api_keys.json \
  /home/ld/config/api_keys.json \
  /root/api_keys.json
do
  case "$f" in
    *.json) list_json_accounts "$f" ;;
    *) list_txt_accounts "$f" ;;
  esac
done
echo
echo "=== ACCOUNT REFS IN LIVE CONFIGS (no secret lines) ==="
# Focused paths
for root in /opt/tsm-vpa /opt/divergences /opt/crypthor /root/karmaa_mp /home/crypto_alpha /home/xgb /home/xgb_match /home/ld /etc/systemd/system; do
  [ -d "$root" ] || continue
  hits=$(grep -RIn --include='*.yaml' --include='*.yml' --include='*.json' --include='*.env' --include='*.service' --include='*.toml' --include='*.cfg' --include='*.ini' --include='*.txt' \
    -E '[Xx]xobster[0-9]+' "$root" 2>/dev/null \
    | grep -viE 'api_key|api_secret|API_KEY|API_SECRET|secret|password|token' \
    | head -n 80)
  if [ -n "$hits" ]; then
    echo "-- $root --"
    echo "$hits"
  fi
done
echo
echo "=== BOT DIRS PRESENT ==="
ls -d /home/xgb /home/xgb_match /home/ld /home/crypto_alpha /opt/tsm-vpa /opt/divergences /opt/crypthor /root/karmaa_mp /opt/botsgeneral 2>/dev/null
echo
echo "=== END ==="
