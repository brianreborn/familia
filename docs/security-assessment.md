# Security assessment mode (#116)

Operator-authorized, **safety-bounded** security assessment for assets the
operator is authorized to test. Deliberately separate from automated tests and
ordinary graph startup.

CLI: `python3 scripts/sec_assess.py`

## Safety boundary

| Included | Not included |
| --- | --- |
| Explicit operator invocation | Inference from graph placement |
| Exact host allowlist | Host reachability / “it answered ping” |
| Bounded time window | Open-ended or prior-run consent |
| Low mode: local inventory + policy reads | Live scans, sockets to targets |
| Detail mode: supervised plan (network refused in this build) | Autonomous exploitation |
| Audit log + stop/status | Silent remediation / config mutation |
| Remediation **proposals** | Applying changes without human approval |

Guardian / pentest **launch-test seatbelts stay intact**: empty `tools.allow: []`
in both `graph.yaml` `pentests.*` and `scripts/guardian-role.json` (legacy
`scripts/pentest-role.json`), plus `launch_test_only: true`. See
[guardian-nodes.md](guardian-nodes.md) and [REQUIREMENTS.md](../REQUIREMENTS.md).
This tool never removes those seatbelts.

## Invocation (all required for `run` / `preflight`)

```sh
export FAMILIA_SEC_ASSESS_CONFIRM=yes

python3 scripts/sec_assess.py preflight \
  --i-authorize-assessment \
  --allowlist angel,galaxy1 \
  --mode low \
  --window-minutes 30

python3 scripts/sec_assess.py run \
  --i-authorize-assessment \
  --allowlist angel,galaxy1 \
  --mode low \
  --window-minutes 30 \
  --graph graph.yaml
```

Optional fixture policy (local JSON only):

```sh
python3 scripts/sec_assess.py run ... --policy tests/fixtures/sec-assess/policy.json
```

Detail mode still requires the same confirms. It does **not** open sockets; it
records a supervised plan and the same offline inventory findings. There is no
silent fallback from `detail` to `low` when auth fails — the run aborts.

## Stop / status / audit

```sh
python3 scripts/sec_assess.py stop
python3 scripts/sec_assess.py status
python3 scripts/sec_assess.py status --clear-stop
```

Default state/audit directory: `~/.local/share/familia/sec-assess/`
(`audit.jsonl`, `run.json`, `STOP`). Overrides for tests/operators:

- `FAMILIA_SEC_ASSESS_STATE` — state directory
- `FAMILIA_SEC_ASSESS_AUDIT` — audit JSONL path

## Remediation

```sh
python3 scripts/sec_assess.py propose-remediation \
  --i-authorize-assessment \
  --allowlist angel,galaxy1
```

Writes a plan under the state directory. **Never applies silently.** Even with
`--apply` and `FAMILIA_SEC_ASSESS_APPLY=I-APPROVE-REMEDIATION`, this MVP records
approval and refuses to mutate targets — the operator applies the proposed
diff/plan by hand.

## What never calls this

- `start.sh` / `scripts/start_graph.py` / ordinary graph startup
- CI / `scripts/run-tests.sh` (tests only exercise refusal and fixture paths)
- Menu one-click paths — **CLI only** in this change (no menu item) so assessment
  cannot be started without the same confirms typed at a shell

## Unit tests

`tests/test_sec_assess.py` uses local fixtures under
`tests/fixtures/sec-assess/` only. No live scans, attack tools, exploit
reproduction, or network probes.
