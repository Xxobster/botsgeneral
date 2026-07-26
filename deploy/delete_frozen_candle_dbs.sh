#!/usr/bin/env bash
# Delete frozen local candle DBs on migrated bots. Keep news + xgb Binance DBs.
set -euo pipefail
echo "HOST=$(hostname -I | awk '{print $1}')"
echo "=== BEFORE disk ==="
df -h / | tail -1

freed=0
rm_candle() {
  local f="$1"
  if [ -f "$f" ]; then
    local sz
    sz=$(stat -c%s "$f" 2>/dev/null || echo 0)
    echo "DELETE $f ($(numfmt --to=iec "$sz" 2>/dev/null || echo "${sz}B"))"
    rm -f "$f" "${f}-wal" "${f}-shm" "${f}-journal" 2>/dev/null || true
    freed=$((freed + sz))
  fi
}

# ---- crypthor2 (212): live Bybit tails + Binance history used only for old merge ----
if [ -d /opt/crypthor/database ]; then
  echo "--- crypthor ---"
  # bybit live tails
  find /opt/crypthor/database -maxdepth 1 -type f \( -name '*_bybit.db' -o -name '*_bybit.db-*' \) -print
  find /opt/crypthor/database -maxdepth 1 -type f -name '*_bybit.db' | while read -r f; do rm_candle "$f"; done
  # per-symbol interval candle files (btcusdt_5m.db etc.) — not trade logs
  for f in /opt/crypthor/database/*usdt_*.db; do
    [ -f "$f" ] || continue
    base=$(basename "$f")
    case "$base" in
      *trade*|*log*) echo "KEEP $f";;
      *_bybit.db) ;; # already handled
      *) rm_candle "$f";;
    esac
  done
fi

# ---- karmaa_mp (212) ----
if [ -d /root/karmaa_mp/database ]; then
  echo "--- karmaa_mp ---"
  for f in /root/karmaa_mp/database/*usdt_*.db /root/karmaa_mp/database/*_bybit.db; do
    [ -f "$f" ] || continue
    base=$(basename "$f")
    case "$base" in
      *trade*|*log*) echo "KEEP $f";;
      *) rm_candle "$f";;
    esac
  done
fi

# ---- divergences: keep research DB file, clear frozen candles table only ----
if [ -f /opt/divergences/data/divergence_lab.db ]; then
  echo "--- divergences (clear candles table, keep research) ---"
  python3 - <<'PY'
import sqlite3
p="/opt/divergences/data/divergence_lab.db"
con=sqlite3.connect(p)
n=con.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
con.execute("DELETE FROM candles")
con.commit()
con.execute("VACUUM")
con.close()
print(f"cleared {n} candle rows from {p}")
PY
fi

# ---- W.I.P: no candle DB (trade log only) — keep ----
if [ -f /opt/wip/database/live_trade_log.db ]; then
  echo "KEEP /opt/wip/database/live_trade_log.db (trades, not candles)"
fi

# ---- NEVER touch news / xgb Binance DBs ----
echo "--- protected (not deleted) ---"
for f in \
  /home/crypto_alpha/database/crypto_alpha.db \
  /home/xgb/database/assets/*.db \
  /home/xgb/database/assets_live/*.db \
  /home/xgb/database/*.db
 do
  [ -e "$f" ] && echo "KEEP $f"
 done 2>/dev/null || true

echo "=== AFTER disk ==="
df -h / | tail -1
echo "Approx bytes removed from candle files: $freed"
echo "Shared DB still present:"
ls -lh /var/lib/botsgeneral/shared_candles.db 2>/dev/null || echo "MISSING shared db!"
