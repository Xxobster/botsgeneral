#!/bin/bash
set -e
# Restart only xxobster2 + xxobster13 live loops with updated cross_pair_live.py
for pid in $(pgrep -f 'vps_run_asset_live.py ethusdt$' || true); do kill "$pid" 2>/dev/null || true; done
for pid in $(pgrep -f 'vps_run_asset_live.py btcusdt$' || true); do kill "$pid" 2>/dev/null || true; done
for pid in $(pgrep -f 'vps_run_asset_live_match.py' || true); do kill "$pid" 2>/dev/null || true; done
sleep 2
# Quit all screens matching these exact names (may have duplicates)
screen -ls | awk '/\.xxobster2(BTC|ETH)USDT|\.xxobster13(BTC|ETH)USDT/{print $1}' | while read -r id; do
  screen -S "$id" -X quit 2>/dev/null || true
done
sleep 2
screen -wipe >/dev/null 2>&1 || true
mkdir -p /home/xgb/log/btcusdt /home/xgb/log/ethusdt /home/xgb_match/log/btcusdt /home/xgb_match/log/ethusdt
screen -dmS xxobster2BTCUSDT bash -lc 'cd /home/xgb && python3 scripts/vps_run_asset_live.py btcusdt >> log/btcusdt/restart.log 2>&1'
screen -dmS xxobster2ETHUSDT bash -lc 'cd /home/xgb && python3 scripts/vps_run_asset_live.py ethusdt >> log/ethusdt/restart.log 2>&1'
screen -dmS xxobster13BTCUSDT bash -lc 'cd /home/xgb_match && PYTHONUNBUFFERED=1 PYTHONPATH=/home/xgb_match /home/xgb_match/venv/bin/python -u scripts/vps_run_asset_live_match.py btcusdt >> log/btcusdt/restart.log 2>&1'
screen -dmS xxobster13ETHUSDT bash -lc 'cd /home/xgb_match && PYTHONUNBUFFERED=1 PYTHONPATH=/home/xgb_match /home/xgb_match/venv/bin/python -u scripts/vps_run_asset_live_match.py ethusdt >> log/ethusdt/restart.log 2>&1'
sleep 5
echo '=== screens ==='
screen -ls | grep -E 'xxobster2|xxobster13' || true
echo '=== procs ==='
pgrep -af 'vps_run_asset_live' | grep -vE 'ethusdt7|ethusdt8|btcusdt7|btcusdt8' | grep -v grep || true
echo '=== import ==='
cd /home/xgb && python3 -c 'from utils.cross_pair_live import MACRO_YAHOO; print("VIX", "VIX" in MACRO_YAHOO)'
