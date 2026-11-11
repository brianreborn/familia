#!/bin/sh
# android-cockpit-switches.sh: entry-screen switches for the Android installer
# when going into the llama-ui web cockpit (familia_home.sh) or from the
# legacy catalog (setup.android-cockpit). Matches familia-menu style
# (numbered picks, --pipe, invalid input stays). Settings persist under
# ${XDG_CONFIG_HOME:-$HOME/.config}/familia/android-cockpit.env (mode 0600).
# A prefix copy may be written for a kept prefix but is never read back.
# The menu exits ONLY on an explicit exit pick (q/quit/exit). Errors,
# finished actions, invalid input and timeouts return to the menu.
# "Continue to web cockpit" (c/23) opens open_ui.sh from the familia_home
# hook (exit 4). From the legacy catalog it says so, or opens open_ui.sh
# when not in --pipe.
#
# Installer discovery (PR #321 paths; degrade if absent):
#   thin client: packaging/android/familia-android-smoke.sh
#   on-phone:    install/termux/install-hermes-android.sh
#                or install/termux/install.sh
# Override: FAMILIA_ANDROID_INSTALLER. Only flags the detected script
# accepts are passed; other switches stay visible as [n/a: ...].
#
# Usage:
#   sh scripts/android-cockpit-switches.sh            interactive (needs a TTY)
#   sh scripts/android-cockpit-switches.sh --pipe     choices from stdin (tests)
#   sh scripts/android-cockpit-switches.sh --dump     settings + installer command
#   sh scripts/android-cockpit-switches.sh --show     installer command only
#   sh scripts/android-cockpit-switches.sh --help
#
# Secure defaults: thin client, gate ON, --yes refused, dry-run ON,
# never auto-start. Each device serves its own webapp (Brian,
# 2026-11-10 11:15 PM PT, "each its own" / self-hosting): on-phone
# and local modes default the host/URL to http://127.0.0.1:9941
# (loopback, no key). Thin client starts at that same loopback (or
# empty), never a fixed remote. A remote host is an explicit opt-in,
# with HTTPS plus an API key per F2.
# HTTPS is the default for a remote (non-loopback) host. The literal
# name localhost counts as loopback for the HTTPS default only (plain
# HTTP is OK); the API key rule stays IP-only (127.0.0.0/8 and ::1).
# Plain HTTP to a remote host is allowed only when the named dev
# switch "dev: allow plain HTTP" is on (off by default, marked * when
# on), or when FAMILIA_DEV_ALLOW_HTTP=1. http:// CBL URLs are always
# rejected. Start, or a non-loopback-IP host, still needs an API key.
# Exit 0 = q (back to familia_home). Exit 4 = continue to open_ui.sh.
set -eu
umask 077

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
INSTALLER=""
SCRIPT_KIND=""
SCRIPT_BASE=""
PIPE=0
MODE=menu
TIMEOUT=${FAMILIA_MENU_TIMEOUT:-60}
HAVE_READ_T=0
HAVE_ENV_U=0
WIDTH=68
USE_BOX=1
COMPACT=0
PAGE=1
PAGES=4
NARROW=0

# Secure defaults (cockpit). The installer CLI still treats --dry-run as opt-in;
# this menu passes --dry-run unless the user turns the switch off.
THIN_CLIENT=1
CTX_GATE=1
FAMILIA_CTX_VAL=""
ALLOW_YES=0
DRY_RUN=1
KEEP_PREFIX=0
START_FAMILIA=0
HTTPS=0
DEV_ALLOW_HTTP=0
# Self-host default: this device's webapp (not a fixed remote).
DEFAULT_HOST=127.0.0.1
DEFAULT_PORT=9941
HOST=$DEFAULT_HOST
PORT=$DEFAULT_PORT
TIER=""
LIC_LLAMA31=1
LIC_DOLPHIN=1
LIC_LFM=0
FETCH_PYYAML=0
COMMIT=""
URL_FILE=""
CBL_TAG=""
CBL_SHA=""
CBL_ASSET=""
CBL_URL=""
API_KEY_FILE=""
RUNTIME_KIND=cbl

XDG_BASE="${XDG_CONFIG_HOME:-$HOME/.config}"
CONFIG_DIR="$XDG_BASE/familia"
XDG_FILE="$CONFIG_DIR/android-cockpit.env"
SMOKE_PREFIX=${FAMILIA_SMOKE_PREFIX:-${TMPDIR:-$HOME/.cache}/familia-smoke}
PREFIX_FILE="$SMOKE_PREFIX/android-cockpit.env"

# Wrap at COLUMNS so no emitted line is wider than the terminal
# (including the "exit. settings saved to ..." path).
say() { say_row "$*"; }
err() { say_row "android-cockpit: $*" >&2; }

default_key_path() { printf '%s' "$CONFIG_DIR/api.key"; }

expand_tilde() {
  # Quote the case patterns and the ${1#...} pattern: an unquoted ~ is
  # itself expanded to $HOME, so a typed ~/key would never match (or
  # would become $HOME/~/key).
  case "$1" in
    "~") printf '%s' "$HOME" ;;
    "~/"*) printf '%s' "$HOME/${1#"~/"}" ;;
    *) printf '%s' "$1" ;;
  esac
}

# uid and octal mode of a path (lstat). GNU or BSD stat.
file_uid_mode() {
  _p=$1
  if stat -c '%u %a' "$_p" >/dev/null 2>&1; then
    stat -c '%u %a' "$_p"
  elif stat -f '%u %OLp' "$_p" >/dev/null 2>&1; then
    stat -f '%u %OLp' "$_p"
  else
    return 1
  fi
}

# Regular file, not a symlink, owned by this uid, mode 0600 or tighter
# (no group/other bits). Used for settings and API key files.
safe_secret_file() {
  _p=$1
  [ -e "$_p" ] || return 1
  if [ -L "$_p" ]; then
    return 1
  fi
  [ -f "$_p" ] || return 1
  _um=$(file_uid_mode "$_p") || return 1
  _uid=${_um%% *}
  _mode=${_um#* }
  [ "$_uid" = "$(id -u)" ] || return 1
  case "$_mode" in
    *[!0-9]*) return 1 ;;
  esac
  # GNU/BSD %a is a decimal-looking octal string (600, 0600). Group and
  # other digits must be 0; do not parse the whole string as base 10.
  case "$_mode" in
    *[!0-7]*) return 1 ;;
  esac
  printf '%s' "$_mode" | grep -Eq '^[0-7]*00$' || [ "$_mode" = 0 ]
}

probe_read_t() {
  # dash has no read -t (rc 2 + a message on stderr). bash accepts it
  # and times out with rc 1 or 142 from /dev/null. Probe must not
  # consume this script's stdin. Do not depend on the English error text.
  _rc=0
  _e=$( ( IFS= read -t 0 -r _probe_x < /dev/null ) 2>&1 ) || _rc=$?
  if [ "$_rc" -eq 2 ] && [ -n "$_e" ]; then
    HAVE_READ_T=0
    return 0
  fi
  HAVE_READ_T=1
}

# Same names as #321 install/termux/widget/familia-hermes-android.sh
# (feat/android-packaging @ 283a526), plus FAMILIA_ALLOW_YES. A leftover
# export of any of these is treated as typed ACCEPT by install.sh / hermes.
license_scrub_vars() {
  # Gate- and override-type names this screen controls, or that weaken
  # a gate if inherited. assemble_and then sets only what the switches
  # selected. Also any currently exported FAMILIA_ALLOW_* or
  # FAMILIA_*ACCEPT* / INSTALL_ACK (see extra_scrub_from_env).
  #   INSTALL_ACK
  #   FAMILIA_ACCEPT_LICENSES
  #   FAMILIA_ACCEPT_UNKNOWN_LICENSES
  #   FAMILIA_LICENSE_ACCEPT_FILE
  #   FAMILIA_ALLOW_YES
  #   FAMILIA_HERMES_CTX_GATE
  #   FAMILIA_BIND
  #   FAMILIA_CTX
  #   FAMILIA_PHONE_MODEL_TIER
  #   FAMILIA_RUNTIME
  #   FAMILIA_API_KEY_FILE
  #   FAMILIA_CBL_ANDROID_TAG
  #   FAMILIA_CBL_ANDROID_SHA256
  #   FAMILIA_CBL_ANDROID_ASSET
  #   FAMILIA_CBL_DOWNLOAD_URL
  #   FAMILIA_CBL_URL
  printf '%s\n' \
    INSTALL_ACK \
    FAMILIA_ACCEPT_LICENSES \
    FAMILIA_ACCEPT_UNKNOWN_LICENSES \
    FAMILIA_LICENSE_ACCEPT_FILE \
    FAMILIA_ALLOW_YES \
    FAMILIA_HERMES_CTX_GATE \
    FAMILIA_BIND \
    FAMILIA_CTX \
    FAMILIA_PHONE_MODEL_TIER \
    FAMILIA_RUNTIME \
    FAMILIA_API_KEY_FILE \
    FAMILIA_CBL_ANDROID_TAG \
    FAMILIA_CBL_ANDROID_SHA256 \
    FAMILIA_CBL_ANDROID_ASSET \
    FAMILIA_CBL_DOWNLOAD_URL \
    FAMILIA_CBL_URL
}

extra_scrub_from_env() {
  env 2>/dev/null | awk -F= '
    /^FAMILIA_ALLOW_[A-Za-z0-9_]+=/ { print $1 }
    /^FAMILIA_[A-Za-z0-9_]*ACCEPT[A-Za-z0-9_]*=/ { print $1 }
    /^INSTALL_ACK=/ { print $1 }
  '
}

all_scrub_vars() {
  { license_scrub_vars; extra_scrub_from_env; } | awk 'NF && !seen[$0]++'
}

probe_env_u() {
  # GNU and BSD env support -u. Some POSIX env do not. Probe must not
  # depend on help text.
  HAVE_ENV_U=0
  _e=$(
    _FAMILIA_ENV_U_PROBE=1
    export _FAMILIA_ENV_U_PROBE
    env -u _FAMILIA_ENV_U_PROBE sh -c 'printf %s "${_FAMILIA_ENV_U_PROBE+set}"' 2>/dev/null
  ) && [ -z "$_e" ] && HAVE_ENV_U=1
  return 0
}

# Clear inherited license-accept env. Use env -u when the probe passed;
# otherwise unset in a subshell, export our NAME=val words, then exec.
run_assembled() {
  if [ "$HAVE_ENV_U" = 1 ]; then
    "$@"
    return $?
  fi
  shift
  (
    # Same documented list as license_scrub_vars, plus discovered ALLOW_*/ACCEPT_*.
    _ul=$(all_scrub_vars)
    for _u in $_ul; do
      unset "$_u" 2>/dev/null || true
    done
    while [ $# -gt 0 ]; do
      case "$1" in
        *=*)
          export "$1" || exit 1
          shift
          ;;
        *)
          break
          ;;
      esac
    done
    exec "$@"
  )
}

kind_of_path() {
  case "${1##*/}" in
    familia-android-smoke.sh) printf '%s' smoke ;;
    install-hermes-android.sh) printf '%s' hermes ;;
    install.sh) printf '%s' install ;;
    install-android.sh) printf '%s' prototype ;;
    *) printf '%s' unknown ;;
  esac
}

flag_ok() {
  _f=$1
  case "$SCRIPT_KIND" in
    smoke)
      case "$_f" in
        --commit|--host|--port|--https|--url-file|--local-inference|--dry-run|--keep|--remove) return 0 ;;
        *) return 1 ;;
      esac
      ;;
    install)
      case "$_f" in
        --dry-run|--yes|--accept-unknown|--runtime|--no-runtime|--uninstall|--purge|--name|--sshd|--force-host|--no-wakelock|--no-path|--branch) return 0 ;;
        *) return 1 ;;
      esac
      ;;
    hermes)
      case "$_f" in
        --dry-run|--yes|--accept-unknown|--skip-install|--launch-only|--no-open) return 0 ;;
        *) return 1 ;;
      esac
      ;;
    prototype)
      case "$_f" in
        --commit|--host|--port|--https|--url-file|--local-inference|--no-ctx-gate|--allow-yes|--yes|--licenses|--fetch-pyyaml|--start|--dry-run|--keep|--remove) return 0 ;;
        *) return 1 ;;
      esac
      ;;
    *)
      case "$_f" in
        --dry-run) return 0 ;;
        *) return 1 ;;
      esac
      ;;
  esac
}

env_ok() {
  _f=$1
  case "$SCRIPT_KIND" in
    smoke)
      case "$_f" in
        FAMILIA_CBL_ANDROID_TAG|FAMILIA_CBL_ANDROID_SHA256|FAMILIA_CBL_ANDROID_ASSET|FAMILIA_CBL_URL|FAMILIA_CTX|FAMILIA_PHONE_MODEL_TIER) return 0 ;;
        *) return 1 ;;
      esac
      ;;
    install|hermes|prototype)
      case "$_f" in
        FAMILIA_CBL_ANDROID_TAG|FAMILIA_CBL_ANDROID_SHA256|FAMILIA_CBL_ANDROID_ASSET|FAMILIA_CBL_DOWNLOAD_URL|FAMILIA_CBL_URL|FAMILIA_CTX|FAMILIA_PHONE_MODEL_TIER|FAMILIA_RUNTIME|FAMILIA_API_KEY_FILE|FAMILIA_ALLOW_YES|FAMILIA_HERMES_CTX_GATE|FAMILIA_ACCEPT_LICENSES) return 0 ;;
        *) return 1 ;;
      esac
      ;;
    *) return 1 ;;
  esac
}

resolve_installer() {
  INSTALLER=""
  SCRIPT_KIND=""
  SCRIPT_BASE=""
  if [ -n "${FAMILIA_ANDROID_INSTALLER:-}" ]; then
    if [ -f "$FAMILIA_ANDROID_INSTALLER" ] && [ -r "$FAMILIA_ANDROID_INSTALLER" ]; then
      INSTALLER=$FAMILIA_ANDROID_INSTALLER
      SCRIPT_KIND=$(kind_of_path "$INSTALLER")
      SCRIPT_BASE=${INSTALLER##*/}
      return 0
    fi
    err "FAMILIA_ANDROID_INSTALLER is set but not a readable file"
    return 1
  fi
  _thin="$ROOT/packaging/android/familia-android-smoke.sh"
  _hermes="$ROOT/install/termux/install-hermes-android.sh"
  _inst="$ROOT/install/termux/install.sh"
  _pick=""
  if [ "$THIN_CLIENT" = 1 ]; then
    if [ -f "$_thin" ] && [ -r "$_thin" ]; then _pick=$_thin
    elif [ -f "$_inst" ] && [ -r "$_inst" ]; then _pick=$_inst
    elif [ "$START_FAMILIA" = 1 ] && [ -f "$_hermes" ] && [ -r "$_hermes" ]; then _pick=$_hermes
    fi
  else
    # hermes always starts familia-start (no skip-start flag). Only pick it
    # when start is ON; otherwise prefer install.sh.
    if [ "$START_FAMILIA" = 1 ] && [ -f "$_hermes" ] && [ -r "$_hermes" ]; then _pick=$_hermes
    elif [ -f "$_inst" ] && [ -r "$_inst" ]; then _pick=$_inst
    elif [ -f "$_thin" ] && [ -r "$_thin" ]; then _pick=$_thin
    elif [ -f "$_hermes" ] && [ -r "$_hermes" ]; then _pick=$_hermes
    fi
  fi
  if [ -n "$_pick" ]; then
    INSTALLER=$_pick
    SCRIPT_KIND=$(kind_of_path "$INSTALLER")
    SCRIPT_BASE=${INSTALLER##*/}
    return 0
  fi
  return 1
}

installer_available() {
  [ -n "${INSTALLER:-}" ] && [ -f "$INSTALLER" ] && [ -r "$INSTALLER" ]
}

need_installer() {
  resolve_installer || true
  if installer_available; then
    return 0
  fi
  err "installer not available on this commit"
  return 1
}

na_label() {
  if [ -n "$SCRIPT_BASE" ]; then
    printf '%s' "n/a: $SCRIPT_BASE has no such flag"
  else
    printf '%s' "n/a: installer not on this commit"
  fi
}

phone_gate_ok() {
  case "$FAMILIA_CTX_VAL" in
    ''|*[!0-9]*) return 1 ;;
  esac
  [ "$FAMILIA_CTX_VAL" -ge 64000 ]
}

tier_ctx() {
  case "$TIER" in
    tiny|small) printf '%s' 2048 ;;
    medium) printf '%s' 4096 ;;
    large) printf '%s' 8192 ;;
    *) printf '%s' 8192 ;;
  esac
}

tier_min_usable() {
  case "$1" in
    tiny) printf '%s' 0 ;;
    small) printf '%s' 1024 ;;
    medium) printf '%s' 2048 ;;
    large) printf '%s' 4096 ;;
    *) printf '%s' 4096 ;;
  esac
}

tier_from_usable() {
  if [ "$1" -lt 1024 ]; then printf '%s' tiny
  elif [ "$1" -lt 2048 ]; then printf '%s' small
  elif [ "$1" -lt 4096 ]; then printf '%s' medium
  else printf '%s' large
  fi
}

# Modest per-ctx usable floor, scaled from a measured 64000-ctx point.
#
# Measurement: galaxy2 (Samsung A57) ran LFM3-1.7B at ctx 65536 with about
# 2 GB RSS. A linear scale from the large-tier table (4096 MiB usable at
# ctx 8192) would demand 32000 MiB usable at 64000 and grey out every real
# phone, which is wrong.
#
# About 3 GiB usable at 64000 would be nicer headroom for the default
# small/medium model, but that floor is impossible with the reserve
# phone-model-default.py actually uses. That file is not on main; on
# #321 (feat/android-packaging @ 283a526) DEFAULT_RESERVE is 5120, and
# install/termux/install.sh uses the same FAMILIA_RESERVE_MIB:-5120.
# An 8 GB phone (about 7600 MiB MemTotal) then has only
# 7600-5120=2480 MiB usable, so a 3072 MiB floor would fail the rule
# that an 8 GB phone must pass at 64000. Keep reserve 5120 and default
# FAMILIA_MIN_USABLE_MIB to 2048 (the measured RSS). Override either
# env if a tighter or looser floor is wanted.
required_usable_for_ctx() {
  _base=${FAMILIA_MIN_USABLE_MIB:-2048}
  case "$_base" in
    ''|*[!0-9]*) _base=2048 ;;
  esac
  printf '%s' $(( (_base * $1 + 63999) / 64000 ))
}

read_total_ram_mib() {
  if [ -n "${FAMILIA_RAM_MIB:-}" ]; then
    printf '%s' "$FAMILIA_RAM_MIB"
    return 0
  fi
  if [ -r /proc/meminfo ]; then
    awk '/^MemTotal:/ { print int($2 / 1024); exit }' /proc/meminfo
    return 0
  fi
  return 1
}

# 0 + reason if RAM cannot hold on-phone at the current ctx/tier.
ram_block_reason() {
  _ram=$(read_total_ram_mib) || {
    printf '%s' "MemTotal unknown; refusing on-phone until FAMILIA_RAM_MIB is set or /proc/meminfo is readable"
    return 0
  }
  case "$_ram" in
    ''|*[!0-9]*)
      printf '%s' "MemTotal unreadable; refusing on-phone"
      return 0
      ;;
  esac
  _res=${FAMILIA_RESERVE_MIB:-5120}
  case "$_res" in
    ''|*[!0-9]*) _res=5120 ;;
  esac
  _usable=$((_ram - _res))
  [ "$_usable" -lt 0 ] && _usable=0
  _tier=$TIER
  [ -n "$_tier" ] || _tier=$(tier_from_usable "$_usable")
  _need=$(tier_min_usable "$_tier")
  if [ -n "$FAMILIA_CTX_VAL" ]; then
    case "$FAMILIA_CTX_VAL" in
      *[!0-9]*) ;;
      *)
        _cneed=$(required_usable_for_ctx "$FAMILIA_CTX_VAL")
        [ "$_cneed" -gt "$_need" ] && _need=$_cneed
        ;;
    esac
  fi
  if [ "$_usable" -lt "$_need" ]; then
    printf '%s' "RAM too low for on-phone: MemTotal ${_ram} MiB, reserve ${_res} MiB, usable ${_usable} MiB < ${_need} MiB needed for tier ${_tier} (ctx ${FAMILIA_CTX_VAL:-$(tier_ctx)})"
    return 0
  fi
  return 1
}

onphone_block_reason() {
  if ! phone_gate_ok; then
    _tc=$(tier_ctx)
    printf '%s' "phone-tier ctx $_tc < 64000; set FAMILIA_CTX >= 64000 to enable on-phone"
    return 0
  fi
  if _rr=$(ram_block_reason); then
    printf '%s' "$_rr"
    return 0
  fi
  return 1
}

use_color() {
  case "${FAMILIA_COLOR:-auto}" in always) return 0 ;; never) return 1 ;; esac
  [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-dumb}" != dumb ]
}

utf8_tty() {
  [ -t 1 ] || return 1
  case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in *UTF-8*|*utf-8*|*utf8*|*UTF8*) return 0 ;; esac
  return 1
}

cp437_tty() {
  [ -t 1 ] || return 1
  case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in *CP437*|*cp437*|*IBM437*|*ibm437*|*437*) return 0 ;; esac
  return 1
}

term_cols() {
  _cols=""
  if [ -n "${COLUMNS:-}" ]; then
    _cols=$COLUMNS
  else
    _cols=$(tput cols 2>/dev/null) || _cols=""
    if [ -z "$_cols" ]; then
      _cols=$(stty size 2>/dev/null | cut -d' ' -f2) || _cols=""
    fi
  fi
  case "$_cols" in ''|*[!0-9]*) _cols=80 ;; esac
  [ "$_cols" -lt 8 ] && _cols=8
  printf '%s' "$_cols"
}

term_rows() {
  _rows=""
  if [ -n "${LINES:-}" ]; then
    _rows=$LINES
  else
    _rows=$(tput lines 2>/dev/null) || _rows=""
    if [ -z "$_rows" ]; then
      _rows=$(stty size 2>/dev/null | cut -d' ' -f1) || _rows=""
    fi
  fi
  case "$_rows" in ''|*[!0-9]*) _rows=24 ;; esac
  [ "$_rows" -lt 8 ] && _rows=8
  printf '%s' "$_rows"
}

# Paged/compact when the terminal is under 30 rows, or when a full
# paint would not fit LINES. Full paint is about 42 lines.
need_pages() {
  _rows=$(term_rows)
  if [ "$_rows" -lt 30 ]; then
    return 0
  fi
  [ "$_rows" -lt 42 ]
}

init_box() {
  _cols=$(term_cols)
  # WIDTH tracks the inner bar; the drawn box is two spaces + corners
  # (COLUMNS-4). No 40-column floor: a 40-column terminal gets WIDTH=36.
  _w=$((_cols - 4))
  [ "$_w" -gt 68 ] && _w=68
  [ "$_w" -lt 8 ] && _w=8
  WIDTH=$_w
  NARROW=0
  [ "$_cols" -lt 68 ] && NARROW=1
  # No box borders under 48 columns, or when the compact/paged
  # layout is in use, so the frame cannot wrap or steal rows.
  USE_BOX=1
  COMPACT=0
  if [ "$_cols" -lt 48 ] || need_pages; then
    USE_BOX=0
    COMPACT=1
  fi
  if [ "$USE_BOX" = 1 ] && [ "$NARROW" != 1 ] && utf8_tty; then
    TL=$(printf '\342\225\224'); TR=$(printf '\342\225\227')
    BL=$(printf '\342\225\232'); BR=$(printf '\342\225\235')
    H=$(printf '\342\225\220');  V=$(printf '\342\225\221')
  elif [ "$USE_BOX" = 1 ] && [ "$NARROW" != 1 ] && cp437_tty; then
    TL=$(printf '\311'); TR=$(printf '\273')
    BL=$(printf '\310'); BR=$(printf '\274')
    H=$(printf '\315');  V=$(printf '\272')
  else
    TL="+"; TR="+"; BL="+"; BR="+"; H="-"; V="|"
  fi
}

C0=""; C1=""; CReset=""
init_color() {
  if use_color; then
    C0=$(printf '\033[1;36m')
    C1=$(printf '\033[0;36m')
    CReset=$(printf '\033[0m')
  else
    C0=""; C1=""; CReset=""
  fi
}

box_bar() {
  if [ "$USE_BOX" != 1 ]; then
    return 0
  fi
  _l=$1; _r=$2
  printf '  %s' "$_l"
  _i=0; while [ "$_i" -lt "$WIDTH" ]; do printf '%s' "$H"; _i=$((_i + 1)); done
  printf '%s\n' "$_r"
}
box_text() {
  _t=$1
  if [ "$USE_BOX" != 1 ]; then
    say_row "$_t"
    return 0
  fi
  _pad=$((WIDTH - 2))
  [ "$_pad" -gt 0 ] || _pad=1
  printf '  %s %s%-*.*s%s %s\n' "$V" "$C1" "$_pad" "$_pad" "$_t" "$CReset" "$V"
}

# Wrap at COLUMNS instead of hard-cutting, so Host, Port and status stay
# visible on a 40-column terminal. No emitted line is longer than COLUMNS.
say_row() {
  _t=$1
  _lim=$(term_cols)
  [ "$_lim" -ge 8 ] || _lim=8
  printf '%s\n' "$_t" | awk -v n="$_lim" '
    {
      s = $0
      first = 1
      while (length(s) > 0) {
        w = n
        prefix = ""
        if (first == 0) {
          prefix = "    "
          w = n - length(prefix)
          if (w < 8) { prefix = ""; w = n }
        }
        if (length(s) <= w) { print prefix s; break }
        chunk = substr(s, 1, w)
        sp = 0
        for (i = length(chunk); i > int(w / 2); i--) {
          if (substr(chunk, i, 1) == " ") { sp = i; break }
        }
        if (sp > 1) {
          print prefix substr(s, 1, sp - 1)
          s = substr(s, sp + 1)
        } else {
          print prefix chunk
          s = substr(s, w + 1)
        }
        first = 0
      }
    }
  '
}

heading() { say_row "  -- $1 --"; }

onoff() { if [ "$1" = 1 ]; then say ON; else say OFF; fi; }

star_if() {
  if [ "$1" = "$2" ]; then printf '%s' ""
  else printf '%s' "*"
  fi
}

trim() {
  printf '%s' "$1" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

strip_cr() {
  printf '%s' "$1" | tr -d '\r'
}

no_ctl_chars() {
  _n=$(printf '%s' "$1" | tr -d '\n\r')
  [ "$1" = "$_n" ]
}

valid_bool() { [ "$1" = 0 ] || [ "$1" = 1 ]; }
valid_commit() { printf '%s' "$1" | grep -Eq '^[0-9a-f]{40}$'; }
valid_sha() { printf '%s' "$1" | grep -Eq '^[0-9a-f]{64}$'; }
valid_port() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
valid_tier() { case "$1" in auto|"") return 0 ;; tiny|small|medium|large) return 0 ;; *) return 1 ;; esac; }
valid_ctx() { case "$1" in ''|clear|unset) return 0 ;; *[!0-9]*) return 1 ;; *) return 0 ;; esac; }
valid_runtime() { case "$1" in cbl|pkg) return 0 ;; *) return 1 ;; esac; }

# Hostname / IPv4 / [IPv6], same charset as familia-android-smoke.sh.
# A leading '-' is rejected so a value cannot inject flags.
valid_host() {
  case "$1" in
    ""|-*) return 1 ;;
  esac
  no_ctl_chars "$1" || return 1
  printf '%s' "$1" | grep -Eq '^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*|\[[0-9A-Fa-f:.]+\])$'
}

# Only real loopback IP addresses (127.0.0.0/8 and ::1). A hostname
# such as 127.example.com or localhost is not an IP and needs a key
# (Boundary: the key rule stays IP-only). Newline or CR is rejected
# so grep -Eq cannot match only the first line.
is_loopback() {
  no_ctl_chars "$1" || return 1
  case "$1" in
    \[::1\]|::1) return 0 ;;
  esac
  printf '%s' "$1" | grep -Eq '^127\.([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\.([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\.([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])$'
}

# Loopback for the HTTPS default only: real loopback IPs plus the
# literal name localhost (plain HTTP is OK). Not used for the key rule.
is_https_loopback() {
  is_loopback "$1" && return 0
  no_ctl_chars "$1" || return 1
  case "$1" in
    localhost) return 0 ;;
  esac
  return 1
}

# Each device serves its own webapp. Fill an empty host/port with the
# self-host loopback; never invent a remote host.
apply_self_host_defaults() {
  [ -n "$HOST" ] || HOST=$DEFAULT_HOST
  [ -n "$PORT" ] || PORT=$DEFAULT_PORT
}

webapp_url() {
  [ -n "$HOST" ] && [ -n "$PORT" ] || return 1
  _h=$HOST
  if [ "$HTTPS" = 1 ]; then
    printf 'https://%s:%s' "$_h" "$PORT"
  else
    printf 'http://%s:%s' "$_h" "$PORT"
  fi
}

# Same rule as assemble_and: start, or a non-loopback-IP host, needs a key.
# Loopback IPs do not (localhost still does).
listener_key_label() {
  if [ "$START_FAMILIA" = 1 ] || { [ -n "$HOST" ] && ! is_loopback "$HOST"; }; then
    printf '%s' "listener: key required"
  elif [ -n "$HOST" ] && is_loopback "$HOST"; then
    printf '%s' "listener: no key (loopback)"
  else
    printf '%s' "listener: key required for a remote host"
  fi
}

valid_path() {
  case "$1" in
    /*) ;;
    *) return 1 ;;
  esac
  no_ctl_chars "$1"
}

valid_https_url() {
  case "$1" in
    https://*) ;;
    *) return 1 ;;
  esac
  no_ctl_chars "$1" || return 1
  printf '%s' "$1" | grep -Eq '^https://[A-Za-z0-9._~:/?#@!$&()*+,;=%-]+$'
}

valid_cbl_tag() {
  case "$1" in
    ""|-*) return 1 ;;
  esac
  printf '%s' "$1" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{0,126}$'
}

valid_cbl_asset() {
  case "$1" in
    ""|-*) return 1 ;;
  esac
  printf '%s' "$1" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._+-]{0,190}$'
}

known_key() {
  case "$1" in
    THIN_CLIENT|CTX_GATE|FAMILIA_CTX_VAL|ALLOW_YES|DRY_RUN|KEEP_PREFIX|START_FAMILIA|HTTPS|DEV_ALLOW_HTTP|HOST|PORT|TIER|LIC_LLAMA31|LIC_DOLPHIN|LIC_LFM|FETCH_PYYAML|COMMIT|URL_FILE|CBL_TAG|CBL_SHA|CBL_ASSET|CBL_URL|API_KEY_FILE|RUNTIME_KIND) return 0 ;;
    *) return 1 ;;
  esac
}

secure_default_for() {
  case "$1" in
    THIN_CLIENT|CTX_GATE|DRY_RUN|LIC_LLAMA31|LIC_DOLPHIN) printf '%s' 1 ;;
    ALLOW_YES|KEEP_PREFIX|START_FAMILIA|HTTPS|DEV_ALLOW_HTTP|LIC_LFM|FETCH_PYYAML) printf '%s' 0 ;;
    RUNTIME_KIND) printf '%s' cbl ;;
    *) printf '%s' "" ;;
  esac
}

warn_bad() {
  err "ignoring invalid $1 in settings (using secure default); value not applied"
}


# Apply one already-trimmed, already-unquoted key=value.
apply_key() {
  _k=$1
  _v=$2
  case "$_k" in
    THIN_CLIENT|CTX_GATE|ALLOW_YES|DRY_RUN|KEEP_PREFIX|START_FAMILIA|HTTPS|DEV_ALLOW_HTTP|LIC_LLAMA31|LIC_DOLPHIN|LIC_LFM|FETCH_PYYAML)
      if valid_bool "$_v"; then
        case "$_k" in
          THIN_CLIENT) THIN_CLIENT=$_v ;;
          CTX_GATE) CTX_GATE=$_v ;;
          ALLOW_YES) ALLOW_YES=$_v ;;
          DRY_RUN) DRY_RUN=$_v ;;
          KEEP_PREFIX) KEEP_PREFIX=$_v ;;
          START_FAMILIA) START_FAMILIA=$_v ;;
          HTTPS) HTTPS=$_v ;;
          DEV_ALLOW_HTTP) DEV_ALLOW_HTTP=$_v ;;
          LIC_LLAMA31) LIC_LLAMA31=$_v ;;
          LIC_DOLPHIN) LIC_DOLPHIN=$_v ;;
          LIC_LFM) LIC_LFM=$_v ;;
          FETCH_PYYAML) FETCH_PYYAML=$_v ;;
        esac
        return 0
      fi
      warn_bad "$_k"
      case "$_k" in
        THIN_CLIENT) THIN_CLIENT=1 ;;
        CTX_GATE) CTX_GATE=1 ;;
        ALLOW_YES) ALLOW_YES=0 ;;
        DRY_RUN) DRY_RUN=1 ;;
        KEEP_PREFIX) KEEP_PREFIX=0 ;;
        START_FAMILIA) START_FAMILIA=0 ;;
        HTTPS) HTTPS=0 ;;
        DEV_ALLOW_HTTP) DEV_ALLOW_HTTP=0 ;;
        LIC_LLAMA31) LIC_LLAMA31=1 ;;
        LIC_DOLPHIN) LIC_DOLPHIN=1 ;;
        LIC_LFM) LIC_LFM=0 ;;
        FETCH_PYYAML) FETCH_PYYAML=0 ;;
      esac
      return 1
      ;;
    FAMILIA_CTX_VAL)
      if [ -z "$_v" ] || valid_ctx "$_v"; then
        if [ "$_v" = clear ] || [ "$_v" = unset ]; then _v=""; fi
        FAMILIA_CTX_VAL=$_v
        return 0
      fi
      warn_bad "$_k"
      FAMILIA_CTX_VAL=""
      return 1
      ;;
    HOST)
      if [ -z "$_v" ]; then HOST=""; return 0; fi
      if valid_host "$_v"; then HOST=$_v; return 0; fi
      warn_bad "$_k"
      HOST=""
      return 1
      ;;
    PORT)
      if [ -z "$_v" ]; then PORT=""; return 0; fi
      if valid_port "$_v"; then PORT=$_v; return 0; fi
      warn_bad "$_k"
      PORT=""
      return 1
      ;;
    TIER)
      if [ -z "$_v" ] || [ "$_v" = auto ]; then TIER=""; return 0; fi
      if valid_tier "$_v"; then TIER=$_v; return 0; fi
      warn_bad "$_k"
      TIER=""
      return 1
      ;;
    RUNTIME_KIND)
      if valid_runtime "$_v"; then RUNTIME_KIND=$_v; return 0; fi
      warn_bad "$_k"
      RUNTIME_KIND=cbl
      return 1
      ;;
    COMMIT)
      if [ -z "$_v" ]; then COMMIT=""; return 0; fi
      if valid_commit "$_v"; then COMMIT=$_v; return 0; fi
      warn_bad "$_k"
      COMMIT=""
      return 1
      ;;
    URL_FILE)
      if [ -z "$_v" ]; then URL_FILE=""; return 0; fi
      _v=$(expand_tilde "$_v")
      if valid_path "$_v"; then URL_FILE=$_v; return 0; fi
      warn_bad "$_k"
      URL_FILE=""
      return 1
      ;;
    API_KEY_FILE)
      if [ -z "$_v" ]; then API_KEY_FILE=""; return 0; fi
      _v=$(expand_tilde "$_v")
      if valid_path "$_v"; then API_KEY_FILE=$_v; return 0; fi
      warn_bad "$_k"
      API_KEY_FILE=""
      return 1
      ;;
    CBL_TAG)
      if [ -z "$_v" ]; then CBL_TAG=""; return 0; fi
      if valid_cbl_tag "$_v"; then CBL_TAG=$_v; return 0; fi
      warn_bad "$_k"
      CBL_TAG=""
      return 1
      ;;
    CBL_SHA)
      if [ -z "$_v" ]; then CBL_SHA=""; return 0; fi
      if valid_sha "$_v"; then CBL_SHA=$_v; return 0; fi
      warn_bad "$_k"
      CBL_SHA=""
      return 1
      ;;
    CBL_ASSET)
      if [ -z "$_v" ]; then CBL_ASSET=""; return 0; fi
      if valid_cbl_asset "$_v"; then CBL_ASSET=$_v; return 0; fi
      warn_bad "$_k"
      CBL_ASSET=""
      return 1
      ;;
    CBL_URL)
      if [ -z "$_v" ]; then CBL_URL=""; return 0; fi
      if valid_https_url "$_v"; then CBL_URL=$_v; return 0; fi
      warn_bad "$_k"
      CBL_URL=""
      return 1
      ;;
    *) return 1 ;;
  esac
}

load_file() {
  # Never abort the menu because a settings file is unreadable (set -e).
  [ -e "$1" ] || return 0
  if [ ! -r "$1" ]; then
    err "settings file not readable; using secure defaults"
    return 0
  fi
  if ! safe_secret_file "$1"; then
    err "ignoring settings file that is a symlink, not owned by you, or not mode 0600 (or tighter). Shared storage or a Windows FS cannot hold 0600; keep it under Termux \$HOME or the XDG config dir."
    return 0
  fi
  _seen=" "
  while IFS= read -r _line || [ -n "$_line" ]; do
    _raw=$_line
    _crless=$(printf '%s' "$_raw" | tr -d '\r')
    _one_cr=$(printf '%s\r' "$_crless")
    if [ "$_raw" != "$_crless" ] && [ "$_raw" != "$_one_cr" ]; then
      _peek=$(strip_cr "$_raw")
      _peek=$(trim "$_peek")
      _pk=${_peek%%=*}
      _pk=$(trim "$_pk")
      case "$_pk" in
        HOST|CBL_URL|URL_FILE)
          err "ignoring invalid $_pk in settings (CR or newline in the value); using secure default"
          continue
          ;;
      esac
    fi
    _line=$(strip_cr "$_line")
    _line=$(trim "$_line")
    case "$_line" in ""|\#*) continue ;; esac
    _k=${_line%%=*}
    _v=${_line#*=}
    _k=$(trim "$_k")
    _v=$(trim "$_v")
    known_key "$_k" || continue
    case "$_k" in
      HOST|CBL_URL|URL_FILE)
        if ! no_ctl_chars "$_v"; then
          err "ignoring invalid $_k in settings (CR or newline in the value); using secure default"
          continue
        fi
        ;;
    esac
    case "$_seen" in
      *" $_k "*)
        err "duplicate settings key $_k; keeping the first value"
        continue
        ;;
    esac
    _seen="$_seen$_k "
    case "$_v" in
      \"*\") _v=${_v#\"}; _v=${_v%\"}; _v=$(trim "$_v") ;;
      \'*\') _v=${_v#\'}; _v=${_v%\'}; _v=$(trim "$_v") ;;
    esac
    apply_key "$_k" "$_v" || true
  done < "$1" || {
    err "could not read settings file; using values already loaded or the secure defaults"
    return 0
  }
  if [ "$THIN_CLIENT" != 1 ]; then
    if _br=$(onphone_block_reason); then
      err "on-phone inference ignored in settings: $_br"
      THIN_CLIENT=1
    fi
  fi
  if [ -n "$CBL_TAG$CBL_ASSET$CBL_URL" ] && ! valid_sha "$CBL_SHA"; then
    err "CBL override ignored in settings: tag/url/asset requires a 64-hex sha256"
    CBL_TAG=""; CBL_SHA=""; CBL_ASSET=""; CBL_URL=""
  fi
  return 0
}

atomic_write() {
  # atomic_write DEST: reads stdin, writes via mktemp + mv in the same dir.
  # Replaces a symlink at DEST instead of following it. Never uses cp.
  _dest=$1
  _dir=$(dirname -- "$_dest")
  mkdir -m 700 -p "$_dir" || { err "could not create $_dir"; return 1; }
  _tmp=$(mktemp "$_dir/android-cockpit.env.XXXXXX") || { err "could not write $_dest"; return 1; }
  trap 'rm -f "$_tmp"; exit 130' INT TERM
  cat > "$_tmp" || { rm -f "$_tmp"; trap - INT TERM; return 1; }
  chmod 0600 "$_tmp"
  mv "$_tmp" "$_dest"
  trap - INT TERM
  return 0
}

save_settings() {
  mkdir -m 700 -p "$CONFIG_DIR" || { err "could not create $CONFIG_DIR"; return 1; }
  if ! {
    printf '# familia android cockpit switches. Do not store API key secrets here, only paths.\n'
    printf 'THIN_CLIENT=%s\n' "$THIN_CLIENT"
    printf 'CTX_GATE=%s\n' "$CTX_GATE"
    printf 'FAMILIA_CTX_VAL=%s\n' "$FAMILIA_CTX_VAL"
    printf 'ALLOW_YES=%s\n' "$ALLOW_YES"
    printf 'DRY_RUN=%s\n' "$DRY_RUN"
    printf 'KEEP_PREFIX=%s\n' "$KEEP_PREFIX"
    printf 'START_FAMILIA=%s\n' "$START_FAMILIA"
    printf 'HTTPS=%s\n' "$HTTPS"
    printf 'DEV_ALLOW_HTTP=%s\n' "$DEV_ALLOW_HTTP"
    printf 'HOST=%s\n' "$HOST"
    printf 'PORT=%s\n' "$PORT"
    printf 'TIER=%s\n' "$TIER"
    printf 'LIC_LLAMA31=%s\n' "$LIC_LLAMA31"
    printf 'LIC_DOLPHIN=%s\n' "$LIC_DOLPHIN"
    printf 'LIC_LFM=%s\n' "$LIC_LFM"
    printf 'FETCH_PYYAML=%s\n' "$FETCH_PYYAML"
    printf 'COMMIT=%s\n' "$COMMIT"
    printf 'URL_FILE=%s\n' "$URL_FILE"
    printf 'CBL_TAG=%s\n' "$CBL_TAG"
    printf 'CBL_SHA=%s\n' "$CBL_SHA"
    printf 'CBL_ASSET=%s\n' "$CBL_ASSET"
    printf 'CBL_URL=%s\n' "$CBL_URL"
    printf 'API_KEY_FILE=%s\n' "$API_KEY_FILE"
    printf 'RUNTIME_KIND=%s\n' "$RUNTIME_KIND"
  } | atomic_write "$XDG_FILE"; then
    return 1
  fi
  if [ -d "$SMOKE_PREFIX" ] || [ "$KEEP_PREFIX" = 1 ]; then
    mkdir -m 700 -p "$SMOKE_PREFIX" 2>/dev/null || true
    if [ -d "$SMOKE_PREFIX" ]; then
      # Write-only copy for a kept prefix; never loaded back (XDG is source of truth).
      atomic_write "$PREFIX_FILE" < "$XDG_FILE" || true
    fi
  fi
  return 0
}

# XDG only. The prefix copy is write-only and is never read back.
load_settings() {
  if [ -e "$XDG_FILE" ]; then
    load_file "$XDG_FILE"
  fi
  apply_dev_http_env
  apply_self_host_defaults
  apply_https_policy
}

licenses_csv() {
  _c=""
  [ "$LIC_LLAMA31" = 1 ] && _c="${_c:+$_c,}llama31"
  [ "$LIC_DOLPHIN" = 1 ] && _c="${_c:+$_c,}dolphin"
  [ "$LIC_LFM" = 1 ] && _c="${_c:+$_c,}lfm"
  printf '%s' "$_c"
}

mode_label() {
  if [ "$THIN_CLIENT" = 1 ]; then say "thin client"
  else say "on-phone inference"
  fi
}

shell_quote() {
  printf "'"
  printf '%s' "$1" | sed "s/'/'\\\\''/g"
  printf "'"
}

print_quoted() {
  _sep=""
  for _a in "$@"; do
    printf '%s%s' "$_sep" "$(shell_quote "$_a")"
    _sep=" "
  done
  printf '\n'
}

key_file_to_use() {
  _kf=${API_KEY_FILE:-$(default_key_path)}
  _kf=$(expand_tilde "$_kf")
  printf '%s' "$_kf"
}

require_key_file() {
  _kf=$(key_file_to_use)
  if [ ! -e "$_kf" ]; then
    err "start / a non-loopback host requires an API key file (set switch 12 or create $(default_key_path)). Key is not logged."
    return 1
  fi
  if ! safe_secret_file "$_kf"; then
    err "API key file must be a regular file owned by you, mode 0600 or tighter (not a symlink, not group- or world-readable). Shared storage or a Windows FS cannot hold 0600; keep it under Termux \$HOME or the XDG config dir. Path: $_kf. Key is not logged."
    return 1
  fi
  return 0
}

cbl_override_ok() {
  if [ -z "$CBL_TAG$CBL_ASSET$CBL_URL" ]; then
    return 0
  fi
  if valid_sha "$CBL_SHA" && [ -n "$CBL_TAG" ]; then
    return 0
  fi
  err "CBL override needs a tag and a 64-hex sha256 together; not passing any CBL env"
  return 1
}

# Build argv in this function and either print a quoted display line or exec it.
# Never pastes values into a string for sh -c.
assemble_and() {
  _action=$1
  resolve_installer || true
  apply_self_host_defaults
  apply_https_policy
  if [ -n "$HOST" ] && ! is_https_loopback "$HOST" && [ "$HTTPS" != 1 ] && [ "$DEV_ALLOW_HTTP" != 1 ]; then
    err "plain HTTP to a remote host needs dev: allow plain HTTP (or FAMILIA_DEV_ALLOW_HTTP=1)"
    return 1
  fi
  need_installer || return 1
  if flag_ok --commit && [ -z "$COMMIT" ]; then err "set a 40-hex --commit first"; return 1; fi
  if flag_ok --host || flag_ok --port; then
    if [ -z "$HOST" ] || [ -z "$PORT" ]; then err "set host and port first"; return 1; fi
  fi
  if [ "$THIN_CLIENT" != 1 ]; then
    if _br=$(onphone_block_reason); then
      err "$_br"
      return 1
    fi
  fi
  if [ "$SCRIPT_KIND" = hermes ] && [ "$START_FAMILIA" != 1 ]; then
    err "install-hermes-android.sh always starts familia-start and has no skip-start flag; turn start ON to run it, or use install.sh"
    return 1
  fi
  if [ "$START_FAMILIA" = 1 ] || { [ -n "$HOST" ] && ! is_loopback "$HOST"; }; then
    require_key_file || return 1
  fi
  _lic=$(licenses_csv)
  if flag_ok --licenses && [ -z "$_lic" ]; then err "enable at least one license set"; return 1; fi

  set -- env
  if [ "$HAVE_ENV_U" = 1 ]; then
    _scrub=$(all_scrub_vars)
    for _u in $_scrub; do
      set -- "$@" -u "$_u"
    done
  fi
  if [ -n "$FAMILIA_CTX_VAL" ] && env_ok FAMILIA_CTX; then
    set -- "$@" "FAMILIA_CTX=$FAMILIA_CTX_VAL"
  fi
  if [ -n "$TIER" ] && env_ok FAMILIA_PHONE_MODEL_TIER; then
    set -- "$@" "FAMILIA_PHONE_MODEL_TIER=$TIER"
  fi
  if cbl_override_ok; then
    if [ -n "$CBL_TAG" ] && env_ok FAMILIA_CBL_ANDROID_TAG && env_ok FAMILIA_CBL_ANDROID_SHA256; then
      set -- "$@" "FAMILIA_CBL_ANDROID_TAG=$CBL_TAG" "FAMILIA_CBL_ANDROID_SHA256=$CBL_SHA"
    fi
    if [ -n "$CBL_ASSET" ] && env_ok FAMILIA_CBL_ANDROID_ASSET; then
      set -- "$@" "FAMILIA_CBL_ANDROID_ASSET=$CBL_ASSET"
    fi
    if [ -n "$CBL_URL" ]; then
      if env_ok FAMILIA_CBL_DOWNLOAD_URL; then
        set -- "$@" "FAMILIA_CBL_DOWNLOAD_URL=$CBL_URL"
      fi
      if env_ok FAMILIA_CBL_URL; then
        set -- "$@" "FAMILIA_CBL_URL=$CBL_URL"
      fi
    fi
  fi
  _kf=$(key_file_to_use)
  if [ -n "$API_KEY_FILE" ] && env_ok FAMILIA_API_KEY_FILE; then
    set -- "$@" "FAMILIA_API_KEY_FILE=$_kf"
  fi
  if [ "$CTX_GATE" != 1 ] && env_ok FAMILIA_HERMES_CTX_GATE && flag_ok --no-ctx-gate; then
    set -- "$@" "FAMILIA_HERMES_CTX_GATE=off"
  fi
  if [ "$THIN_CLIENT" != 1 ] && env_ok FAMILIA_RUNTIME; then
    set -- "$@" "FAMILIA_RUNTIME=$RUNTIME_KIND"
  fi
  if [ "$THIN_CLIENT" != 1 ]; then
    set -- "$@" "FAMILIA_BIND=127.0.0.1"
  fi

  set -- "$@" sh "$INSTALLER"
  if flag_ok --commit && [ -n "$COMMIT" ]; then set -- "$@" --commit "$COMMIT"; fi
  if flag_ok --host && [ -n "$HOST" ]; then set -- "$@" --host "$HOST"; fi
  if flag_ok --port && [ -n "$PORT" ]; then set -- "$@" --port "$PORT"; fi
  if [ "$HTTPS" = 1 ] && flag_ok --https; then set -- "$@" --https; fi
  if [ -n "$URL_FILE" ] && flag_ok --url-file; then set -- "$@" --url-file "$URL_FILE"; fi
  if [ "$THIN_CLIENT" != 1 ]; then
    if flag_ok --local-inference; then set -- "$@" --local-inference; fi
    if flag_ok --runtime; then set -- "$@" --runtime "$RUNTIME_KIND"; fi
  else
    if flag_ok --no-runtime; then set -- "$@" --no-runtime; fi
  fi
  if [ "$CTX_GATE" != 1 ] && flag_ok --no-ctx-gate && [ "$THIN_CLIENT" != 1 ]; then
    set -- "$@" --no-ctx-gate
  fi
  if [ "$DRY_RUN" = 1 ] && flag_ok --dry-run; then set -- "$@" --dry-run; fi
  if [ "$KEEP_PREFIX" = 1 ] && flag_ok --keep; then set -- "$@" --keep; fi
  if [ "$START_FAMILIA" = 1 ] && flag_ok --start; then set -- "$@" --start; fi
  if [ "$START_FAMILIA" != 1 ] && flag_ok --no-open; then set -- "$@" --no-open; fi
  if [ "$FETCH_PYYAML" = 1 ] && flag_ok --fetch-pyyaml; then set -- "$@" --fetch-pyyaml; fi
  if flag_ok --licenses && [ -n "$_lic" ]; then set -- "$@" --licenses "$_lic"; fi

  case "$_action" in
    show)
      printf 'command:\n  '
      print_quoted "$@"
      return 0
      ;;
    run)
      run_assembled "$@"
      return $?
      ;;
    preview)
      print_quoted "$@"
      return 0
      ;;
    *) return 1 ;;
  esac
}

# Brian F2 (2026-11-10 11:09 PM PT): HTTPS is the default for a remote
# (non-loopback) host. Plain HTTP to a remote host is allowed only when
# the named dev switch is on. Loopback IPs and the literal name
# localhost stay HTTP-OK (localhost still needs a key; that rule is
# IP-only).
https_default() {
  if [ -n "$HOST" ] && ! is_https_loopback "$HOST"; then
    printf '%s' 1
  else
    printf '%s' 0
  fi
}

apply_dev_http_env() {
  case "${FAMILIA_DEV_ALLOW_HTTP:-}" in
    1|yes|YES|true|TRUE|on|ON) DEV_ALLOW_HTTP=1 ;;
    0|no|NO|false|FALSE|off|OFF) DEV_ALLOW_HTTP=0 ;;
  esac
}

# Force HTTPS on for a remote host unless the dev switch is on.
apply_https_policy() {
  if [ -n "$HOST" ] && ! is_https_loopback "$HOST" && [ "$DEV_ALLOW_HTTP" != 1 ]; then
    HTTPS=1
  fi
}

# Same text in the menu, --dump, --show, and run_installer (before confirm).
# Shown only when the dev switch is on and a remote host is on plain HTTP.
plain_http_warning_text() {
  printf '%s' "warning: dev: allow plain HTTP is ON*; remote host uses plain HTTP"
}

warn_plain_http() {
  apply_https_policy
  if [ -n "$HOST" ] && ! is_https_loopback "$HOST" && [ "$HTTPS" != 1 ] && [ "$DEV_ALLOW_HTTP" = 1 ]; then
    err "$(plain_http_warning_text)"
    return 0
  fi
  return 1
}

dump_settings() {
  resolve_installer || true
  apply_self_host_defaults
  apply_https_policy
  say "android-cockpit settings (secure defaults unless changed):"
  say "  mode=$(mode_label)  gate=$(onoff "$CTX_GATE")  ctx=${FAMILIA_CTX_VAL:-unset}"
  say "  allow_yes=$(onoff "$ALLOW_YES")  dry_run=$(onoff "$DRY_RUN")  keep=$(onoff "$KEEP_PREFIX")  start=$(onoff "$START_FAMILIA")"
  say "  https=$(onoff "$HTTPS")  dev_allow_http=$(onoff "$DEV_ALLOW_HTTP")$(star_if "$DEV_ALLOW_HTTP" 0)  host=${HOST:-unset}  port=${PORT:-unset}  tier=${TIER:-auto}"
  say "  licenses=$(licenses_csv)  fetch_pyyaml=$(onoff "$FETCH_PYYAML")  runtime=$RUNTIME_KIND"
  say "  commit=${COMMIT:-unset}  cbl_override=${CBL_TAG:-in-repo pin}  url_file=${URL_FILE:-unset}"
  say "  config=$XDG_FILE"
  say "  prefix=$SMOKE_PREFIX (write-only copy; XDG is loaded)"
  if _u=$(webapp_url); then
    say "  url=$_u"
  fi
  say "  $(listener_key_label)"
  if installer_available; then
    say "  installer=$INSTALLER ($SCRIPT_KIND)"
  else
    say "  installer=not on this commit"
  fi
  warn_plain_http || true
}

sw_val() {
  if flag_ok "$1"; then
    printf '%s' "$2"
  else
    na_label
  fi
}

host_display() {
  if [ -n "$HOST" ]; then printf '%s' "$HOST"
  else printf '%s' "unset (required)"
  fi
}
port_display() {
  if [ -n "$PORT" ]; then printf '%s' "$PORT"
  else printf '%s' "unset (required)"
  fi
}


banner_state() {
  _mode=$(mode_label)
  _start="no auto-start"
  [ "$START_FAMILIA" = 1 ] && _start="start ON"
  if [ "${COMPACT:-0}" = 1 ]; then
    printf '%s gate=%s dry=%s start=%s HTTPS=%s' \
      "$_mode" "$(onoff "$CTX_GATE")" "$(onoff "$DRY_RUN")" \
      "$(onoff "$START_FAMILIA")" "$(onoff "$HTTPS")"
    return 0
  fi
  printf '%s, gate %s, --yes refused, dry-run %s, %s, HTTPS %s' \
    "$_mode" "$(onoff "$CTX_GATE")" "$(onoff "$DRY_RUN")" "$_start" "$(onoff "$HTTPS")"
}

key_display() {
  if [ -n "$API_KEY_FILE" ]; then
    printf '%s' "$API_KEY_FILE"
  else
    default_key_path
  fi
}

lfm_pin_warning() {
  if [ "$LIC_LFM" = 1 ]; then
    if [ "${COMPACT:-0}" = 1 ]; then
      say_row "  warning: LFM has no pinned license text in packaging/android/licenses; review the LiquidAI LFM3-1.7B LICENSE"
    else
      say_row "  warning: LFM has no pinned license text in packaging/android/licenses; review https://huggingface.co/LiquidAI/LFM3-1.7B/blob/main/LICENSE"
    fi
  fi
}

onphone_short_reason() {
  if ! phone_gate_ok; then
    printf '%s' "ctx below 64000"
    return 0
  fi
  if ram_block_reason >/dev/null; then
    printf '%s' "RAM floor"
    return 0
  fi
  return 1
}

paint_status() {
  if installer_available; then
    _inst="installer=$SCRIPT_BASE"
  else
    _inst="installer=not on this commit"
  fi
  if [ "${COMPACT:-0}" = 1 ]; then
    say_row "  $_inst  $(listener_key_label)"
  else
    say_row "  status  mode=$(mode_label)$(star_if "$THIN_CLIENT" 1)  gate=$(onoff "$CTX_GATE")$(star_if "$CTX_GATE" 1)  dry-run=$(onoff "$DRY_RUN")$(star_if "$DRY_RUN" 1)  start=$(onoff "$START_FAMILIA")$(star_if "$START_FAMILIA" 0)  HTTPS=$(onoff "$HTTPS")$(star_if "$HTTPS" "$(https_default)")"
    say_row "  $_inst  $(listener_key_label)"
  fi
  if [ -n "$HOST" ] && ! is_https_loopback "$HOST" && [ "$HTTPS" != 1 ] && [ "$DEV_ALLOW_HTTP" = 1 ]; then
    say_row "  $(plain_http_warning_text)"
  fi
  if [ "${COMPACT:-0}" = 1 ]; then
    if _br=$(onphone_short_reason); then
      say_row "  on-phone n/a: $_br"
    fi
  else
    if _br=$(onphone_block_reason); then
      say_row "  on-phone: [n/a: $_br]"
    fi
  fi
  lfm_pin_warning
}

paint_title() {
  say ""
  if [ "${COMPACT:-0}" = 1 ] || [ "$USE_BOX" != 1 ]; then
    say_row "FAMILIA ANDROID COCKPIT SWITCHES"
    say_row "$(banner_state)"
    return 0
  fi
  box_bar "$TL" "$TR"
  box_text "FAMILIA  ANDROID COCKPIT  SWITCHES"
  box_text "$(banner_state)"
  box_bar "$BL" "$BR"
}

# Sequential items 1-24. n/a reasons are wrapped on the next line.
paint_safety() {
  heading "Safety"
  if [ "${COMPACT:-0}" = 1 ]; then
    say_row "   1) Mode     [$(mode_label)]$(star_if "$THIN_CLIENT" 1)"
    say_row "   2) Gate     [$(onoff "$CTX_GATE")]$(star_if "$CTX_GATE" 1)"
    if flag_ok --no-ctx-gate || env_ok FAMILIA_HERMES_CTX_GATE; then
      :
    else
      say_row "      [$(na_label)]"
    fi
    say_row "   3) CTX      [${FAMILIA_CTX_VAL:-unset}]"
    say_row "   4) --yes    [n/a: ACCEPT required]"
    say_row "   5) Dry-run  [$(onoff "$DRY_RUN")]$(star_if "$DRY_RUN" 1)"
    say_row "   6) Keep     [$(sw_val --keep "$(onoff "$KEEP_PREFIX")")]$(star_if "$KEEP_PREFIX" 0)"
    say_row "   7) Start    [$(onoff "$START_FAMILIA")]$(star_if "$START_FAMILIA" 0)"
    if [ "$SCRIPT_KIND" = hermes ] && [ "$START_FAMILIA" != 1 ]; then
      say_row "      [n/a: hermes always starts]"
    elif ! flag_ok --start && ! flag_ok --no-open; then
      say_row "      [$(na_label)]"
    fi
    return 0
  fi
  say_row "   1) Mode (thin client / on-phone inference)     [$(mode_label)]$(star_if "$THIN_CLIENT" 1)"
  say_row "   2) Context gate 64000                          [$(onoff "$CTX_GATE")]$(star_if "$CTX_GATE" 1)"
  if flag_ok --no-ctx-gate || env_ok FAMILIA_HERMES_CTX_GATE; then
    :
  else
    say_row "      [$(na_label)]"
  fi
  say_row "   3) Context override FAMILIA_CTX                [${FAMILIA_CTX_VAL:-unset}]"
  say_row "   4) Allow --yes"
  say_row "      [n/a: typed ACCEPT is required; this screen never passes --yes]"
  say_row "   5) Dry-run                                     [$(onoff "$DRY_RUN")]$(star_if "$DRY_RUN" 1)"
  say_row "   6) Keep prefix (leaves the prefix on disk)     [$(sw_val --keep "$(onoff "$KEEP_PREFIX")")]$(star_if "$KEEP_PREFIX" 0)"
  say_row "   7) Start after install                         [$(onoff "$START_FAMILIA")]$(star_if "$START_FAMILIA" 0)"
  if [ "$SCRIPT_KIND" = hermes ] && [ "$START_FAMILIA" != 1 ]; then
    say_row "      [n/a: install-hermes-android.sh always starts familia-start; turn start ON to run it]"
  elif ! flag_ok --start && ! flag_ok --no-open; then
    say_row "      [$(na_label)]"
  fi
}

paint_network() {
  heading "Network"
  if [ "${COMPACT:-0}" = 1 ]; then
    say_row "   8) HTTPS    [$(sw_val --https "$(onoff "$HTTPS")")]$(star_if "$HTTPS" "$(https_default)")"
    say_row "   9) Host     [$(host_display)]"
    say_row "  10) Port     [$(port_display)]"
    if _u=$(webapp_url); then
      say_row "      url $_u"
    fi
    say_row "  11) URL file [${URL_FILE:-unset}]"
    if ! flag_ok --url-file; then
      say_row "      [$(na_label)]"
    fi
    say_row "  12) API key  [$(key_display)]"
    say_row "  24) dev: allow plain HTTP [$(onoff "$DEV_ALLOW_HTTP")]$(star_if "$DEV_ALLOW_HTTP" 0)"
    return 0
  fi
  say_row "   8) HTTPS                                       [$(sw_val --https "$(onoff "$HTTPS")")]$(star_if "$HTTPS" "$(https_default)")"
  say_row "   9) Host                                        [$(host_display)]"
  say_row "  10) Port                                        [$(port_display)]"
  if _u=$(webapp_url); then
    say_row "      url  $_u"
  fi
  say_row "  11) URL file (--url-file)                        [${URL_FILE:-unset}]"
  if ! flag_ok --url-file; then
    say_row "      [$(na_label)]"
  fi
  say_row "  12) API key file (path only, never the key)     [$(key_display)]"
  say_row "  24) dev: allow plain HTTP                       [$(onoff "$DEV_ALLOW_HTTP")]$(star_if "$DEV_ALLOW_HTTP" 0)"
}

paint_models() {
  heading "Models"
  if [ "${COMPACT:-0}" = 1 ]; then
    say_row "  13) Tier     [${TIER:-auto}]"
    say_row "  14) Runtime  [$RUNTIME_KIND]"
    if ! flag_ok --runtime && ! env_ok FAMILIA_RUNTIME; then
      say_row "      [$(na_label)]"
    fi
    say_row "  15) Llama    [$(onoff "$LIC_LLAMA31")]"
    say_row "  16) Dolphin  [$(onoff "$LIC_DOLPHIN")]"
    say_row "  17) LFM      [$(onoff "$LIC_LFM")]$(star_if "$LIC_LFM" 0)"
    if ! flag_ok --licenses; then
      say_row "      [$(na_label)]"
    fi
    return 0
  fi
  say_row "  13) Model tier (auto|tiny|small|medium|large)   [${TIER:-auto}]"
  say_row "  14) On-phone runtime (cbl|pkg)                  [$RUNTIME_KIND]"
  if ! flag_ok --runtime && ! env_ok FAMILIA_RUNTIME; then
    say_row "      [$(na_label)]"
  fi
  say_row "  15) License set: Llama 3.1                      [$(onoff "$LIC_LLAMA31")]"
  say_row "  16) License set: Dolphin                        [$(onoff "$LIC_DOLPHIN")]"
  say_row "  17) License set: LFM                            [$(onoff "$LIC_LFM")]$(star_if "$LIC_LFM" 0)"
  if ! flag_ok --licenses; then
    say_row "      [$(na_label)]"
  fi
}

paint_advanced() {
  heading "Advanced"
  if [ "${COMPACT:-0}" = 1 ]; then
    say_row "  18) PyYAML   [$(sw_val --fetch-pyyaml "$(onoff "$FETCH_PYYAML")")]$(star_if "$FETCH_PYYAML" 0)"
    say_row "  19) CBL pin  [${CBL_TAG:-in-repo pin}]"
    say_row "  20) Commit   [${COMMIT:-unset}]"
    say_row "  21) Show installer command"
    say_row "  22) Run installer (then return here)"
    say_row "  23) Continue to web cockpit"
    say_row "   d) Reset to secure defaults"
    say_row "   q) Exit (back to familia home)"
    return 0
  fi
  say_row "  18) Fetch PyYAML if missing (pip --user)        [$(sw_val --fetch-pyyaml "$(onoff "$FETCH_PYYAML")")]$(star_if "$FETCH_PYYAML" 0)"
  say_row "  19) CBL pin override (tag + sha256)             [${CBL_TAG:-in-repo pin}]"
  say_row "  20) Commit (40-hex)                             [${COMMIT:-unset}]"
  say_row "  21) Show installer command"
  say_row "  22) Run installer (then return here)"
  say_row "  23) Continue to web cockpit"
  say_row "   d) Reset to secure defaults"
  say_row "   q) Exit (back to familia home)"
}

paint_will_run() {
  _prev=$(assemble_and preview 2>/dev/null) || _prev=""
  if [ -n "$_prev" ]; then
    say_row "  will run: $_prev"
  elif installer_available; then
    say_row "  will run: (set required fields, then 21/22)"
  else
    say_row "  will run: installer not available on this commit"
  fi
}

paint_nav() {
  say_row "  n next  p prev  c continue  d reset  q exit  (page $PAGE/$PAGES)"
}

paint() {
  resolve_installer || true
  apply_self_host_defaults
  apply_https_policy
  init_box
  init_color
  case "$PAGE" in
    ''|*[!0-9]*) PAGE=1 ;;
  esac
  [ "$PAGE" -lt 1 ] && PAGE=1
  [ "$PAGE" -gt "$PAGES" ] && PAGE=$PAGES
  paint_title
  paint_status
  if need_pages; then
    case "$PAGE" in
      1) paint_safety ;;
      2) paint_network ;;
      3) paint_models ;;
      4) paint_advanced; say ""; paint_will_run ;;
    esac
    paint_nav
  else
    paint_safety
    paint_network
    paint_models
    paint_advanced
    say ""
    paint_will_run
  fi
  say ""
}


toggle() {
  if [ "$1" = 1 ]; then say 0; else say 1; fi
}

# Epoch seconds, portable to dash and mksh (no $SECONDS).
now_s() {
  date +%s 2>/dev/null || printf '%s' 0
}

# read_line PROMPT VAR ; 0 ok, 1 timeout, 2 EOF
# HAVE_READ_T is probed once. dash (Debian/Termux sh) has no -t.
#
# Real A57 data (galaxy1, 2026-11-10; Brian OK'd the test; via ssh from
# miryam, read-only). /system/bin/sh is MIRBSD KSH R59 2020/10/31 Android:
#   read -t 2 on a TTY that times out returns rc=142 after 2s.
#   read -t 2 </dev/null (EOF) returns rc=1.
# So on Android mksh, rc 1 means EOF, not a timeout (Platform's premise
# that a TTY timeout used rc 1 was wrong). Classification:
#   rc > 128 (142, like bash) is a timeout;
#   rc 1 is EOF, with the N1 elapsed guard as a safety net (rc 1
#   counts as a timeout only if elapsed >= the timeout window);
#   two EOFs stop.
assign_var() {
  case "$1" in
    choice) choice=$2 ;;
    _in) _in=$2 ;;
    _ignore) _ignore=$2 ;;
    _conf) _conf=$2 ;;
    *) return 1 ;;
  esac
  return 0
}

read_line() {
  _p=$1
  _dest=$2
  printf '%s' "$_p" >&2
  _v=""
  _rc=0
  if [ "$PIPE" = 1 ] || [ "$HAVE_READ_T" != 1 ]; then
    IFS= read -r _v || _rc=$?
    if [ "$_rc" -ne 0 ]; then
      if [ -n "$_v" ]; then
        :
      else
        return 2
      fi
    fi
  else
    _t0=$(now_s)
    IFS= read -t "$TIMEOUT" -r _v || _rc=$?
    _t1=$(now_s)
    _elapsed=0
    case "$_t0" in *[!0-9]*) _t0=0 ;; esac
    case "$_t1" in *[!0-9]*) _t1=0 ;; esac
    [ "$_t1" -ge "$_t0" ] && _elapsed=$((_t1 - _t0))
    if [ "$_rc" -ne 0 ]; then
      if [ -n "$_v" ]; then
        :
      elif [ "$_rc" -gt 128 ] || [ "$_rc" -eq 142 ]; then
        # galaxy1 mksh and bash: TTY timeout is rc 142 (>128).
        return 1
      elif [ "$_rc" -eq 1 ] && [ -t 0 ]; then
        # galaxy1 mksh: rc 1 is EOF (also what read -t </dev/null
        # returns). Keep the N1 elapsed guard as a safety net in
        # case some other ksh uses rc 1 for a TTY timeout too.
        # An immediate rc 1 (Ctrl-D / hangup) is EOF; two EOFs stop.
        _need=$TIMEOUT
        [ "$_need" -gt 1 ] && _need=$((TIMEOUT - 1))
        [ "$_need" -lt 1 ] && _need=1
        if [ "$_elapsed" -ge "$_need" ]; then
          return 1
        fi
        return 2
      else
        return 2
      fi
    fi
  fi
  assign_var "$_dest" "$_v"
  return 0
}

prompt_val() {
  _msg=$1; _var=$2
  _cur=""
  case "$_var" in
    FAMILIA_CTX_VAL) _cur=$FAMILIA_CTX_VAL ;;
    HOST) _cur=$HOST ;;
    PORT) _cur=$PORT ;;
    TIER) _cur=$TIER ;;
    COMMIT) _cur=$COMMIT ;;
    URL_FILE) _cur=$URL_FILE ;;
    API_KEY_FILE) _cur=$API_KEY_FILE ;;
    CBL_TAG) _cur=$CBL_TAG ;;
    CBL_SHA) _cur=$CBL_SHA ;;
    CBL_ASSET) _cur=$CBL_ASSET ;;
    CBL_URL) _cur=$CBL_URL ;;
    RUNTIME_KIND) _cur=$RUNTIME_KIND ;;
  esac
  _st=0
  _in=""
  read_line "  $_msg [${_cur:-empty}]: " _in || _st=$?
  if [ "$_st" -ne 0 ]; then
    if [ "$_st" -eq 1 ]; then err "timeout; leaving this value unchanged"
    else err "no input; leaving this value unchanged"
    fi
    return 0
  fi
  [ -n "$_in" ] || return 0
  case "$_var" in
    FAMILIA_CTX_VAL) FAMILIA_CTX_VAL=$_in ;;
    HOST) HOST=$_in ;;
    PORT) PORT=$_in ;;
    TIER) TIER=$_in ;;
    COMMIT) COMMIT=$_in ;;
    URL_FILE) URL_FILE=$_in ;;
    API_KEY_FILE) API_KEY_FILE=$_in ;;
    CBL_TAG) CBL_TAG=$_in ;;
    CBL_SHA) CBL_SHA=$_in ;;
    CBL_ASSET) CBL_ASSET=$_in ;;
    CBL_URL) CBL_URL=$_in ;;
    RUNTIME_KIND) RUNTIME_KIND=$_in ;;
  esac
  return 0
}

show_command() {
  # --dump already warned once in dump_settings.
  if [ "$MODE" != dump ]; then
    warn_plain_http || true
  fi
  assemble_and show || return 0
}

run_installer() {
  _preview=$(assemble_and preview) || { return 0; }
  say "running:"
  say "  $_preview"
  warn_plain_http || true
  if [ "$DRY_RUN" != 1 ]; then
    if [ "$SCRIPT_KIND" = install ] || [ "$SCRIPT_KIND" = hermes ]; then
      err "warning: this is a persistent phone install (writes \$HOME/familia); it is not throwaway like the smoke prefix."
    fi
    _conf=""
    _st=0
    read_line "dry-run is OFF; type 'run' to proceed: " _conf || _st=$?
    if [ "$_st" -ne 0 ] || [ "$_conf" != run ]; then
      err "not confirmed; back to the menu."
      return 0
    fi
  fi
  if assemble_and run; then
    say "installer finished (status 0). Back to the menu."
  else
    say "installer exited with status $?. Back to the menu."
  fi
}

edit_cbl() {
  say "CBL override needs BOTH tag and sha256 (PR #321). Empty tag clears the override."
  say "In-repo pin example: android-b12032-1 (android-b11969-1 is opt-in fallback only)."
  prompt_val "CBL tag (e.g. android-b12032-1, empty=in-repo pin)" CBL_TAG
  if [ -z "$CBL_TAG" ]; then
    CBL_SHA=""; CBL_ASSET=""; CBL_URL=""
    say "CBL override cleared (in-repo pin)."
    return 0
  fi
  if ! valid_cbl_tag "$CBL_TAG"; then
    err "tag is not a valid token; override not applied"
    CBL_TAG=""; CBL_SHA=""; CBL_ASSET=""; CBL_URL=""
    return 0
  fi
  prompt_val "CBL sha256 (64 hex)" CBL_SHA
  if ! valid_sha "$CBL_SHA"; then
    err "sha256 must be 64 hex chars; override not applied"
    CBL_TAG=""; CBL_SHA=""; CBL_ASSET=""; CBL_URL=""
    return 0
  fi
  prompt_val "CBL asset filename (empty=infer)" CBL_ASSET
  if [ -n "$CBL_ASSET" ] && ! valid_cbl_asset "$CBL_ASSET"; then
    err "asset name rejected; left empty"
    CBL_ASSET=""
  fi
  _cbl_url_old=$CBL_URL
  prompt_val "CBL https URL (empty=default github releases)" CBL_URL
  if [ -n "$CBL_URL" ] && ! valid_https_url "$CBL_URL"; then
    err "CBL URL must be https:// only (no http://, no CR/newline); left unchanged"
    CBL_URL=$_cbl_url_old
  fi
}

reset_defaults() {
  THIN_CLIENT=1
  CTX_GATE=1
  FAMILIA_CTX_VAL=""
  ALLOW_YES=0
  DRY_RUN=1
  KEEP_PREFIX=0
  START_FAMILIA=0
  HTTPS=0
  DEV_ALLOW_HTTP=0
  HOST=$DEFAULT_HOST
  PORT=$DEFAULT_PORT
  TIER=""
  LIC_LLAMA31=1
  LIC_DOLPHIN=1
  LIC_LFM=0
  FETCH_PYYAML=0
  COMMIT=""
  URL_FILE=""
  CBL_TAG=""
  CBL_SHA=""
  CBL_ASSET=""
  CBL_URL=""
  API_KEY_FILE=""
  RUNTIME_KIND=cbl
  say "reset to secure defaults (thin client, gate ON, --yes refused, dry-run ON, no auto-start, self-host http://127.0.0.1:9941, HTTPS on for remote hosts, plain HTTP only with dev: allow plain HTTP)."
}

do_choice() {
  _c=$1
  case "$_c" in
    1)
      if [ "$THIN_CLIENT" = 1 ]; then
        if _br=$(onphone_block_reason); then
          err "on-phone inference is disabled: $_br"
          return 0
        fi
        THIN_CLIENT=0
      else
        THIN_CLIENT=1
        if [ "$START_FAMILIA" = 1 ]; then
          START_FAMILIA=0
          say "start turned off (thin client never auto-starts a local server)."
        fi
      fi
      apply_self_host_defaults
      say "mode=$(mode_label)"
      if [ -n "$HOST" ] && is_loopback "$HOST"; then
        say "webapp host $(webapp_url) (this device; a remote host is an explicit opt-in)"
      fi
      ;;
    2) CTX_GATE=$(toggle "$CTX_GATE"); say "gate=$(onoff "$CTX_GATE")" ;;
    3)
      _old=$FAMILIA_CTX_VAL
      prompt_val "FAMILIA_CTX integer (or 'clear')" FAMILIA_CTX_VAL
      if [ "$FAMILIA_CTX_VAL" = clear ] || [ "$FAMILIA_CTX_VAL" = unset ]; then
        FAMILIA_CTX_VAL=""
      elif [ -n "$FAMILIA_CTX_VAL" ] && ! valid_ctx "$FAMILIA_CTX_VAL"; then
        err "ctx must be an integer; left unchanged"
        FAMILIA_CTX_VAL=$_old
      fi
      if [ "$THIN_CLIENT" != 1 ]; then
        if _br=$(onphone_block_reason); then
          THIN_CLIENT=1
          err "on-phone turned off: $_br"
        fi
      fi
      ;;
    4)
      err "allow --yes is n/a: typed ACCEPT is required; this screen never passes --yes"
      ;;
    5) DRY_RUN=$(toggle "$DRY_RUN"); say "dry-run=$(onoff "$DRY_RUN")" ;;
    6)
      KEEP_PREFIX=$(toggle "$KEEP_PREFIX")
      say "keep prefix=$(onoff "$KEEP_PREFIX")"
      if [ "$KEEP_PREFIX" = 1 ]; then
        err "warning: --keep leaves the prefix on disk (smoke is throwaway unless --keep)."
      fi
      ;;
    7)
      START_FAMILIA=$(toggle "$START_FAMILIA")
      if [ "$START_FAMILIA" = 1 ] && [ "$THIN_CLIENT" = 1 ]; then
        say "start=$(onoff "$START_FAMILIA") (thin client: open the host webapp, no local server)"
      else
        say "start=$(onoff "$START_FAMILIA")"
      fi
      ;;
    8)
      if [ "$HTTPS" = 1 ] && [ -n "$HOST" ] && ! is_https_loopback "$HOST" && [ "$DEV_ALLOW_HTTP" != 1 ]; then
        err "plain HTTP to a remote host needs 24) dev: allow plain HTTP (or FAMILIA_DEV_ALLOW_HTTP=1); HTTPS left ON"
      else
        HTTPS=$(toggle "$HTTPS")
        say "https=$(onoff "$HTTPS")"
      fi
      ;;
    9)
      _old=$HOST
      prompt_val "host (hostname, IPv4, or [IPv6])" HOST
      if [ -n "$HOST" ] && ! valid_host "$HOST"; then
        err "host must be a hostname, IPv4 or [IPv6] (no leading '-', no flag injection, no CR/newline); left unchanged"
        HOST=$_old
      fi
      apply_self_host_defaults
      apply_https_policy
      if [ -n "$HOST" ] && ! is_https_loopback "$HOST" && [ "$HTTPS" = 1 ] && [ "$DEV_ALLOW_HTTP" != 1 ]; then
        say "HTTPS enabled for remote host (plain HTTP needs 24) dev: allow plain HTTP)"
      fi
      ;;
    10)
      _old=$PORT
      prompt_val "port (1-65535)" PORT
      if [ -n "$PORT" ] && ! valid_port "$PORT"; then
        err "port must be 1-65535; left unchanged"
        PORT=$_old
      fi
      ;;
    11)
      _old=$URL_FILE
      prompt_val "absolute path to --url-file (one-use host link)" URL_FILE
      if [ -n "$URL_FILE" ]; then
        URL_FILE=$(expand_tilde "$URL_FILE")
        if ! valid_path "$URL_FILE"; then
          err "url-file path must be absolute (or start with ~/), no CR/newline; left unchanged"
          URL_FILE=$_old
        fi
      fi
      ;;
    12)
      _old=$API_KEY_FILE
      prompt_val "API key file path (not the key itself)" API_KEY_FILE
      if [ -n "$API_KEY_FILE" ]; then
        API_KEY_FILE=$(expand_tilde "$API_KEY_FILE")
        if ! valid_path "$API_KEY_FILE"; then
          err "API key path must be absolute (or start with ~/); left unchanged"
          API_KEY_FILE=$_old
        fi
      fi
      ;;
    13)
      _old=$TIER
      prompt_val "tier (auto|tiny|small|medium|large)" TIER
      if [ "$TIER" = auto ]; then TIER=""; fi
      if [ -n "$TIER" ] && ! valid_tier "$TIER"; then
        err "unknown tier; left unchanged"
        TIER=$_old
      fi
      ;;
    14)
      _old=$RUNTIME_KIND
      prompt_val "on-phone runtime (cbl|pkg)" RUNTIME_KIND
      if ! valid_runtime "$RUNTIME_KIND"; then
        err "runtime must be cbl or pkg; left unchanged"
        RUNTIME_KIND=$_old
      fi
      ;;
    15) LIC_LLAMA31=$(toggle "$LIC_LLAMA31"); say "llama31=$(onoff "$LIC_LLAMA31")" ;;
    16) LIC_DOLPHIN=$(toggle "$LIC_DOLPHIN"); say "dolphin=$(onoff "$LIC_DOLPHIN")" ;;
    17)
      LIC_LFM=$(toggle "$LIC_LFM")
      say "lfm=$(onoff "$LIC_LFM")"
      if [ "$LIC_LFM" = 1 ]; then
        lfm_pin_warning
      fi
      ;;
    18) FETCH_PYYAML=$(toggle "$FETCH_PYYAML"); say "fetch-pyyaml=$(onoff "$FETCH_PYYAML")" ;;
    19) edit_cbl ;;
    20)
      _old=$COMMIT
      prompt_val "40-hex commit" COMMIT
      if [ -n "$COMMIT" ] && ! valid_commit "$COMMIT"; then
        err "commit must be a full 40-hex sha; left unchanged"
        COMMIT=$_old
      fi
      ;;
    21) show_command ;;
    22) run_installer ;;
    24)
      DEV_ALLOW_HTTP=$(toggle "$DEV_ALLOW_HTTP")
      say "dev: allow plain HTTP=$(onoff "$DEV_ALLOW_HTTP")"
      if [ "$DEV_ALLOW_HTTP" = 1 ]; then
        err "warning: dev: allow plain HTTP is ON*; plain HTTP to a remote host is allowed"
      else
        apply_https_policy
        if [ -n "$HOST" ] && ! is_https_loopback "$HOST" ]; then
          say "HTTPS enabled for remote host (dev: allow plain HTTP is off)"
        fi
      fi
      ;;
    23|c|C)
      if [ "${FAMILIA_COCKPIT_HOOK:-}" = 1 ]; then
        return 4
      fi
      err "the web cockpit opens from the familia home menu (Open llama-ui web cockpit)."
      if [ "$PIPE" = 1 ]; then
        return 0
      fi
      if [ -f "$ROOT/scripts/open_ui.sh" ] && [ -r "$ROOT/scripts/open_ui.sh" ]; then
        if save_settings; then
          say "opening scripts/open_ui.sh. settings saved to $XDG_FILE"
        else
          err "settings not saved (see above); opening scripts/open_ui.sh anyway."
        fi
        exec sh "$ROOT/scripts/open_ui.sh"
      fi
      return 0
      ;;
    d|D) reset_defaults ;;
    q|Q|quit|exit) return 3 ;;
    *)
      err "'$_c' isn't one of the choices. Type a number from 1 to 24, n, p, c, d, or q to exit."
      ;;
  esac
  return 0
}

menu_loop() {
  _eof=0
  while true; do
    paint
    _st=0
    choice=""
    if need_pages; then
      _prompt="Choose 1-24, n, p, c, d, q: "
    else
      _prompt="Choose 1-24, c, d, or q to exit: "
    fi
    # Keep the prompt itself within COLUMNS.
    _cols=$(term_cols)
    _plen=$(printf '%s' "$_prompt" | wc -c)
    if [ "$_plen" -gt "$_cols" ]; then
      _prompt="Choose 1-24, n, p, q: "
    fi
    read_line "$_prompt" choice || _st=$?
    if [ "$_st" -eq 1 ]; then
      err "timeout; back to the menu."
      _eof=0
      continue
    fi
    if [ "$_st" -eq 2 ]; then
      err "end of input; still in the menu (pick q to exit, or c to continue to the web cockpit)."
      _eof=$((_eof + 1))
      if [ "$_eof" -ge 2 ]; then
        err "stdin closed without an exit pick; stopping so this does not loop."
        return 2
      fi
      continue
    fi
    _eof=0
    [ -n "$choice" ] || { err "empty choice; back to the menu."; continue; }
    case "$choice" in
      n|N)
        if need_pages; then
          PAGE=$((PAGE + 1))
          [ "$PAGE" -gt "$PAGES" ] && PAGE=1
        else
          err "paging is only used on short terminals; back to the menu."
        fi
        continue
        ;;
      p|P)
        if need_pages; then
          PAGE=$((PAGE - 1))
          [ "$PAGE" -lt 1 ] && PAGE=$PAGES
        else
          err "paging is only used on short terminals; back to the menu."
        fi
        continue
        ;;
    esac
    _dc=0
    do_choice "$choice" || _dc=$?
    if [ "$_dc" -eq 3 ]; then
      if save_settings; then
        say "exit. settings saved to $XDG_FILE"
      else
        err "settings not saved (see above); exiting anyway because you picked exit."
      fi
      return 0
    fi
    if [ "$_dc" -eq 4 ]; then
      if save_settings; then
        say "continue to web cockpit. settings saved to $XDG_FILE"
      else
        err "settings not saved (see above); continuing anyway because you picked continue."
      fi
      return 4
    fi
    save_settings || err "settings not saved; back to the menu."
    if [ "$PIPE" != 1 ]; then
      read_line "Press Enter to go back to the menu..." _ignore || true
    fi
  done
}


usage() { sed -n '2,/^set -eu$/p' "$0" | sed '/^set -eu$/d;s/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --pipe) PIPE=1 ;;
    --dump) MODE=dump ;;
    --show) MODE=show ;;
    *) err "unknown option '$1' (see --help)"; exit 2 ;;
  esac
  shift
done

probe_read_t
probe_env_u
load_settings
ALLOW_YES=0
resolve_installer || true

case "$MODE" in
  dump) dump_settings; say ""; show_command || true; exit 0 ;;
  show) show_command; exit $? ;;
esac

if [ ! -t 0 ] && [ "$PIPE" != 1 ]; then
  dump_settings
  err "no terminal, so no interactive menu. Use --pipe to feed choices, or --dump / --show."
  exit 2
fi

menu_loop
exit $?
