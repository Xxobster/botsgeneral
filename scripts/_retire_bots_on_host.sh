#!/usr/bin/env bash
# Stop/disable retired bots on this host. Args: space-separated name patterns.
set -euo pipefail
PATTERNS=("$@")
if [[ ${#PATTERNS[@]} -eq 0 ]]; then
  echo "usage: $0 pattern [pattern...]" >&2
  exit 2
fi

echo "HOST=$(hostname -I | awk '{print $1}')"
echo "PATTERNS=${PATTERNS[*]}"

# Disable matching unit files
while IFS= read -r unit; do
  [[ -z "$unit" ]] && continue
  echo "disable --now $unit"
  systemctl disable --now "$unit" 2>&1 || true
  systemctl stop "$unit" 2>&1 || true
done < <(
  systemctl list-unit-files --type=service --no-legend \
    | awk '{print $1}' \
    | while read -r u; do
        for p in "${PATTERNS[@]}"; do
          if [[ "$u" == *"$p"* ]]; then
            echo "$u"
            break
          fi
        done
      done
)

# Kill leftover matching processes (best-effort)
for p in "${PATTERNS[@]}"; do
  pgrep -af "$p" 2>/dev/null | grep -v "vps_retire\|bash -c\|pgrep" || true
  pkill -f "$p" 2>/dev/null || true
done

echo "REMAINING units:"
systemctl list-units --type=service --all --no-pager \
  | grep -iE "$(IFS='|'; echo "${PATTERNS[*]}")" || echo "(none)"
echo "DONE"
