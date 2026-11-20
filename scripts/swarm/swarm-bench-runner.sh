#!/bin/sh
# Register this Unix host:user node as a self-hosted swarm worker (one runner per
# host:user; several users on one host are independent familia nodes).
# Unix counterpart of brianreborn/japanglify scripts/swarm-bench-runner.ps1
# (same naming: <HOST>-<role>, same registration-token flow, --replace).
#
# Usage: sh scripts/swarm/swarm-bench-runner.sh [--repo owner/name] [--role swarm-bench]
#          [--labels extra,labels] [--dir ~/actions-runner] [--service] [--dry-run]
#
# Name <host>-<user>-<role>; labels <role>,host:<host>,node:<host>-<user>[,extra].
# Idempotent: an existing .runner with the required labels is left alone.
# The registration token is held in a variable only; it is never echoed or logged.
# --service installs a per-user supervisor (no root): systemd --user unit, else
# crontab @reboot loop (japanglify uses HKCU Run for the same logon-scoped role).
# Disarm: touch $DIR/.swarm-disarmed (loop stops relaunching; japanglify idle stop).
# Forge calls go through scripts/swarm/forge.sh (R0). Needs: curl, tar, gh.
set -eu

REPO=brianreborn/familia
ROLE=swarm-bench
EXTRA=familia-worker
DIR=${SWARM_RUNNER_DIR:-${HOME:?HOME unset}/actions-runner}
SERVICE=0
DRY=0
while [ $# -gt 0 ]; do
	case "$1" in
	--repo) REPO=$2; shift ;;
	--role) ROLE=$2; shift ;;
	--labels) EXTRA=$2; shift ;;
	--dir) DIR=$2; shift ;;
	--service) SERVICE=1 ;;
	--dry-run) DRY=1 ;;
	-h|--help) sed -n '2,13p' "$0"; exit 0 ;;
	*) echo "unknown arg: $1" >&2; exit 2 ;;
	esac
	shift
done

host=$(hostname 2>/dev/null | cut -d. -f1)
user=$(id -un)
NODE=$host-$user
NAME=${SWARM_RUNNER_NAME:-$NODE-$ROLE}
LABELS="$ROLE,host:$host,node:$NODE"
FORGE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/forge.sh
export SWARM_REPO=$REPO
[ -n "$EXTRA" ] && LABELS="$LABELS,$EXTRA"
for t in curl tar gh; do
	command -v "$t" >/dev/null 2>&1 || { echo "missing $t" >&2; exit 1; }
done

case "$(uname -s)" in
Linux) os=linux ;;
Darwin) os=osx ;;
*) echo "GitHub ships actions-runner for Linux/macOS only; $(uname -s) unsupported (gap)" >&2; exit 1 ;;
esac
case "$(uname -m)" in
x86_64|amd64) arch=x64 ;;
aarch64|arm64) arch=arm64 ;;
armv7l) arch=arm ;;
*) echo "unsupported arch $(uname -m)" >&2; exit 1 ;;
esac

echo "repo=$REPO name=$NAME labels=$LABELS dir=$DIR"
if [ "$DRY" -eq 1 ]; then echo "dry-run: nothing changed"; exit 0; fi

mkdir -p "$DIR"
cd "$DIR"
if [ ! -x ./config.sh ]; then
	ver=$(gh api repos/actions/runner/releases/latest --jq .tag_name | sed 's/^v//')
	tgz="actions-runner-$os-$arch-$ver.tar.gz"
	curl -fsSLo "$tgz" "https://github.com/actions/runner/releases/download/v$ver/$tgz"
	tar xzf "$tgz"
	rm -f "$tgz"
fi

registered=0
if [ -f .runner ]; then
	# Check GitHub's view of our labels (old installs may lack the role label).
	have=$(sh "$FORGE" runners 2>/dev/null | awk -F'\t' -v n="$NAME" '$1==n{print $3}' || true)
	case ",$have," in
	*",$ROLE,"*) registered=1; echo "runner already registered ($NAME)" ;;
	*) echo "registered locally but GitHub lacks label $ROLE; re-registering with --replace" ;;
	esac
fi

if [ "$registered" -eq 0 ]; then
	tok=$(sh "$FORGE" reg-token)
	[ -n "$tok" ] || { echo "could not mint registration token (need repo admin)" >&2; exit 1; }
	./config.sh --unattended --url "$(sh "$FORGE" runner-url)" --token "$tok" \
		--name "$NAME" --labels "$LABELS" --work _work --replace >/dev/null
	tok=
	echo "registered $NAME labels=self-hosted,Linux,<arch>,$LABELS"
fi

cat > "$DIR/swarm-run-loop.sh" <<LOOP
#!/bin/sh
# Keep Runner.Listener alive for this user (relaunch every 20s unless disarmed).
cd "$DIR"
while :; do
	[ -f .swarm-disarmed ] && { sleep 20; continue; }
	./run.sh >> "$DIR/_diag/swarm-loop.log" 2>&1
	sleep 20
done
LOOP
mkdir -p "$DIR/_diag"; chmod +x "$DIR/swarm-run-loop.sh"

if [ "$SERVICE" -eq 1 ]; then
	unit=swarm-runner-$ROLE.service
	if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
		mkdir -p "$HOME/.config/systemd/user"
		cat > "$HOME/.config/systemd/user/$unit" <<UNIT
[Unit]
Description=familia swarm runner $NAME
After=network-online.target
[Service]
ExecStart=$DIR/swarm-run-loop.sh
Restart=always
RestartSec=20
[Install]
WantedBy=default.target
UNIT
		systemctl --user daemon-reload
		systemctl --user enable --now "$unit"
		echo "systemd --user $unit enabled"
		if [ "$(loginctl show-user "$user" -p Linger --value 2>/dev/null)" != yes ]; then
			echo "To run without a login session, root must enable linger (R6 root-queue job):"
			echo "  queue-add.sh linger-$NODE   with body:   loginctl enable-linger $user"
		fi
	elif command -v crontab >/dev/null 2>&1; then
		tdir=$(umask 077 && mktemp -d "${TMPDIR:-/tmp}/familia-cron.$$.XXXXXX"); trap '[ -n "$tdir" ] && rm -rf -- "$tdir" 2>/dev/null' EXIT; trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM
		tab="$tdir/crontab"
		crontab -l 2>/dev/null | grep -v "swarm-run-loop.sh" > "$tab" || true
		echo "@reboot $DIR/swarm-run-loop.sh" >> "$tab"
		crontab "$tab"
		echo "crontab @reboot loop installed; start now: nohup $DIR/swarm-run-loop.sh &"
	elif [ -d "${PREFIX:-/nonexistent}/var/service" ]; then
		echo "Termux: create \$PREFIX/var/service/swarm-$ROLE/run exec'ing $DIR/swarm-run-loop.sh (termux-services)"
	else
		echo "no per-user supervisor found; run $DIR/swarm-run-loop.sh in screen/tmux"
	fi
else
	echo "foreground: $DIR/swarm-run-loop.sh   (or rerun with --service for autostart)"
fi
