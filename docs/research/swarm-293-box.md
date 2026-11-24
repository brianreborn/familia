# install.sh has no published SHA256SUMS for the verified single-download install

Issue: https://github.com/brianreborn/familia/issues/293
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 16:55 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

? qodesh Worker (familia fleet worker), filed with Brian's OK

**Fix:** the 0.2 release publishes `install.sh` together with `SHA256SUMS`, and README/QUICKSTART show a `sha256sum -c` step using a URL pinned to the tag.

Related 0.2 blocker: #277 (`--yes` still accepts the licenses).

This blocks the 0.2 clean-host verification.

? qodesh Worker (familia fleet worker), filed with Brian's OK

**Work:** (a) what the issue asks, in your own words, (b) a proposed approach and
the files or components likely involved, (c) risks and test ideas, (d) open
questions. Do not invent measurements, file contents or results; say
'unknown' instead.
 
? qodesh Worker (familia fleet worker), filed with Brian's OK

**Fix:** the 0.2 release publishes `install.sh` together with `SHA256SUMS`, and README/QUICKSTART show a `sha256sum -c` step using a URL pinned to the tag.

Related 0.2 blocker: #277 (`--yes` still accepts the licenses).

This blocks the 0.2 clean-host verification.

? qodesh Worker (familia fleet worker), filed with Brian's OK

**Work:** (a) what the issue asks, in your own words, (b) a proposed approach and
the files or components likely involved, (c) risks and test ideas, (d) open
questions. Do not invent

-- swarm/box
