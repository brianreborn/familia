# Deferred: should pentests also be blocked from tool-adding skills inherited from their agent?

Issue: https://github.com/brianreborn/familia/issues/77
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:29 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

```

**Today:** `scripts/skills.py` and the graph check (`graph_types.check_skills`) refuse a skill with `adds_tools: true` only when it is listed directly under `pentests.<name>.skills`. A pentest whose `agent:` has tool-adding skills under `agents.<agent>.skills` is not refused by this check. Pentest launches are still launch-test only, with tools disabled two independent ways in `with-fleet.sh` / `hermes.sh`. Skills aren't loaded into hermes yet anyway (#72).

**Option when this is picked up:** in `check_graph_skills`, also refuse (or strip at launch) any `adds_tools` skill inherited from the pentest's agent. Then make sure the hermes skills loader from #72 never loads skills for pentest launches.

Write: (a) what the issue asks, in your own words, (b) a proposed approach and
the files or components likely involved, (c) risks and test ideas, (d) open
questions. Do not invent measurements, file contents or results; say
'unknown' instead.

**Status: open** (owner decision, [number]). Behavior stays as it is for now.

**Today:** `scripts/skills.py` and the graph check (`graph_types.check_skills`) refuse a skill with `adds_tools: true` only when it is listed directly under `pentests.<name>.skills`. A pentest whose `agent:` has tool-adding skills under `agents.<agent>.skills` is not refused by this check. Pentest launches are still launch-test only, with tools disabled two

-- swarm/box
