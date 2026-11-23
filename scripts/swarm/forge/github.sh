# GitHub adapter (sourced by forge.sh). Uses gh; GH_TOKEN or gh auth.
forge_comment() { gh issue comment "$1" -R "$SWARM_REPO" --body-file "$2"; }
forge_comments() { gh issue view "$1" -R "$SWARM_REPO" --comments --json comments --jq '.comments[].body'; }
forge_runners() {
	gh api "repos/$SWARM_REPO/actions/runners" --paginate \
		--jq '.runners[] | "\(.name)\t\(.status)\t\([.labels[].name]|join(","))"'
}
forge_reg_token() { gh api --method POST "repos/$SWARM_REPO/actions/runners/registration-token" --jq .token; }
forge_runner_url() { echo "${SWARM_FORGE_URL:-https://github.com}/$SWARM_REPO"; }
forge_dispatch() {
	wf=$1 ref=$2; shift 2
	set -- $(for kv in "$@"; do printf -- '-f %s ' "$kv"; done)
	gh workflow run "$wf" -R "$SWARM_REPO" --ref "$ref" "$@"
}
