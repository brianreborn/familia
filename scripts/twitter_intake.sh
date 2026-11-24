#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SKILL="$ROOT/skills/ideas-from-x/SKILL.md"
if [[ ! -f "$SKILL" ]]; then
  echo "twitter_intake: missing $SKILL" >&2
  exit 2
fi
printf "%s\n" "twitter_intake: canonical skill present: $SKILL"
printf "%s\n" "twitter_intake: no autonomous write runner configured; use an approved agent/human review path"
