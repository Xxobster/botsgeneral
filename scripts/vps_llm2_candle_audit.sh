#!/usr/bin/env bash
set -euo pipefail
echo "===HOST $(hostname -I) ==="
echo "===REGISTRY VPS BLOCK==="
grep -A30 '^vps:' /opt/botsgeneral/config/bots_registry.yaml | head -40
echo "===REGISTRY llm2* BOTS==="
grep -nE '^(  )?[a-z0-9_]+:' /opt/botsgeneral/config/bots_registry.yaml | head -80
echo "===DISCOVER==="
/opt/botsgeneral/venv/bin/python -m botsgeneral --vps "$(hostname -I | awk '{print $1}')" discover
echo "===RUNNING LLM2==="
systemctl list-units --type=service --state=running --no-pager | grep -i llm2 || true
echo "===PACK TF SCAN==="
for d in /opt/llm2-structure* /home/llm2; do
  [ -d "$d" ] || continue
  echo "-- $d"
  # pack meta / certificate / live config
  for f in "$d/certificate.yaml" "$d/pack/meta.yaml" "$d/pack/config.yaml" "$d/pack/pack.yaml"; do
    [ -f "$f" ] || continue
    echo "FILE $f"
    grep -nE 'timeframe|symbol|15m|1m|4h|1h|1w' "$f" | head -40 || true
  done
  find "$d/pack" -maxdepth 2 -type f \( -name '*.yaml' -o -name '*.yml' -o -name '*.json' \) 2>/dev/null | head -20
done
echo "===SHARED SERIES==="
/opt/botsgeneral/venv/bin/python /tmp/print_shared_history_coverage.py
