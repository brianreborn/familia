# Wire LFM3-1.7B-Uncensored as nodes.coder on miryam

Issue: https://github.com/brianreborn/familia/issues/613
Runner: surface1 (stamp v=1 host=surface1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-22 22:36 PST
Approved-content-sha256: 7c302875f6f3e385c7b40e7979144ea957d163f90600a3d444c5ae9d4ab87a68

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:9931); treat it as unverified until reviewed.

## 1. Read-only probe (measured on surface1)

stamp v=1 host=surface1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

---

**Issue #613**

(a) **What it asks:**  
The issue reports that on `main`, the node `nodes.coder` in the `miryam` project (port 9941, status active) is configured to use the model `qwen35-2b-q4km` instead of the intended LFM3?1.7B?uncensored (`lfm3-17b-uncensored-q4km`). Several related files and settings have stale or incorrect values: 64?k context/thread/RAM figures were measured for Qwen3.5?2B, not LFM3; the model?s `role` is currently `chat` while the coder node needs a validator role that allows ?coder? (similar to Nanbeige?s dual usage); and `generated/graph-miryam.yaml` still references `qwen35-2b-q4km` for the coder entry. The docs/README and `start.sh` already treat `lfm3-17b-uncensored-q4km` as the single?node default, but the checked?in fleet graph does not reflect that.

(b) **Proposed approach**

1. **Validate role compatibility** ? Check whether the validator role for `nodes.coder` permits the model?s ?coder? role (or add such allowance). If a similar dual?role pattern exists elsewhere, mirror it.
2. **Update node configuration** ? Change `nodes.coder` to point at `lfm3-17b-uncensored-q4km`, keep its context 65536 and thread count 3, and set `load_mode: none`. Also ensure the measured values (64?k KV/RSS/threads) are re?measured for this model or clearly marked as unmeasured.
3. **Refresh generated files** ? Edit `generated/graph-miryam.yaml` so that the coder entry uses `model: lfm3-17b-uncensored-q4km`. Run any test fixtures that hard?code the miryam coder model and update them to match.
4. **Re?measure or annotate** ? Re?run measurements for RAM, context window, threads, etc., on LFM3?1.7B?uncensored; if a quick re?measure isn?t feasible, add an `unmeasured:` flag in the relevant fields and document why.

Files/components involved:
- `nodes.coder` (port 9941 / miryam) ? node config.
- `models.lfm3-17b-uncensored-q4km` ? model catalog entry (sha256 pinned).
- `generated/graph-miryam.yaml` ? generated graph file, stale entries for coder.
- Possibly a validator role definition that needs updating.

(c) **Risks and test ideas**

- **Role mismatch** ? If the validator role doesn?t allow ?coder?, swapping the model may cause validation failure. Test by running `nodes.coder` after change; if it fails, adjust role or add dual?role like Nanbeige.
- **Resource claims** ? The old 64?k figures for Qwen3.5 are likely wrong for LFM3. Run a quick memory/thread check on the new model (or at least note them as unmeasured) to avoid misleading docs.
- **Stale generated files** ? Other scripts or tests may import `graph-miryam.yaml` and expect qwen35?2b; update those imports too.
- **Deferred models** ? LFM3?VL/Omni/Audio remain opt?in; ensure no accidental propagation of the old model into those entries.

Test ideas:
- After editing, run the miryam node locally (`start.sh` or `nodes.coder`) and confirm it reports `lfm3-17b-uncensored-q4km`.
- Verify that `generated/graph-miryam.yaml` contains the correct model field for coder.
- Re?run any CI validation steps (graph checks, role rules) to ensure no ?unmeasured? fields cause failures.
- Check thread/RAM usage on a short inference run and compare against expected values.

(d) **Open questions**

- What is the current validator role definition in `miryam`? Does it allow a model?s ?coder? role?
- Have we measured (or can we quickly measure) the context window, KV size, RSS, and thread count for `lfm3-17b-uncensored-q4km`?
- Are there other generated files or test fixtures besides `generated/graph-miryam.yaml` that reference `qwen35-2b-q4km` in a coder role?
- Should the ?unmeasured? fields be explicitly marked, and if so, which ones (threads, RAM, etc.)?

---

-- swarm/surface1
