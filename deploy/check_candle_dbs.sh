#!/usr/bin/env bash
set -euo pipefail
echo "===== SHARED ====="
ls -lh /var/lib/botsgeneral/shared_candles.db 2>/dev/null || echo "no shared db"
python3 - <<'PY'
import sqlite3, time
from pathlib import Path
p=Path("/var/lib/botsgeneral/shared_candles.db")
if not p.exists():
    raise SystemExit
con=sqlite3.connect(str(p))
now=time.time()*1000
print(f"{'ex':7} {'sym':10} {'tf':4} {'bars':>8} {'lag_min':>8} {'mtime_fresh':>12}")
for ex,sym,tf,n,mx in con.execute("SELECT exchange,symbol,timeframe,COUNT(*),MAX(ts_ms) FROM candles GROUP BY 1,2,3 ORDER BY 1,2,3"):
    lag=(now-mx)/60000 if mx else None
    print(f"{ex:7} {sym:10} {tf:4} {n:8d} {lag:8.1f}" if lag is not None else f"{ex} {sym} {tf} {n}")
con.close()
print("shared file mtime:", time.ctime(p.stat().st_mtime))
PY

check_db() {
  local label="$1"; shift
  echo
  echo "===== $label ====="
  for f in "$@"; do
    if [ -f "$f" ]; then
      mt=$(stat -c '%y' "$f" 2>/dev/null | cut -d. -f1)
      sz=$(stat -c '%s' "$f" 2>/dev/null)
      echo "FILE $f size=$sz mtime=$mt"
      python3 - "$f" <<'PY' 2>/dev/null || true
import sqlite3,sys,time
p=sys.argv[1]
con=sqlite3.connect(p)
tables=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("  tables:", ",".join(tables[:12]))
# try common candle layouts
for q in [
 "SELECT COUNT(*), MAX(ts_ms) FROM candles",
 "SELECT COUNT(*), MAX(timestamp) FROM candles",
]:
  try:
    n,mx=con.execute(q).fetchone(); print(f"  candles n={n} max={mx}"); break
  except Exception: pass
for t in tables:
  if t.endswith("_bybit") or "_5m" in t or t.startswith("btcusdt") or t=="raw_klines":
    try:
      cols=[c[1] for c in con.execute(f"PRAGMA table_info({t})")]
      if "ts_ms" in cols:
        n,mx=con.execute(f"SELECT COUNT(*), MAX(ts_ms) FROM {t}").fetchone()
      elif "timestamp" in cols:
        n,mx=con.execute(f"SELECT COUNT(*), MAX(timestamp) FROM {t}").fetchone()
      else:
        n=con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]; mx=None
      print(f"  {t}: n={n} max={mx}")
    except Exception as e:
      print(f"  {t}: err {e}")
con.close()
PY
    fi
  done
}

HOST=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "HOST=$HOST"

# 212-style paths
check_db "CRYPTHOR bybit dbs" /opt/crypthor/database/btcusdt_5m_bybit.db /opt/crypthor/database/ethusdt_5m_bybit.db /opt/crypthor/database/bnbusdt_5m_bybit.db /opt/crypthor/database/solusdt_5m_bybit.db
check_db "DIVERGENCES" /opt/divergences/data/divergence_lab.db
check_db "KARMAA" /root/karmaa_mp/database/btcusdt_5m_bybit.db /root/karmaa_mp/database/btcusdt_5m.db

# 94-style paths
check_db "NEWS" /home/crypto_alpha/database/crypto_alpha.db
check_db "WIP" /opt/wip/database/live_trade_log.db

echo
echo "===== SHARED_CANDLES_DB in env/units ====="
grep -R "SHARED_CANDLES" /etc/systemd/system /etc/crypthor /etc/wip /opt/crypthor/deploy /opt/divergences/config /root/karmaa_mp/deploy /home/crypto_alpha/scripts /opt/wip/deploy 2>/dev/null | head -40 || true
echo
echo "===== process cmdline SHARED / kline hints ====="
ps auxww | grep -E 'run_live|live_trade|bybit_runner|crypthor|karmaa|crypto_alpha|wip' | grep -v grep | head -30 || true
