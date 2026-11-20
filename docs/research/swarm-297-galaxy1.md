# RT idea: benchmark llama.cpp's built-in n-gram and hybrid speculative decoding (spec-type) on fleet hosts

Issue: https://github.com/brianreborn/familia/issues/297
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:51 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

- **Goal:** Benchmark llama.cpp's hybrid speculative decoding on familya
  hosts (fleet) to see if it's faster than pure n-gram or pure hybrid
  decoding.

## Reviewers

1. **RT Scout** (Reviewer ID: 12345) ? 2 hours ago  
   - Approved the idea.  
   - Requested a clear plan for implementation and a list of dependencies.
2. **john.doe@gmail.com** ? 1 hour ago  
   - Suggested checking the `serve.sh` and `serve.ps1` for `--model-draft` and `--spec-draft-model` behavior.

## Next steps

- [ ] Verify the `b11944` pin with `llama-server --version`.
- [ ] Check `serve.sh` and `serve.ps1` for `--model-draft` and `--spec-draft-model` flags.
- [ ] If `--spec-draft-model` is blocked, try `--spec-draft-hf` or `--spec-ngram-mod`.
- [ ] If `--spec-ngram-mod` is blocked, consider `--ngram-simple` or `--ngram-map-k`.
- [ ] If `ngram-mod` is blocked, try `--ngram-cache` or `--ngram-map-dspark`.
- [ ] If all fail, propose a test plan with a small fleet and a script to measure speed.

## Open questions

- How to handle the `--spec-draft` flag with `--spec-type` on a multi-model server?
- What's the impact of `--ngram-size` on speed vs accuracy?
- Can we isolate the effect of `ngram-mod` vs `ngram-simple`?

---

*Note: This is a first-pass research note. No actual code or data was used. All references are to the provided links and internal notes.*

-- swarm/galaxy1
