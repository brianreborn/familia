# rt-idea: Mesh LLM: split big models across household devices (research only)

Issue: https://github.com/brianreborn/familia/issues/310
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 19:31 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## First experiment
**Read-only comparison only for this issue:** find and cite Mesh LLM repo/docs; write a 1-page comparison against familia graph.yaml placement. A 2-host layer split is **out of scope** here and needs a new card plus Brian's OK.

## Reviewer conditions (credited)
- **Senior Developer (APPROVE):** **read-only comparison only; the optional 2-host split needs a new card and Brian's OK**; record peer-to-peer auth and transport (plaintext keys/activations on the LAN are a blocker, see familia#304); never touch angel or the phones.
- **Researcher (APPROVE):** research only, does not gate familia v0.2/v0.3; cite Mesh LLM repo/docs before comparing; comparison is box only; 2-host split needs Brian's OK and must not run on fleet hosts (box/scratch VMs only); cover peer auth/transport ? cleartext HTTP for keys/prompts flagged like familia#304 (L14), require TLS or SSH tunnel; tok/s figures **pending**, none quoted from the post.
- **Platform Reviewer (APPROVE):** cite a real Mesh LLM repo/docs; comparison is box-only text work; any later 2-host split needs a new card + Brian's OK; never angel; no Android phones/Termux without Brian's per-host OK (note9 retired ? do not name it as a target); record Windows vs POSIX path/argv handling and prefer familia graph.yaml conventions when docs and code disagree; if a peer dies mid-split, say whether the graph fails closed

-- swarm/box
