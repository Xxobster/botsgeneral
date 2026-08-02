#!/usr/bin/env bash
set -euo pipefail
VPS=185.203.119.52
PATCH=/tmp/botsgeneral_patch
cd /opt/botsgeneral
cp -a "$PATCH/bots_registry.yaml" config/bots_registry.yaml
cp -a "$PATCH/keys.py" botsgeneral/keys.py
cp -a "$PATCH/botsgeneral-collector@.service" deploy/botsgeneral-collector@.service
cp -a "$PATCH/bots" deploy/bots
sed -i 's/\r$//' deploy/bots deploy/*.sh deploy/*.service || true
install -m 755 deploy/bots /usr/local/bin/bots
ln -sfn /usr/local/bin/bots /root/bots
cp deploy/botsgeneral-collector@.service /etc/systemd/system/
systemctl disable --now botsgeneral-collector@94.156.189.76.service 2>/dev/null || true
systemctl daemon-reload
systemctl enable --now "botsgeneral-collector@${VPS}.service"
sleep 3
systemctl is-active "botsgeneral-collector@${VPS}.service"
python3 - <<'PY'
from pathlib import Path
p = Path("/etc/botsgeneral/report.yaml")
text = p.read_text() if p.exists() else ""
if "Xxobster10" not in text or "accounts:" not in text:
    extra = """
# This VPS (185.203.119.52) — LD live accounts (keys in /home/ld/config/api_keys.json)
accounts:
  - Xxobster9
  - Xxobster10
  - Xxobster11
"""
    p.write_text(text.rstrip() + "\n" + extra + "\n")
    print("updated report.yaml accounts")
else:
    print("report.yaml already has accounts")
PY
echo "=== discover ==="
BOTSGENERAL_VPS="$VPS" /opt/botsgeneral/venv/bin/python -m botsgeneral --vps "$VPS" discover
echo "=== sitrep ==="
bots sitrep
echo "=== which bots ==="
which bots
bots --help | head -8
echo "=== collector units ==="
systemctl list-units 'botsgeneral*' --all --no-pager
echo "=== candle necessity ==="
python3 - <<'PY'
import os, sys
sys.path.insert(0, "/opt/botsgeneral")
os.environ["BOTSGENERAL_VPS"] = "185.203.119.52"
from botsgeneral.discover import discover_pairs, load_registry, unique_pairs, bot_runtime_status
reg = load_registry()
pairs = discover_pairs(reg, "185.203.119.52")
print("pairs_to_fetch", unique_pairs(pairs) or "(none — shared candle collect not needed)")
for b in bot_runtime_status(reg, "185.203.119.52"):
    print(f"  {b['bot']}: running={b['running']} serve_candles={b['serve_candles']} path_ok={b['path_exists']}")
PY
