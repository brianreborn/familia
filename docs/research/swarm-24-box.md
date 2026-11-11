# Decision-model catalog for the always-on GPU role (Drex 1.5/1.1, GLiDE, K2-Type-0.9B, Clef, GEV-26B-Decide)

Issue: https://github.com/brianreborn/familia/issues/24
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:18 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Write
(a) What the issue asks: add decision models as unplaced model options in the
graph catalog. Small ones are candidates for the **always-on** role on legacy GPUs
and iGPUs (qodesh 8600 GT 256 MB, miryam HD 620; see feat/qodesh-legacy-gpu), so
the GPU runs a model that is usually active rather than one that is usually idle.

(b) Proposed approach: I will create a new file `decision-model-catalog.md` in the
graph-catalog repo. The file will contain a table with columns: Model, RT, Note from
#20. For each model, I will add a new entry in the graph-catalog repo's `catalog.md`
file. The new entry will have the same columns as the existing ones. I will also
update the `graph-catalog` repo's `README.md` to mention the new file.

(c) Risks and test ideas: I will test the new entries by adding them to the graph
catalog and then running the graph-bootstraps-llama.cpp script. I will also check
the file contents and results for each model.

(d) Open questions: I do not know the file contents or results for each model, so I
will ask the validator and the community for more information.

**Related:** code-bootstraps-llama.cpp#9 (decision model stays available).
## Write
(a) What the issue asks: add decision models as unplaced model options in the graph catalog. Small ones are candidates for the **always-on** role on legacy GPUs and iGPUs (qodesh

-- swarm/box
