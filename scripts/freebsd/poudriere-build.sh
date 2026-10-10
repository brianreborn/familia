#!/bin/sh
# Build sysutils/familia stand-alone with poudriere (FreeBSD only).
# Idempotent: creates jail / ports tree / overlay only if missing.
# Usage: poudriere-build.sh [-n] [-j JAIL] [-v VERSION] [-a ARCH] [-p PORTS]
#   -n  dry run (print commands, change nothing)
# Status: PRELIMINARY, untested on a real FreeBSD host (TBD).
set -eu
DRY=0 JAIL=151amd64 VER=15.1-RELEASE ARCH=amd64 PORTS=default OVL=familia
while getopts nj:v:a:p: o; do case $o in
  n) DRY=1;; j) JAIL=$OPTARG;; v) VER=$OPTARG;; a) ARCH=$OPTARG;; p) PORTS=$OPTARG;;
  *) sed -n '2,7p' "$0"; exit 2;; esac; done
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
OVLDIR="$HERE/packaging/freebsd"
run() { echo "+ $*"; [ "$DRY" = 1 ] || "$@"; }
[ "$(uname -s)" = FreeBSD ] || [ "$DRY" = 1 ] || { echo "needs FreeBSD (use -n)" >&2; exit 1; }
command -v poudriere >/dev/null 2>&1 || run pkg install -y poudriere
has() { poudriere "$1" -l -q 2>/dev/null | awk '{print $1}' | grep -qx "$2"; }
has jail "$JAIL" || run poudriere jail -c -j "$JAIL" -v "$VER" -a "$ARCH"
has ports "$PORTS" || run poudriere ports -c -p "$PORTS" -m git+https -B main
has ports "$OVL" || run poudriere ports -c -p "$OVL" -m null -M "$OVLDIR"
run poudriere bulk -j "$JAIL" -p "$PORTS" -O "$OVL" sysutils/familia
