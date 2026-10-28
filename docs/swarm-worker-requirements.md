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
(japanglify `loops.md`). Rule: **one runner per host:user node** (replaces japanglify's
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
