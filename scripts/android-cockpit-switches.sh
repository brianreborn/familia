#!/bin/sh
# android-cockpit-switches.sh: entry-screen switches for the Android installer
# when going into the llama-ui web cockpit (familia_home.sh) or from the
# legacy catalog (setup.android-cockpit). Matches familia-menu style
# (numbered picks, --pipe, invalid input stays). Settings persist under
# ${XDG_CONFIG_HOME:-$HOME/.config}/familia/android-cockpit.env (mode 0600)
# and, when present, inside the smoke prefix as android-cockpit.env.
# The menu exits ONLY on an explicit exit pick (q/quit/exit). Errors,
# finished actions, invalid input and timeouts return to the menu.
#
# The installer (install-android.sh) is not shipped here; it depends on
# files that live on PR #321. When it is absent this screen prints
# "installer not available on this commit" and returns to the menu.
# Override the search path with FAMILIA_ANDROID_INSTALLER.
#
# Usage:
#   sh scripts/android-cockpit-switches.sh            interactive (needs a TTY)
#   sh scripts/android-cockpit-switches.sh --pipe     choices from stdin (tests)
#   sh scripts/android-cockpit-switches.sh --dump     settings + installer command
#   sh scripts/android-cockpit-switches.sh --show     installer command only
#   sh scripts/android-cockpit-switches.sh --help
#
# Secure defaults: thin client, gate ON, --yes refused, dry-run ON,
# never auto-start. Any network listener still needs an API key.
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
INSTALLER=""
PIPE=0
MODE=menu
TIMEOUT=${FAMILIA_MENU_TIMEOUT:-60}

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
HOST=""
PORT=""
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

XDG_BASE="${XDG_CONFIG_HOME:-$HOME/.config}"
CONFIG_DIR="$XDG_BASE/familia"
XDG_FILE="$CONFIG_DIR/android-cockpit.env"
SMOKE_PREFIX=${FAMILIA_SMOKE_PREFIX:-${TMPDIR:-$HOME/.cache}/familia-smoke}
PREFIX_FILE="$SMOKE_PREFIX/android-cockpit.env"

say() { printf '%s\n' "$*"; }
err() { printf 'android-cockpit: %s\n' "$*" >&2; }

# Conventional paths only. Do not vendor PR #321 content into this tree.
resolve_installer() {
  INSTALLER=""
  if [ -n "${FAMILIA_ANDROID_INSTALLER:-}" ]; then
    if [ -f "$FAMILIA_ANDROID_INSTALLER" ] && [ -r "$FAMILIA_ANDROID_INSTALLER" ]; then
      INSTALLER=$FAMILIA_ANDROID_INSTALLER
      return 0
    fi
    err "FAMILIA_ANDROID_INSTALLER is set but not a readable file"
    return 1
  fi
  for _cand in \
    "$ROOT/packaging/android/install-android.sh" \
    "$ROOT/install/termux/install-android.sh"
  do
    if [ -f "$_cand" ] && [ -r "$_cand" ]; then
      INSTALLER=$_cand
      return 0
    fi
  done
  return 1
}

installer_available() {
  [ -n "${INSTALLER:-}" ] && [ -f "$INSTALLER" ] && [ -r "$INSTALLER" ]
}

need_installer() {
  if installer_available; then
    return 0
  fi
  err "installer not available on this commit"
  return 1
}

use_color() {
  case "${FAMILIA_COLOR:-auto}" in always) return 0 ;; never) return 1 ;; esac
  [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-dumb}" != dumb ]
}

utf8_tty() {
  [ -t 1 ] || return 1
  case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in *UTF-8*|*utf8*|*UTF8*) return 0 ;; esac
  return 1
}

# Box drawing: UTF-8 cp437 double-box via octal (source stays 7-bit ASCII);
# plus-minus fallback when stdout is not a UTF-8 TTY.
init_box() {
  if utf8_tty; then
    TL=$(printf '\342\225\224'); TR=$(printf '\342\225\227')
    BL=$(printf '\342\225\232'); BR=$(printf '\342\225\235')
    H=$(printf '\342\225\220');  V=$(printf '\342\225\221')
  else
    TL="+"; TR="+"; BL="+"; BR="+"; H="-"; V="|"
  fi
}

C0=""; C1=""; CR=""
init_color() {
  if use_color; then
    C0=$(printf '\033[1;36m')
    C1=$(printf '\033[0;36m')
    CR=$(printf '\033[0m')
  else
    C0=""; C1=""; CR=""
  fi
}

WIDTH=68
box_bar() {
  _l=$1; _r=$2
  printf '  %s' "$_l"
  _i=0; while [ "$_i" -lt "$WIDTH" ]; do printf '%s' "$H"; _i=$((_i + 1)); done
  printf '%s\n' "$_r"
}
box_text() {
  # pad/truncate to WIDTH-2
  _t=$1
  _pad=$((WIDTH - 2))
  printf '  %s %s%-*.*s%s %s\n' "$V" "$C1" "$_pad" "$_pad" "$_t" "$CR" "$V"
}

onoff() { if [ "$1" = 1 ]; then say ON; else say OFF; fi; }
yesno() { if [ "$1" = 1 ]; then say yes; else say no; fi; }

known_key() {
  case "$1" in
    THIN_CLIENT|CTX_GATE|FAMILIA_CTX_VAL|ALLOW_YES|DRY_RUN|KEEP_PREFIX|START_FAMILIA|HTTPS|HOST|PORT|TIER|LIC_LLAMA31|LIC_DOLPHIN|LIC_LFM|FETCH_PYYAML|COMMIT|URL_FILE|CBL_TAG|CBL_SHA|CBL_ASSET|CBL_URL|API_KEY_FILE) return 0 ;;
    *) return 1 ;;
  esac
}

load_file() {
  [ -f "$1" ] || return 0
  while IFS= read -r _line || [ -n "$_line" ]; do
    case "$_line" in ""|\#*) continue ;; esac
    _k=${_line%%=*}
    _v=${_line#*=}
    known_key "$_k" || continue
    # Values are already written unquoted or as a safe token; strip a matching pair of quotes.
    case "$_v" in
      \"*\") _v=${_v#\"}; _v=${_v%\"} ;;
    esac
    case "$_k" in
      THIN_CLIENT) THIN_CLIENT=$_v ;;
      CTX_GATE) CTX_GATE=$_v ;;
      FAMILIA_CTX_VAL) FAMILIA_CTX_VAL=$_v ;;
      ALLOW_YES) ALLOW_YES=$_v ;;
      DRY_RUN) DRY_RUN=$_v ;;
      KEEP_PREFIX) KEEP_PREFIX=$_v ;;
      START_FAMILIA) START_FAMILIA=$_v ;;
      HTTPS) HTTPS=$_v ;;
      HOST) HOST=$_v ;;
      PORT) PORT=$_v ;;
      TIER) TIER=$_v ;;
      LIC_LLAMA31) LIC_LLAMA31=$_v ;;
      LIC_DOLPHIN) LIC_DOLPHIN=$_v ;;
      LIC_LFM) LIC_LFM=$_v ;;
      FETCH_PYYAML) FETCH_PYYAML=$_v ;;
      COMMIT) COMMIT=$_v ;;
      URL_FILE) URL_FILE=$_v ;;
      CBL_TAG) CBL_TAG=$_v ;;
      CBL_SHA) CBL_SHA=$_v ;;
      CBL_ASSET) CBL_ASSET=$_v ;;
      CBL_URL) CBL_URL=$_v ;;
      API_KEY_FILE) API_KEY_FILE=$_v ;;
    esac
  done < "$1"
}

save_settings() {
  _tmp=""
  mkdir -p "$CONFIG_DIR" || { err "could not create $CONFIG_DIR"; return 1; }
  _tmp=$(mktemp "$CONFIG_DIR/android-cockpit.env.XXXXXX") || { err "could not write settings"; return 1; }
  {
    printf '# familia android cockpit switches. Do not store API key secrets here, only paths.\n'
    printf 'THIN_CLIENT=%s\n' "$THIN_CLIENT"
    printf 'CTX_GATE=%s\n' "$CTX_GATE"
    printf 'FAMILIA_CTX_VAL=%s\n' "$FAMILIA_CTX_VAL"
    printf 'ALLOW_YES=%s\n' "$ALLOW_YES"
    printf 'DRY_RUN=%s\n' "$DRY_RUN"
    printf 'KEEP_PREFIX=%s\n' "$KEEP_PREFIX"
    printf 'START_FAMILIA=%s\n' "$START_FAMILIA"
    printf 'HTTPS=%s\n' "$HTTPS"
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
  } > "$_tmp"
  chmod 0600 "$_tmp"
  mv "$_tmp" "$XDG_FILE"
  if [ -d "$SMOKE_PREFIX" ] || [ "$KEEP_PREFIX" = 1 ]; then
    mkdir -p "$SMOKE_PREFIX" 2>/dev/null || true
    if [ -d "$SMOKE_PREFIX" ]; then
      cp "$XDG_FILE" "$PREFIX_FILE"
      chmod 0600 "$PREFIX_FILE"
    fi
  fi
  return 0
}

# Prefix copy wins if present (a kept prefix is self-contained); else XDG.
load_settings() {
  if [ -f "$PREFIX_FILE" ]; then load_file "$PREFIX_FILE"
  elif [ -f "$XDG_FILE" ]; then load_file "$XDG_FILE"
  fi
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

build_command() {
  # Prints one sh line on stdout. Missing required fields: return 1 after err.
  need_installer || return 1
  if [ -z "$COMMIT" ]; then err "set a 40-hex --commit first"; return 1; fi
  if [ -z "$HOST" ] || [ -z "$PORT" ]; then err "set host and port first"; return 1; fi
  if [ "$START_FAMILIA" = 1 ] && [ "$THIN_CLIENT" = 1 ]; then
    err "start familia-start requires on-phone inference (turn off thin client)"
    return 1
  fi
  if [ "$START_FAMILIA" = 1 ]; then
    _kf=${API_KEY_FILE:-$HOME/.config/familia/api.key}
    if [ ! -f "$_kf" ]; then
      err "start requires an API key file (set switch 18 or create ~/.config/familia/api.key). Key is not logged."
      return 1
    fi
  fi
  _lic=$(licenses_csv)
  if [ -z "$_lic" ]; then err "enable at least one license set"; return 1; fi
  _cmd="sh $(printf '%s' "$INSTALLER")"
  _cmd="$_cmd --commit $(printf '%s' "$COMMIT")"
  _cmd="$_cmd --host $(printf '%s' "$HOST")"
  _cmd="$_cmd --port $(printf '%s' "$PORT")"
  [ "$HTTPS" = 1 ] && _cmd="$_cmd --https"
  [ -n "$URL_FILE" ] && _cmd="$_cmd --url-file $(printf '%s' "$URL_FILE")"
  [ "$THIN_CLIENT" != 1 ] && _cmd="$_cmd --local-inference"
  [ "$CTX_GATE" != 1 ] && _cmd="$_cmd --no-ctx-gate"
  if [ "$ALLOW_YES" = 1 ]; then
    _cmd="$_cmd --allow-yes --yes"
  fi
  [ "$DRY_RUN" = 1 ] && _cmd="$_cmd --dry-run"
  [ "$KEEP_PREFIX" = 1 ] && _cmd="$_cmd --keep"
  [ "$START_FAMILIA" = 1 ] && _cmd="$_cmd --start"
  [ "$FETCH_PYYAML" = 1 ] && _cmd="$_cmd --fetch-pyyaml"
  _cmd="$_cmd --licenses $_lic"
  # env prefix (values not containing spaces in our validators)
  _env=""
  [ -n "$FAMILIA_CTX_VAL" ] && _env="${_env} FAMILIA_CTX=$FAMILIA_CTX_VAL"
  [ -n "$TIER" ] && _env="${_env} FAMILIA_PHONE_MODEL_TIER=$TIER"
  [ -n "$CBL_TAG" ] && _env="${_env} FAMILIA_CBL_ANDROID_TAG=$CBL_TAG"
  [ -n "$CBL_SHA" ] && _env="${_env} FAMILIA_CBL_ANDROID_SHA256=$CBL_SHA"
  [ -n "$CBL_ASSET" ] && _env="${_env} FAMILIA_CBL_ANDROID_ASSET=$CBL_ASSET"
  [ -n "$CBL_URL" ] && _env="${_env} FAMILIA_CBL_URL=$CBL_URL"
  [ -n "$API_KEY_FILE" ] && _env="${_env} FAMILIA_API_KEY_FILE=$API_KEY_FILE"
  [ "$ALLOW_YES" = 1 ] && _env="${_env} FAMILIA_ALLOW_YES=yes"
  [ "$CTX_GATE" != 1 ] && _env="${_env} FAMILIA_HERMES_CTX_GATE=off"
  _env=$(printf '%s' "$_env" | sed 's/^ //')
  if [ -n "$_env" ]; then
    printf '%s %s\n' "$_env" "$_cmd"
  else
    printf '%s\n' "$_cmd"
  fi
}

dump_settings() {
  say "android-cockpit settings (secure defaults unless changed):"
  say "  mode=$(mode_label)  gate=$(onoff "$CTX_GATE")  ctx=${FAMILIA_CTX_VAL:-unset}"
  say "  allow_yes=$(onoff "$ALLOW_YES")  dry_run=$(onoff "$DRY_RUN")  keep=$(onoff "$KEEP_PREFIX")  start=$(onoff "$START_FAMILIA")"
  say "  https=$(onoff "$HTTPS")  host=${HOST:-unset}  port=${PORT:-unset}  tier=${TIER:-auto}"
  say "  licenses=$(licenses_csv)  fetch_pyyaml=$(onoff "$FETCH_PYYAML")"
  say "  commit=${COMMIT:-unset}  cbl_override=${CBL_TAG:-in-repo pin}"
  say "  config=$XDG_FILE"
  say "  prefix=$SMOKE_PREFIX"
  if installer_available; then
    say "  installer=$INSTALLER"
  else
    say "  installer=not on this commit"
  fi
}

paint() {
  init_box
  init_color
  say ""
  box_bar "$TL" "$TR"
  box_text "FAMILIA  ANDROID COCKPIT  SWITCHES"
  box_text "thin client, gate ON, --yes refused, dry-run ON, no auto-start"
  box_bar "$BL" "$BR"
  if installer_available; then
    _inst="installer=present"
  else
    _inst="installer=not on this commit"
  fi
  say "  ${C0}status${CR}  mode=$(mode_label)  gate=$(onoff "$CTX_GATE")  yes=$(onoff "$ALLOW_YES")  dry-run=$(onoff "$DRY_RUN")  start=$(onoff "$START_FAMILIA")"
  say "  $_inst"
  say ""
  say "   1) Mode (thin client / on-phone inference)     [$(mode_label)]"
  say "   2) Context gate 64000                          [$(onoff "$CTX_GATE")]"
  say "   3) Context override FAMILIA_CTX                [${FAMILIA_CTX_VAL:-unset}]"
  say "   4) Allow --yes                                 [$(onoff "$ALLOW_YES")]"
  say "   5) Dry-run                                     [$(onoff "$DRY_RUN")]"
  say "   6) Keep prefix                                 [$(onoff "$KEEP_PREFIX")]"
  say "   7) Start familia-start after install           [$(onoff "$START_FAMILIA")]"
  say "   8) HTTPS                                       [$(onoff "$HTTPS")]"
  say "   9) Host                                        [${HOST:-unset}]"
  say "  10) Port                                        [${PORT:-unset}]"
  say "  11) Model tier (auto|tiny|small|medium|large)   [${TIER:-auto}]"
  say "  12) License set: Llama 3.1                      [$(onoff "$LIC_LLAMA31")]"
  say "  13) License set: Dolphin                        [$(onoff "$LIC_DOLPHIN")]"
  say "  14) License set: LFM                            [$(onoff "$LIC_LFM")]"
  say "  15) Fetch PyYAML if missing (pip --user)        [$(onoff "$FETCH_PYYAML")]"
  say "  16) CBL pin override (tag + sha256)             [${CBL_TAG:-in-repo pin}]"
  say "  17) Commit (40-hex)                             [${COMMIT:-unset}]"
  say "  18) API key file (path only, never the key)     [${API_KEY_FILE:-default}]"
  say "  19) Show installer command"
  say "  20) Run installer (then return here)"
  say "   q) Exit"
  say ""
}

toggle() {
  if [ "$1" = 1 ]; then say 0; else say 1; fi
}

# read_line PROMPT VAR ; 0 ok, 1 timeout, 2 EOF
read_line() {
  _p=$1
  printf '%s' "$_p" >&2
  _v=""
  if [ "$PIPE" = 1 ]; then
    IFS= read -r _v || { [ -n "$_v" ] || return 2; }
  else
    # read -t is bash/mksh; a POSIX sh without it just blocks (no timeout).
    if IFS= read -t "$TIMEOUT" -r _v 2>/dev/null; then
      :
    else
      _rc=$?
      if [ -n "$_v" ]; then
        :
      elif [ "$_rc" -ge 128 ] || [ "$_rc" -eq 142 ] || [ "$_rc" -eq 1 ]; then
        # 128+signal or bash 142 / some shells 1 = timeout; EOF is also 1 on dash.
        # Distinguish: if stdin is a TTY, treat as timeout; else EOF.
        if [ -t 0 ]; then return 1; fi
        return 2
      else
        return 2
      fi
    fi
  fi
  eval "$2=\$_v"
  return 0
}

prompt_val() {
  # prompt_val MESSAGE VAR [validator]
  _msg=$1; _var=$2
  _cur=""
  eval "_cur=\$$_var"
  _st=0
  read_line "  $_msg [${_cur:-empty}]: " _in || _st=$?
  if [ "$_st" -ne 0 ]; then
    if [ "$_st" -eq 1 ]; then err "timeout; leaving this value unchanged"
    else err "no input; leaving this value unchanged"
    fi
    return 0
  fi
  # empty = leave unchanged (return to menu)
  [ -n "$_in" ] || return 0
  eval "$_var=\$_in"
  return 0
}

valid_commit() { printf '%s' "$1" | grep -Eq '^[0-9a-f]{40}$'; }
valid_port() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
valid_tier() { case "$1" in auto|"") return 0 ;; tiny|small|medium|large) return 0 ;; *) return 1 ;; esac; }
valid_ctx() { case "$1" in ''|clear|unset) return 0 ;; *[!0-9]*) return 1 ;; *) return 0 ;; esac; }

show_command() {
  need_installer || return 0
  _line=$(build_command) || return 0
  say "command:"
  say "  $_line"
}

run_installer() {
  need_installer || return 0
  _line=$(build_command) || return 0
  say "running:"
  say "  $_line"
  # shellcheck disable=SC2086
  if sh -c "$_line"; then
    say "installer finished (status 0). Back to the menu."
  else
    say "installer exited with status $?. Back to the menu."
  fi
}

edit_cbl() {
  say "CBL override needs BOTH tag and sha256 (PR #321). Empty tag clears the override."
  prompt_val "CBL tag (e.g. android-b11969-1, empty=in-repo pin)" CBL_TAG
  if [ -z "$CBL_TAG" ]; then
    CBL_SHA=""; CBL_ASSET=""; CBL_URL=""
    say "CBL override cleared (in-repo pin)."
    return 0
  fi
  prompt_val "CBL sha256 (64 hex)" CBL_SHA
  if ! printf '%s' "$CBL_SHA" | grep -Eq '^[0-9a-f]{64}$'; then
    err "sha256 must be 64 hex chars; override not applied"
    CBL_TAG=""; CBL_SHA=""; CBL_ASSET=""; CBL_URL=""
    return 0
  fi
  prompt_val "CBL asset filename (empty=infer)" CBL_ASSET
  prompt_val "CBL base or file URL (empty=default github releases)" CBL_URL
}

do_choice() {
  _c=$1
  case "$_c" in
    1) THIN_CLIENT=$(toggle "$THIN_CLIENT")
       if [ "$THIN_CLIENT" = 1 ] && [ "$START_FAMILIA" = 1 ]; then
         START_FAMILIA=0
         say "start turned off (thin client never auto-starts)."
       fi
       say "mode=$(mode_label)" ;;
    2) CTX_GATE=$(toggle "$CTX_GATE"); say "gate=$(onoff "$CTX_GATE")" ;;
    3)
      prompt_val "FAMILIA_CTX integer (or 'clear')" FAMILIA_CTX_VAL
      if [ "$FAMILIA_CTX_VAL" = clear ] || [ "$FAMILIA_CTX_VAL" = unset ]; then FAMILIA_CTX_VAL=""; fi
      if [ -n "$FAMILIA_CTX_VAL" ] && ! valid_ctx "$FAMILIA_CTX_VAL"; then
        err "ctx must be an integer; left unset"
        FAMILIA_CTX_VAL=""
      fi
      ;;
    4) ALLOW_YES=$(toggle "$ALLOW_YES"); say "allow --yes=$(onoff "$ALLOW_YES")" ;;
    5) DRY_RUN=$(toggle "$DRY_RUN"); say "dry-run=$(onoff "$DRY_RUN")" ;;
    6) KEEP_PREFIX=$(toggle "$KEEP_PREFIX"); say "keep prefix=$(onoff "$KEEP_PREFIX")" ;;
    7)
      START_FAMILIA=$(toggle "$START_FAMILIA")
      if [ "$START_FAMILIA" = 1 ] && [ "$THIN_CLIENT" = 1 ]; then
        START_FAMILIA=0
        err "start needs on-phone inference; left OFF"
      else
        say "start=$(onoff "$START_FAMILIA")"
      fi
      ;;
    8) HTTPS=$(toggle "$HTTPS"); say "https=$(onoff "$HTTPS")" ;;
    9) prompt_val "host (hostname, IPv4, or [IPv6])" HOST ;;
    10)
      prompt_val "port (1-65535)" PORT
      if [ -n "$PORT" ] && ! valid_port "$PORT"; then
        err "port must be 1-65535; left unset"
        PORT=""
      fi
      ;;
    11)
      prompt_val "tier (auto|tiny|small|medium|large)" TIER
      if [ "$TIER" = auto ]; then TIER=""; fi
      if [ -n "$TIER" ] && ! valid_tier "$TIER"; then
        err "unknown tier; left auto"
        TIER=""
      fi
      ;;
    12) LIC_LLAMA31=$(toggle "$LIC_LLAMA31"); say "llama31=$(onoff "$LIC_LLAMA31")" ;;
    13) LIC_DOLPHIN=$(toggle "$LIC_DOLPHIN"); say "dolphin=$(onoff "$LIC_DOLPHIN")" ;;
    14) LIC_LFM=$(toggle "$LIC_LFM"); say "lfm=$(onoff "$LIC_LFM")" ;;
    15) FETCH_PYYAML=$(toggle "$FETCH_PYYAML"); say "fetch-pyyaml=$(onoff "$FETCH_PYYAML")" ;;
    16) edit_cbl ;;
    17)
      prompt_val "40-hex commit" COMMIT
      if [ -n "$COMMIT" ] && ! valid_commit "$COMMIT"; then
        err "commit must be a full 40-hex sha; left unset"
        COMMIT=""
      fi
      ;;
    18) prompt_val "API key file path (not the key itself)" API_KEY_FILE ;;
    19) show_command ;;
    20) run_installer ;;
    q|Q|quit|exit) return 3 ;;
    *)
      err "'$_c' isn't one of the choices. Type a number from 1 to 20, or q to exit."
      ;;
  esac
  return 0
}

menu_loop() {
  _eof=0
  while true; do
    paint
    _st=0
    read_line "Choose 1-20, or q to exit: " choice || _st=$?
    if [ "$_st" -eq 1 ]; then
      err "timeout; back to the menu."
      _eof=0
      continue
    fi
    if [ "$_st" -eq 2 ]; then
      err "end of input; still in the menu (pick q to exit)."
      _eof=$((_eof + 1))
      if [ "$_eof" -ge 2 ]; then
        err "stdin closed without an exit pick; stopping so this does not loop."
        return 2
      fi
      continue
    fi
    _eof=0
    [ -n "$choice" ] || { err "empty choice; back to the menu."; continue; }
    _dc=0
    do_choice "$choice" || _dc=$?
    if [ "$_dc" -eq 3 ]; then
      save_settings || err "settings not saved (see above); exiting anyway because you picked exit."
      say "exit. settings saved to $XDG_FILE"
      return 0
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

load_settings
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
