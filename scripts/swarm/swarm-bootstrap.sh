#!/bin/sh
# Fresh swarm worker checkout. Familia copy of brianreborn/japanglify
# scripts/swarm-bootstrap.sh, with the repos made flags instead of constants.
# Layout (japanglify docs/japanglify/hosts.json "workdir"):
#   {home}/swarm-agents/{project}/{hostname}-{user}/{role}/{official,dev}
#
# usage: swarm-bootstrap.sh [--official=owner/repo] [--dev=owner/repo]
#          [--official-branch=main] [--dev-branch=main] [--project=familia]
#          [--role=swarm-bench] [--runner] [--dry-run]
set -eu

OFFICIAL_REPO=brianreborn/familia
DEV_REPO=
OFFICIAL_BRANCH=main
DEV_BRANCH=main
PROJECT=
ROLE=swarm-bench
RUNNER=0
DRY=0
for a in "$@"; do
	case "$a" in
	--official=*) OFFICIAL_REPO=${a#--official=} ;;
	--dev=*) DEV_REPO=${a#--dev=} ;;
	--official-branch=*) OFFICIAL_BRANCH=${a#--official-branch=} ;;
	--dev-branch=*) DEV_BRANCH=${a#--dev-branch=} ;;
	--project=*) PROJECT=${a#--project=} ;;
	--role=*) ROLE=${a#--role=} ;;
	--runner) RUNNER=1 ;;
	--dry-run) DRY=1 ;;
	-h|--help) sed -n '2,9p' "$0"; exit 0 ;;
	*) echo "unknown arg: $a" >&2; exit 2 ;;
	esac
done
[ -n "$PROJECT" ] || PROJECT=${OFFICIAL_REPO##*/}
[ -n "$DEV_REPO" ] || DEV_REPO=$OFFICIAL_REPO

home=${HOME:?HOME is not set}
host=$(hostname 2>/dev/null | cut -d. -f1)
root=${SWARM_AGENTS:-$home/swarm-agents}
agent=$root/$PROJECT/$host-$(id -un)/$ROLE
official=$agent/official
dev=$agent/dev
echo "agentHome=$agent"
echo "official=$official ($OFFICIAL_REPO@$OFFICIAL_BRANCH)"
echo "dev=$dev ($DEV_REPO@$DEV_BRANCH)"

command -v git >/dev/null 2>&1 || { echo "missing git" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || echo "warn: python3 not on PATH" >&2
command -v gh >/dev/null 2>&1 || echo "warn: gh not on PATH (needed for --runner)" >&2

ensure() {
	url=$1 dir=$2 branch=$3
	if [ "$DRY" -eq 1 ]; then
		if [ -d "$dir/.git" ]; then echo "would pull $dir ($branch)"; else echo "would clone $url -> $dir ($branch)"; fi
		return 0
	fi
	mkdir -p "$(dirname "$dir")"
	if [ -d "$dir/.git" ]; then
		git -C "$dir" fetch origin
		git -C "$dir" checkout "$branch"
		git -C "$dir" pull --ff-only origin "$branch"
	else
		git clone --branch "$branch" "https://github.com/$url.git" "$dir"
	fi
}
ensure "$OFFICIAL_REPO" "$official" "$OFFICIAL_BRANCH"
if [ "$DEV_REPO" != "$OFFICIAL_REPO" ] || [ "$DEV_BRANCH" != "$OFFICIAL_BRANCH" ]; then
	ensure "$DEV_REPO" "$dev" "$DEV_BRANCH"
fi
[ "$DRY" -eq 1 ] && exit 0
if [ "$RUNNER" -eq 1 ]; then
	sh "$official/scripts/swarm/swarm-bench-runner.sh" --repo "$OFFICIAL_REPO" --role "$ROLE"
fi
