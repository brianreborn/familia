# Swarm Worker Requirements (v0.3)

Official requirements for a familia swarm worker on any Unix (Linux, FreeBSD, Termux).
The first instance is the Linux repair install on `linux-55` (real address only in
`hosts.local.yaml`, see [hosts-overlay.md](hosts-overlay.md)).

Sources:
- Design (canonical for the green-* layer): [brianreborn/pqfreebsd `docs/swarm-conductor.md`, `docs/swarm-roles.json`](https://github.com/brianreborn/pqfreebsd/blob/main/docs/swarm-conductor.md)
- Reference implementation: [brianreborn/japanglify `docs/swarm-conductor/`, `.github/workflows/swarm-*.yml`, `scripts/swarm-*`](https://github.com/brianreborn/japanglify/tree/main/docs/swarm-conductor). Only generic mechanics are borrowed; no Japanglify product, linguistics, adb or `/uat` content.
- Root job queue: [brianreborn/angel-freebsd `ROOT-QUEUE.md`, `bin/`](https://github.com/brianreborn/angel-freebsd/blob/main/ROOT-QUEUE.md)

Legend: **B** = borrowed as-is in spirit, **G** = generalized for familia, **N** = new here.

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
- Termux: termux-services `$PREFIX/var/service/`.
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
| Supervisor | systemd --user + linger | cron `@reboot` | termux-services |
| Root queue shell/group | `/bin/sh`, `root` | `/BSD/sh`, `wheel` | no root; queue unused |

## Gaps

- Forgejo adapter is a stub; watchdog is GitHub-only.
- No runner for FreeBSD/Termux; R8 on Linux.
- `tests/e2e_user_journey.sh` must exist on the tested ref (job reports `skip` otherwise).
- Secrets `FAMILIA_PRIVATE_LOGS_TOKEN` and optional `SWARM_ADMIN_TOKEN` must be added by Brian.
