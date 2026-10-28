# Monitoring console (SSH-based)

`familia-monitor` (also `scripts/monitor.sh`, `python3 scripts/monitor.py`) shows every host in
`graph.yaml` from wherever you are, including a phone over SSH. SSH is the transport. Each refresh
pipes a small read-only probe (`scripts/monitor/probe.py`, or `probe.ps1` on Windows) into
`ssh HOST python3 -` and reads back one JSON object. Nothing is installed on the remote, and no new
port is opened anywhere. There is no HTTP dashboard.

## Quickstart

```sh
./familia-monitor --list           # which hosts it knows and how it reaches each one
./familia-monitor                  # live console (curses; plain text when there is no TTY)
./familia-monitor --once           # one text snapshot, then exit (exit 2 if a host is bad/stale or a process died)
./familia-monitor --once miryam    # one host, full detail
./familia-monitor --json           # one JSON snapshot for scripts
./familia-monitor --watch-deaths   # alert loop: one line per death / OOM kill / host up-down, bell on deaths
```

The host running the console is probed directly with no SSH, when its hostname matches a graph host.
Other hosts are reached in this order:

1. The private override file `~/.config/familia/monitor.json` (or `--config`, or `$FAMILIA_MONITOR_CONFIG`).
   It is never committed:
   ```json
   {"hosts": {
     "qodesh": {"ssh": "qodesh"},
     "phone7": {"ssh": "phone7", "ssh_opts": ["-i", "~/.ssh/familia_monitor", "-o", "IdentitiesOnly=yes"]},
     "shalom": {"enabled": false},
     "miryam": {"local": true}
   }}
   ```
   Per-host keys: `ssh` (an alias or `user@host`), `ssh_opts`, `known_hosts`, `os`, `probe` (`stdin` | `pinned`),
   `enabled`, `local`. Hosts that are not in the graph can be added here as well.
2. An `~/.ssh/config` alias with the graph host's name (`Host phone7` … `HostName`/`User`/`Port`).
3. Nothing else by default. Addresses in `graph.yaml` are only used if you set `"allow_graph_addr": true`,
   because connection details belong in private config.

A host with no transport is listed as `no transport` and never contacted.

SSH always runs as `ssh -T -o BatchMode=yes -o ConnectTimeout=5`, with ControlMaster/ControlPersist
(sockets in `~/.cache/familia/cm-*`). Only the first refresh pays for the handshake. Host keys are
checked normally: add the host to `known_hosts` yourself first.

## What it shows

Each host gets one summary row: state, uptime, load, CPU, RAM available/total, swap, highest
temperature, familia process count, healthy endpoints, and probe cost (`time on host / round trip`).
Colors:

- **green**: ok
- **yellow**: warn (RAM <15% available, swap >50% used, an `active` graph node not answering `/health`,
  ≥80°C, disk <5% free)
- **red**: bad (RAM <7%, OOM kills since the last sample, ≥90°C)
- **magenta**: stale (unreachable; the last-seen time and the error are shown)

The detail view (Enter, or `--once HOST`) adds:

- per-core CPU, RAM, zram and swap, and battery
- every familia process (llama-server/cli/bench, rpc-server, hermes, escalation proxy), with pid,
  graph node (matched by port), RSS, CPU, uptime and the flags that matter: model, ctx, ngl, threads,
  parallel, port, kv type, cache-ram, and `GGML_VK_VISIBLE_DEVICES` (when readable)
- `/health` and `/v1/models` for each graph node's port on 127.0.0.1
- top processes by RSS, disks, GPUs (nvidia-smi, `/sys/class/drm`, Android GPU sysfs; WMI on Windows)
  and temperatures
- kernel OOM and earlyoom kills from the journal
- the tail of the newest familia logs (`~/familia-perf.log`, `~/.cache/familia/logs/*`, the repo `.cache/familia/*.log`)

Secrets (`--api-key`, `hf_…`, `Bearer …`, `token=`) are redacted by the probe. Addresses in SSH
errors are replaced with `<addr>`.

### Keys (live)

| key | action |
|---|---|
| `↑`/`↓`, `j`/`k` | select host (scroll in detail view) |
| `Enter`, `→`, `d` | host detail |
| `Esc`, `←`, `b` | back |
| `PgUp`/`PgDn`, space | page in the detail view |
| `r` | refresh all hosts now |
| `a` | acknowledge (clear) the alert banner |
| `+` / `-` | refresh interval ±1 s |
| `?` | help line |
| `q` | quit |

## Process deaths (standing rule)

Every sample is compared with the previous one, keyed on pid plus kernel start time, so a reused pid
still counts as a death. The previous sample is saved in `~/.local/state/familia/monitor-last.json`,
so even consecutive `--once` runs (cron, a phone) catch deaths in between. When a familia
server process disappears, the console:

- shows a red banner that stays until you press `a`, and rings the terminal bell
- gives cause hints: the matching earlyoom/kernel OOM record (signal, RSS), low memory at the last
  sample, or "host rebooted"; otherwise it says the exit code is not visible (the process is not the
  monitor's child) and points to the log
- includes the last lines of the node's `serve-NODE.log` (or the newest familia log)
- appends the event to `~/.local/state/familia/monitor-events.jsonl` (mode 0600; `--event-log` to change)

One-shot tools (`llama-bench`, `llama-cli`) that exit without an OOM record are logged as `exited`
and do not raise an alert. OOM kills of other processes are reported once as warnings.

`--on-death CMD` (off by default) runs `sh -c CMD` once per death, with `FAMILIA_HOST`,
`FAMILIA_NODE`, `FAMILIA_PID`, `FAMILIA_PROC`, `FAMILIA_PORT`, `FAMILIA_CAUSE` and `FAMILIA_EVENT_JSON`
set. For example, relaunch the node through its documented launcher:

```sh
./familia-monitor --watch-deaths --on-death 'ssh "$FAMILIA_HOST" "cd ~/repositories/familia && nohup scripts/serve.sh $FAMILIA_NODE >/dev/null 2>&1 &"'
```

The monitor itself never restarts anything.

## Overhead (measured on miryam, i5-7200U, 2026-10-19)

| path | probe time on host | probe CPU | probe max RSS | round trip |
|---|---|---|---|---|
| local (no ssh) | 300–450 ms | ~200 ms | ~29 MiB | 0.45–0.7 s |
| ssh to localhost, first connect | ~350 ms | ~210 ms | ~29 MiB | 2.4 s |
| ssh to localhost, ControlMaster reused | ~335 ms | ~215 ms | ~29 MiB | 0.53–0.58 s |

Of the probe time, 250 ms is the CPU sampling window (`--interval`). The OOM journal query runs in
parallel with it. These numbers were measured at load average 12–15, with other jobs running. With
the default 3 s refresh, one host costs roughly 7% of one core. Use `-i 5` or more on the oldest
machines and phones.

## Platforms

- **Linux:** needs `python3` (stdlib only). Journal access for OOM history needs the `adm` or
  `systemd-journal` group; without it the kill list is just empty.
- **Termux (Android):** needs `pkg install python` (already present on the phones). Android hides
  other apps' processes and usually `/proc/stat`, so per-core CPU and the top list cover Termux only.
  Battery comes from `/sys/class/power_supply` when readable. `dumpsys` and Termux:API are not used.
  `--watch-deaths` works well in a phone terminal over SSH.
- **Windows:** the probe is PowerShell 5.1 (`probe.ps1`: CIM, Get-Process, nvidia-smi if present,
  WMI video controller; the legacy 341.xx driver reports `N/A` for most nvidia-smi fields). It is sent
  as `powershell -NoProfile -NonInteractive -Command "[Console]::In.ReadToEnd() | Invoke-Expression"`,
  so the command contains no `$` and works the same whether sshd's shell is cmd.exe or Git bash. The
  Windows host needs OpenSSH **Server** to be monitored (qodesh currently has only the client). Running the
  console *on* Windows works without ControlMaster, which Win32-OpenSSH lacks.

## Hardened monitoring key (optional)

The console needs nothing beyond your normal SSH login. To give a monitoring key no shell at all,
deploy a pinned probe and force it in `authorized_keys`:

```sh
# on the monitored host (once; copy the file however you normally do)
mkdir -p ~/.local/share/familia && cp scripts/monitor/probe.py ~/.local/share/familia/monitor-probe.py
```

```
# ~/.ssh/authorized_keys on the monitored host: one line, a key used only for monitoring
restrict,command="python3 ~/.local/share/familia/monitor-probe.py --forced",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA...monitoring-key... familia-monitor
```

`restrict` (OpenSSH ≥ 7.2) already implies the `no-*` options, which are listed for older servers.
With `--forced`, the probe reads only the validated `--ports` / `--since` numbers from
`SSH_ORIGINAL_COMMAND` and ignores everything else, including `--logs`, so the key can't choose
which files are read. On the console side, point that host at the key with
`"ssh_opts": ["-i", "~/.ssh/familia_monitor", "-o", "IdentitiesOnly=yes"]` and `"probe": "pinned"`.
Re-copy the probe when it changes. On Windows the equivalent forced command is
`powershell -NoProfile -NonInteractive -File %USERPROFILE%\.local\share\familia\monitor-probe.ps1`.

This is part of the end-of-sprint SSH lockdown, tracked privately. Keep real host names, keys and
addresses out of this repo.

## Deploy the pinned probe (one command)

```sh
# this machine
./familia-monitor --deploy-probe --   # or:
sh scripts/monitor/deploy-probe.sh --local

# one or more ssh aliases
sh scripts/monitor/deploy-probe.sh miryam phone7
# or from private monitor.json hosts.*.ssh:
sh scripts/monitor/deploy-probe.sh

# Windows OpenSSH Server (also copies probe.ps1)
sh scripts/monitor/deploy-probe.sh --windows qodesh
```

Then set `"probe": "pinned"` for those hosts in `~/.config/familia/monitor.json`.
`--dry-run` prints the mkdir/scp/cp plan without touching the remotes.

## Not yet

Still open on #71: a live tok/s readout against registry numbers, and forwarding
alerts to the hermes relay. Live tests of `probe.ps1` / Termux once those hosts
are back in range.
