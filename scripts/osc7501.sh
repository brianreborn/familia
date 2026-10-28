#!/bin/sh
# osc7501.sh — emit Program Status Protocol (OSC 7501) reports.
# Spec: https://www.superlogical.com/rex/docs/build/program-status (rev ~0.4)
# Vendor-neutral. Presentation stays in the terminal; we only emit.
#
# Sourceable:  . scripts/osc7501.sh
# CLI:
#   sh scripts/osc7501.sh emit STATE [--id ID] [--kind K] [--progress N]
#                          [--app A] [--title T] [--msg M] [--force]
#   sh scripts/osc7501.sh query [--force]
#   sh scripts/osc7501.sh encode TEXT     # print base64 (no pad) to stdout
#   sh scripts/osc7501.sh --self-test     # encode/limits checks (no TTY needed)
#
# Emit is a no-op when stdout is not a TTY unless --force or FAMILIA_OSC7501=1.
# Failures soft-fail (never kill a sourced parent).
set -eu

_osc_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd 2>/dev/null) || _osc_root=.

# ---- encode -----------------------------------------------------------------

osc7501_b64() {
  # Standard base64 of UTF-8; strip newlines and optional padding.
  # Soft-fail empty → empty.
  _t=${1-}
  if [ -z "$_t" ]; then
    printf ''
    return 0
  fi
  if command -v base64 >/dev/null 2>&1; then
    # Prefer -w0 / -b0 when available; else tr -d.
    printf '%s' "$_t" | (base64 -w0 2>/dev/null || base64 -b0 2>/dev/null || base64 | tr -d '\n\r') | tr -d '='
  elif command -v openssl >/dev/null 2>&1; then
    printf '%s' "$_t" | openssl base64 -A 2>/dev/null | tr -d '='
  else
    # Last resort: python3
    python3 -c 'import base64,sys; print(base64.b64encode(sys.argv[1].encode()).decode().rstrip("="), end="")' "$_t" 2>/dev/null || printf ''
  fi
}

# ---- validation helpers -----------------------------------------------------

_osc_valid_state() {
  case "$1" in
    idle|working|done|blocked|error|clear) return 0 ;;
    *) return 1 ;;
  esac
}

_osc_valid_kind() {
  case "$1" in
    permission|question|auth|"") return 0 ;;
    *) return 1 ;;
  esac
}

_osc_valid_id() {
  # segment (/segment)* ; segment = [A-Za-z0-9_.+-]{1,32}; ≤8 levels; ≤128 total
  _id=$1
  [ -z "$_id" ] && return 0
  [ "${#_id}" -gt 128 ] && return 1
  # shellcheck disable=SC2169  # busybox-ok length
  case "$_id" in
    *[!A-Za-z0-9_./+-]*|/*|*/) return 1 ;;
  esac
  _depth=0
  _rest=$_id
  while [ -n "$_rest" ]; do
    _seg=${_rest%%/*}
    [ -z "$_seg" ] && return 1
    [ "${#_seg}" -gt 32 ] && return 1
    _depth=$((_depth + 1))
    [ "$_depth" -gt 8 ] && return 1
    if [ "$_rest" = "$_seg" ]; then
      break
    fi
    _rest=${_rest#*/}
  done
  return 0
}

_osc_valid_app() {
  _a=$1
  [ -z "$_a" ] && return 0
  [ "${#_a}" -gt 32 ] && return 1
  case "$_a" in
    *[!A-Za-z0-9_.+-]*) return 1 ;;
  esac
  return 0
}

_osc_valid_progress() {
  _p=$1
  [ -z "$_p" ] && return 0
  case "$_p" in
    *[!0-9]*) return 1 ;;
  esac
  [ "$_p" -ge 0 ] && [ "$_p" -le 100 ]
}

_osc_should_emit() {
  # force flag via OSC7501_FORCE=1 or FAMILIA_OSC7501=1 or arg --force handled by caller
  if [ "${OSC7501_FORCE:-0}" = 1 ] || [ "${FAMILIA_OSC7501:-0}" = 1 ]; then
    return 0
  fi
  [ -t 1 ]
}

# ---- emit -------------------------------------------------------------------

osc7501_emit() {
  # osc7501_emit STATE [key=value ...] OR options: --id --kind --progress --app --title --msg --force
  # Also accepts bare STATE then remaining options.
  _state=""; _id=""; _kind=""; _progress=""; _app="familia"; _title=""; _msg=""
  _force=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --id) _id=${2-}; shift ;;
      --kind) _kind=${2-}; shift ;;
      --progress) _progress=${2-}; shift ;;
      --app) _app=${2-}; shift ;;
      --title) _title=${2-}; shift ;;
      --msg) _msg=${2-}; shift ;;
      --force) _force=1 ;;
      --) shift; break ;;
      idle|working|done|blocked|error|clear)
        if [ -z "$_state" ]; then _state=$1; else
          printf 'osc7501: unexpected arg %s\n' "$1" >&2; return 1
        fi
        ;;
      state=*) _state=${1#state=} ;;
      id=*) _id=${1#id=} ;;
      kind=*) _kind=${1#kind=} ;;
      progress=*) _progress=${1#progress=} ;;
      app=*) _app=${1#app=} ;;
      title=*) _title=${1#title=} ;;
      msg=*) _msg=${1#msg=} ;;
      -h|--help)
        cat <<'H'
Usage: osc7501_emit STATE [--id ID] [--kind K] [--progress N] [--app A] [--title T] [--msg M] [--force]
States: idle working done blocked error clear
Kind (blocked only): permission question auth
H
        return 0
        ;;
      *)
        # Unknown token: if no state yet, treat as state; else soft-skip
        if [ -z "$_state" ]; then
          _state=$1
        else
          printf 'osc7501: skip unknown arg %s\n' "$1" >&2
        fi
        ;;
    esac
    shift
  done

  if [ -z "$_state" ]; then
    printf 'osc7501: state required\n' >&2
    return 1
  fi
  _osc_valid_state "$_state" || { printf 'osc7501: bad state %s\n' "$_state" >&2; return 1; }
  _osc_valid_kind "$_kind" || { printf 'osc7501: bad kind %s\n' "$_kind" >&2; return 1; }
  _osc_valid_id "$_id" || { printf 'osc7501: bad id %s\n' "$_id" >&2; return 1; }
  _osc_valid_app "$_app" || { printf 'osc7501: bad app %s\n' "$_app" >&2; return 1; }
  _osc_valid_progress "$_progress" || { printf 'osc7501: bad progress %s\n' "$_progress" >&2; return 1; }

  # kind only with blocked; progress only with working|blocked
  if [ -n "$_kind" ] && [ "$_state" != "blocked" ]; then
    _kind=""
  fi
  if [ -n "$_progress" ]; then
    case "$_state" in
      working|blocked) ;;
      *) _progress="" ;;
    esac
  fi

  # Strip controls from free text before encode (spec: no U+0000–001F, 007F, 0080–009F)
  _title=$(printf '%s' "$_title" | tr -d '\000-\037\177')
  _msg=$(printf '%s' "$_msg" | tr -d '\000-\037\177')

  _pairs="state=${_state}"
  [ -n "$_id" ] && _pairs="${_pairs}:id=${_id}"
  [ -n "$_kind" ] && _pairs="${_pairs}:kind=${_kind}"
  [ -n "$_progress" ] && _pairs="${_pairs}:progress=${_progress}"
  [ -n "$_app" ] && _pairs="${_pairs}:app=${_app}"
  if [ -n "$_title" ]; then
    _tb=$(osc7501_b64 "$_title")
    [ "${#_tb}" -gt 256 ] && { printf 'osc7501: title too long\n' >&2; return 1; }
    _pairs="${_pairs}:title=${_tb}"
  fi
  if [ -n "$_msg" ]; then
    _mb=$(osc7501_b64 "$_msg")
    [ "${#_mb}" -gt 2732 ] && { printf 'osc7501: msg too long\n' >&2; return 1; }
    _pairs="${_pairs}:msg=${_mb}"
  fi

  # Whole sequence OSC..ST ≤ 4096
  # ESC ] 7501 ; pairs ESC \
  _seq=$(printf '\033]7501;%s\033\\' "$_pairs")
  if [ "${#_seq}" -gt 4096 ]; then
    printf 'osc7501: sequence exceeds 4096 bytes\n' >&2
    return 1
  fi

  if [ "$_force" = 1 ]; then
    OSC7501_FORCE=1
  fi
  if ! _osc_should_emit; then
    # Capture for tests / dry inspect without writing OSC to a pipe.
    if [ -n "${OSC7501_CAPTURE:-}" ]; then
      printf '%s' "$_seq" >>"$OSC7501_CAPTURE"
    fi
    return 0
  fi
  # Write raw bytes to stdout (terminal). Also append capture when set.
  printf '%s' "$_seq"
  if [ -n "${OSC7501_CAPTURE:-}" ]; then
    printf '%s' "$_seq" >>"$OSC7501_CAPTURE"
  fi
  return 0
}

osc7501_query() {
  # Feature detection: OSC 7501 ; ? ST
  _force=0
  while [ $# -gt 0 ]; do
    case "$1" in --force) _force=1 ;; esac
    shift
  done
  [ "$_force" = 1 ] && OSC7501_FORCE=1
  _seq=$(printf '\033]7501;?\033\\')
  if ! _osc_should_emit; then
    [ -n "${OSC7501_CAPTURE:-}" ] && printf '%s' "$_seq" >>"$OSC7501_CAPTURE"
    return 0
  fi
  printf '%s' "$_seq"
  [ -n "${OSC7501_CAPTURE:-}" ] && printf '%s' "$_seq" >>"$OSC7501_CAPTURE"
  return 0
}

# Convenience wrappers used by pilot_hud / home / setup / proto
osc7501_working() { osc7501_emit working --app "${OSC7501_APP:-familia}" "$@"; }
osc7501_done()    { osc7501_emit done    --app "${OSC7501_APP:-familia}" "$@"; }
osc7501_blocked() { osc7501_emit blocked --app "${OSC7501_APP:-familia}" "$@"; }
osc7501_error()   { osc7501_emit error   --app "${OSC7501_APP:-familia}" "$@"; }
osc7501_idle()    { osc7501_emit idle    --app "${OSC7501_APP:-familia}" "$@"; }
osc7501_clear()   { osc7501_emit clear   --app "${OSC7501_APP:-familia}" "$@"; }

_osc_self_test() {
  # No TTY needed. Exercise encode + emit into a capture file.
  _tmp=$(mktemp)
  OSC7501_CAPTURE=$_tmp
  export OSC7501_CAPTURE
  OSC7501_FORCE=0
  # Non-TTY: should still capture when OSC7501_CAPTURE set
  osc7501_emit working --id home/setup --app familia --msg "Building frame" --progress 40 || exit 1
  osc7501_emit blocked --id home/setup --kind permission --msg "Approve install?" || exit 1
  osc7501_emit done --id home/setup --msg "Setup finished" || exit 1
  osc7501_query || exit 1
  # Validate captured bytes contain OSC 7501 and ST
  python3 - "$_tmp" <<'PY'
import sys, re, base64
raw = open(sys.argv[1], "rb").read()
assert b"\x1b]7501;" in raw, raw[:80]
assert raw.count(b"\x1b]7501;") >= 4
# Pull first report body
m = re.search(br"\x1b\]7501;([^\x1b]+)\x1b\\", raw)
assert m, "no ST-terminated report"
body = m.group(1).decode()
assert "state=working" in body
assert "id=home/setup" in body
assert "app=familia" in body
assert "progress=40" in body
# msg is base64 of "Building frame"
kv = dict(p.split("=", 1) for p in body.split(":") if "=" in p)
pad = "=" * ((4 - len(kv["msg"]) % 4) % 4)
assert base64.b64decode(kv["msg"] + pad).decode() == "Building frame"
# bad state rejected
print("ok", len(raw), "bytes captured")
PY
  # Bad state must fail
  if osc7501_emit bogus 2>/dev/null; then
    printf 'self-test: expected bad state to fail\n' >&2
    rm -f "$_tmp"
    exit 1
  fi
  rm -f "$_tmp"
  printf 'osc7501: self-test ok\n'
}

# ---- CLI --------------------------------------------------------------------
case "${0##*/}" in
  osc7501.sh)
    cmd=${1:-}; [ $# -gt 0 ] && shift || true
    case "$cmd" in
      emit) osc7501_emit "$@" ;;
      query) osc7501_query "$@" ;;
      encode) osc7501_b64 "${1-}" ; printf '\n' ;;
      working|done|blocked|error|idle|clear) osc7501_emit "$cmd" "$@" ;;
      --self-test|self-test) _osc_self_test ;;
      -h|--help|"")
        cat <<'H'
Usage:
  sh scripts/osc7501.sh emit STATE [--id ID] [--kind K] [--progress N]
                                   [--app A] [--title T] [--msg M] [--force]
  sh scripts/osc7501.sh query [--force]
  sh scripts/osc7501.sh encode TEXT
  sh scripts/osc7501.sh --self-test

Program Status Protocol (OSC 7501). Spec rev ~0.4.
Source: . scripts/osc7501.sh   then call osc7501_emit / osc7501_working …
H
        ;;
      *) printf 'osc7501: unknown %s\n' "$cmd" >&2; exit 2 ;;
    esac
    ;;
esac
