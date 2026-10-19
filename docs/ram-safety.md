# RAM safety (provisional guidance)

After miryam OOM'd and hard-hung (2026-10-09 PT) while coder (~3 GiB),
embed, and a long compaction self-test ran together, we do **not** aim for
high RAM utilization.

> **Status (2026-10-19):** the numbers below (`reserve_ram_mib`, the ~2 GiB
> small-host floor, the 3 / 3.5 GiB free targets used in benchmark guards) are
> **provisional, fuzzy guidance, not hard lines.** Idle load on miryam has been
> sampled once (LESSONS-LEARNED L-memcap), and earlyoom, zram and the memcap
> scope are deployed there (table below). Revisit the margins as more idle and
> load data lands in the registry. Under-using RAM is preferred to idle CPU/iGPU
> only up to the point of risk; brushing a target (e.g. 3.43 GiB vs 3.5) is within
> guidance.

## Guidance

1. **Reserve for the OS and companions.** On miryam (`ram_mib: 7270`),
   `reserve_ram_mib` is **3072** (provisional) so the OS, hermes-agent,
   browser and SSH keep headroom.
2. **Aim for ~2 GiB free after estimated node use on hosts under 8 GiB**
   (weights + KV + 256 MiB overhead + `cache_ram_mib` + draft weights).
3. **Prefer one heavy server at a time on miryam.**
   Test hard on purpose, but rely on earlyoom and zram to catch a spike instead of
   packing several heavy processes together.
4. **Validate against the target host's measured `ram_mib`.**
5. **iGPU and Vulkan memory is system RAM.** A Vulkan build allocates about
   1.8 GB of shared-memory host buffers even with `-ngl 0`, which counts against the
   memcap scope. `scripts/serve.sh` and the hermes harness hide the Vulkan devices
   (`GGML_VK_VISIBLE_DEVICES=`) for `-ngl 0` nodes (LESSONS-LEARNED L-vkshm; live
   re-check planned, [#40](https://github.com/brianreborn/familia/issues/40)).

## What the validator does

| Check | Result |
|---|---|
| `estimated_used > ram_mib` | **ERROR**: clear overcommit, fails. |
| `estimated_used + reserve_ram_mib > ram_mib` | WARNING (provisional margin). |
| `ram_mib < 8192` and `ram_mib - estimated_used < 2048` | WARNING (provisional small-host floor). |

## Baseline numbers (miryam)

| Placement | Est. use | Free after est. | With reserve 3072 |
|---|---|---|---|
| coder 64k alone | ~2928 MiB | ~4342 MiB | no warning |
| coder + embed | ~3479 MiB | ~3791 MiB | no warning (tight) |

## Deployment status on miryam (2026-10-10)

| layer | status |
|---|---|
| `scripts/serve.sh` memcap (systemd-run --user scope, MemoryHigh 2200M / MemoryMax 2600M / MemorySwapMax 0, oom_score_adj 800) | **deployed** (no root). Default on for miryam; set `FAMILIA_MEMCAP=0/1` to override. Verified with a SmolLM2 test server: scope showed MemoryMax=629145600 (600M test cap), oom_score_adj=800 |
| earlyoom (args below) | **deployed** 2026-10-10 13:40 PT by the user's sudo paste. `active`; the running process shows `-m 8,4 -s 10,5 -r 60 --prefer (^\|/)(llama-server\|llama-bench\|llama-cli)$ --avoid (^\|/)(gnome-shell\|Xwayland\|sshd\|systemd\|grok-bot)$ -n`. Verified from `ps`, because rcs isn't in the adm group and can't read its journal |
| zram-tools (zstd, 25%, prio 100) | **deployed**: `/dev/zram0` is 1.8 GiB, zstd, priority 100. The old 16 MiB sda3 swap stays at priority -1 |
| systemd-oomd | **not configured by us** (Ubuntu default, active). It only watches the `user@*.service` cgroups, killing at 50% memory pressure sustained for 20 s, and swap above 90%. earlyoom acts first, on low free memory, and only targets llama-*. Coexistence looks OK: they trigger on different signals, and earlyoom normally fires earlier. The risk is that oomd may pick a whole desktop app cgroup under sustained pressure. Our memcapped scope is the most likely large candidate, which is what we want. |

Before deployment, swap was a 16 MiB `/dev/sda3` partition and it was full. swappiness was 60. It still is: a 4 GiB swapfile at a lower priority than zram is planned ([#43](https://github.com/brianreborn/familia/issues/43)).

Sudo block for miryam (paste into a terminal):
```
sudo apt-get install -y earlyoom zram-tools && echo "EARLYOOM_ARGS=\"-m 8,4 -s 10,5 -r 60 --prefer '(^|/)(llama-server|llama-bench|llama-cli)\$' --avoid '(^|/)(gnome-shell|Xwayland|sshd|systemd|grok-bot)\$' -n\"" | sudo tee /etc/default/earlyoom && printf 'ALGO=zstd\nPERCENT=25\nPRIORITY=100\n' | sudo tee /etc/default/zramswap && sudo systemctl enable --now earlyoom && sudo systemctl restart earlyoom zramswap && swapon --show && journalctl -u earlyoom -n 5 --no-pager
```

## System-level protections (reference)

All but 3 and 4 need root. On miryam, 1 and 5 are deployed (by the sudo block above) and 3 is what `scripts/serve.sh` does by default; 2 is the alternative we did not choose. Listed in order of value.

### 1. earlyoom (kill the biggest *model* process before the desktop freezes)
```
sudo apt install earlyoom
sudo tee /etc/default/earlyoom >/dev/null <<'EOF'
EARLYOOM_ARGS="-m 8,4 -s 10,5 -r 60 --prefer '(^|/)(llama-server|llama-bench|llama-cli)$' --avoid '(^|/)(gnome-shell|Xwayland|sshd|systemd|grok-bot)$' -n"
EOF
sudo systemctl enable --now earlyoom
```
(`-m 8,4`: SIGTERM at <8% available, SIGKILL at <4%; only the preferred regex is targeted first.)

### 2. Alternative: systemd-oomd (Ubuntu ships it; do not run both with earlyoom)
```
sudo mkdir -p /etc/systemd/oomd.conf.d
sudo tee /etc/systemd/oomd.conf.d/familia.conf >/dev/null <<'EOF'
[OOM]
SwapUsedLimit=90%
DefaultMemoryPressureLimit=60%
DefaultMemoryPressureDurationSec=20s
EOF
sudo systemctl restart systemd-oomd
```
It only acts on cgroups with `ManagedOOMMemoryPressure=kill`, which the wrapper below sets.

### 3. cgroup wrapper for llama-server (no root needed once user lingering/delegation works)
```
systemd-run --user --scope -p MemoryHigh=2200M -p MemoryMax=2600M -p MemorySwapMax=0 \
  -p ManagedOOMMemoryPressure=kill -p OOMScoreAdjust=800 \
  -- llama-server <args from: python3 scripts/validate_graph.py --args coder>
```
`MemoryHigh` throttles and reclaims, and `MemoryMax` kills only this server. Size it from the node estimate plus about 15%.
Note: page cache from mmapped weights counts toward the cgroup. Test once before relying on it.

### 4. OOM score for model processes (fallback, no root needed to raise your own)
```
echo 800 > /proc/<llama-server pid>/oom_score_adj     # makes the kernel pick it first
```

### 5. zram swap (cushion for spikes; miryam's disk swap is only 16 MiB)
```
sudo apt install zram-tools
echo -e "ALGO=zstd\nPERCENT=25\nPRIORITY=100" | sudo tee /etc/default/zramswap
sudo systemctl restart zramswap
cat /proc/swaps
```
