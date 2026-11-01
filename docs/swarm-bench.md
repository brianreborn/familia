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
