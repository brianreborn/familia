# lib/deps.mk: shared argument parsing and install confirmation for install/*/deps.sh.
# Canonical copy: brianreborn/familia lib/deps.mk (familia only; needs lib/msg.mk loaded first).
# deps_args "$@": sets INSTALL YES DRY PROFILE RUNTIME from
#   --install --yes|-y --dry-run|-n --no-runtime base|build --profile=X --profile X
# deps_confirm CMD QUESTION [RERUN_NOTE]: print the suggestion; without --install exit 1;
#   with --dry-run print and exit 0; otherwise ask QUESTION on /dev/tty unless --yes.
# shellcheck disable=SC2034  # INSTALL YES DRY PROFILE RUNTIME are read by the calling deps.sh
deps_args() {
  INSTALL=0; YES=0; DRY=0; PROFILE=base; RUNTIME=1
  _deps_prev=""
  for _deps_a in "$@"; do
    case "$_deps_a" in
      --install) INSTALL=1 ;;
      --yes|-y) YES=1 ;;
      --dry-run|-n) DRY=1 ;;
      --no-runtime) RUNTIME=0 ;;
      base|build) PROFILE=$_deps_a ;;
      --profile=*) PROFILE=${_deps_a#--profile=} ;;
    esac
    if [ "$_deps_prev" = "--profile" ]; then PROFILE=$_deps_a; fi
    _deps_prev=$_deps_a
  done
}
deps_confirm() {
  say "suggested: $1"
  if [ "$INSTALL" != 1 ]; then
    say "re-run with --install to install them (add --yes for non-interactive)${3:-}"
    exit 1
  fi
  if [ "$DRY" = 1 ]; then say "[dry-run] $1"; exit 0; fi
  if [ "$YES" != 1 ] && [ -r /dev/tty ]; then
    printf '%s [y/N] ' "${MK_TAG:+$MK_TAG: }$2" >&2
    read -r _deps_ans < /dev/tty || _deps_ans=n
    case "$_deps_ans" in y|Y|yes) ;; *) say "aborted"; exit 1 ;; esac
  fi
}
