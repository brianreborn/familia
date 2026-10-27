#!/bin/sh
# pilot_hud.sh: Mecha anime Pilot cockpit HUD helpers for the gum-home build/setup phase.
# Sourceable:  . scripts/pilot_hud.sh
# Or: sh scripts/pilot_hud.sh canopy|strip|instruments|spin -- TITLE...
# Charm gum when present; plain ANSI fallback. 80-col safe. No heavy TUI.
set -eu

# Allow sourcing without set -e killing the parent on a missing gum.
_pilot_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd 2>/dev/null) || _pilot_root=.
PATH="${HOME:-}/.local/bin:${PATH:-}"
export PATH

# ANSI (readable on Windows conhost + xterm)
_PILOT_R='\033[0m'
_PILOT_BOLD='\033[1m'
_PILOT_DIM='\033[2m'
_PILOT_CYAN='\033[36m'
_PILOT_TEAL='\033[96m'
_PILOT_AMBER='\033[33m'
_PILOT_GREEN='\033[32m'
_PILOT_RED='\033[31m'

_pilot_have_gum() { command -v gum >/dev/null 2>&1; }

pilot_canopy() {
  # One-shot canopy / reticle header at phase start.
  title=${1:-FAMILIA PILOT LINK}
  if _pilot_have_gum; then
    gum style --border double --border-foreground 51 --foreground 159 --bold \
      --align center --width 72 --padding "0 1" \
      "◈ $title ◈" \
      "COCKPIT HUD  ·  FRAME SYNC  ·  ORDNANCE PREFETCH"
  else
    printf '%b\n' "${_PILOT_CYAN}${_PILOT_BOLD}"
    printf '  ╔══════════════════════════════════════════════════════════════════════╗\n'
    printf '  ║  ◈ %-64s ◈  ║\n' "$title"
    printf '  ║  COCKPIT HUD  ·  FRAME SYNC  ·  ORDNANCE PREFETCH                  ║\n'
    printf '  ╚══════════════════════════════════════════════════════════════════════╝%b\n' "$_PILOT_R"
  fi
}

pilot_strip() {
  # Bold status strip: pilot_strip SYNCING_FRAME "pins + configure"
  code=${1:-STATUS}; shift
  msg=${*:-}
  if _pilot_have_gum; then
    gum style --border rounded --border-foreground 214 --foreground 230 --bold \
      --width 72 --padding "0 1" \
      "[$code] $msg"
  else
    printf '%b[%s]%b %b%s%b\n' "$_PILOT_AMBER$_PILOT_BOLD" "$code" "$_PILOT_R" "$_PILOT_TEAL" "$msg" "$_PILOT_R"
  fi
}

pilot_instruments() {
  # Two instruments: foreground compute vs background download.
  # pilot_instruments "REACTOR BUILD: configure" "PREFETCHING ORDNANCE: SmolLM+Laya"
  fg=${1:-REACTOR: idle}
  bg=${2:-ORDNANCE: idle}
  if _pilot_have_gum; then
    gum style --border rounded --border-foreground 51 --foreground 159 \
      --width 72 --padding "0 1" \
      "┌ INSTRUMENT 1 — FOREGROUND ─────────────────────" \
      "│ $fg" \
      "├ INSTRUMENT 2 — BACKGROUND ─────────────────────" \
      "│ $bg" \
      "└────────────────────────────────────────────────"
  else
    printf '%b\n' "$_PILOT_CYAN"
    printf '  ┌ INSTRUMENT 1 — FOREGROUND ─────────────────────────────────────────┐\n'
    printf '  │ %s\n' "$fg"
    printf '  ├ INSTRUMENT 2 — BACKGROUND ─────────────────────────────────────────┤\n'
    printf '  │ %s\n' "$bg"
    printf '  └────────────────────────────────────────────────────────────────────┘%b\n' "$_PILOT_R"
  fi
}

pilot_ok() { printf '%bLINK ESTABLISHED%b %s\n' "$_PILOT_GREEN$_PILOT_BOLD" "$_PILOT_R" "$*"; }
pilot_warn() { printf '%bCAUTION%b %s\n' "$_PILOT_AMBER$_PILOT_BOLD" "$_PILOT_R" "$*"; }
pilot_fail() { printf '%bFRAME FAULT%b %s\n' "$_PILOT_RED$_PILOT_BOLD" "$_PILOT_R" "$*"; }

pilot_spin() {
  # pilot_spin "SYNCING FRAME" -- cmd...
  title=$1; shift
  if [ "${1:-}" = "--" ]; then shift; fi
  if _pilot_have_gum && [ $# -gt 0 ]; then
    gum spin --spinner pulse --title "$title" -- "$@"
  elif [ $# -gt 0 ]; then
    printf '%b» %s…%b\n' "$_PILOT_TEAL" "$title" "$_PILOT_R"
    "$@"
  else
    printf '%b» %s%b\n' "$_PILOT_TEAL" "$title" "$_PILOT_R"
  fi
}

# CLI dispatcher when executed (not sourced)
case "${0##*/}" in
  pilot_hud.sh)
    cmd=${1:-}; [ $# -gt 0 ] && shift || true
    case "$cmd" in
      canopy) pilot_canopy "$@" ;;
      strip) pilot_strip "$@" ;;
      instruments) pilot_instruments "$@" ;;
      ok) pilot_ok "$@" ;;
      warn) pilot_warn "$@" ;;
      fail) pilot_fail "$@" ;;
      spin) pilot_spin "$@" ;;
      -h|--help|"")
        cat <<'H'
Usage: sh scripts/pilot_hud.sh canopy|strip|instruments|spin|ok|warn|fail …
Source: . scripts/pilot_hud.sh   then call pilot_* functions
H
        ;;
      *) printf 'pilot_hud: unknown %s\n' "$cmd" >&2; exit 2 ;;
    esac
    ;;
esac
