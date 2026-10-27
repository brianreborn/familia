# Launch status protocol v1 (#95)

Every launcher prints one line `FAMILIA-LAUNCH {json}` per outcome (`scripts/launch_status.py`).
Fields: `v`(1) `phase`(launch|run) `status` `code` `engine` `model` `params` `rc` `signal` `evidence` `t_ready_s` `ts`.

| status | meaning | codes (exit code) |
|---|---|---|
| READY / EXITED_OK | healthy / clean exit | OK_READY, OK_EXIT (0) |
| LAUNCH_FAILED | never reached health | LF_BAD_PARAMS 64, LF_MISSING_RUNTIME 65, LF_MODEL_FILE 66, LF_TIMEOUT 67, LF_PORT 68, LF_OOM_CAP 69, LF_ENGINE 70, LF_TOKENIZER 71 |
| CRASHED | died after READY | CR_SIGNAL 80, CR_ASSERT 81, CR_OOM_KERNEL 82, CR_OOM_MEMCG 83, CR_EXIT 84 |
| KILLED | external killer identified | KL_WATCHDOG 90, KL_USER 91, KL_OOMD 92, KL_EARLYOOM 93 |

## Admission (fleet memory budget)
Before launch a job reserves its estimated peak (that reservation is also its hard MemoryMax).
Admitted only if sum(live reservations) + new <= MemTotal - 1.5 GiB and new fits MemAvailable - 1.5 GiB
minus other launches' not-yet-resident reservations; otherwise LF_OOM_CAP (69). Ledger:
`$XDG_RUNTIME_DIR/familia-admission-<uid>.json` (flock, dead pids pruned).
Big jobs (est. peak > 4 GiB, any sweep/bench) also take the per-host mutex
`~/.local/state/familia/big.lock`. Shell jobs: `scripts/with-host-lock [--big] --mib N -- CMD`.
Never test classification by provoking real crashes or OOM kills; use recorded fixtures.
