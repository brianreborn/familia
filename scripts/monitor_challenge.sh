#!/usr/bin/env bash
set -euo pipefail

REPO="brianreborn/familia"
GH="gh"

# 1. Find all menu- branches
BRANCHES=$($GH api repos/$REPO/branches --paginate | jq -r '.[].name' | grep '^menu-') || true

# 2. Ensure CI ran (push no‑op commit if needed)
for B in $BRANCHES; do
  echo "[monitor] Checking CI for $B"
  $GH api repos/$REPO/commits -F message="ci‑keepalive [$B]" -F branch=$B > /dev/null 2>&1 || true
done

# 3. Download performance artifacts (expects artifact named "${B}_perf")
declare -A SCORE
for B in $BRANCHES; do
  ART=$($GH api repos/$REPO/actions/artifacts --paginate |
        jq -r ".artifacts[] | select(.name==\"${B}_perf\") | .id")
  if [[ -n $ART ]]; then
    $GH api repos/$REPO/actions/artifacts/$ART/zip -H "Accept: application/zip" -o /tmp/${B}_perf.zip
    unzip -p /tmp/${B}_perf.zip generated/performance.log > /tmp/${B}_perf.json
    LAT=$(jq '.latency_ms' /tmp/${B}_perf.json)
    MEM=$(jq '.peak_mem_mb' /tmp/${B}_perf.json)
    CPU=$(jq '.cpu_time_s' /tmp/${B}_perf.json)
    SCORE[$B]=$(awk "BEGIN {print (0.4*$LAT)+(0.3*$MEM)+(0.2*$CPU)}")
  fi
done

# 4. Pick best (lowest score)
WIN=$(for k in "${!SCORE[@]}"; do echo "$k ${SCORE[$k]}"; done | sort -k2n | head -n1 | cut -d' ' -f1)

# 5. Merge into a unified branch on development (no auto‑merge to main)
git checkout development
git pull origin development
git checkout -b menu-unified-$WIN
git merge --no-ff $WIN -m "Auto‑merged $WIN as unified menu (target dev)"

# 6. Pull extra menu items from other branches
for B in $BRANCHES; do
  [[ $B == $WIN ]] && continue
  if git diff --name-only $WIN..$B | grep -q "menu-extras.txt"; then
    git checkout $B -- menu-extras.txt
    cat menu-extras.txt >> docs/menu-extras.md
  fi
done

# 7. Push unified branch and open PR against development
git push origin menu-unified-$WIN
PR=$($GH pr create -B development -H menu-unified-$WIN \
      --title "Menu Redesign – Unified (dev)" \
      --body "Auto‑merged best implementation $WIN. Extras collected in docs/menu-extras.md.")

echo "Unified PR created: $PR"

# 8. Cleanup
rm -f /tmp/*_perf.*

# Conflict handling – prompt user if merge conflict
if git ls-files -u | grep -q .; then
  echo "[PROMPT] Merge conflict while integrating $WIN. Please resolve manually."
fi
