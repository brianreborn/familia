#!/bin/sh
# Thin forge adapter (requirements R0). Every forge-specific call the swarm makes
# goes through here. Backend chosen by $SWARM_FORGE, else .github/swarm-conductor.json
# "forge.kind", else github.
#
#   forge.sh comment ISSUE BODYFILE     post a result comment on an issue
#   forge.sh comments ISSUE             print comment bodies (for markers)
#   forge.sh runners                    name<TAB>status<TAB>labels per runner
#   forge.sh reg-token                  print a runner registration token (stdout only; caller must not log)
#   forge.sh runner-url                 URL the runner registers against
#   forge.sh dispatch WORKFLOW REF k=v… start a workflow run
#
# Env: SWARM_REPO (owner/name; default $GITHUB_REPOSITORY), SWARM_FORGE_URL.
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
kind=${SWARM_FORGE:-}
if [ -z "$kind" ]; then
	cfg=$here/../../.github/swarm-conductor.json
	if [ -f "$cfg" ] && command -v python3 >/dev/null 2>&1; then
		kind=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("forge",{}).get("kind","github"))' "$cfg")
	fi
fi
kind=${kind:-github}
[ -f "$here/forge/$kind.sh" ] || { echo "forge.sh: no adapter for '$kind'" >&2; exit 2; }
SWARM_REPO=${SWARM_REPO:-${GITHUB_REPOSITORY:-brianreborn/familia}}
export SWARM_REPO
. "$here/forge/$kind.sh"
cmd=${1:?usage: forge.sh comment|comments|runners|reg-token|runner-url|dispatch}
shift
case "$cmd" in
comment) forge_comment "$@" ;;
comments) forge_comments "$@" ;;
runners) forge_runners ;;
reg-token) forge_reg_token ;;
runner-url) forge_runner_url ;;
dispatch) forge_dispatch "$@" ;;
*) echo "forge.sh: unknown command $cmd" >&2; exit 2 ;;
esac
