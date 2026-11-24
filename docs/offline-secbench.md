# Offline security-model benches (#117)

Optional, **opt-in** offline benchmark that scores operator-supplied model answers against synthetic defensive fixtures. Use it to measure whether a specialized security-analysis model improves hands-off vulnerability *identification* and *remediation advice* versus a baseline — **per platform**.

Disabled by default. Separate from ordinary CI, from automated pentest launch tests, and from the **#116 live assessment** path.

## Safety boundary

- **Synthetic local fixtures and static artifacts only.**
- No live targets, network probes, attack tools, exploit reproduction, executable attack payloads, PoCs, encode/decode recipes, or timing-attack procedures.
- Evaluates **defensive findings** and **safe remediation guidance** only.
- Does **not** download, select, or enable a specialized model. You capture answers offline and supply them as JSON; the bench only scores text.
- Does **not** alter `graph.yaml`, model selection, target systems, or stored artifacts.
- Default behavior with no opt-in: refuse, exit 2, load nothing for scoring.

## Opt-in

Either:

```bash
python3 scripts/offline_secbench.py --enable --platform linux --answers-dir PATH
```

or:

```bash
FAMILIA_OFFLINE_SECBENCH=1 python3 scripts/offline_secbench.py --platform linux --answers-dir PATH
```

Without `--enable` and without `FAMILIA_OFFLINE_SECBENCH=1`, the script prints a clear refusal to stderr and exits 2.

## Supplying baseline and candidate answers

The bench does **not** run inference. Capture model outputs yourself (any offline workflow you already use), then provide JSON objects shaped like:

```json
{
  "model": "my-baseline-or-candidate-name",
  "runtime": "llama.cpp|hermes|other",
  "revision": "gguf-hash-or-git-sha-or-label",
  "text": "the model's full defensive analysis and remediation advice for this fixture"
}
```

Two ways to pass them:

1. **Per-case directory** (preferred for a full set):

   ```text
   answers/
     secrets-in-config.baseline.json
     secrets-in-config.candidate.json
     insecure-default.baseline.json
     …
   ```

   ```bash
   FAMILIA_OFFLINE_SECBENCH=1 python3 scripts/offline_secbench.py \
     --platform linux --answers-dir answers --json
   ```

2. **Single shared files** (same answer text scored against every case — useful for smoke checks):

   ```bash
   FAMILIA_OFFLINE_SECBENCH=1 python3 scripts/offline_secbench.py \
     --platform linux --baseline bas.json --candidate cand.json --json
   ```

Optional `--out PATH` writes the JSON report to a path you name. With no `--out`, the script only prints (stdout). It never writes under the repo on its own.

## Fixtures

Default directory: `tests/fixtures/offline_secbench/`.

Each case JSON has `id`, `platforms` (or `platform`), `title`, a synthetic `artifact` (fake config/code with clearly fake tokens such as `EXAMPLE_ONLY_PASSWORD_not_real`), and `expect`:

- `must_find` — defensive finding categories the answer should mention
- `must_not_find` — false-positive controls / exploit-flavored terms that must **not** appear
- `remediation_hints` — safe remediation phrases the answer should mention

`manifest.json` lists the cases. Example canned answers for unit tests live under `answers/`.

List ids (still requires opt-in):

```bash
python3 scripts/offline_secbench.py --enable --list --platform linux
```

## Scoring and report

Pure string/heuristic rubric (no network, no subprocess to llama):

- finding coverage, false-positive avoidance, remediation-hint coverage → per-case score
- report fields: `schema_version`, `enabled`, `platform`, `host_facts` (hostname / `platform.uname` only — no graph writes), `baseline_meta`, `candidate_meta`, `cases[]`, `summary{baseline_mean,candidate_mean,benefit,reason}`
- `benefit` is `true`, `false`, or `inconclusive` from the mean delta (margin 0.05)

Results are **measured evidence only**. Leave model selection to the operator; do not auto-enable a specialized model from this report.

## What this is not

| This (#117) | Not this |
|---|---|
| Offline, synthetic fixtures | #116 live / hands-on assessment |
| Operator-supplied answer JSON | Automatic model download or graph mutation |
| Defensive findings + remediation text | Pentest launch, exploit PoCs, attack tools |
| Opt-in CLI / env | Default CI gate |

## Tests

Automated tests cover **only** opt-in gating, fixture loading, and report formatting:

```bash
python3 -m pytest tests/test_offline_secbench.py -q
```

They never launch attack tools or contact a target.

## Menu / commands

Documented as `test.offline-secbench` under Test & benchmark in [commands.md](commands.md). Also listed as a developer helper (like `system_prompt_check.py`); not an always-on end-user action.
