#!/bin/sh
# required_checks.sh: giant flashing must-run for the three critical bash smokes.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
GUM=$(command -v gum || true)

case "${1:-}" in
  -h|--help)
    cat <<'USAGE'
Usage: sh scripts/required_checks.sh

★ Must-run: execute the three critical bash smokes for real:
  tests/test_with_fleet.sh
  tests/test_nexus_localhost.sh
  tests/test_bt_loopback.sh

Example:
  sh scripts/required_checks.sh
  ./familia   # then pick ★ Required checks (must-run)
USAGE
    exit 0 ;;
esac

flash() {
  # ANSI blink + bright red/yellow banner (also via gum style when available)
  msg=$1
  if [ -n "$GUM" ]; then
    gum style --border double --border-foreground 196 --foreground 226 --bold \
      --align center --width 72 --padding "1 2" \
      "★ REQUIRED CHECK (MUST-RUN) ★" "$msg"
  else
    printf '\033[5;1;91m'
    printf '╔══════════════════════════════════════════════════════════════════════╗\n'
    printf '║  ★ REQUIRED CHECK (MUST-RUN) ★                                       ║\n'
    printf '║  %s\n' "$msg"
    printf '╚══════════════════════════════════════════════════════════════════════╝\n'
    printf '\033[0m'
  fi
}

run_one() {
  rel=$1
  flash "$rel"
  printf '\n'
  if [ -n "$GUM" ]; then
    gum spin --spinner pulse --title "Running $rel …" -- bash "$ROOT/$rel" \
      && printf '\033[1;32mPASS\033[0m %s\n' "$rel" \
      || { printf '\033[1;91mFAIL\033[0m %s\n' "$rel"; return 1; }
  else
    bash "$ROOT/$rel" \
      && printf '\033[1;32mPASS\033[0m %s\n' "$rel" \
      || { printf '\033[1;91mFAIL\033[0m %s\n' "$rel"; return 1; }
  fi
}

flash "Three critical bash smokes — run for REAL (not dry-run)"
printf '\n  1) tests/test_with_fleet.sh\n  2) tests/test_nexus_localhost.sh\n  3) tests/test_bt_loopback.sh\n\n'

fails=0
run_one tests/test_with_fleet.sh || fails=$((fails+1))
run_one tests/test_nexus_localhost.sh || fails=$((fails+1))
run_one tests/test_bt_loopback.sh || fails=$((fails+1))

printf '\n'
if [ "$fails" = 0 ]; then
  if [ -n "$GUM" ]; then
    gum style --foreground 46 --bold "All three Required checks PASSED."
  else
    printf '\033[1;32mAll three Required checks PASSED.\033[0m\n'
  fi
  exit 0
fi
if [ -n "$GUM" ]; then
  gum style --foreground 196 --bold "$fails of 3 Required checks FAILED."
else
  printf '\033[1;91m%s of 3 Required checks FAILED.\033[0m\n' "$fails"
fi
exit 1
