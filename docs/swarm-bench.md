# swarm bench (`scripts/swarm/bench.sh`)

Speed smoke for `/run bench` (#183). Exit codes: 0 ok, 1 failure, 2 bad knob value,
77 skipped because the RAM guard is unavailable, 78 skipped (no llama-bench, host busy, or short on RAM).
`SWARM_BENCH_FORCE=1` skips the idle guard entirely.

Load guard: skip when the 1-minute load >= `SWARM_BENCH_MAX_LOAD`, default nproc/2 with a floor of 1
(so a 1-CPU host is not always skipped).

## FreeBSD: RAM guard needs procfs + linprocfs

The RAM guard reads `MemAvailable` from `/proc/meminfo`, then `/compat/linux/proc/meminfo`.
FreeBSD's native procfs has no `meminfo`; linprocfs does. No sysctl fallback is used. If neither file
exists the script prints `RAM guard unavailable: mount procfs+linprocfs (see fstab)` to stderr and
skips with exit 77 instead of passing silently.

To enable it, add to `/etc/fstab`:

```
proc     /proc                procfs     rw  0 0
linproc  /compat/linux/proc   linprocfs  rw  0 0
```

linprocfs needs the Linux ABI kld: `kldload linux64` now, and `linux_enable="YES"` in `/etc/rc.conf`
to persist it.

**Brian must personally approve applying these fstab / rc.conf changes to any host** (for example angel).
Agents document them; they do not apply them.

## Run when idle (`scripts/swarm/bench_idle.py`, opt-in)

`bench.sh` only runs when asked. `scripts/swarm/bench_idle.py` is a one-shot trigger a scheduler
calls every few minutes; it runs `bench.sh` only when this host:user is idle. Nothing installs or
enables it: each host's owner opts in with one of the per-user examples below.

Each call:

1. Takes a non-blocking `flock` on `STATE/bench_idle.lock`. A second trigger exits 0 at once, so runs
   never overlap.
2. Skips if `STATE/disarmed` exists, if the last run was less than `--min-interval` ago (default 6 h),
   or, after `bench.sh` itself skipped (77/78), until a backoff has passed (15 min, doubling, capped
   at the min interval).
3. Checks idleness: 1- and 5-minute load below `--max-load` (default nproc/4, at least 1; stricter
   than bench.sh), `MemAvailable` at least `--min-avail-mib` (default 4096), and no `llama-server`,
   `llama-cli`, `llama-bench`, `llama-run` or `llama-mtmd-cli` process (so it never competes with
   chat). A busy host is not an attempt; the next tick checks again.
4. Runs `sh bench.sh` under `nice -n 19` and `ionice -c3` where those exist, with every GPU device
   hidden (CPU only) and `SWARM_BENCH_FORCE` removed from the environment, so bench.sh's own load,
   RAM and llama-server guards always apply. The trigger never sets `SWARM_BENCH_FORCE`.
5. Writes the result table to `STATE/results/<UTC stamp>.md` (mode 0600) and appends one JSON line to
   `STATE/runs.jsonl`.

`STATE` is `$SWARM_BENCH_IDLE_STATE`, else `$XDG_STATE_HOME/familia/bench`, else
`$HOME/.local/state/familia/bench`. It is created 0700, must be owned by the caller and is refused under
`/tmp`, `/var/tmp` or `/dev/shm`. Temporary work uses one private `mkdtemp()` directory inside
`STATE` per run (exported to bench.sh as `TMPDIR` and its working directory), removed when the run
ends. The trigger opens no sockets and listens on nothing; bench.sh's model download is its only
network use.

Exit codes: 0 ran OK or skipped, 1 bench.sh failed, 2 bad arguments or an unsafe state dir.
Try it without running anything: `python3 scripts/swarm/bench_idle.py --dry-run`.

Environment knobs: `SWARM_BENCH_IDLE_INTERVAL`, `SWARM_BENCH_IDLE_BACKOFF`, `SWARM_BENCH_IDLE_MAX_LOAD`,
`SWARM_BENCH_IDLE_MIN_AVAIL_MIB`, `SWARM_BENCH_IDLE_TIMEOUT` (whole run, default 4 h),
`SWARM_BENCH_IDLE_BUSY_PROCS` (comma list), `SWARM_BENCH_IDLE_BENCH`, `SWARM_BENCH_IDLE_STATE`.
All `SWARM_BENCH_*` tuning knobs of bench.sh pass through.

### Opt-in scheduling examples (per user, no root)

systemd (Linux): copy `packaging/systemd-user/familia-bench-idle.service` and `.timer` to
`$HOME/.config/systemd/user/`, adjust `WorkingDirectory` if the checkout is not `$HOME/familia`, then
`systemctl --user daemon-reload && systemctl --user enable --now familia-bench-idle.timer`.
The unit adds `Nice=19`, `IOSchedulingClass=idle` and `CPUSchedulingPolicy=idle`. Without a login
session the user manager stops; `loginctl enable-linger` would change that but needs root.

User crontab (Linux, FreeBSD, macOS; `crontab -e`):

```
*/20 * * * * cd "$HOME/familia" && python3 scripts/swarm/bench_idle.py >/dev/null 2>&1
```

FreeBSD: use the user crontab line. There is no `ionice`; the trigger uses `nice` only. `idprio`
for non-root users needs `security.bsd.unprivileged_idprio=1` (a sysctl change), and the RAM guard
needs the procfs/linprocfs fstab and rc.conf lines above; bench.sh exits 77 until then and the trigger
backs off.

Termux (Android): a user crontab via `crond` from `termux-services`, or `termux-job-scheduler`, can
call the same command. Installing packages or services on a phone is a device change: do not enable
it on the fleet phones without the owner's explicit yes.

**Anything beyond these per-user examples (a system-wide unit, `loginctl enable-linger`, `sudo`,
sysctl, `/etc/fstab` or `/etc/rc.conf`) needs Brian's explicit yes for each host.** No familia
installer applies any of it.
