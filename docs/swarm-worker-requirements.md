# Swarm Worker Requirements (v0.3)

Official requirements for a familia swarm worker on any Unix (Linux, FreeBSD, Termux).
The first instance is the Linux repair install on `linux-55` (real address only in
`hosts.local.yaml`, see [hosts-overlay.md](hosts-overlay.md)).

Sources:
- Design (canonical for the green-* layer): [brianreborn/pqfreebsd `docs/swarm-conductor.md`, `docs/swarm-roles.json`](https://github.com/brianreborn/pqfreebsd/blob/main/docs/swarm-conductor.md)
- Reference implementation: [brianreborn/japanglify `docs/swarm-conductor/`, `.github/workflows/swarm-*.yml`, `scripts/swarm-*`](https://github.com/brianreborn/japanglify/tree/main/docs/swarm-conductor). Only generic mechanics are borrowed; no Japanglify product, linguistics, adb or `/uat` content.
- Root job queue: [brianreborn/angel-freebsd `ROOT-QUEUE.md`, `bin/`](https://github.com/brianreborn/angel-freebsd/blob/main/ROOT-QUEUE.md)

Legend: **B** = borrowed as-is in spirit, **G** = generalized for familia, **N** = new here.

A coordinator-free pull design (GitHub is the nexus; no central host) is
proposed in [Coordinator-free pull swarm](#coordinator-free-pull-swarm-proposed-2026-11-10).
It is design-only. R0-R11 describe the current contract, which still has a
conductor and a miryam-to-phone SSH smoke path.

## R0 Forge-agnostic (HARD, v0.3) — N

Every forge-specific call goes through one thin adapter, `scripts/swarm/forge.sh`,
backend picked by `$SWARM_FORGE` or `.github/swarm-conductor.json` `forge.kind`.
Adapters live in `scripts/swarm/forge/<kind>.sh`. Shipped: `github` (implemented),
`forgejo` (stub with API mapping). mxOS hosts on Forgejo at `git.mx-os.mx`
([announcement](https://mx-os.mx/posts/2025-06-04-ya_tenemos_forgejo/),
[runner playbook](https://git.mx-os.mx/MxOS/ansible-forgejo-runner)).

Minimum forge contract. A forge without all three is out of scope:

1. **Issues and comments**: post a comment, read comments.
2. **Self-hosted runners**: mint a registration token, register, read runner status.
3. **Hosted trivial jobs at arbitrary times**: scheduled and dispatched short jobs
   (used for dispatch, report, ping, watchdog).

Adapter verbs: `comment`, `comments`, `runners`, `reg-token`, `runner-url`, `dispatch`.
Workflows stay in the GitHub/Forgejo/Gitea common Actions subset (`on: schedule |
workflow_dispatch | issue_comment`, `runs-on` labels, `$GITHUB_OUTPUT`, `actions/checkout`).
GitHub-only pieces are isolated and marked (currently `swarm-watchdog.yml`'s `gh run`
calls).

## R1 Roles — B (pqfreebsd `swarm-roles.json`)

| Role | Who | May | Must not |
|---|---|---|---|
| swarm-conductor (high) | Grok Bot issue watcher | ingest, propose assignment, comment, ledger.append | push, run domain tests, `secret.*`, `device.*`, merge main |
| watchdog (high) | `swarm-watchdog.yml`, `swarm-ping.yml` | cancel, status, alert human | propose assignment, push, merge |
| swarm-bench (low) | self-hosted runner | domain tests, comment, push agent branch | propose assignment, `secret.*`, merge main, direct root |

The conductor dispatches; it does not implement, build or sign. Dispatch is not enter.

## R2 Registration — G

- One runner **per host:user node**. A host may run several independent familia
  nodes, one per Unix user, each with its own runner, instance key, ports and state.
- Name `<host>-<user>-<role>`; dir `$HOME/actions-runner` of that user.
- Labels: `self-hosted`, OS, arch (added by the runner), `<role>`,
  `host:<host>`, `node:<host>-<user>`, plus capability labels such as `familia-worker`;
  `vulkan`/`cuda` only where present.
- `scripts/swarm/swarm-bench-runner.sh` registers idempotently (re-registers with
  `--replace` only when the forge lacks the role label, as japanglify
  `swarm-bench-runner.ps1` does). The registration token is never printed or logged.

## R3 Layout and host entries — G

`$HOME/swarm-agents/<project>/<host>-<user>/<role>/{official,dev}`
(`scripts/swarm/swarm-bootstrap.sh`, from japanglify `scripts/swarm-bootstrap.sh` with
`--official=`/`--dev=` repo flags). Host entries in `.github/swarm-conductor.json`
`hosts` are keyed `host:user`; unknown nodes get no role (japanglify `hosts.json`
`unknown`). No real IPs or users in tracked files.

## R4 Dispatch — B (japanglify `events.md`, `swarm-conductor-uat.yml`)

hosted `dispatch` job, then self-hosted `bench` job, then hosted `report` job.
The forge is the event bus: the runner long-polls; nobody polls a host. Triggers: owner
comment `/run e2e [ref]` or `workflow_dispatch`. Loop guard: bots never issue commands
(japanglify `loops.md`). Rule: **one runner per host:user node**. Hosted jobs follow R9 (replaces japanglify's
one-runner-per-host).

## R5 Results and logs — G

- Every result is an issue comment: pass/fail/skip, exit code, host, and the last 20
  lines, posted by the hosted `report` job (a dead runner cannot comment).
- Full logs go to `brianreborn/familia-private` `logs/swarm/<yyyymmdd>/<run>-<host>.log`
  via secret **`FAMILIA_PRIVATE_LOGS_TOKEN`** (fine-grained PAT or deploy key with
  Contents: write on familia-private only). Never to the public repo.
- Key- and token-shaped strings are redacted before upload. API keys are read on the
  host from the per-instance key file (familia #172 design) and never pass through the
  forge.

## R6 Privileged steps — B (angel-freebsd root queue)

Workers never use sudo. Root work is published with `queue-add.sh ID` and approved one
key at a time by root in `root-queue.sh` (copy to a root-only dir, double stat, run only
the private copy). Prefer per-user mechanisms so root is rarely needed (familia
`DESIGN.md` "Least privilege"). No disk or firmware steps on angel or the Vertex 2
without Brian's OK for each step.

## R7 Liveness — G (japanglify HKCU Run loop, angel-freebsd `@reboot`)

A per-user supervisor keeps the listener up; the Grok CLI is not the supervisor.
- Linux: `systemd --user` unit running `swarm-run-loop.sh`; `loginctl enable-linger
  <user>` (one root-queue job) to survive logout.
- FreeBSD / no systemd: crontab `@reboot` loop (as angel-freebsd `install-grok-crontab.sh`).
- Termux: the intended supervisor is termux-services `$PREFIX/var/service/`.
  Today `install/termux/install.sh` does not install a runit service and only
  holds `termux-wake-lock` (code wins; see Path B install below). Doze and the
  phantom-process killer can still freeze or kill the agent, so lease expiry
  and fencing are the recovery path until a supervised unit is actually
  installed (Brian's per-host OK).
- Disarm by touching `$HOME/actions-runner/.swarm-disarmed` (japanglify idle stop).
- `swarm-ping.yml` reports runner status (unknown, not green, when the token cannot read
  runners; set `SWARM_ADMIN_TOKEN` to fix). `swarm-watchdog.yml` comments once when a
  bench job is queued over 20 minutes.

## R8 Sandbox — G (pqfreebsd `pqcap-enter --root $WORK`)

FreeBSD: workers `cap_enter` with the workspace as root. Linux/Termux: **gap**. Interim
isolation is the per-user node itself (a dedicated Unix user); bubblewrap is the
candidate.


## R9 Trivial hosted jobs and security domains (HARD) — N

Forge-hosted jobs MUST be trivial. They may only update issue records (comments,
labels, state) and send messages (dispatch the worker, notify). No building, testing,
synthesis, analysis or LLM calls in a hosted job. When more is needed, the hosted job
only triggers the responsible component. The `report` job posts the worker-produced
summary as is; it does not compute or interpret it.

An external program may run only inside one of these domains, consistent with the
pqfreebsd roles (R1):

| Domain | Identity | Allowed | May hold | Trust boundary |
|---|---|---|---|---|
| D1 Forge-hosted trivial jobs | `github-actions[bot]` / forge bot (role watchdog, plus dispatch/report) | parse an owner command, comment, label, read runner/run status, start the self-hosted job | `GITHUB_TOKEN` (issues write, actions read); optional `SWARM_ADMIN_TOKEN` (runners read) | no checkout of untested code into execution; no secrets beyond these; never reads worker logs |
| D2 Conductor | Grok Bot issue watcher (swarm-conductor, high integrity) | read issues/PRs, propose assignments, post `/run` commands as the owner-approved actor, comment | Grok Bot's forge connector only | never builds, tests, holds host keys, touches devices or merges |
| D3 Worker node | one Unix user on one host (`<host>-<user>`, swarm-bench, low integrity) | check out the ref, build, test, run local familia models and agents, redact and upload its own log, produce the summary | runner credentials in `$HOME/actions-runner`; job `GITHUB_TOKEN`; `FAMILIA_PRIVATE_LOGS_TOKEN` (write familia-private only); its own instance API key, read on the host and never sent to the forge | no root; no other users' state; no merge; no release secrets |
| D4 Root queue | root on that host, a human approving each script | run one approved, root-owned private copy | host root only | input is only a published script; worker cannot change bytes after claim; nothing runs unapproved |
| D5 External programs on behalf | whatever program D3 or D4 launches (llama-server, test harness, forgejo-runner) | exactly what the launching domain may do | inherits a subset of the launcher's credentials, never more | runs as the launcher's identity; cannot start from D1 or D2 directly |

Rules: D1 and D2 can only reach D3 through the forge (job queue or issue command). D3
reaches D4 only through `queue-add.sh`. No domain passes a secret to a lower domain or to
the forge.

## R11 identd (v0.3) — N

Each worker host runs an RFC 1413 ident service, so that TCP peers on the LAN can be
mapped to a host:user. It is **advisory** only: never used for authorization, LAN-only
(firewall port 113 from outside), and recorded in the stamp as `ident=<user>@<host>`.

| OS | Service |
|---|---|
| FreeBSD | base inetd built-in `ident` (`auth stream tcp nowait root internal` in `inetd.conf(5)`; `inetd_enable=YES`) |
| Linux | `oidentd` (or `pidentd`) from the distro, LAN-bound |
| Termux/Android, Windows, macOS | none in base; marked unavailable in the stamp |

Enabling it is a root step, so it goes through the root queue (R6). Regression test:
a worker job connects to a local TCP listener, queries `127.0.0.1:113` for that
connection, and asserts that the reply equals `id -un`. It reports `skip` when no identd
is present. That job is still to be added (gap).

## R10 Identity stamping (v1.0) — N

Every layer attempts an identity stamp. All layers are optional **except system-login
identity** (host, OS user, uid, login session) wherever familia needs it. That part is
mandatory, and a job that cannot get it fails.

Format: one line, `key=value` pairs separated by spaces, with no secrets (no tokens, keys,
passwords or key fingerprints). Values that are missing are left out, not invented:

`stamp v=1 host=<host> user=<user> uid=<uid> session=<id|tty> pid=<pid> node=<host>-<user> role=<role> forge=<kind>:<account> run=<run-id> rq=<root-queue-id> prog=<name>@<version> model=<alias> peer=<addr:port>`

| Layer | Field | Required |
|---|---|---|
| OS login | host, user, uid, session | **yes** |
| Process | pid (and the familia PID logging) | yes when a process is involved |
| Runner/node | node, role | yes on workers |
| Forge account | forge | optional |
| Conductor | `conductor=grokbot` | optional |
| Root queue | rq, plus the approving root uid | optional; written in `results/ID` |
| External program | prog | optional |
| Model/agent call | model | optional |
| Network peer | peer (ident advisory, see R11) | optional |

Recorded: the first line of every worker log, the issue result comment (the worker-made
summary carries it; the hosted job does not add one), and the ledger (`ledger.append`,
pqfreebsd R1) when there is one.

Per-OS sources for the mandatory part:

| OS | host | user/uid | session |
|---|---|---|---|
| Linux | `hostname` | `id -un`, `id -u` | `$XDG_SESSION_ID` / `loginctl`, else `tty` |
| FreeBSD | `hostname` | `id -un`, `id -u` | `tty`; `who am i` |
| Termux/Android | `getprop ro.product.model` or `hostname` | `id -un` (`u0_aNNN`), `id -u` | `$TERMUX_VERSION` and `tty` |
| macOS | `scutil --get LocalHostName` | `id -un`, `id -u` | `tty`; `who am i` |
| Windows | `$env:COMPUTERNAME` | `whoami`, `whoami /user` (SID) | `query session` / `$env:SESSIONNAME` |

Status: the worker summary already starts with a stamp line on Unix (`swarm-worker.yml`
bench job). The other layers are spec-only for v1.0.

### R10.1 Kernel-verified peer credentials for local IPC

For local IPC (root queue, mailbox rings, cockpit and serve local endpoints), a
self-reported identity is not enough. The receiving side reads the peer's credentials
from the kernel and records them in the stamp as `peer_uid= peer_gid= peer_pid=`. This
is mandatory wherever familia needs the login-type identity (R10). An endpoint that
cannot read peer creds must refuse, or fall back to a filesystem-permission check that
the kernel enforces (for example the root queue's mode 1770 `pending/`, owned by the
group, with a root-only claim).

| OS | Mechanism | Source |
|---|---|---|
| Linux | `SO_PEERCRED` (`struct ucred` uid/gid/pid at connect); `SCM_CREDENTIALS` per message with `SO_PASSCRED` | [unix(7)](https://man7.org/linux/man-pages/man7/unix.7.html), [socket(7)](https://man7.org/linux/man-pages/man7/socket.7.html) |
| FreeBSD | `getpeereid(3)`; `LOCAL_PEERCRED` (`struct xucred`, incl. `cr_pid`); `SCM_CREDS` (`struct cmsgcred`) | [unix(4)](https://man.freebsd.org/cgi/man.cgi?query=unix&sektion=4), [getpeereid(3)](https://man.freebsd.org/cgi/man.cgi?query=getpeereid&sektion=3) |
| macOS | `getpeereid(3)`; `LOCAL_PEERCRED` (xucred), `LOCAL_PEERPID` | [getpeereid(3)](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/getpeereid.3.html), `<sys/un.h>` |
| Android/Termux | `SO_PEERCRED` on AF_UNIX (Linux kernel; per-app uid) | unix(7); Android `LocalSocket.getPeerCredentials()` |
| Windows | named pipes: `GetNamedPipeClientProcessId`, `ImpersonateNamedPipeClient` then the token SID; AF_UNIX (Win10 1803+) has no peer-cred option, so use named pipes for identity-bearing IPC | [GetNamedPipeClientProcessId](https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-getnamedpipeclientprocessid), [ImpersonateNamedPipeClient](https://learn.microsoft.com/windows/win32/api/namedpipeapi/nf-namedpipeapi-impersonatenamedpipeclient), [AF_UNIX on Windows](https://devblogs.microsoft.com/commandline/af_unix-comes-to-windows/) |

TCP loopback has no kernel peer identity. Endpoints bound to 127.0.0.1 (for example
:9931/:9933) keep the API key, and should move to a Unix socket or named pipe where an
identity is required. Spec only for v1.0.

## Per-OS differences

| | Linux | FreeBSD | Termux |
|---|---|---|---|
| Runner binary | GitHub actions-runner | none official (gap; forgejo-runner builds) | none official (gap) |
| Supervisor | systemd --user + linger | cron `@reboot` | `termux-wake-lock` today; termux-services is aspirational |
| Root queue shell/group | `/bin/sh`, `root` | `/BSD/sh`, `wheel` | no root; queue unused |

## Gaps

- Forgejo adapter is a stub; watchdog is GitHub-only.
- No runner for FreeBSD/Termux; R8 on Linux. A57 phones stay in that gap: bounded python/compile smoke is opt-in SSH from the miryam runner (`docs/ci/a57-ssh-dispatch.md`), not a `runs-on` Android label.
- `tests/e2e_user_journey.sh` must exist on the tested ref (job reports `skip` otherwise).
- Secrets `FAMILIA_PRIVATE_LOGS_TOKEN` and optional `SWARM_ADMIN_TOKEN` must be added by Brian.

## Coordinator-free pull swarm (proposed, 2026-11-10)

Status: design only. Not implemented. Source: Brian voice session, 2026-11-10.
This section is the target architecture for familia swarm CI/CD. It is added
here because this file is the canonical familia swarm-worker design (DESIGN.md
is the product and topology design; `docs/config/graph/swarms.md` is the
`graph.yaml` `swarms:` field reference; `docs/swarm-bench.md` is the bench
script). Where this section conflicts with the conductor-dispatch path in R1
and R4, this section wins for future work. R0-R11 stay the current contract
until this is implemented.

### No coordinator, no central host

There is no swarm brain and no dispatcher host. GitHub (the forge, via the R0
adapter) is the nexus: the queue, the lease, the result log, and the visible
status all live there. Every reachable machine is a peer: miryam, the Linux
laptop, galaxy1 and galaxy2 (A57 phones), angel (FreeBSD), qodesh, shalom,
and any other host that can see the forge.

miryam is only a peer with a convenient network position. It does not assign
work, and it does not control other hosts. No host dispatches to another over
SSH as a control channel. SSH is only opportunistic access when a peer happens
to be reachable (a human or a peer checking liveness, copying a log the
operator asked for, or the transitional A57 fallback below). Control always
returns to the forge.

### Vetted issues, then explicit admin approval

This document is where peers learn how work is picked up. An issue or task is
not runnable just because it exists.

1. The issue is vetted (it is in scope, has a clear job, and is recorded here
   or in the issue body as swarm-eligible work).
2. Brian gives explicit admin approval for that work to enter the pull queue
   (an approval label or an owner `/run` / equivalent forge command, already
   `owner_only` in `.github/swarm-conductor.json`). An approval label is a
   valid gate only if the peer verifies, from the issue timeline `labeled`
   event, that the actor who applied it is the repository owner. Bare label
   presence is not enough: a Path B token on a low-trust phone may have
   issues:write in order to claim, and must not be able to approve itself.
   The approval is bound to the head SHA (or issue-body revision) it was
   given for. A later push invalidates it. A peer must check SHA == approved
   SHA at claim time and again immediately before executing, so a push after
   `/run` cannot run unapproved code on self-hosted peers.
3. Only then may a free peer claim it.

Discovery of open issues can stay open and parallel. Claiming and running are
side effects, so they wait on that admin gate (see Approval gates below, and
LESSONS-LEARNED `L-2026-11-10`, merged in #379). A bot must not approve, and
a bot must not issue `/run` (the existing loop guard stays).

### How a peer picks the next task

A phone or laptop is not told what to do. When it is free, it pulls.

**Path A: GitHub Actions self-hosted runner (preferred where the official
runner exists).** The runner long-polls the forge for jobs whose `runs-on`
labels are a capability set the peer advertised: OS, arch, RAM class, GPU
API / family, and model-family, plus role labels such as `swarm-bench`. Labels
are capabilities, not host names. `host:<host>` and `node:<host>-<user>` may
still exist as optional identity stamps (R2, R10), but workflows must not
route on them. The peer that is free and matches takes the job. Nobody pushes
the job to a named machine. Path A does not have the Path B claim race:
  the Actions job queue hands each job to exactly one runner, and that
  assignment is the claim.

**Path B: tiny pull agent (when `actions/runner` is unsupported),** including
FreeBSD and Android-native / Termux today (see Gaps). The agent polls the
forge for approved, unclaimed work in the Path B queue (see one-queue rule
below). It does not treat a label, assignee, or comment as an atomic claim
(GitHub has no compare-and-set on those; two peers can both "succeed"). The
claim protocol is in Claim, lease, and fencing. The agent does not SSH to a
sibling to hand off the job.

Matching is any-of on optional capabilities (any peer that has at least the
required set may take it) and all-of on required ones (OS, arch, or a stated
minimum RAM). A job that needs a phone GPU says `android` + `vulkan` + a
model-family, not `galaxy1`.

Capability labels are one lowercase ASCII set, `[a-z0-9-]` only. Do not put
colons in new capability labels: a pull agent may use them in lock, state,
or cache file names, and `:` is invalid on Windows. Path B matches
case-insensitively, as Actions does. Official runner auto-labels
(`Linux`, `X64`, `ARM64`) and `uname` values are mapped into this set.
`host:` / `node:` stay identity stamps only (R2, R10), not routing labels.

| Source | Capability label |
|---|---|
| Actions auto-label `Linux`; Linux `uname -s` | `linux` |
| FreeBSD `uname -s` | `freebsd` |
| Termux (its `uname -s` is `Linux`, not `android`) | `android` |
| `amd64`, `x86_64`, or Actions `X64` | `x64` |
| `aarch64` or Actions `ARM64` | `arm64` |
| Vulkan / CUDA present | `vulkan` / `cuda` |
| Role (existing) | `swarm-bench` |

RAM-class and model-family labels, when added, follow the same alphabet
(for example `ram-8g`, `qwen35`).

Every task lives in exactly one queue: either a Path A Actions job or a
Path B labeled-issue / dispatch item, never both. If Actions has already
queued the job, Path B must not also claim it.

Polls and claims use jittered backoff and ETag / conditional requests. Each
peer has a max-concurrent-claims default of 1. HTTP 403 and 429 are backoff,
not a failure and not a free slot. A burst of peers waking on one approval
must not treat every "I posted a claim comment" as a win.

**Path B install and supervision** (see also R3 layout and R7 liveness; a
persistent install still needs Brian's per-host OK):

- Termux: state, lock, and work directories go under Termux `$HOME` (for
  example `$HOME/.local/state/familia/pull-agent`, with work under the R3
  `$HOME/swarm-agents/...` tree). Never `/sdcard`, `/storage/*`, or
  `/data/local/tmp`, which `install/termux/install.sh` already refuses for
  key files. Hold `termux-wake-lock`, as that installer does. Say plainly
  that Android's phantom-process killer and Doze can still kill or freeze
  the agent; lease expiry plus fencing is the recovery path, not the
  supervisor.
- FreeBSD: stay rootless, per R6. A crontab `@reboot` entry starting
  `daemon -r -P $STATE/agent.pid -o $STATE/agent.log <agent>` gives restart
  supervision without root (`install/freebsd/install-familia.sh` already
  uses `@reboot`). An `rc.d` script under `/usr/local/etc/rc.d` is a
  root-queue step.
- Every node needs a single-instance local lock: a `mkdir`-atomic lock
  directory holding an owner token (pid plus process start time), reclaimed
  only when that pid/start pair is gone. Without it, cron or runit can start
  a second agent on the same node.
- Supervised daemons are the default for unattended runs. A named `screen`
  session is for manual or interactive ones (Brian's screen policy, L-screen),
  not a substitute for the unattended supervisor.

### Claim, lease, and fencing

GitHub issue labels, assignees, and comments are a display cache only. They
are not a compare-and-set. Two peers can both add a label, both become
assignees, and both post a claim comment, and each would think it holds the
lease.

A real claim uses one of these CAS mechanisms:

- Preferred: create a git ref (`POST /git/refs`, for example
  `refs/claims/<issue>-<generation>`). The forge returns 422 if the ref
  already exists; that is the lost race, and the peer looks again.
- Alternative, when a claims ref namespace is not available: the claim is a
  comment that carries a claim id. After posting, the agent re-reads, and
  the earliest unexpired claim comment, ordered by forge `created_at` and
  then comment id, wins. Losers delete or strike their claim comment.

Each successful claim carries a monotonic generation or fencing token (the
claim ref SHA, or the winning claim comment id). Every result and every reap
must name that claim id / generation. Lease expiry and renewal use forge
server time only (comment `created_at`, or the response `Date` header), plus
a grace margin. Local wall clocks are never used to stamp or to test expiry;
phones and RTC-less boards drift and jump after sleep, and a fast-clock
reaper must not void a live lease.

The holder heartbeats (renews) the lease so a long job can outlive the
initial interval. The lease length must cover the renewal interval plus an
Android or FreeBSD sleep pause, or the agent must re-check before every side
effect (do both). This is what stops a Doze-paused or phantom-killed phone
agent from waking after its lease was reaped and posting a result it no
longer holds. Before every side effect the holder re-reads that its claim is
still current and aborts if it has lost the generation. A result whose token
has been superseded is labeled stale, not pass or fail, and is ignored;
last-writer-wins on labels or statuses is not enough.

Reaping is not "drop the lease label and clear the assignee." Any peer may
reap, but the reap is conditional on the exact stale generation: reap of
generation N is the same CAS as creating the tombstone / next claim
(generation N+1). Two concurrent reapers then collide on the CAS instead of
erasing a fresh claim that landed in between. After a successful reap, the
task returns to the queue as unclaimed, still-approved work (same approved
SHA, unless that approval was invalidated by a new push). Reaping is not
reserved for miryam or a conductor.

Every side effect (result post, private-log upload, install, or anything
that touches phone or host state) is keyed by the idempotency tuple
(issue, approved head SHA, claim generation). A retry on another peer is
safe only when that key is checked and honored. A busy or expired claim is
not a pass. "Idempotent because it is a smoke test" is not a substitute.

A device (for example one A57 phone) has one device-level claim that both
Path B and the opportunistic SSH fallback must take. The SSH fallback takes
that same forge claim plus the phone-side flock, not only a flock on the
runner host. Otherwise a phone agent and a miryam SSH job can oversubscribe
the same device.

### Result submission

The peer that ran the work posts the result back to the nexus, in public
enough form that any other peer or a person can see it without asking the
runner host. The post includes the claim generation / fencing token; a
stale token is ignored as above.

- job logs and artifacts on the workflow run
- check runs on the commit or pull request
- signed issue or PR comments (pass/fail/skip, exit code, identity stamp from
  R10, fencing token, and a short tail of the log)
- commit statuses

Full logs may still go to `brianreborn/familia-private` under
`logs/swarm/<yyyymmdd>/` with redaction, as in R5, and the same idempotency
key. The hosted `report` job in R4/R9 remains a valid way to paste a worker
summary when the worker itself cannot comment (a dead or disconnected peer).
The report job still must not reinterpret a failure as a pass, still must
not compute new results (R9), and still must drop a superseded fencing
token. Key- and token-shaped strings stay redacted. API keys stay on the
host and never pass through the forge.

### Failure surfacing

Nothing fails silently.

- A failed job is a failed check, a failed status, and a visible issue label
  such as `swarm-failed`. The comment says what went wrong.
- Lease expiry and stale-claim reaping follow Claim, lease, and fencing
  (forge server time, generation-conditional CAS, no check-then-act erase of
  a fresh claim).
- A peer that is offline is not a lost task. The forge still shows the job as
  queued or the issue as approved-and-unclaimed.
- The watchdog comments when an approved task has had no successful claim
  for a bound T (starvation), and when a task's claim generation passes a
  bound K (a lease flapping between peers).
- Diagnostics report what is wrong without writing to a disk under test.
  Progress and logs go off-target (a log file on a different disk, or the
  forge / familia-private path), preferably inside a named screen session
  (`L-screen`, `L-2026-11-10` item 4, `L-190` item 6).

### Host-agnostic routing

- Workflows must not hardcode a host list or a host-name `runs-on` label.
- Routing is label-based capability matching, as above.
- When zero eligible hosts are online, the job stays queued and visible
  (Actions queued state, issue label, watchdog comment). It does not fail
  closed as "no such host" and it does not get pushed over SSH to a stand-in.
- Retries follow the idempotency key (issue, approved head SHA, claim
  generation). A failed or expired claim may be retried on any other capable
  peer, not only on the machine that first touched it, and only after a
  successful generation-conditional reap.

### Migration from the miryam-to-phone SSH smoke

Today `.github/workflows/a57-ssh-smoke.yml` and
`docs/ci/a57-ssh-dispatch.md` run a bounded python/compile smoke by having the
miryam runner SSH to galaxy1 and galaxy2. That path is a documented gap in
this file: the phones are not Actions runners, and there is no official
runner for FreeBSD or Termux.

Keep that SSH smoke as an opportunistic fallback only, not as the control
path. It may run only when the peer already holds the shared device-level
forge claim (see Claim, lease, and fencing) for an approved job whose
capabilities include "A57 Termux smoke", the inventory on that peer allows
SSH, and the phone-side flock is also taken. It must not be how work is
assigned, and it must not run beside a Path B agent on the same phone. The
target is Path B on the phones themselves (a tiny pull agent, or a later
supported runner), with the same admin-approval, SHA binding, and lease
rules. Do not add a `runs-on` phone or `host:miryam` requirement to new
workflows.

### Security

- Self-hosted runner scopes stay least-privilege: the job `GITHUB_TOKEN` is
  contents-read plus the write rights needed to post its own results (issues,
  checks, statuses). Registration tokens are never printed or logged (R2).
- Phones and other low-trust peers hold no secrets beyond the runner or pull
  agent token. No `FAMILIA_PRIVATE_LOGS_TOKEN`, no host SSH keys for other
  machines, no instance API keys from the forge, and no release secrets.
  If a private log upload is needed from a phone, a higher-trust peer or the
  hosted report job publishes the already-redacted summary.
- Fork pull requests never run on self-hosted runners or on the pull agent.
  The existing A57 gate (owner repo, `development` only, no
  `pull_request_target`, no fork head) stays the model.
- D1 hosted jobs stay trivial (R9): comment, label, status, dispatch into the
  forge queue. They do not SSH, build, or test.
- The conductor role in R1, if it remains at all, may only watch and comment.
  It must not dispatch to a host, hold host keys, or become a control plane.
  Peers pull; nothing pushes.

### Approval gates and interactive latency

Approval gates are filters on side effects, not global locks on discovery or
parallel work (`L-2026-11-10`). Vetting and Brian's admin approval (bound to
a head SHA) gate a task entering the runnable queue, and later gates may
cover writes, reboots, installs, root-queue scripts (R6), and other side
effects. They must not serialize independent read-only probes or make one
approval a waiter that only lets one job through.

Interactive feedback should stay under about 400 ms so the operator still
has a sense of flow (`L-2026-11-10` item 5; attribution of the IBM /
@lauriewired threshold is not yet verified). Queue state, claim result, and
"I am running this" should be visible on the forge quickly. Long jobs still
run long; the first ack must not wait on them.

### Persistent installs

A persistent runner, pull agent, or boot service on a host still needs
Brian's per-host OK before it is installed or left running unattended. This
section does not grant that OK for miryam, the Linux laptop, the A57 phones,
angel, qodesh, shalom, or any other machine.

### Current code that this section would change

Documented so the design and the tree are not silently at odds. This PR does
not change these files.

- `.github/workflows/a57-ssh-smoke.yml` routes the smoke job to
  `[self-hosted, Linux, swarm-bench, host:miryam]` and uses SSH from that
  host as the control path to the phones.
- `.github/workflows/swarm-worker.yml` uses
  `[self-hosted, Linux, swarm-bench]` (no host name, but Linux-only, no
  RAM/GPU/model-family labels) after a hosted `ubuntu-latest` dispatch.
- `.github/swarm-conductor.json` `hosts` is a hardcoded inventory
  (`linux-55`, `miryam:green`, `grok-bot-vm-414137730:box`). `runnerLabels`
  still includes `host:<host>` and `node:<host>-<user>`. R1 and R4 describe
  a conductor that dispatches.
- Hosted trivial or analysis jobs correctly use `ubuntu-latest` today
  (`tests.yml`, `lint-warnings.yml`, `nvso-userspace-smoke.yml`,
  `swarm-ping.yml`, `swarm-watchdog.yml`, and the A57/swarm gate and report
  jobs). `codeql.yml` is also hosted, but it picks `macos-latest` for the
  swift matrix leg and `ubuntu-latest` otherwise. That remains valid for D1
  and for work that must not run on self-hosted peers. It is not a host-name
  hardcode, but it is also not label-based self-hosted routing.
