#!/usr/bin/env bash
set -euo pipefail
# Run the X‑Twitter intake skill
# The skill is defined in skills/ideas-from-x/SKILL.md
# Assuming the familia CLI can invoke a skill via:
#   familia skill run ideas-from-x-posts
# Adjust the command if the actual CLI differs.
if command -v familia >/dev/null 2>&1; then
  familia skill run ideas-from-x-posts 
else
  echo Error: familia command not found – cannot run skill >&2
  exit 1
fi
