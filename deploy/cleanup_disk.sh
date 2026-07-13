#!/usr/bin/env bash
# Free disk on trading VPS — safe cleanup (logs, caches, old journals).
set -euo pipefail
echo "=== BEFORE ==="
df -h / | tail -1
du -sh /var/log /var/lib/botsgeneral /opt /home /root 2>/dev/null || true

# Package caches
apt-get clean -y 2>/dev/null || true
apt-get autoclean -y 2>/dev/null || true
rm -rf /var/cache/apt/archives/*.deb 2>/dev/null || true

# Journals (keep 3 days / 200M)
journalctl --vacuum-time=3d 2>/dev/null || true
journalctl --vacuum-size=200M 2>/dev/null || true

# Pip / npm / tmp
rm -rf /root/.cache/pip /home/*/.cache/pip 2>/dev/null || true
rm -rf /tmp/* /var/tmp/* 2>/dev/null || true

# Rotated / huge logs
find /var/log -type f \( -name '*.gz' -o -name '*.old' -o -name '*.1' -o -name '*.2' \) -delete 2>/dev/null || true
find /var/log -type f -name '*.log' -size +50M -exec truncate -s 0 {} \; 2>/dev/null || true

# Python caches under bot trees
find /opt /home /root -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find /opt /home /root -type f -name '*.pyc' -delete 2>/dev/null || true

# Old screen / bot log archives (keep last 14 days of *.log)
find /opt /home /root -type f \( -name '*.log.[0-9]*' -o -name '*.log.gz' \) -mtime +7 -delete 2>/dev/null || true

# Snap old revisions
if command -v snap >/dev/null 2>&1; then
  snap list --all 2>/dev/null | awk '/disabled/{print $1, $3}' | while read -r name rev; do
    snap remove "$name" --revision="$rev" 2>/dev/null || true
  done
fi

# Core dumps (files only — never directories like numpy/core)
find /var/crash /tmp /var/tmp /root /home -xdev -type f \( -name 'core' -o -name 'core.[0-9]*' \) -delete 2>/dev/null || true

# Optional bulky caches (safe on trading VPS)
rm -rf /root/.npm/_cacache 2>/dev/null || true
rm -rf /root/.cache 2>/dev/null || true
# Old Cursor/VS Code server leftovers & worktrees (keep current if disk allows)
if [[ "${BOTSGENERAL_CLEAN_CURSOR:-1}" == "1" ]]; then
  rm -rf /root/.cursor/worktrees 2>/dev/null || true
  # prune old cursor-server versions keeping newest
  if [[ -d /root/.cursor-server/bin ]]; then
    cd /root/.cursor-server/bin && ls -1t 2>/dev/null | tail -n +2 | xargs -r rm -rf
  fi
  if [[ -d /root/.vscode-server/bin ]]; then
    cd /root/.vscode-server/bin && ls -1t 2>/dev/null | tail -n +2 | xargs -r rm -rf
  fi
fi


echo "=== LARGEST dirs (top) ==="
du -xh / --max-depth=2 2>/dev/null | sort -hr | head -25

echo "=== AFTER ==="
df -h / | tail -1
