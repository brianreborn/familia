#!/bin/sh
# setup_goals.sh: goal-oriented Set up flows for the familia menu.
# Usage: sh scripts/setup_goals.sh <goal> [--dry-run] [--yes]
# Goals: first-time | sync-pins | remove-path
# Each goal leads to a real next action (preview then confirm where destructive).
# Called from the gum home (Install / first-time setup) and legacy menu.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PY=${PYTHON:-python3}
GOAL=""
DRY=0
YES=0

say() { printf 'familia-setup: %s\n' "$*"; }
die() { printf 'familia-setup: error: %s\n' "$1" >&2; exit "${2:-1}"; }

usage() {
  cat <<'USAGE'
Usage: sh scripts/setup_goals.sh <goal> [--dry-run] [--yes]

Goals (each ends with a real next action):
  first-time   deps → licenses → configure → confirm → install for real →
               offer PATH → print next: Talk to the protomodel (./familia)
  sync-pins    ask preview vs apply → sync_pins --dry-run or sync_pins
  remove-path  danger: uninstall-cli preview, then confirm remove from PATH

Options:
  --dry-run, -n   print the steps without running them
  --yes, -y       answer yes to confirm prompts (non-interactive apply)

Examples:
  sh scripts/setup_goals.sh first-time --dry-run
  sh scripts/setup_goals.sh sync-pins
  familia-menu.sh --run setup.first-time --dry-run
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    first-time|sync-pins|remove-path) GOAL=$1 ;;
    --dry-run|-n) DRY=1 ;;
    --yes|-y) YES=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument '$1' (see --help)" 2 ;;
  esac
  shift
done
[ -n "$GOAL" ] || { usage >&2; exit 2; }

can_prompt() { [ -t 0 ] && [ "${FAMILIA_NO_TTY:-}" != 1 ]; }

confirm() {
  # confirm QUESTION — --yes, or y on a terminal
  [ "$YES" = 1 ] && return 0
  can_prompt || return 1
  printf '%s [y/N] ' "$1" >&2
  read -r a || return 1
  case "$a" in y|Y|yes|YES) return 0 ;; esac
  return 1
}

ask_choice() {
  # ask_choice PROMPT — prints choice on stdout; empty on cancel/EOF
  can_prompt || { printf '%s\n' ""; return 1; }
  printf '%s' "$1" >&2
  read -r a || { printf '%s\n' ""; return 1; }
  printf '%s\n' "$a"
}

run_step() {
  # run_step LABEL CMD...
  label=$1; shift
  say "==> $label"
  if [ "$DRY" = 1 ]; then
    say "[dry-run] $*"
    return 0
  fi
  "$@"
}

installer() {
  if [ -f "$ROOT/install/linux/install.sh" ]; then
    printf '%s\n' "$ROOT/install/linux/install.sh"
  elif [ -f "$ROOT/install/termux/install.sh" ]; then
    printf '%s\n' "$ROOT/install/termux/install.sh"
  else
    die "no installer found under install/linux or install/termux"
  fi
}

goal_first_time() {
  # Mecha pilot HUD: this UI owns overlapping build (foreground) + model prefetch (background).
  # install.sh still owns boring prelim packages → ~/.local; the canopy is the home/setup phase.
  if [ -f "$ROOT/scripts/pilot_hud.sh" ]; then
    # shellcheck disable=SC1091
    . "$ROOT/scripts/pilot_hud.sh"
    pilot_canopy "FAMILIA PILOT LINK — FIRST-TIME SETUP"
  else
    say "Goal: first-time setup on this machine"
  fi

  # Kick free-download of first-try models in background while foreground work runs.
  if [ "$DRY" = 1 ]; then
    say "[dry-run] would PREFETCHING ORDNANCE (models) in background"
  elif [ -f "$ROOT/scripts/prefetch-first-models.sh" ]; then
    if [ -f "$ROOT/scripts/pilot_hud.sh" ]; then
      pilot_strip "PREFETCHING ORDNANCE" "first-try models (SmolLM + Laya) → background"
      pilot_instruments "REACTOR BUILD: deps → licenses → configure → install"         "PREFETCHING ORDNANCE: see .cache/prefetch-first-models.log"
    else
      say "prefetching first-try model in background…"
    fi
    sh "$ROOT/scripts/prefetch-first-models.sh" --background || say "prefetch: soft-fail (non-fatal)"
  fi

  run_step "SYNCING FRAME — OS packages" sh "$ROOT/install/deps.sh" --install
  # Ensure gum for the home (user-local); soft-fail.
  if [ -f "$ROOT/scripts/install-gum.sh" ]; then
    if [ "$DRY" = 1 ]; then
      say "[dry-run] sh scripts/install-gum.sh --dry-run"
    else
      sh "$ROOT/scripts/install-gum.sh" --yes || say "gum soft-fail; legacy: ./familia --legacy-menu"
    fi
  fi
  run_step "LICENSE GATE" "$PY" "$ROOT/scripts/licenses.py" review
  if [ -f "$ROOT/scripts/pilot_hud.sh" ] && [ "$DRY" != 1 ]; then
    pilot_strip "REACTOR BUILD" "configure (pins + hooks)"
  fi
  run_step "REACTOR BUILD — configure" sh "$ROOT/scripts/configure.sh"
  if [ "$DRY" = 1 ]; then
    say "[dry-run] would ask: Apply install on this host?"
    say "[dry-run] would run: sh $(installer)"
    say "[dry-run] would offer: Put familia on PATH?"
    say "[dry-run] next: Talk to the protomodel (./familia) or hosts.start"
    return 0
  fi
  if confirm "Apply install on this host for real?"; then
    if [ -f "$ROOT/scripts/pilot_hud.sh" ]; then
      pilot_strip "FRAME DEPLOY" "host installer"
      pilot_instruments "REACTOR BUILD: host install running"         "PREFETCHING ORDNANCE: $(sh "$ROOT/scripts/prefetch-first-models.sh" --status 2>&1 | head -1)"
    fi
    run_step "FRAME DEPLOY — install" sh "$(installer)"
  else
    say "Skipped install. You can run setup.install later, or Advanced → install."
  fi
  if confirm "Put familia on your PATH (shim in ~/.local/bin)?"; then
    run_step "Install familia CLI shim" sh "$ROOT/scripts/install-cli.sh"
    if confirm "Also add ~/.local/bin to PATH in ~/.profile?"; then
      run_step "Add PATH block to ~/.profile" sh "$ROOT/scripts/install-cli.sh" path --add --yes
    fi
  else
    say "Skipped PATH. Use setup.install-cli later, or Advanced → install-cli."
  fi
  say ""
  if [ -f "$ROOT/scripts/pilot_hud.sh" ]; then
    pilot_ok "First-time setup finished."
    pilot_strip "NEXT" "Talk to the protomodel — ./familia"
  else
    say "First-time setup finished."
    say "Next: Talk to the protomodel — run ./familia and pick that goal"
  fi
  say "  or start a server: ./familia start   /   ./familia-menu.sh --run hosts.start"
}

goal_sync_pins() {
  say "Goal: sync pinned parts only"
  if [ "$DRY" = 1 ]; then
    say "[dry-run] would ask: preview or apply?"
    say "[dry-run] preview: $PY scripts/sync_pins.py --dry-run"
    say "[dry-run] apply:   $PY scripts/sync_pins.py  (license gate first when run from menu)"
    return 0
  fi
  choice=$(ask_choice "Sync pins: [p]review (no changes), [a]pply, or [q]uit? " || true)
  case "$choice" in
    p|P|preview)
      run_step "Preview pin sync" "$PY" "$ROOT/scripts/sync_pins.py" --dry-run
      ;;
    a|A|apply)
      run_step "Apply pin sync" "$PY" "$ROOT/scripts/sync_pins.py"
      ;;
    q|Q|""|quit)
      say "Cancelled."
      return 0
      ;;
    *)
      die "expected p, a, or q (got '$choice')" 2
      ;;
  esac
}

goal_remove_path() {
  say "Goal: remove familia from PATH (danger)"
  say "This removes the recorded CLI shim / PATH entries — not your checkout or models."
  if [ "$DRY" = 1 ]; then
    say "[dry-run] would run: sh scripts/install-cli.sh uninstall --dry-run"
    say "[dry-run] would ask confirm, then: sh scripts/install-cli.sh uninstall --yes"
    return 0
  fi
  run_step "Uninstall preview" sh "$ROOT/scripts/install-cli.sh" uninstall --dry-run || true
  if confirm "Remove familia from PATH for real?"; then
    run_step "Uninstall CLI from PATH" sh "$ROOT/scripts/install-cli.sh" uninstall --yes
  else
    say "Cancelled — PATH unchanged."
  fi
}

case "$GOAL" in
  first-time) goal_first_time ;;
  sync-pins) goal_sync_pins ;;
  remove-path) goal_remove_path ;;
esac
