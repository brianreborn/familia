# A57 SSH smoke (miryam runner)

Bounded python/compile smoke on the two A57 phones (`galaxy1`, `galaxy2`).
The phones are existing Termux SSH workers. They are **not** GitHub Actions
runners. Nothing in this workflow uses `runs-on` with an Android or phone label.

This file is the dispatch contract. It is not a Termux install guide, and it
does not claim the phone `sshd` survives reboot.

## What runs

`.github/workflows/a57-ssh-smoke.yml` follows the swarm shape in
[swarm-worker-requirements.md](../swarm-worker-requirements.md) (hosted gate,
then the self-hosted worker, then a hosted paste of the worker summary):

| Job | Runner | What it may do |
|---|---|---|
| `gate` | `ubuntu-latest` | Accept only `push` to `development`, or `workflow_dispatch` of that ref, in `brianreborn/familia`. Exit 2 otherwise. |
| `smoke` | `[self-hosted, Linux, swarm-bench, host:miryam]` | Check out that development SHA (`persist-credentials: false`) and run `scripts/swarm/a57_ssh_dispatch.py --job python-compile --devices both`. |
| `report` | `ubuntu-latest` | Paste the worker's status lines into the step summary. It does not SSH and does not reinterpret a failure as a pass. |

The Actions step clears `A57_SSH_CI_SSH`, the local-allow and budget overrides, and `A57_SSH_CI_INVENTORY` before the script runs, so CI always uses the default inventory path and the real `ssh` binary. A manual rerun on the host may set those variables; the workflow does not.

The miryam listener is the one already started from `$HOME/actions-runner/swarm-run-loop.sh`. This repo does not install or restart that loop. The published registration script names its user unit `swarm-runner-<role>.service` (default role `swarm-bench`). Pickup depends on the **labels**, not on the unit name.

Workflow concurrency is one run at a time (`cancel-in-progress: false`), so a second push waits instead of killing an open SSH session. Each phone also has its own non-blocking flock on the runner, and the remote smoke takes a non-blocking flock under `~/.cache` on that phone. A second overlap reports `busy`, not `pass`.

Per phone, SSH uses `ConnectTimeout=10`, the process budget defaults to 35s and is capped at 60s, and a kill grace follows. The remote Python alarm is 20s. The job `timeout-minutes` is 8. On timeout the runner kills the SSH process group (TERM, then KILL). It does not signal other processes on the phone.

## Trust

Fork pull requests and `pull_request_target` are not triggers. The script also refuses those event names, any `GITHUB_REPOSITORY` other than `brianreborn/familia`, any ref other than `refs/heads/development`, and a GitHub event file that says the repository is a fork or the pull-request head is a different repo. `A57_SSH_CI_ALLOW_LOCAL=1` permits a manual rerun on the runner host only when no GitHub event is set. It does not override an untrusted event.

There is no device choice and no ref field in the workflow inputs. `--job` and `--devices` in the workflow file are literals (`python-compile`, `both`). A SHA is taken from `github.sha`, checked as hex, and recorded locally. It is not passed to the phone.

The script does not run for `issue_comment` or `/run`. The swarm conductor must not gain device access. The existing `/run` bench job checks out an owner-supplied ref; this smoke does not.

## SSH

Inventory path, first match:

1. `--inventory` or `$A57_SSH_CI_INVENTORY`
2. `$XDG_CONFIG_HOME/familia/a57-ssh-ci.yaml`
3. `~/.config/familia/a57-ssh-ci.yaml`

Copy [a57-ssh-ci.yaml.example](a57-ssh-ci.yaml.example). Allowed device keys are only `addr`, `port`, `user`, `known_hosts`, and `identity_file`. An extra key (including any SSH option override) refuses the device. Unknown top-level keys refuse the file.

The client is `ssh -F /dev/null` with `BatchMode=yes`, `StrictHostKeyChecking=yes`, `UserKnownHostsFile` set to the pin, `GlobalKnownHostsFile=/dev/null`, `ProxyJump=none`, `ProxyCommand=none`, `IdentitiesOnly=yes`, `IdentityAgent=none`, `ForwardAgent=no`, `ControlMaster=no`, and `UpdateHostKeys=no`. The child environment is only `PATH`, `HOME`, `LANG`, and `LC_ALL`. Token, key, and password values from the runner are not copied. `GITHUB_TOKEN` still exists in the Actions job; it is not forwarded.

Addresses must be private IPv4. Loopback, link-local, public, and documentation TEST-NET ranges are refused or treated as not configured, and SSH is not opened. The known_hosts file and the identity file must be regular files owned by the runner user. The identity mode must be `0600` or `0400`. The pin must not be group- or world-writable. Because the port is not 22, the pin entry has to be for `[addr]:port`.

The remote command is a fixed `python3 -I` program on stdin. The only approved job is `python-compile`: print the Python version, compile `print(1)` in a temporary directory, delete that directory. It does not install packages, download models, open a socket, read an API key, or signal other processes. It does not call a familia HTTP API. A future job that does, including on loopback, still has to use the on-host instance key and must not receive that key from the forge.

Resident llama servers on loopback port 18112 are out of scope. This smoke does not probe, stop, or evict them. Wake locks and `sshd` are not changed.

## Status lines

Stdout is one header, one `device=<name> status=<status>` line per phone, and `overall=`. Status is only:

| status | meaning |
|---|---|
| `pass` | Python compile smoke exited 0 |
| `fail` | The phone ran the smoke and it failed |
| `unavailable` | SSH could not connect (offline, refused, timed out at connect) |
| `hostkey` | Pinned host key did not match. Checks are not relaxed |
| `timeout` | The local budget expired and the SSH process group was killed |
| `busy` | This phone's runner lock or remote lock was already held |
| `not-configured` | Inventory missing, device missing, or still the example placeholders |
| `refused` | Unsafe inventory or arguments. No SSH for that case |

`overall=pass` and process exit 0 happen only when every selected device is `pass`. Exit 2 is a refusal before SSH. Any other non-pass is exit 1. An offline phone is `unavailable`, not a pass. A missing inventory is `not-configured`, not a pass.

## Deployment handoff

This change does not SSH, does not copy files onto miryam or the phones, and does not restart services. After it is on `development`, the next push queues the workflow. Until the private inventory exists, the check is red with `not-configured`.

1. Confirm the miryam runner is online and its labels include `self-hosted`, `Linux`, `swarm-bench`, and `host:miryam` (`sh scripts/swarm/forge.sh runners`, or the Swarm ping workflow). If `swarm-bench` or `host:miryam` is absent, the job stays **queued**. Do not add an Android runner, and do not point `runs-on` at an unpublished label to force a pickup.
2. As the runner user, copy the example to `~/.config/familia/a57-ssh-ci.yaml` (mode `0600`). Fill `addr`, `port`, and `user` from your own records. Direct LAN, port `8022`. Do not commit it.
3. Point `known_hosts` at a pin file that user can read, mode not group/world-writable, with the existing keys for `[addr]:8022`. Copy the pin you already trust. Do not switch on `accept-new` or `StrictHostKeyChecking=no`.
4. Point `identity_file` at the existing key that already authenticates from that user, mode `0600` or `0400`. `BatchMode` cannot prompt. The agent is not used. Do not create a new key in the repo.
5. Do not reboot the phones, restart `sshd`, install packages, download models, or stop the llama servers on port 18112. Phone `sshd` reboot persistence is **unverified**. If `sshd` is down, the status is `unavailable`.
6. A manual rerun on the runner host, with no GitHub event in the environment, is `A57_SSH_CI_ALLOW_LOCAL=1 python3 scripts/swarm/a57_ssh_dispatch.py`. `workflow_dispatch` from the Actions UI appears once this file is on the repository default branch. Before that, `sh scripts/swarm/forge.sh dispatch a57-ssh-smoke.yml development` targets the `development` ref. Do not dispatch any other ref: GitHub runs the workflow file from the ref you name.

## Rollback

- Disable the workflow in the Actions UI, or revert the workflow file. The runner loop can stay up.
- Remove `~/.config/familia/a57-ssh-ci.yaml`. Later runs fail closed with `not-configured`.
- Touching `$HOME/actions-runner/.swarm-disarmed` stops the **whole** swarm listener, not only this job.

The phone lock file `~/.cache/familia-a57-ci.lock` is an empty flock target. Deleting it is optional. A killed SSH client can leave a `familia-a57-smoke-*` directory; the next run does not need it. This smoke does not delete anything else.

## Disagreements with existing docs and code

Tracked behavior wins where it conflicts with an assumption. These were left as they are:

- `graph.yaml` notes say galaxy1/galaxy2 SSH via ProxyJump angel. This dispatcher does not use those aliases. It sets `-F /dev/null` and `ProxyJump=none` so the direct path is explicit. `graph.yaml` was not edited.
- `scripts/monitor.py` reuses SSH with `ControlMaster=auto` and `ControlPersist=120`. A persisted master would outlive this job's timeout, so this dispatcher sets `ControlMaster=no` and `ControlPath=none`.
- `scripts/offline_improve.py`, `scripts/nexus/nexus.py`, and `docs/transport-poc.md` use `StrictHostKeyChecking=accept-new`. That would trust a first-seen key. This path uses `yes` plus the pinned file.
- `scripts/swarm/bench.sh` skips when `llama-server` is running. This smoke is not a benchmark and does not call `bench.sh`. It also does not skip, and it does not stop that process.
- `scripts/swarm/swarm-bench-runner.sh` installs `swarm-runner-<role>.service` (default `swarm-runner-swarm-bench.service`). The unit name reported for the live miryam listener is `swarm-runner-familia.service`. The published note in `.github/swarm-conductor.json` still says the miryam loop was started by hand with no boot service. Neither file was changed. Label match is the contract; the unit name was not re-verified here.
- Swarm R5 says every result is an issue comment. This push has no issue. The hosted `report` job pastes the worker summary and does not file a comment. R9 (hosted jobs stay trivial) still holds.
- Swarm R4's triggers are an owner `/run` comment or `workflow_dispatch`. This workflow adds `push` to `development` only. It does not add `pull_request`.
- Requirements R2/R7 and the per-OS table: Termux has no official Actions runner. That gap stays. These phones are SSH targets of the miryam worker (a program the worker launches), not runners.
- `scripts/swarm/swarm-watchdog.yml` only comments when the `bench` job of `swarm-worker.yml` is queued. It does not watch this workflow. A queued smoke job is visible on the Actions run; it is not a pass.
- Connection fields for the graph belong in `hosts.local.yaml`. This inventory is a separate file because that overlay has no known_hosts or identity path, and loading it would not apply `ProxyJump=none`.

## Residual risks

- Anyone who can push a workflow to `development` can change this file and run other commands on the miryam runner. The script's trust check only applies when this copy is the one executed. `workflow_dispatch` of a different branch runs that branch's workflow file. Do not dispatch untrusted refs. Fork pull requests do not trigger this workflow.
- The runner registration token and `GITHUB_TOKEN` remain on the runner. They are not forwarded to the phone. A workflow edit could read them. That is the existing self-hosted-runner boundary, not a new phone credential.
- If the registered labels are not exactly the four above, the job stays queued until the runner picks it up. Queued is not success.
- A hard kill of the runner step can skip the remote `finally`. The flock is released by the kernel when the process dies. A temp directory on the phone may remain. No other cleanup runs, and llama servers are not killed to compensate.
- Host-key mismatch fails closed. The fix is a new pin in the private file, not a weaker SSH option.
- Until the inventory is installed, development pushes fail this check. Do not mark the check required, and do not treat red as a phone failure, until that file exists.
- Reboot persistence of phone `sshd` was not verified. A phone that comes back without `sshd` reports `unavailable`.
