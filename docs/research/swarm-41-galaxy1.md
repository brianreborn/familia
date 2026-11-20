# Live-verify prompt-cache reuse after code-bootstraps #16 (cache-ram per profile)

Issue: https://github.com/brianreborn/familia/issues/41
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:25 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

You?re not asking for a full fix, just a working test plan.

---

# 1. What?s the problem and why does it matter?

We?re testing the **prompt-cache reuse** in the family model after the cache-ram was fixed.  
The fix was: *cache-ram per profile* (up to 2048 MiB), but only 768 MiB is used on the system.  
This means the model can reuse cache across profiles, but only if the profile is not too large.  
We need to confirm that the model can still reuse cache correctly **without** being forced to reload cache on every profile.

## 2. How to test it (proposed approach)

We?ll do a **live verification**:

1. **Reproduce the environment**:  
   - Use the same `familya.git` repo, pin `40b12ad`, and run the latest commit.
   - Make sure `code-bootstraps-llama.cpp` is installed and configured.

2. **Test with two prompts**:  
   - Send the same prompt twice (e.g., `"What is your name?"`).
   - First run: should prompt again (cache hit).
   - Second run: should **not** prompt again (cache should skip), and tokens/s should be higher.

3. **Check for cache behavior**:  
   - Use tools like `time` or `perf` to see if cache hits are faster after the fix.
   - If cache is hit, the model should use less RAM (should be ? 768 MiB).

4. **Edge case**:  
   - If `CACHE_RAM=0` is set, does it re-process the prompt?

## 3. What do we expect?

- **Before fix**: Cache was per profile, so full reuse was possible.
- **After fix**: Cache should be per profile (as expected), but we need to confirm it **doesn?t** cause a full re-prompt.

## 4. Risks and test ideas

- **False negative**: Cache might not skip the prompt if it?s too large.
- **Memory pressure**: If profile size is too high, even with 768 MiB, it might fail.
- **Timing**: If cache misses are rare, we should see fewer tokens/s.

## 5. Open questions

- What?s the exact behavior with `CACHE_RAM=0`? Does it re-process the prompt?
- How does this affect training vs inference?
- Should we benchmark cache hit rates across profile sizes?

---

**Next steps:**  
- Run the test with a real prompt (e.g., `"What is your name?"`).
- Monitor logs for prompt-cache behavior.
- If the model still prompts, we?ll need to adjust the cache setting or profile size.

Let me know if you want a script to automate this check.

-- swarm/galaxy1
